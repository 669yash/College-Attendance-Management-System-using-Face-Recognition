"""
Main Flask application for College Attendance Marking & Management System
"""
from flask import Flask, render_template, redirect, url_for
from flask_login import LoginManager
from pymongo import MongoClient
from bson import ObjectId
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

# Import configuration
from config import MONGODB_URI, DATABASE_NAME, SECRET_KEY

# Import routes
from routes.auth import auth_bp
from routes.students import students_bp
from routes.professors import professors_bp
from routes.classes import classes_bp

# Import User model
from models.user import User

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = SECRET_KEY

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


if __name__ == '__main__':
    # Run the application
    app.run(debug=True, host='0.0.0.0', port=5000)

