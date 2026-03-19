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
_env_upload_root = os.environ.get('UPLOAD_ROOT', '').strip()
if _env_upload_root:
    _expanded = os.path.expanduser(_env_upload_root)
    _root_path = Path(_expanded)
    UPLOAD_FOLDER = _root_path if _root_path.is_absolute() else (BASE_DIR / _root_path)
else:
    UPLOAD_FOLDER = BASE_DIR / 'static' / 'assets'
MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

# Paths
STUDENTS_FOLDER = UPLOAD_FOLDER / 'students'
CLASSROOM_FOLDER = UPLOAD_FOLDER / 'classroom'

# Create directories if they don't exist
STUDENTS_FOLDER.mkdir(parents=True, exist_ok=True)
CLASSROOM_FOLDER.mkdir(parents=True, exist_ok=True)

# Email/OTP Configuration
MAIL_SERVER = os.environ.get('MAIL_SERVER', '')
MAIL_PORT = int(os.environ.get('MAIL_PORT', '587'))
MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'True').lower() == 'true'
MAIL_USERNAME = os.environ.get('MAIL_USERNAME', '')
MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD', '')
MAIL_SENDER = os.environ.get('MAIL_SENDER', MAIL_USERNAME)
OTP_EXPIRY_MINUTES = int(os.environ.get('OTP_EXPIRY_MINUTES', '10'))
OTP_RESEND_COOLDOWN_SECONDS = int(os.environ.get('OTP_RESEND_COOLDOWN_SECONDS', '30'))

# Professor verification policy
REQUIRE_PROFESSOR_DOMAIN = os.environ.get('REQUIRE_PROFESSOR_DOMAIN', 'False').lower() == 'true'
ALLOWED_PROFESSOR_EMAIL_DOMAIN = os.environ.get('ALLOWED_PROFESSOR_EMAIL_DOMAIN', '')
PROFESSOR_INVITE_CODE = os.environ.get('PROFESSOR_INVITE_CODE', '')

# Face recognition thresholds
FACE_MATCH_TOLERANCE = float(os.environ.get('FACE_MATCH_TOLERANCE', '0.45'))
UNKNOWN_FACE_THRESHOLD = float(os.environ.get('UNKNOWN_FACE_THRESHOLD', '0.60'))
MIN_CONFIDENCE_MARGIN = float(os.environ.get('MIN_CONFIDENCE_MARGIN', '0.08'))
FACE_DETECTION_MODEL = os.environ.get('FACE_DETECTION_MODEL', 'hog')
MIN_MATCHES_FOR_PRESENT = int(os.environ.get('MIN_MATCHES_FOR_PRESENT', '2'))
FACE_DETECTION_WORKERS = int(os.environ.get('FACE_DETECTION_WORKERS', '4'))

# Notifications and emails
ENABLE_ATTENDANCE_EMAILS = os.environ.get('ENABLE_ATTENDANCE_EMAILS', 'False').lower() == 'true'
ENABLE_ATTENDANCE_NOTIFICATIONS = os.environ.get('ENABLE_ATTENDANCE_NOTIFICATIONS', 'True').lower() == 'true'

# Login security
LOGIN_BASE_COOLDOWN_SECONDS = int(os.environ.get('LOGIN_BASE_COOLDOWN_SECONDS', '30'))

# Session inactivity timeout (minutes)
INACTIVITY_TIMEOUT_MINUTES = int(os.environ.get('INACTIVITY_TIMEOUT_MINUTES', '15'))

# Admin registration
ADMIN_REGISTRATION_KEY = os.environ.get('ADMIN_REGISTRATION_KEY', '')

# Meraki MV camera integration
MERAKI_API_KEY = os.environ.get('MERAKI_API_KEY', '')
MERAKI_NETWORK_ID = os.environ.get('MERAKI_NETWORK_ID', '')
MERAKI_SNAPSHOT_INTERVAL_SECONDS = int(os.environ.get('MERAKI_SNAPSHOT_INTERVAL_SECONDS', '5'))
CAMERA_CLASSROOM_SERIALS = [s.strip() for s in os.environ.get('CAMERA_CLASSROOM_SERIALS', '').split(',') if s.strip()]
CAMERA_OUTDOOR_SERIALS = [s.strip() for s in os.environ.get('CAMERA_OUTDOOR_SERIALS', '').split(',') if s.strip()]
CAMERAS_CSV_PATH = os.environ.get('CAMERAS_CSV_PATH', '').strip()

# Unregistered detections storage
UNREGISTERED_FOLDER = UPLOAD_FOLDER / 'unregistered'
UNREGISTERED_FOLDER.mkdir(parents=True, exist_ok=True)

