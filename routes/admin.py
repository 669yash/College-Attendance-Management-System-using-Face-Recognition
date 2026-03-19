"""
Admin routes for viewing activity logs
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file, jsonify
from flask_login import login_required, current_user
from pymongo import MongoClient
from bson.objectid import ObjectId
from datetime import datetime
from config import MONGODB_URI, DATABASE_NAME, UNREGISTERED_FOLDER, CLASSROOM_FOLDER, CAMERA_CLASSROOM_SERIALS, CAMERA_OUTDOOR_SERIALS
from datetime import datetime, timedelta
from utils.face_recognition_interface import encode_student_faces, process_unregistered_from_image, mark_attendance_from_classroom_images
from utils.meraki_integration import fetch_snapshot_to_folder, get_categorized_cameras, get_or_fetch_cached_snapshot, get_camera_catalog
from utils.helpers import ensure_directory
from pathlib import Path
import threading
import time
from flask import send_file, make_response

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

client = MongoClient(MONGODB_URI)
db = client[DATABASE_NAME]

# Dictionary to hold active scheduling threads
active_schedules = {}


@admin_bp.route('/activity-log')
@login_required
def activity_log():
    if current_user.role != 'admin':
        flash('Access denied', 'error')
        return redirect(url_for('auth.login'))

    page = int(request.args.get('page', '1'))
    per_page = int(request.args.get('per_page', '50'))
    skip = max(0, (page - 1) * per_page)
    action = request.args.get('action')
    role = request.args.get('role')

    query = {}
    if action:
        query['action'] = action
    if role:
        query['role'] = role

    cursor = db.activity_logs.find(query).sort('timestamp', -1).skip(skip).limit(per_page)
    logs = list(cursor)

    return render_template('admin/activity_log.html', logs=logs, page=page, per_page=per_page, action=action, role=role)


@admin_bp.route('/reencode-faces', methods=['POST'])
@login_required
def reencode_faces():
    if current_user.role != 'admin':
        flash('Access denied', 'error')
        return redirect(url_for('auth.login'))
    students = list(db.users.find({'role': 'student'}))
    ok = 0
    fail = 0
    for s in students:
        roll = s.get('roll_number')
        if not roll:
            continue
        try:
            if encode_student_faces(roll):
                ok += 1
            else:
                fail += 1
        except Exception:
            fail += 1
    flash(f'Re-encoded faces. Success: {ok}, Failed: {fail}', 'info')
    return redirect(url_for('admin.activity_log'))

@admin_bp.route('/unregistered')
@login_required
def unregistered():
    if current_user.role != 'admin':
        flash('Access denied', 'error')
        return redirect(url_for('auth.login'))
    page = int(request.args.get('page', '1'))
    per_page = int(request.args.get('per_page', '50'))
    skip = max(0, (page - 1) * per_page)
    rows = list(db.unregistered_detections.find({}).sort('timestamp', -1).skip(skip).limit(per_page))
    return render_template('admin/unregistered.html', rows=rows, page=page, per_page=per_page)

@admin_bp.route('/unregistered-image')
@login_required
def unregistered_image():
    if current_user.role != 'admin':
        return redirect(url_for('auth.login'))
    path = request.args.get('path')
    if not path:
        return redirect(url_for('admin.unregistered'))
    p = UNREGISTERED_FOLDER / Path(path).name if isinstance(path, str) else None
    try:
        fp = Path(path)
        if fp.exists():
            return send_file(str(fp))
        if p and p.exists():
            return send_file(str(p))
    except Exception:
        pass
    flash('Image not found', 'error')
    return redirect(url_for('admin.unregistered'))

@admin_bp.route('/poll-cameras', methods=['POST'])
@login_required
def poll_cameras():
    if current_user.role != 'admin':
        flash('Access denied', 'error')
        return redirect(url_for('auth.login'))
    serials = CAMERA_CLASSROOM_SERIALS + CAMERA_OUTDOOR_SERIALS
    captured = 0
    flagged = 0
    for serial in serials:
        folder = UNREGISTERED_FOLDER
        ensure_directory(folder)
        img_path = fetch_snapshot_to_folder(serial, folder, prefix=f"{serial}")
        if img_path:
            captured += 1
            out = process_unregistered_from_image(img_path, folder, location=serial, camera_serial=serial)
            flagged += int(out.get('unknown_faces', 0))
    flash(f'Polled {len(serials)} cameras. Snapshots: {captured}, Unregistered flagged: {flagged}', 'info')
    return redirect(url_for('admin.unregistered'))

@admin_bp.route('/mark-attendance-from-camera', methods=['POST'])
@login_required
def mark_attendance_from_camera():
    if current_user.role != 'admin':
        flash('Access denied', 'error')
        return redirect(url_for('auth.login'))
    class_id = request.form.get('class_id')
    serial = request.form.get('serial')
    if not serial:
        loc = request.form.get('location')
        if loc:
            catalog = get_camera_catalog()
            for c in catalog:
                if (c.get('location') or '').strip() == loc.strip():
                    serial = c.get('serial')
                    break
    if not class_id or not serial:
        flash('Class and camera serial are required', 'error')
        return redirect(url_for('admin.camera_management'))
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    folder = CLASSROOM_FOLDER / str(class_id) / ts
    ensure_directory(folder)
    saved = 0
    for i in range(4):
        p = fetch_snapshot_to_folder(serial, folder, prefix=f"{serial}_{i+1}")
        if p:
            saved += 1
    if saved < 4:
        flash('Failed to capture enough snapshots for attendance', 'error')
        return redirect(url_for('admin.unregistered'))
    result = mark_attendance_from_classroom_images(class_id, str(folder), ts)
    attendance = result.get('attendance') or {}
    metrics = result.get('metrics') or {}
    students_rolls = set(attendance.keys())
    try:
        cls_obj = db.classes.find_one({'_id': ObjectId(class_id)})
        stu_docs = list(db.users.find({'role': 'student', 'year': cls_obj['year'], 'division': cls_obj['division']}))
        for s in stu_docs:
            students_rolls.add(s.get('roll_number'))
    except Exception:
        pass
    now = datetime.now()
    present = 0
    absent = 0
    for roll in students_rolls:
        st = 'present' if attendance.get(roll) == 'present' else 'absent'
        if st == 'present':
            present += 1
        else:
            absent += 1
        try:
            db.attendance_records.insert_one({
                'class_id': ObjectId(class_id),
                'student_roll': roll,
                'timestamp': now,
                'session_id': ts,
                'status': st
            })
        except Exception:
            pass
    flash(f'Attendance marked. Present: {present} Absent: {absent}', 'success')
    return redirect(url_for('professors.edit_attendance', class_id=class_id, session_id=ts, present_count=present, absent_count=absent, total=present+absent))

def _run_scheduled_attendance(camera_serial, class_id, start_time, end_time, interval_minutes):
    with admin_bp.app_context():
        while datetime.now() < end_time:
            if datetime.now() >= start_time:
                try:
                    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
                    folder = CLASSROOM_FOLDER / str(class_id) / ts
                    ensure_directory(folder)
                    saved = 0
                    for i in range(4):
                        p = fetch_snapshot_to_folder(camera_serial, folder, prefix=f"{camera_serial}_{i+1}")
                        if p:
                            saved += 1
                    if saved >= 4:
                        result = mark_attendance_from_classroom_images(class_id, str(folder), ts)
                        attendance = result.get('attendance') or {}
                        metrics = result.get('metrics') or {}
                        students_rolls = set(attendance.keys())
                        try:
                            cls_obj = db.classes.find_one({'_id': ObjectId(class_id)})
                            stu_docs = list(db.users.find({'role': 'student', 'year': cls_obj['year'], 'division': cls_obj['division']}))
                            for s in stu_docs:
                                students_rolls.add(s.get('roll_number'))
                        except Exception:
                            pass
                        now = datetime.now()
                        present = 0
                        absent = 0
                        for roll in students_rolls:
                            st = 'present' if attendance.get(roll) == 'present' else 'absent'
                            if st == 'present':
                                present += 1
                            else:
                                absent += 1
                            try:
                                db.attendance_records.insert_one({
                                    'class_id': ObjectId(class_id),
                                    'student_roll': roll,
                                    'timestamp': now,
                                    'session_id': ts,
                                    'status': st
                                })
                            except Exception:
                                pass
                        print(f"Scheduled attendance marked for class {class_id} using camera {camera_serial}. Present: {present}, Absent: {absent}")
                    else:
                        print(f"Failed to capture enough snapshots for scheduled attendance for class {class_id} using camera {camera_serial}.")
                except Exception as e:
                    print(f"Error during scheduled attendance for class {class_id} using camera {camera_serial}: {e}")
            time.sleep(interval_minutes * 60)
        print(f"Scheduled attendance for class {class_id} using camera {camera_serial} has ended.")
        if camera_serial in active_schedules:
            del active_schedules[camera_serial]

@admin_bp.route('/schedule-attendance', methods=['POST'])
@login_required
def schedule_attendance():
    if current_user.role != 'admin':
        flash('Access denied', 'error')
        return redirect(url_for('auth.login'))

    camera_serial = request.form.get('camera_serial')
    class_id = request.form.get('class_id')
    start_time_str = request.form.get('start_time')
    end_time_str = request.form.get('end_time')
    interval_minutes = int(request.form.get('interval_minutes'))

    if not all([camera_serial, class_id, start_time_str, end_time_str, interval_minutes]):
        flash('All scheduling fields are required.', 'error')
        return redirect(url_for('admin.camera_management'))

    try:
        start_time = datetime.fromisoformat(start_time_str)
        end_time = datetime.fromisoformat(end_time_str)
    except ValueError:
        flash('Invalid date/time format.', 'error')
        return redirect(url_for('admin.camera_management'))

    if start_time >= end_time:
        flash('Start time must be before end time.', 'error')
        return redirect(url_for('admin.camera_management'))
    
    if camera_serial in active_schedules and active_schedules[camera_serial].is_alive():
        flash(f'Attendance scheduling for camera {camera_serial} is already active.', 'info')
        return redirect(url_for('admin.camera_management'))

    # Start a new thread for scheduled attendance
    scheduler_thread = threading.Thread(
        target=_run_scheduled_attendance,
        args=(camera_serial, class_id, start_time, end_time, interval_minutes)
    )
    scheduler_thread.daemon = True
    scheduler_thread.start()
    active_schedules[camera_serial] = scheduler_thread

    flash(f'Attendance scheduled for camera {camera_serial} from {start_time_str} to {end_time_str} every {interval_minutes} minutes.', 'success')
    return redirect(url_for('admin.camera_management'))

@admin_bp.route('/camera-management')
@login_required
def camera_management():
    if current_user.role != 'admin':
        flash('Access denied', 'error')
        return redirect(url_for('auth.login'))
    
    categorized_cameras = get_categorized_cameras()
    classroom_cameras = categorized_cameras.get('classroom', [])
    outdoor_cameras = categorized_cameras.get('outdoor', [])
    classes = list(db.classes.find({}))
    catalog = get_camera_catalog()
    serials = [c.get('serial') for c in catalog]
    locations = sorted(list({(c.get('location') or '').strip() for c in catalog if (c.get('location') or '').strip()}))

    return render_template('admin/camera_management.html', 
                           classroom_cameras=classroom_cameras, 
                           outdoor_cameras=outdoor_cameras,
                           classes=classes,
                           serials=serials,
                           locations=locations)

@admin_bp.route('/camera-snapshot')
@login_required
def camera_snapshot():
    if current_user.role != 'admin':
        return make_response('', 204)
    serial = request.args.get('serial')
    if not serial:
        return make_response('', 204)
    p = get_or_fetch_cached_snapshot(serial)
    if not p:
        # No snapshot available; avoid redirect loops for <img> tags
        return make_response('', 204)
    try:
        return send_file(p)
    except Exception:
        return make_response('', 204)
