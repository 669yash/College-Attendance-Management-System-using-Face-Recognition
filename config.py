"""
Configuration file for College Attendance Marking & Management System
"""
import os
from pathlib import Path

# Base directory
BASE_DIR = Path(__file__).parent

# Flask Configuration
SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
DEBUG = os.environ.get('DEBUG', 'True').lower() == 'true'

# MongoDB Configuration
MONGODB_URI = os.environ.get('MONGODB_URI', 'mongodb://localhost:27017/')
DATABASE_NAME = os.environ.get('DATABASE_NAME', 'attendance_system')

# File Upload Configuration
UPLOAD_FOLDER = BASE_DIR / 'static' / 'assets'
MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

# Paths
STUDENTS_FOLDER = UPLOAD_FOLDER / 'students'
CLASSROOM_FOLDER = UPLOAD_FOLDER / 'classroom'

# Create directories if they don't exist
STUDENTS_FOLDER.mkdir(parents=True, exist_ok=True)
CLASSROOM_FOLDER.mkdir(parents=True, exist_ok=True)

