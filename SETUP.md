# Quick Setup Guide

## Prerequisites
- Python 3.8 or higher
- MongoDB Atlas account (or local MongoDB instance)
- pip package manager

## Step-by-Step Setup

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure Environment
Create a `.env` file in the root directory:
```env
SECRET_KEY=your-secret-key-here-change-this-in-production
DEBUG=True
MONGODB_URI=mongodb+srv://username:password@cluster.mongodb.net/?retryWrites=true&w=majority
DATABASE_NAME=attendance_system
```

### 3. MongoDB Atlas Setup
1. Go to [MongoDB Atlas](https://www.mongodb.com/cloud/atlas)
2. Create a free cluster
3. Create a database user
4. Whitelist your IP address (or use 0.0.0.0/0 for development)
5. Get your connection string and update `MONGODB_URI` in `.env`

### 4. Run the Application
```bash
python app.py
```

The application will be available at `http://localhost:5000`

## First-Time Usage

### Register as Professor
1. Go to `/register`
2. Select "Professor" role
3. Fill in name, email, and password
4. Submit registration

### Register as Student
1. Go to `/register`
2. Select "Student" role
3. Fill in all required fields
4. Upload 4-5 clear face images
5. Submit registration

### Professor Workflow
1. Login as professor
2. Create a class (subject, year, division, time slot)
3. Click "Mark Attendance" for a class
4. Upload 4-5 classroom images
5. System processes images and marks attendance
6. View attendance records and download reports

### Student Workflow
1. Login as student
2. View dashboard with attendance statistics
3. Check subject-wise attendance
4. View detailed attendance records
5. Download CSV report

## Face Recognition Integration

The system provides integration hooks in `utils/face_recognition_interface.py`.

To integrate your ML model:
1. Implement your face recognition script
2. Update `mark_attendance_from_classroom_images()` function
3. The function should return: `{'roll_number': 'present'/'absent', ...}`

Example integration:
```python
def mark_attendance_from_classroom_images(class_id, classroom_images_path, timestamp):
    # Call your ML model script
    result = subprocess.run([
        'python', 
        'ml_model/face_recognition.py',
        '--classroom_images', str(classroom_images_path),
        '--class_id', str(class_id),
        '--timestamp', str(timestamp)
    ], capture_output=True, text=True)
    
    # Parse result and return attendance dictionary
    return parse_ml_result(result)
```

## Troubleshooting

### MongoDB Connection Error
- Verify your MongoDB Atlas connection string
- Check if your IP is whitelisted
- Ensure database user credentials are correct

### File Upload Issues
- Check that `static/assets/` directories exist
- Verify file permissions
- Ensure file size is under 16MB

### Import Errors
- Ensure all dependencies are installed: `pip install -r requirements.txt`
- Check Python version (3.8+)
- Verify virtual environment is activated

## Production Deployment

For production:
1. Set `DEBUG=False` in `.env`
2. Use a strong `SECRET_KEY`
3. Configure proper MongoDB connection with authentication
4. Use a production WSGI server (e.g., Gunicorn)
5. Set up proper file storage (consider cloud storage for images)
6. Enable HTTPS
7. Configure proper error logging

## Support

For issues or questions, refer to the main README.md file.

