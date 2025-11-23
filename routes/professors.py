"""
Professor routes for dashboard and class management
"""
from flask import Blueprint, render_template, request, flash, redirect, url_for, send_file
from flask_login import login_required, current_user
from pymongo import MongoClient
from bson import ObjectId
from datetime import datetime
from config import MONGODB_URI, DATABASE_NAME, CLASSROOM_FOLDER
from utils.helpers import save_uploaded_file, ensure_directory
from utils.report_generator import generate_class_attendance_report
from utils.face_recognition_interface import mark_attendance_from_classroom_images
import io

professors_bp = Blueprint('professors', __name__, url_prefix='/professor')

# MongoDB connection
client = MongoClient(MONGODB_URI)
db = client[DATABASE_NAME]


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
    time_slot = request.form.get('time_slot')
    
    if not all([class_name, subject, year, division, time_slot]):
        flash('Please fill in all fields', 'error')
        return redirect(url_for('professors.dashboard'))
    
    # Create class document
    class_data = {
        'class_name': class_name,
        'subject': subject,
        'year': year,
        'division': division,
        'time_slot': time_slot,
        'professor_id': current_user.id,
        'created_at': datetime.now()
    }
    
    result = db.classes.insert_one(class_data)
    
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
    
    if request.method == 'POST':
        # Handle file uploads (4-5 classroom images)
        uploaded_files = request.files.getlist('classroom_images')
        valid_files = [f for f in uploaded_files if f.filename]
        
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
        
        # Call face recognition interface to mark attendance
        # This will process images and return attendance results
        attendance_results = mark_attendance_from_classroom_images(
            class_id, classroom_folder, timestamp
        )
        
        # Debug logging
        print(f"\n[DEBUG] Attendance results received: {attendance_results}")
        print(f"[DEBUG] Number of results: {len(attendance_results)}")
        
        # Get all students in this class (based on year and division)
        students = list(db.users.find({
            'role': 'student',
            'year': class_info['year'],
            'division': class_info['division']
        }))
        
        print(f"[DEBUG] Students in class: {len(students)}")
        for s in students:
            print(f"[DEBUG]   - {s['roll_number']}: {s['name']}")
        
        # Get all roll numbers from attendance_results (includes matched students)
        all_roll_numbers = set(attendance_results.keys())
        
        # Also include students from class query
        for student in students:
            all_roll_numbers.add(student['roll_number'])
        
        print(f"[DEBUG] Total students to process: {len(all_roll_numbers)}")
        
        # Get full student data for all roll numbers
        all_students = list(db.users.find({
            'role': 'student',
            'roll_number': {'$in': list(all_roll_numbers)}
        }))
        
        # Create attendance records
        current_timestamp = datetime.now()
        attendance_records = []
        present_count = 0
        absent_count = 0
        
        # Process all students (from class and matched)
        for roll_number in all_roll_numbers:
            # Check if student was detected in images
            if roll_number in attendance_results and attendance_results[roll_number] == 'present':
                status = 'present'
                present_count += 1
            else:
                status = 'absent'
                absent_count += 1
            
            record = {
                'class_id': ObjectId(class_id),
                'student_roll': roll_number,
                'timestamp': current_timestamp,
                'status': status
            }
            attendance_records.append(record)
        
        print(f"[DEBUG] Created {len(attendance_records)} attendance records")
        print(f"[DEBUG] Present: {present_count}, Absent: {absent_count}")
        
        # Insert attendance records
        if attendance_records:
            result = db.attendance_records.insert_many(attendance_records)
            print(f"[DEBUG] Inserted {len(result.inserted_ids)} records into database")
            flash(f'Attendance marked successfully! {present_count} present, {absent_count} absent out of {len(attendance_records)} students. You can now review and edit if needed.', 'success')
            # Redirect to edit page so professor can review and manually adjust
            return redirect(url_for('professors.edit_attendance', class_id=class_id, session_id=timestamp))
        else:
            flash('No students found in this class.', 'warning')
        return redirect(url_for('professors.view_attendance', class_id=class_id))
    
    # Convert ObjectId to string for template rendering
    if class_info:
        class_info['_id'] = str(class_info['_id'])
    
    return render_template('professor/mark_attendance.html', class_info=class_info)


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
    if current_user.role != 'professor':
        flash('Access denied', 'error')
        return redirect(url_for('auth.login'))
    
    # Verify class belongs to professor
    class_info = db.classes.find_one({'_id': ObjectId(class_id), 'professor_id': current_user.id})
    if not class_info:
        flash('Class not found or access denied', 'error')
        return redirect(url_for('professors.dashboard'))
    
    # Get session_id from query params (timestamp from latest attendance marking)
    session_id = request.args.get('session_id')
    
    # Get all students in this class
    students = list(db.users.find({
        'role': 'student',
        'year': class_info['year'],
        'division': class_info['division']
    }).sort('roll_number', 1))
    
    # Get the most recent attendance records for this class
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
    
    return render_template('professor/edit_attendance.html',
                         class_info=class_info,
                         students=student_list,
                         all_students=all_students_same_class,
                         enrolled_roll_numbers=enrolled_roll_numbers,
                         session_timestamp=latest_timestamp)


@professors_bp.route('/update-attendance/<class_id>', methods=['POST'])
@login_required
def update_attendance(class_id):
    """Update attendance records after manual editing"""
    if current_user.role != 'professor':
        flash('Access denied', 'error')
        return redirect(url_for('auth.login'))
    
    # Verify class belongs to professor
    class_info = db.classes.find_one({'_id': ObjectId(class_id), 'professor_id': current_user.id})
    if not class_info:
        flash('Class not found or access denied', 'error')
        return redirect(url_for('professors.dashboard'))
    
    # Get attendance data from form
    attendance_data = request.form.to_dict()
    
    # Get all students in class
    students = list(db.users.find({
        'role': 'student',
        'year': class_info['year'],
        'division': class_info['division']
    }))
    
    # Get the latest timestamp to update those records
    latest_records = list(db.attendance_records.find(
        {'class_id': ObjectId(class_id)}
    ).sort('timestamp', -1).limit(len(students) * 2))  # Increased limit to account for additional students
    
    if not latest_records:
        flash('No attendance records found to update.', 'error')
        return redirect(url_for('professors.view_attendance', class_id=class_id))
    
    latest_timestamp = latest_records[0]['timestamp']
    
    # Delete old records for this session
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
        # Get status from form (default to absent if not checked)
        status = attendance_data.get(f'status_{roll_number}', 'absent')
        
        if status == 'present':
            present_count += 1
        else:
            absent_count += 1
        
        record = {
            'class_id': ObjectId(class_id),
            'student_roll': roll_number,
            'timestamp': current_timestamp,
            'status': status
        }
        new_records.append(record)
    
    # Process additional students who were manually added
    # Look for status_* keys that don't match enrolled students
    for key, value in attendance_data.items():
        if key.startswith('status_') and value == 'present':
            roll_number = key.replace('status_', '')
            # If this student is not in the enrolled list but was marked present, add them
            if roll_number not in processed_roll_numbers:
                # Verify student exists (but allow adding even if not found for flexibility)
                student = db.users.find_one({
                    'role': 'student',
                    'roll_number': roll_number
                })
                
                # Add the record even if student doesn't exist in database
                # This allows professors to add students who might not be registered yet
                present_count += 1
                record = {
                    'class_id': ObjectId(class_id),
                    'student_roll': roll_number,
                    'timestamp': current_timestamp,
                    'status': 'present'
                }
                new_records.append(record)
                processed_roll_numbers.add(roll_number)
    
    # Insert updated records
    if new_records:
        db.attendance_records.insert_many(new_records)
        flash(f'Attendance updated successfully! {present_count} present, {absent_count} absent.', 'success')
    else:
        flash('No attendance records to update.', 'warning')
    
    return redirect(url_for('professors.view_attendance', class_id=class_id))


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
    
    return send_file(output, mimetype='text/csv',
                    as_attachment=True, download_name=filename)

