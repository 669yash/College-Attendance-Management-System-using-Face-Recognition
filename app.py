"""
Main Flask application for College Attendance Marking & Management System
"""
from flask import Flask, render_template, redirect, url_for, session, request, flash
from flask_login import LoginManager, logout_user, current_user
from pymongo import MongoClient
from bson import ObjectId
from dotenv import load_dotenv
import uuid
import os

# Load environment variables
load_dotenv()

# Import configuration
from config import MONGODB_URI, DATABASE_NAME, SECRET_KEY, INACTIVITY_TIMEOUT_MINUTES
from datetime import datetime, timedelta
from utils.helpers import log_activity

# Import routes
from routes.auth import auth_bp
from routes.students import students_bp
from routes.professors import professors_bp
from routes.classes import classes_bp
from routes.admin import admin_bp

# Import User model
from models.user import User

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = SECRET_KEY
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=INACTIVITY_TIMEOUT_MINUTES)
app.config['BOOT_TOKEN'] = str(uuid.uuid4())

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'auth.login'
login_manager.login_message = 'Please login to access this page.'
login_manager.login_message_category = 'info'

# MongoDB connection
client = MongoClient(MONGODB_URI)
db = client[DATABASE_NAME]

# Create face_encodings collection index
try:
    db.face_encodings.create_index('roll_number', unique=True)
except:
    pass


@login_manager.user_loader
def load_user(user_id):
    """Load user for Flask-Login"""
    try:
        user_data = db.users.find_one({'_id': ObjectId(user_id)})
        if user_data:
            return User(
                str(user_data['_id']),
                user_data['email'],
                user_data['role'],
                user_data.get('roll_number')
            )
    except Exception as e:
        print(f"Error loading user: {e}")
    return None


# Register blueprints
app.register_blueprint(auth_bp)
app.register_blueprint(students_bp)
app.register_blueprint(professors_bp)
app.register_blueprint(classes_bp)
app.register_blueprint(admin_bp)


@app.route('/')
def index():
    """Home page - redirect to login"""
    return redirect(url_for('auth.login'))


@app.errorhandler(404)
def not_found(error):
    """Handle 404 errors"""
    return render_template('errors/404.html'), 404


@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors"""
    return render_template('errors/500.html'), 500


@app.before_request
def enforce_inactivity_logout():
    try:
        # Skip for static files and login-related endpoints to avoid loops
        if request.endpoint and (
            request.endpoint.startswith('static') or
            request.endpoint in {'auth.login', 'auth.register', 'auth.verify_email', 'auth.forgot_password', 'auth.reset_password', 'auth.resend_reset_otp'}
        ):
            return
        if current_user.is_authenticated:
            if session.get('boot_token') != app.config.get('BOOT_TOKEN'):
                logout_user()
                session.clear()
                flash('Please login again.', 'info')
                return redirect(url_for('auth.login'))
            now = datetime.utcnow()
            timeout_seconds = INACTIVITY_TIMEOUT_MINUTES * 60
            session.permanent = True
            # On a fresh login, initialize and skip enforcement once
            if session.get('_fresh', False):
                session['last_activity'] = now.timestamp()
                session['boot_token'] = app.config.get('BOOT_TOKEN')
                return
            last = session.get('last_activity')
            if last is None:
                session['last_activity'] = now.timestamp()
                return
            try:
                last_val = float(last)
                last_dt = datetime.utcfromtimestamp(last_val)
            except Exception:
                session['last_activity'] = now.timestamp()
                return
            # If clock skew or invalid, reset without logging out
            if last_dt > now:
                session['last_activity'] = now.timestamp()
                return
            if (now - last_dt).total_seconds() > timeout_seconds:
                uid = getattr(current_user, 'id', None)
                role = getattr(current_user, 'role', 'user')
                logout_user()
                session.pop('last_activity', None)
                flash('You have been logged out due to inactivity.', 'info')
                try:
                    log_activity(db, actor_id=ObjectId(uid) if uid else None, role=role, action='auto_logout_inactivity', details={'timeout_minutes': INACTIVITY_TIMEOUT_MINUTES})
                except Exception:
                    pass
                return redirect(url_for('auth.login'))
            # Otherwise refresh
            session['last_activity'] = now.timestamp()
    except Exception:
        pass


if __name__ == '__main__':
    # Run the application
    app.run(debug=True, host='0.0.0.0', port=5000, use_reloader=False, threaded=True)

