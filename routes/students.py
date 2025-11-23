"""
Student routes for dashboard and attendance viewing
"""
from flask import Blueprint, render_template, request, send_file, flash, redirect, url_for
from flask_login import login_required, current_user
from bson import ObjectId
from pymongo import MongoClient
from datetime import datetime
from config import MONGODB_URI, DATABASE_NAME
from utils.report_generator import generate_student_attendance_report
import io

students_bp = Blueprint('students', __name__, url_prefix='/student')

# MongoDB connection
client = MongoClient(MONGODB_URI)
db = client[DATABASE_NAME]


@students_bp.route('/dashboard')
@login_required
def dashboard():
    """Student dashboard with attendance analytics"""
    if current_user.role != 'student':
        flash('Access denied', 'error')
        return redirect(url_for('auth.login'))
    
    # Get student data
    student_data = db.users.find_one({'_id': ObjectId(current_user.id)})
    if not student_data:
        flash('Student data not found', 'error')
        return redirect(url_for('auth.logout'))
    
    roll_number = student_data['roll_number']
    
    # Get all attendance records for this student
    attendance_records = list(db.attendance_records.find(
        {'student_roll': roll_number}
    ).sort('timestamp', -1))
    
    # Get class information
    class_ids = list(set([str(r['class_id']) for r in attendance_records]))
    classes = {str(cls['_id']): cls for cls in db.classes.find(
        {'_id': {'$in': [ObjectId(cid) for cid in class_ids]}}
    )}
    
    # Calculate overall statistics
    total_classes = len(attendance_records)
    present_count = sum(1 for r in attendance_records if r['status'] == 'present')
    absent_count = total_classes - present_count
    overall_percentage = (present_count / total_classes * 100) if total_classes > 0 else 0
    
    # Calculate subject-wise statistics
    subject_stats = {}
    for record in attendance_records:
        class_id = str(record['class_id'])
        class_info = classes.get(class_id, {})
        subject = class_info.get('subject', 'Unknown')
        
        if subject not in subject_stats:
            subject_stats[subject] = {'present': 0, 'absent': 0, 'total': 0}
        
        subject_stats[subject]['total'] += 1
        if record['status'] == 'present':
            subject_stats[subject]['present'] += 1
        else:
            subject_stats[subject]['absent'] += 1
    
    # Calculate percentages for each subject
    for subject in subject_stats:
        stats = subject_stats[subject]
        stats['percentage'] = (stats['present'] / stats['total'] * 100) if stats['total'] > 0 else 0
    
    # Prepare attendance records with class info
    detailed_records = []
    for record in attendance_records[:50]:  # Limit to last 50 records
        class_id = str(record['class_id'])
        class_info = classes.get(class_id, {})
        
        dt = record['timestamp']
        if isinstance(dt, str):
            dt = datetime.fromisoformat(dt)
        
        detailed_records.append({
            'date': dt.strftime('%Y-%m-%d'),
            'time': dt.strftime('%H:%M:%S'),
            'class_name': class_info.get('class_name', 'N/A'),
            'subject': class_info.get('subject', 'N/A'),
            'status': record['status']
        })
    
    return render_template('student/dashboard.html',
                         student=student_data,
                         overall_percentage=overall_percentage,
                         present_count=present_count,
                         absent_count=absent_count,
                         total_classes=total_classes,
                         subject_stats=subject_stats,
                         detailed_records=detailed_records)


@students_bp.route('/download-report')
@login_required
def download_report():
    """Download student attendance report as CSV"""
    if current_user.role != 'student':
        flash('Access denied', 'error')
        return redirect(url_for('auth.login'))
    
    # Get student data
    student_data = db.users.find_one({'_id': ObjectId(current_user.id)})
    if not student_data:
        flash('Student data not found', 'error')
        return redirect(url_for('students.dashboard'))
    
    roll_number = student_data['roll_number']
    
    # Generate CSV report
    csv_content = generate_student_attendance_report(roll_number, db)
    
    # Create file-like object
    output = io.BytesIO()
    output.write(csv_content.encode('utf-8'))
    output.seek(0)
    
    # Generate filename
    filename = f'attendance_report_{roll_number}_{datetime.now().strftime("%Y%m%d")}.csv'
    
    return send_file(output, mimetype='text/csv',
                    as_attachment=True, download_name=filename)

