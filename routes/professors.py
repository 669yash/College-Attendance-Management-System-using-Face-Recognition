"""
Professor routes for dashboard and class management
"""
from flask import Blueprint, render_template, request, flash, redirect, url_for, send_file, jsonify, abort
from flask_login import login_required, current_user
from pymongo import MongoClient
from bson import ObjectId
from datetime import datetime
from config import (
    MONGODB_URI,
    DATABASE_NAME,
    CLASSROOM_FOLDER,
    MAIL_SERVER,
    MAIL_PORT,
    MAIL_USE_TLS,
    MAIL_USERNAME,
    MAIL_PASSWORD,
    MAIL_SENDER,
    ENABLE_ATTENDANCE_EMAILS,
    ENABLE_ATTENDANCE_NOTIFICATIONS,
)
from utils.helpers import save_uploaded_file, ensure_directory, log_activity, allowed_file
from utils.report_generator import generate_class_attendance_report
from utils.face_recognition_interface import mark_attendance_from_classroom_images
import io
import smtplib
import ssl
from threading import Thread
from pathlib import Path
import json
import re

professors_bp = Blueprint('professors', __name__, url_prefix='/professor')

# MongoDB connection
client = MongoClient(MONGODB_URI)
db = client[DATABASE_NAME]


def run_attendance_task(task_id_str, class_id_str, classroom_folder_s, ts):
    try:
        print(f"[TASK] Starting attendance task {task_id_str} for class {class_id_str}")
        recognition_output = mark_attendance_from_classroom_images(
            class_id_str, classroom_folder_s, ts
        )
        attendance_results = recognition_output.get('attendance', recognition_output)
        metrics = recognition_output.get('metrics', {})
        print(f"[TASK] Recognition complete: {len(attendance_results)} results")
        class_info_local = db.classes.find_one({'_id': ObjectId(class_id_str)})
        students_local = list(db.users.find({
            'role': 'student',
            'year': class_info_local['year'],
            'division': class_info_local['division']
        }))
        all_roll_numbers = set(attendance_results.keys())
        for student in students_local:
            all_roll_numbers.add(student['roll_number'])
        all_students_local = list(db.users.find({
            'role': 'student',
            'roll_number': {'$in': list(all_roll_numbers)}
        }))
        current_timestamp_local = datetime.now()
        session_id_local = ts
        attendance_records_local = []
        present_count_local = 0
        absent_count_local = 0
        for roll_number in all_roll_numbers:
            if roll_number in attendance_results and attendance_results[roll_number] == 'present':
                status_local = 'present'
                present_count_local += 1
            else:
                status_local = 'absent'
                absent_count_local += 1
            attendance_records_local.append({
                'class_id': ObjectId(class_id_str),
                'student_roll': roll_number,
                'timestamp': current_timestamp_local,
                'session_id': session_id_local,
                'status': status_local
            })
        if attendance_records_local:
            db.attendance_records.insert_many(attendance_records_local)
            student_by_roll_local = {s['roll_number']: s for s in all_students_local}
            if ENABLE_ATTENDANCE_NOTIFICATIONS:
                notif_docs_local = []
                for rec in attendance_records_local:
                    sdoc_local = student_by_roll_local.get(rec['student_roll'])
                    if not sdoc_local:
                        continue
                    msg_local = f"You were marked {rec['status'].upper()} for {class_info_local['class_name']} ({class_info_local['subject']})."
                    notif_docs_local.append({
                        'user_id': sdoc_local['_id'],
                        'roll_number': sdoc_local['roll_number'],
                        'class_id': ObjectId(class_id_str),
                        'session_id': session_id_local,
                        'status': rec['status'],
                        'message': msg_local,
                        'timestamp': current_timestamp_local,
                        'read': False,
                    })
                if notif_docs_local:
                    db.notifications.insert_many(notif_docs_local)
            if ENABLE_ATTENDANCE_EMAILS and MAIL_SERVER and MAIL_USERNAME and MAIL_PASSWORD:
                def send_attendance_email(recipient, status):
                    try:
                        subject = "Attendance Update"
                        pid = class_info_local.get('professor_id')
                        if pid:
                            try:
                                pid = pid if isinstance(pid, ObjectId) else ObjectId(pid)
                            except Exception:
                                pid = None
                        prof_user = db.users.find_one({'_id': pid}) if pid else None
                        prof_name = (prof_user or {}).get('name', 'Professor')
                        display = f"{class_info_local.get('subject','Class')} by Prof. {prof_name}"
                        body = (
                            f"Hello,\n\nYou were marked {status.upper()} for {display}\n"
                            f"on {current_timestamp_local.strftime('%Y-%m-%d %H:%M:%S')}.\n\nSession ID: {session_id_local}.\n\nRegards,\nAttendance System"
                        )
                        message = f"From: {MAIL_SENDER}\r\nTo: {recipient}\r\nSubject: {subject}\r\n\r\n{body}"
                        if MAIL_USE_TLS:
                            context = ssl.create_default_context()
                            with smtplib.SMTP(MAIL_SERVER, MAIL_PORT) as server:
                                server.starttls(context=context)
                                server.login(MAIL_USERNAME, MAIL_PASSWORD)
                                server.sendmail(MAIL_SENDER, recipient, message)
                        else:
                            with smtplib.SMTP(MAIL_SERVER, MAIL_PORT) as server:
                                server.login(MAIL_USERNAME, MAIL_PASSWORD)
                                server.sendmail(MAIL_SENDER, recipient, message)
                        return True
                    except Exception:
                        return False
                sent_local = 0
                for rec in attendance_records_local:
                    sdoc_local = student_by_roll_local.get(rec['student_roll'])
                    if sdoc_local and sdoc_local.get('email'):
                        if send_attendance_email(sdoc_local['email'], rec['status']):
                            sent_local += 1
                print(f"[TASK] Sent {sent_local} attendance emails")
            print(f"[TASK] Writing results: {present_count_local} present, {absent_count_local} absent")
            db.attendance_tasks.update_one({'_id': ObjectId(task_id_str)}, {'$set': {
                'status': 'done',
                'present_count': present_count_local,
                'absent_count': absent_count_local,
                'session_id': session_id_local
            }})
        else:
            print(f"[TASK] No records, finishing with zeros")
            db.attendance_tasks.update_one({'_id': ObjectId(task_id_str)}, {'$set': {
                'status': 'done',
                'present_count': 0,
                'absent_count': 0,
                'session_id': session_id_local
            }})
    except Exception as e:
        print(f"[TASK] Error: {e}")
        db.attendance_tasks.update_one({'_id': ObjectId(task_id_str)}, {'$set': {
            'status': 'error',
            'error': str(e)
        }})

@professors_bp.route('/dashboard')
@login_required
def dashboard():
    """Professor dashboard"""
    if current_user.role != 'professor':
        flash('Access denied', 'error')
        return redirect(url_for('auth.login'))
    
    # Get professor data
    professor_data = db.users.find_one({'_id': ObjectId(current_user.id)})
    if not professor_data:
        flash('Professor data not found', 'error')
        return redirect(url_for('auth.logout'))
    
    # Get all classes created by this professor
    classes = list(db.classes.find({'professor_id': current_user.id}).sort('_id', -1))
    # Annotate with attendance existence and display name
    prof = db.users.find_one({'_id': ObjectId(current_user.id)})
    prof_name = (prof or {}).get('name', 'Professor')
    for cls in classes:
        try:
            has = db.attendance_records.find_one({'class_id': cls['_id']}) is not None
        except Exception:
            has = False
        cls['has_attendance'] = has
        subj = cls.get('subject') or cls.get('class_name') or 'Class'
        cls['display_name'] = f"{subj} by Prof. {prof_name}"
    # Convert ObjectId to string for template rendering
    for cls in classes:
        cls['_id'] = str(cls['_id'])
    
    return render_template('professor/dashboard.html',
                         professor=professor_data,
                         classes=classes)


@professors_bp.route('/create-class', methods=['POST'])
@login_required
def create_class():
    """Create a new class"""
    if current_user.role != 'professor':
        flash('Access denied', 'error')
        return redirect(url_for('auth.login'))
    
    class_name = request.form.get('class_name')
    subject = request.form.get('subject')
    year = request.form.get('year')
    division = request.form.get('division')
    class_date = request.form.get('class_date')
    start_time = request.form.get('start_time')
    end_time = request.form.get('end_time')
    
    if not all([class_name, subject, year, division, class_date, start_time, end_time]):
        flash('Please fill in all fields', 'error')
        return redirect(url_for('professors.dashboard'))
    
    # Derive display values
    try:
        class_date_obj = datetime.strptime(class_date, '%Y-%m-%d')
        day_of_week = class_date_obj.strftime('%A')
        time_slot = f"{day_of_week} {start_time} - {end_time}"
    except Exception:
        time_slot = f"{start_time} - {end_time}"
        day_of_week = ''

    # Create class document
    class_data = {
        'class_name': class_name,
        'subject': subject,
        'year': year,
        'division': division,
        'time_slot': time_slot,
        'class_date': class_date,
        'day_of_week': day_of_week,
        'start_time': start_time,
        'end_time': end_time,
        'professor_id': current_user.id,
        'created_at': datetime.now()
    }
    
    result = db.classes.insert_one(class_data)
    try:
        log_activity(db, actor_id=ObjectId(current_user.id), role='professor', action='create_class', details={'class_name': class_name, 'subject': subject, 'year': year, 'division': division, 'class_date': class_date, 'start_time': start_time, 'end_time': end_time}, class_id=result.inserted_id)
    except Exception:
        pass
    
    flash(f'Class "{class_name}" created successfully!', 'success')
    return redirect(url_for('professors.dashboard'))


@professors_bp.route('/mark-attendance/<class_id>', methods=['GET', 'POST'])
@login_required
def mark_attendance(class_id):
    """Mark attendance by uploading classroom images"""
    if current_user.role != 'professor':
        flash('Access denied', 'error')
        return redirect(url_for('auth.login'))
    
    # Verify class belongs to professor
    class_info = db.classes.find_one({'_id': ObjectId(class_id), 'professor_id': current_user.id})
    if not class_info:
        flash('Class not found or access denied', 'error')
        return redirect(url_for('professors.dashboard'))
    
    # Disallow marking if attendance already exists for this class
    if db.attendance_records.find_one({'class_id': ObjectId(class_id)}):
        flash('Attendance has already been marked for this class. You can review and edit from Attendance History.', 'info')
        return redirect(url_for('professors.attendance_sessions', class_id=class_id))
    if request.method == 'POST':
        # Handle file uploads (4-5 classroom images)
        uploaded_files = request.files.getlist('classroom_images')
        valid_files = [f for f in uploaded_files if f.filename]
        bad_ext = [f.filename for f in valid_files if not allowed_file(f.filename)]
        if bad_ext:
            flash(f"Unsupported image format(s): {', '.join(bad_ext)}. Allowed: JPG, JPEG, PNG, GIF.", 'error')
            return redirect(url_for('professors.mark_attendance', class_id=class_id))
        
        if len(valid_files) < 4 or len(valid_files) > 5:
            flash('Please upload 4-5 classroom images', 'error')
            return redirect(url_for('professors.mark_attendance', class_id=class_id))
        
        # Create timestamp folder for this attendance session
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        classroom_folder = CLASSROOM_FOLDER / str(class_id) / timestamp
        ensure_directory(classroom_folder)
        
        # Save uploaded images
        saved_files = []
        print(f"\n[DEBUG] Attempting to save {len(valid_files)} files")
        print(f"[DEBUG] Classroom folder: {classroom_folder}")
        
        for idx, file in enumerate(valid_files):
            print(f"[DEBUG] Processing file {idx+1}: {file.filename}")
            if hasattr(file, 'content_type'):
                print(f"[DEBUG]   File content type: {file.content_type}")
            
            # Determine file extension from original filename
            if '.' in file.filename:
                original_ext = file.filename.rsplit('.', 1)[1].lower()
            else:
                # Default to jpg if no extension
                original_ext = 'jpg'
                print(f"[DEBUG]   Warning: No file extension, defaulting to .jpg")
            
            # Use original extension or jpg
            save_filename = f'image_{idx+1}.{original_ext}'
            file_path = save_uploaded_file(file, classroom_folder, save_filename)
            if file_path:
                saved_files.append(file_path)
                print(f"[DEBUG]   [OK] Saved successfully as {save_filename}")
            else:
                print(f"[DEBUG]   [FAIL] Failed to save {file.filename}")
        
        print(f"[DEBUG] Successfully saved {len(saved_files)} out of {len(valid_files)} files")
        
        if len(saved_files) < 4:
            flash(f'Failed to save some images. Only {len(saved_files)} out of {len(valid_files)} images were saved. Please check file formats (JPG, PNG, GIF) and try again.', 'error')
            return redirect(url_for('professors.mark_attendance', class_id=class_id))
        
        task_doc = {
            'class_id': ObjectId(class_id),            'class_id_str': str(class_id),
            'timestamp': datetime.now(),
            'session_id': timestamp,
            'status': 'running'
        }
        task_id = db.attendance_tasks.insert_one(task_doc).inserted_id
        t = Thread(target=run_attendance_task, args=(str(task_id), str(class_id), str(classroom_folder), timestamp))
        t.daemon = True
        t.start()
        return redirect(url_for('professors.attendance_task', task_id=str(task_id)))
    
    # Convert ObjectId to string for template rendering
    if class_info:
        class_info['_id'] = str(class_info['_id'])
    
    return render_template('professor/mark_attendance.html', class_info=class_info)

@professors_bp.route('/attendance-task/<task_id>')
@login_required
def attendance_task(task_id):
    doc = db.attendance_tasks.find_one({'_id': ObjectId(task_id)})
    if not doc:
        flash('Task not found', 'error')
        return redirect(url_for('professors.dashboard'))
    if doc.get('status') == 'done':
        return redirect(url_for('professors.edit_attendance', class_id=str(doc.get('class_id_str', doc['class_id'])), session_id=doc.get('session_id')))
    if doc.get('status') == 'error':
        flash('Attendance processing failed', 'error')
        return redirect(url_for('professors.mark_attendance', class_id=str(doc['class_id'])))
    html = """
    <html><head><title>Processing Attendance</title>
    <script>
    async function poll(){
      try{
        const r = await fetch(window.location.pathname.replace('attendance-task','attendance-task-status'));
        const j = await r.json();
        if(j.status==='done'){
          window.location = j.redirect;
        }else if(j.status==='error'){
          document.getElementById('msg').innerText = 'Processing failed';
        }else{
          setTimeout(poll, 2000);
        }
      }catch(e){ setTimeout(poll, 2000); }
    }
    window.onload = poll;
    </script></head>
    <body style="font-family:system-ui;padding:24px;">
      <h3 id="msg">Processing attendance…</h3>
    </body></html>
    """
    return html

@professors_bp.route('/attendance-task-status/<task_id>')
@login_required
def attendance_task_status(task_id):
    doc = db.attendance_tasks.find_one({'_id': ObjectId(task_id)})
    if not doc:
        return jsonify({'status': 'error'})
    if doc.get('status') == 'done':
        present = int(doc.get('present_count', 0))
        absent = int(doc.get('absent_count', 0))
        total = present + absent
        redirect_url = url_for(
            'professors.edit_attendance',
            class_id=str(doc.get('class_id_str', doc['class_id'])),
            session_id=doc.get('session_id'),
            present_count=present,
            absent_count=absent,
            total=total,
        )
        return jsonify({'status': 'done', 'redirect': redirect_url})
    if doc.get('status') == 'error':
        return jsonify({'status': 'error', 'message': doc.get('error', 'unknown')})
    return jsonify({'status': 'pending'})


@professors_bp.route('/classroom-image/<class_id>/<session_id>/<filename>')
@login_required
def classroom_image(class_id, session_id, filename):
    folder = CLASSROOM_FOLDER / str(class_id) / str(session_id)
    fp = folder / filename
    if not fp.exists():
        return abort(404)
    return send_file(str(fp))


@professors_bp.route('/student/<roll_number>')
@login_required
def student_attendance_view(roll_number):
    if current_user.role not in ('professor', 'admin'):
        flash('Access denied', 'error')
        return redirect(url_for('auth.login'))
    student = db.users.find_one({'role': 'student', 'roll_number': roll_number})
    if not student:
        flash('Student not found', 'error')
        return redirect(url_for('professors.dashboard'))
    records = list(db.attendance_records.find({'student_roll': roll_number}).sort('timestamp', -1))
    class_ids = list(set([rec['class_id'] for rec in records]))
    classes = {str(cls['_id']): cls for cls in db.classes.find({'_id': {'$in': class_ids}})}
    subject_stats = {}
    for rec in records:
        cls = classes.get(str(rec['class_id']), {})
        subject = cls.get('subject', 'Unknown')
        if subject not in subject_stats:
            subject_stats[subject] = {'present': 0, 'absent': 0, 'total': 0}
        subject_stats[subject]['total'] += 1
        if rec['status'] == 'present':
            subject_stats[subject]['present'] += 1
        else:
            subject_stats[subject]['absent'] += 1
    for subject, stats in subject_stats.items():
        stats['percentage'] = (stats['present'] / stats['total'] * 100) if stats['total'] > 0 else 0
    detailed = []
    from datetime import datetime as _dt
    for rec in records[:50]:
        dt = rec['timestamp']
        if isinstance(dt, str):
            dt = _dt.fromisoformat(dt)
        cls = classes.get(str(rec['class_id']), {})
        detailed.append({
            'date': dt.strftime('%Y-%m-%d'),
            'time': dt.strftime('%H:%M:%S'),
            'subject': cls.get('subject', 'N/A'),
            'class_name': cls.get('class_name', 'N/A'),
            'status': rec['status']
        })
    return render_template('professor/student_attendance.html', student=student, subject_stats=subject_stats, detailed_records=detailed)


@professors_bp.route('/students')
@login_required
def students_list():
    if current_user.role not in ('professor', 'admin'):
        flash('Access denied', 'error')
        return redirect(url_for('auth.login'))
    prof_key = current_user.id
    years = sorted([y for y in db.classes.distinct('year', {'professor_id': prof_key}) if y])
    divisions = sorted([d for d in db.classes.distinct('division', {'professor_id': prof_key}) if d])
    if not years:
        years = sorted([y for y in db.users.distinct('year', {'role': 'student'}) if y])
    if not divisions:
        divisions = sorted([d for d in db.users.distinct('division', {'role': 'student'}) if d])
    year = request.args.get('year')
    division = request.args.get('division')
    q = (request.args.get('q') or '').strip()
    query = {'role': 'student'}
    if year:
        query['year'] = year
    if division:
        query['division'] = division
    if q:
        try:
            rx = re.compile(re.escape(q), re.IGNORECASE)
            query['$or'] = [
                {'name': rx},
                {'roll_number': rx},
                {'year': rx},
                {'division': rx},
            ]
        except Exception:
            pass
    students = list(db.users.find(query).sort('roll_number', 1))
    rows = []
    for s in students:
        roll = s.get('roll_number')
        total = db.attendance_records.count_documents({'student_roll': roll})
        present = db.attendance_records.count_documents({'student_roll': roll, 'status': 'present'})
        absent = max(0, total - present)
        pct = (present / total * 100) if total > 0 else 0
        rows.append({
            'roll_number': roll,
            'name': s.get('name'),
            'year': s.get('year'),
            'division': s.get('division'),
            'present': present,
            'absent': absent,
            'total': total,
            'percentage': pct
        })
    return render_template('professor/students_list.html', years=years, divisions=divisions, selected_year=year, selected_division=division, q=q, rows=rows)


@professors_bp.route('/view-attendance/<class_id>')
@login_required
def view_attendance(class_id):
    """View attendance for a specific class"""
    if current_user.role != 'professor':
        flash('Access denied', 'error')
        return redirect(url_for('auth.login'))
    
    # Verify class belongs to professor
    class_info = db.classes.find_one({'_id': ObjectId(class_id), 'professor_id': current_user.id})
    if not class_info:
        flash('Class not found or access denied', 'error')
        return redirect(url_for('professors.dashboard'))
    
    # Get all students in this class
    students = list(db.users.find({
        'role': 'student',
        'year': class_info['year'],
        'division': class_info['division']
    }))
    
    # Get all attendance records for this class
    attendance_records = list(db.attendance_records.find(
        {'class_id': ObjectId(class_id)}
    ).sort('timestamp', -1))
    
    # Calculate attendance for each student
    student_attendance = {}
    for student in students:
        roll = student['roll_number']
        student_attendance[roll] = {
            'name': student['name'],
            'roll_number': roll,
            'present': 0,
            'absent': 0,
            'total': 0,
            'percentage': 0
        }
    
    # Count attendance
    for record in attendance_records:
        roll = record['student_roll']
        if roll in student_attendance:
            student_attendance[roll]['total'] += 1
            if record['status'] == 'present':
                student_attendance[roll]['present'] += 1
            else:
                student_attendance[roll]['absent'] += 1
    
    # Calculate percentages
    for roll in student_attendance:
        stats = student_attendance[roll]
        stats['percentage'] = (stats['present'] / stats['total'] * 100) if stats['total'] > 0 else 0
    
    # Convert ObjectId to string for template rendering
    if class_info:
        class_info['_id'] = str(class_info['_id'])
    
    return render_template('professor/attendance_view.html',
                         class_info=class_info,
                         student_attendance=sorted(student_attendance.values(), key=lambda x: x['roll_number']))


@professors_bp.route('/edit-attendance/<class_id>')
@login_required
def edit_attendance(class_id):
    """Edit attendance after face recognition - allows manual adjustment"""
    if current_user.role not in ('professor', 'admin'):
        flash('Access denied', 'error')
        return redirect(url_for('auth.login'))
    
    # Verify class belongs to professor
    if current_user.role == 'admin':
        class_info = db.classes.find_one({'_id': ObjectId(class_id)})
    else:
        class_info = db.classes.find_one({'_id': ObjectId(class_id), 'professor_id': current_user.id})
    if not class_info:
        flash('Class not found or access denied', 'error')
        return redirect(url_for('professors.dashboard'))
    
    session_id = request.args.get('session_id')
    pc = request.args.get('present_count')
    ac = request.args.get('absent_count')
    total = request.args.get('total')
    if pc is not None and ac is not None and total is not None:
        try:
            flash(f'Attendance marked successfully! {int(pc)} present, {int(ac)} absent out of {int(total)} students. You can now review and edit if needed.', 'success')
        except Exception:
            pass
    
    # Get all students in this class
    students = list(db.users.find({
        'role': 'student',
        'year': class_info['year'],
        'division': class_info['division']
    }).sort('roll_number', 1))
    
    # Get the most recent attendance records for this class
    if session_id:
        latest_records = list(db.attendance_records.find({
            'class_id': ObjectId(class_id),
            'session_id': session_id
        }))
    else:
        latest_records = list(db.attendance_records.find(
            {'class_id': ObjectId(class_id)}
        ).sort('timestamp', -1).limit(len(students) if students else 100))
    
    # Get the latest timestamp
    latest_timestamp = latest_records[0]['timestamp'] if latest_records else None
    
    # Create student list with current attendance status
    student_list = []
    enrolled_roll_numbers = set()
    for student in students:
        roll = student['roll_number']
        enrolled_roll_numbers.add(roll)
        # Check if student has attendance record for latest session
        latest_status = None
        for record in latest_records:
            if record['student_roll'] == roll and record['timestamp'] == latest_timestamp:
                latest_status = record['status']
                break
        
        student_list.append({
            'roll_number': roll,
            'name': student['name'],
            'status': latest_status if latest_status else 'absent'
        })
    
    # Get all other students from same year/division who aren't enrolled (for adding manually)
    # This allows adding students who might be in the class but not in the official enrollment
    all_students_same_class = list(db.users.find({
        'role': 'student',
        'year': class_info['year'],
        'division': class_info['division']
    }).sort('roll_number', 1))
    
    # Convert ObjectId to string for template rendering
    if class_info:
        class_info['_id'] = str(class_info['_id'])
    
    # Sort so present students appear first
    student_list_sorted = sorted(student_list, key=lambda s: (s['status'] != 'present', s['roll_number']))

    annotated_images = []
    try:
        if session_id:
            folder = CLASSROOM_FOLDER / str(class_id) / str(session_id)
            if folder.exists():
                for p in folder.glob('annotated_*'):
                    annotated_images.append(p.name)
    except Exception:
        pass
    enrolled_list = []
    try:
        enrolled_list = sorted(list(enrolled_roll_numbers))
    except Exception:
        enrolled_list = []
    all_students_simple = []
    try:
        all_students_simple = [{'roll_number': str(s.get('roll_number', '')), 'name': s.get('name', '')} for s in all_students_same_class]
    except Exception:
        all_students_simple = []
    return render_template('professor/edit_attendance.html',
                         class_info=class_info,
                         students=student_list_sorted,
                         all_students=all_students_same_class,
                         enrolled_roll_numbers=enrolled_roll_numbers,
                         enrolled_roll_numbers_list=enrolled_list,
                         all_students_simple=all_students_simple,
                         session_timestamp=latest_timestamp,
                         session_id=session_id,
                         annotated_images=annotated_images)
    


@professors_bp.route('/update-attendance/<class_id>', methods=['POST'])
@login_required
def update_attendance(class_id):
    """Update attendance records after manual editing"""
    if current_user.role not in ('professor', 'admin'):
        flash('Access denied', 'error')
        return redirect(url_for('auth.login'))
    
    # Verify class belongs to professor
    if current_user.role == 'admin':
        class_info = db.classes.find_one({'_id': ObjectId(class_id)})
    else:
        class_info = db.classes.find_one({'_id': ObjectId(class_id), 'professor_id': current_user.id})
    if not class_info:
        flash('Class not found or access denied', 'error')
        return redirect(url_for('professors.dashboard'))
    
    # Get attendance data from form
    attendance_data = request.form.to_dict()
    session_id = attendance_data.get('session_id')
    
    # Get all students in class
    students = list(db.users.find({
        'role': 'student',
        'year': class_info['year'],
        'division': class_info['division']
    }))
    
    # Get the latest timestamp to update those records
    if session_id:
        latest_records = list(db.attendance_records.find({
            'class_id': ObjectId(class_id),
            'session_id': session_id
        }))
    else:
        latest_records = list(db.attendance_records.find(
            {'class_id': ObjectId(class_id)}
        ).sort('timestamp', -1).limit(len(students) * 2))
    
    if not latest_records:
        flash('No attendance records found to update.', 'error')
        return redirect(url_for('professors.view_attendance', class_id=class_id))
    
    latest_timestamp = latest_records[0]['timestamp']
    
    # Delete old records for this session
    if session_id:
        db.attendance_records.delete_many({
            'class_id': ObjectId(class_id),
            'session_id': session_id
        })
    else:
        db.attendance_records.delete_many({
            'class_id': ObjectId(class_id),
            'timestamp': latest_timestamp
        })
    
    # Create new attendance records based on form data
    current_timestamp = datetime.now()
    new_records = []
    present_count = 0
    absent_count = 0
    processed_roll_numbers = set()
    
    # Process enrolled students
    for student in students:
        roll_number = student['roll_number']
        processed_roll_numbers.add(roll_number)
        # Get status from form (radio present/absent)
        status = attendance_data.get(f'status_{roll_number}', 'absent')
        
        if status == 'present':
            present_count += 1
        else:
            absent_count += 1
        
        record = {
            'class_id': ObjectId(class_id),
            'student_roll': roll_number,
            'timestamp': current_timestamp,
            'session_id': session_id,
            'status': status
        }
        new_records.append(record)
    
    # Process additional students who were manually added via radios
    for key, value in attendance_data.items():
        if key.startswith('status_'):
            roll_number = key.replace('status_', '')
            if roll_number not in processed_roll_numbers and value in ('present', 'absent'):
                if value == 'present':
                    present_count += 1
                else:
                    absent_count += 1
                new_records.append({
                    'class_id': ObjectId(class_id),
                    'student_roll': roll_number,
                    'timestamp': current_timestamp,
                    'session_id': session_id,
                    'status': value
                })
                processed_roll_numbers.add(roll_number)

    # Process additional present roll numbers list (comma-separated)
    add_rolls_raw = attendance_data.get('additional_present_rolls', '')
    if add_rolls_raw:
        for rr in [r.strip() for r in add_rolls_raw.split(',') if r.strip()]:
            if rr not in processed_roll_numbers:
                present_count += 1
                new_records.append({
                    'class_id': ObjectId(class_id),
                    'student_roll': rr,
                    'timestamp': current_timestamp,
                    'session_id': session_id,
                    'status': 'present'
                })
                processed_roll_numbers.add(rr)
    
    # Insert updated records
    if new_records:
        db.attendance_records.insert_many(new_records)
        try:
            log_activity(db, actor_id=ObjectId(current_user.id), role='professor', action='update_attendance', details={'present_count': present_count, 'absent_count': absent_count, 'session_id': session_id}, class_id=ObjectId(class_id))
        except Exception:
            pass
        if ENABLE_ATTENDANCE_NOTIFICATIONS:
            try:
                by_roll = {s['roll_number']: s for s in students}
                notif_docs = []
                for rec in new_records:
                    sdoc = by_roll.get(rec['student_roll'])
                    if not sdoc:
                        continue
                    msg = f"You were marked {rec['status'].upper()} for {class_info['class_name']} ({class_info['subject']})."
                    notif_docs.append({
                        'user_id': sdoc['_id'],
                        'roll_number': sdoc['roll_number'],
                        'class_id': ObjectId(class_id),
                        'session_id': session_id,
                        'status': rec['status'],
                        'message': msg,
                        'timestamp': current_timestamp,
                        'read': False,
                    })
                if notif_docs:
                    db.notifications.insert_many(notif_docs)
            except Exception:
                pass
        if ENABLE_ATTENDANCE_EMAILS and MAIL_SERVER and MAIL_USERNAME and MAIL_PASSWORD:
            roll_set = list({rec['student_roll'] for rec in new_records})
            sdocs = list(db.users.find({'role': 'student', 'roll_number': {'$in': roll_set}}))
            by_roll = {s['roll_number']: s for s in sdocs}
            def send_attendance_email(recipient, status):
                try:
                    subject = "Attendance Update"
                    pid = class_info.get('professor_id')
                    if pid:
                        try:
                            pid = pid if isinstance(pid, ObjectId) else ObjectId(pid)
                        except Exception:
                            pid = None
                    prof_user = db.users.find_one({'_id': pid}) if pid else None
                    prof_name = (prof_user or {}).get('name', 'Professor')
                    display = f"{class_info.get('subject','Class')} by Prof. {prof_name}"
                    body = (
                        f"Hello,\n\nYou were marked {status.upper()} for {display}\n"
                        f"on {current_timestamp.strftime('%Y-%m-%d %H:%M:%S')}.\n\nSession ID: {session_id}.\n\nRegards,\nAttendance System"
                    )
                    message = f"From: {MAIL_SENDER}\r\nTo: {recipient}\r\nSubject: {subject}\r\n\r\n{body}"
                    if MAIL_USE_TLS:
                        context = ssl.create_default_context()
                        with smtplib.SMTP(MAIL_SERVER, MAIL_PORT) as server:
                            server.starttls(context=context)
                            server.login(MAIL_USERNAME, MAIL_PASSWORD)
                            server.sendmail(MAIL_SENDER, recipient, message)
                    else:
                        with smtplib.SMTP(MAIL_SERVER, MAIL_PORT) as server:
                            server.login(MAIL_USERNAME, MAIL_PASSWORD)
                            server.sendmail(MAIL_SENDER, recipient, message)
                    return True
                except Exception:
                    return False
            sent_u = 0
            for rec in new_records:
                sdoc = by_roll.get(rec['student_roll'])
                if sdoc and sdoc.get('email'):
                    if send_attendance_email(sdoc['email'], rec['status']):
                        sent_u += 1
        flash(f'Attendance updated successfully! {present_count} present, {absent_count} absent.', 'success')
    else:
        flash('No attendance records to update.', 'warning')
    
    return redirect(url_for('professors.view_attendance', class_id=class_id))


@professors_bp.route('/attendance-sessions/<class_id>')
@login_required
def attendance_sessions(class_id):
    if current_user.role != 'professor':
        flash('Access denied', 'error')
        return redirect(url_for('auth.login'))

    class_info = db.classes.find_one({'_id': ObjectId(class_id), 'professor_id': current_user.id})
    if not class_info:
        flash('Class not found or access denied', 'error')
        return redirect(url_for('professors.dashboard'))

    pipeline = [
        {'$match': {'class_id': ObjectId(class_id)}},
        {'$group': {
            '_id': '$session_id',
            'session_id': {'$first': '$session_id'},
            'timestamp': {'$first': '$timestamp'},
            'present': {'$sum': {'$cond': [{'$eq': ['$status', 'present']}, 1, 0]}},
            'absent': {'$sum': {'$cond': [{'$eq': ['$status', 'absent']}, 1, 0]}},
            'total': {'$sum': 1}
        }},
        {'$sort': {'timestamp': -1}}
    ]
    sessions = list(db.attendance_records.aggregate(pipeline))

    if class_info:
        class_info['_id'] = str(class_info['_id'])

    return render_template('professor/attendance_sessions.html',
                           class_info=class_info,
                           sessions=sessions)


@professors_bp.route('/download-report/<class_id>')
@login_required
def download_report(class_id):
    """Download class attendance report as CSV"""
    if current_user.role != 'professor':
        flash('Access denied', 'error')
        return redirect(url_for('auth.login'))
    
    # Verify class belongs to professor
    class_info = db.classes.find_one({'_id': ObjectId(class_id), 'professor_id': current_user.id})
    if not class_info:
        flash('Class not found or access denied', 'error')
        return redirect(url_for('professors.dashboard'))
    
    # Generate CSV report
    csv_content = generate_class_attendance_report(ObjectId(class_id), db)
    
    # Create file-like object
    output = io.BytesIO()
    output.write(csv_content.encode('utf-8'))
    output.seek(0)
    
    # Generate filename
    filename = f'attendance_report_{class_info["class_name"]}_{datetime.now().strftime("%Y%m%d")}.csv'
    
    try:
        log_activity(db, actor_id=ObjectId(current_user.id), role='professor', action='download_class_report', details={'class_name': class_info['class_name']}, class_id=ObjectId(class_id))
    except Exception:
        pass
    return send_file(output, mimetype='text/csv',
                    as_attachment=True, download_name=filename)
