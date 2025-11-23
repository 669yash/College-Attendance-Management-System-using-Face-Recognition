"""
CSV Report Generator for Attendance Records
"""
import csv
import io
from datetime import datetime


def generate_student_attendance_report(student_roll, db):
    """
    Generate CSV report for a specific student's attendance
    
    Args:
        student_roll: Student's roll number
        db: MongoDB database instance
    
    Returns:
        str: CSV content as string
    """
    # Get all attendance records for the student
    attendance_records = db.attendance_records.find(
        {'student_roll': student_roll}
    ).sort('timestamp', -1)
    
    # Get class information
    classes = {str(cls['_id']): cls for cls in db.classes.find()}
    
    # Create CSV in memory
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write header
    writer.writerow(['Date', 'Time', 'Class Name', 'Subject', 'Status'])
    
    # Write attendance records
    for record in attendance_records:
        class_id = str(record['class_id'])
        class_info = classes.get(class_id, {})
        
        dt = record['timestamp']
        if isinstance(dt, str):
            dt = datetime.fromisoformat(dt)
        
        writer.writerow([
            dt.strftime('%Y-%m-%d'),
            dt.strftime('%H:%M:%S'),
            class_info.get('class_name', 'N/A'),
            class_info.get('subject', 'N/A'),
            record['status']
        ])
    
    return output.getvalue()


def generate_class_attendance_report(class_id, db):
    """
    Generate CSV report for all students in a class
    
    Args:
        class_id: Class ID
        db: MongoDB database instance
    
    Returns:
        str: CSV content as string
    """
    # Get class information
    class_info = db.classes.find_one({'_id': class_id})
    if not class_info:
        return ""
    
    # Get all attendance records for this class
    attendance_records = db.attendance_records.find(
        {'class_id': class_id}
    ).sort('timestamp', -1)
    
    # Get all students in the class (based on year and division)
    students = list(db.users.find({
        'role': 'student',
        'year': class_info.get('year'),
        'division': class_info.get('division')
    }))
    
    # Create a dictionary to aggregate attendance by student
    student_attendance = {}
    for student in students:
        student_attendance[student['roll_number']] = {
            'name': student['name'],
            'present': 0,
            'absent': 0,
            'total': 0
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
    
    # Create CSV in memory
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write header
    writer.writerow([
        'Roll Number',
        'Student Name',
        'Present',
        'Absent',
        'Total Classes',
        'Attendance Percentage'
    ])
    
    # Write student attendance data
    for roll, data in sorted(student_attendance.items()):
        percentage = (data['present'] / data['total'] * 100) if data['total'] > 0 else 0
        writer.writerow([
            roll,
            data['name'],
            data['present'],
            data['absent'],
            data['total'],
            f"{percentage:.2f}%"
        ])
    
    return output.getvalue()

