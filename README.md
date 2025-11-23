# College Attendance Marking & Management System

A production-ready Flask-based web application for automated attendance marking using face recognition technology.

## Features

### Student Features
- **Registration**: Register with name, roll number, year, division, email, and password
- **Face Image Upload**: Upload 4-5 face images during registration
- **Login**: Secure authentication using email and password
- **Dashboard**: View attendance analytics (overall & subject-wise)
- **Detailed Records**: View detailed attendance history
- **CSV Reports**: Download attendance reports in CSV format

### Professor Features
- **Registration/Login**: Create account and login
- **Class Management**: Create classes with subject, year, division, and time slot
- **Attendance Marking**: Upload 4-5 classroom images to automatically mark attendance
- **View Attendance**: View attendance records for all students in a class
- **CSV Reports**: Download class attendance reports

## Tech Stack

- **Backend**: Flask 3.0.0
- **Frontend**: Jinja2 Templates + Tailwind CSS
- **Database**: MongoDB Atlas (pymongo)
- **Authentication**: Flask-Login + bcrypt
- **File Uploads**: Saved under `static/assets/`
- **ML Integration**: Hooks provided for external face recognition model

## Project Structure

```
project/
│── app.py                      # Main Flask application
│── config.py                   # Configuration settings
│── requirements.txt            # Python dependencies
│── .env.example                # Environment variables template
│── static/
│     └── assets/
│          ├── students/        # Student face images
│          └── classroom/       # Classroom images
│── templates/
│     ├── base.html             # Base template
│     ├── auth/
│     │     ├── login.html
│     │     └── register.html
│     ├── student/
│     │     └── dashboard.html
│     └── professor/
│           ├── dashboard.html
│           ├── mark_attendance.html
│           └── attendance_view.html
│── routes/
│     ├── auth.py               # Authentication routes
│     ├── students.py           # Student routes
│     ├── professors.py         # Professor routes
│     └── classes.py            # Class management routes
│── utils/
│     ├── report_generator.py   # CSV report generation
│     ├── face_recognition_interface.py  # ML model integration hooks
│     └── helpers.py            # Helper functions
│── models/
│     └── user.py               # User model for Flask-Login
```

## Installation

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd IAttendance
   ```

2. **Create virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Set up environment variables**
   ```bash
   cp .env.example .env
   ```
   Edit `.env` and add your MongoDB Atlas connection string and secret key.

5. **Run the application**
   ```bash
   python app.py
   ```

   The application will be available at `http://localhost:5000`

## Configuration

### Environment Variables

Create a `.env` file with the following variables:

```env
SECRET_KEY=your-secret-key-here
DEBUG=True
MONGODB_URI=mongodb+srv://username:password@cluster.mongodb.net/?retryWrites=true&w=majority
DATABASE_NAME=attendance_system
```

### MongoDB Atlas Setup

1. Create a MongoDB Atlas account
2. Create a new cluster
3. Get your connection string
4. Update `MONGODB_URI` in `.env`

## Database Schema

### Collection: `users`
```json
{
  "_id": ObjectId,
  "name": "string",
  "email": "string",
  "hashed_password": "string",
  "role": "student" | "professor",
  "roll_number": "string" (students only),
  "year": "string" (students only),
  "division": "string" (students only)
}
```

### Collection: `classes`
```json
{
  "_id": ObjectId,
  "class_name": "string",
  "subject": "string",
  "year": "string",
  "division": "string",
  "time_slot": "string",
  "professor_id": "string",
  "created_at": DateTime
}
```

### Collection: `attendance_records`
```json
{
  "_id": ObjectId,
  "class_id": ObjectId,
  "student_roll": "string",
  "timestamp": DateTime,
  "status": "present" | "absent"
}
```

## Face Recognition System

**✅ COMPLETE WORKING FACE RECOGNITION IMPLEMENTED**

The system includes a fully functional face recognition system using the `face_recognition` library:

### Features:
- **Automatic Face Encoding**: Student faces are encoded during registration
- **Real-time Detection**: Detects faces in classroom images
- **Intelligent Matching**: Matches detected faces with student encodings
- **Robust Recognition**: Uses averaged encodings from multiple images
- **MongoDB Storage**: Face encodings stored in database for fast retrieval

### How It Works:

1. **Student Registration**:
   - Student uploads 4-5 face images
   - System detects and encodes faces automatically
   - Creates averaged face encoding (128-dimensional vector)
   - Stores encoding in MongoDB `face_encodings` collection

2. **Attendance Marking**:
   - Professor uploads 4-5 classroom images
   - System detects all faces in images
   - Compares each face with stored student encodings
   - Uses distance metric (tolerance: 0.6) for matching
   - Automatically marks attendance based on matches

### Installation:

See `FACE_RECOGNITION_SETUP.md` for detailed installation instructions.

Quick install:
```bash
pip install face-recognition opencv-python numpy Pillow
```

**Note**: `face-recognition` requires `dlib`, which may need additional setup. See the setup guide for OS-specific instructions.

## Usage

### Student Workflow

1. Register with email, password, roll number, year, division
2. Upload 4-5 face images during registration
3. Login to access dashboard
4. View attendance statistics and download reports

### Professor Workflow

1. Register/Login as professor
2. Create classes with subject, year, division, time slot
3. Mark attendance by uploading 4-5 classroom images
4. View attendance records for each class
5. Download attendance reports

## Security Features

- Password hashing using bcrypt
- Session management with Flask-Login
- Role-based access control
- Secure file upload validation

## License

This project is licensed under the MIT License.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## Support

For issues and questions, please open an issue on the repository.

