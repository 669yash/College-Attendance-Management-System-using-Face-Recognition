"""
Authentication routes for login and registration
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from pymongo import MongoClient
from bson import ObjectId
from config import MONGODB_URI, DATABASE_NAME
from utils.helpers import save_uploaded_file, ensure_directory
from utils.face_recognition_interface import validate_student_images
from config import STUDENTS_FOLDER
from models.user import User

auth_bp = Blueprint('auth', __name__)

# MongoDB connection
client = MongoClient(MONGODB_URI)
db = client[DATABASE_NAME]


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """User login route"""
    if current_user.is_authenticated:
        # Redirect based on role
        if current_user.role == 'student':
            return redirect(url_for('students.dashboard'))
        elif current_user.role == 'professor':
            return redirect(url_for('professors.dashboard'))
    
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        if not email or not password:
            flash('Please fill in all fields', 'error')
            return render_template('auth/login.html')
        
        # Find user in database
        user_data = db.users.find_one({'email': email})
        
        if user_data and check_password_hash(user_data['hashed_password'], password):
            # Create User object for flask_login
            user = User(
                str(user_data['_id']),
                user_data['email'],
                user_data['role'],
                user_data.get('roll_number')
            )
            login_user(user)
            
            # Redirect based on role
            if user_data['role'] == 'student':
                return redirect(url_for('students.dashboard'))
            elif user_data['role'] == 'professor':
                return redirect(url_for('professors.dashboard'))
        else:
            flash('Invalid email or password', 'error')
    
    return render_template('auth/login.html')


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    """User registration route"""
    if current_user.is_authenticated:
        if current_user.role == 'student':
            return redirect(url_for('students.dashboard'))
        elif current_user.role == 'professor':
            return redirect(url_for('professors.dashboard'))
    
    if request.method == 'POST':
        role = request.form.get('role')
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')
        
        if not all([role, name, email, password]):
            flash('Please fill in all required fields', 'error')
            return render_template('auth/register.html')
        
        # Check if email already exists
        if db.users.find_one({'email': email}):
            flash('Email already registered', 'error')
            return render_template('auth/register.html')
        
        # Student-specific fields
        if role == 'student':
            roll_number = request.form.get('roll_number')
            year = request.form.get('year')
            division = request.form.get('division')
            
            if not all([roll_number, year, division]):
                flash('Please fill in all student fields', 'error')
                return render_template('auth/register.html')
            
            # Check if roll number already exists
            if db.users.find_one({'roll_number': roll_number}):
                flash('Roll number already registered', 'error')
                return render_template('auth/register.html')
            
            # Create student directory
            student_folder = STUDENTS_FOLDER / roll_number
            ensure_directory(student_folder)
            
            # Handle file uploads (4-5 face images)
            uploaded_files = request.files.getlist('face_images')
            valid_files = [f for f in uploaded_files if f.filename]
            
            if len(valid_files) < 4 or len(valid_files) > 5:
                flash('Please upload 4-5 face images', 'error')
                return render_template('auth/register.html')
            
            # Save uploaded images
            for idx, file in enumerate(valid_files):
                save_uploaded_file(file, student_folder, f'image_{idx+1}.jpg')
            
            # Encode student faces for face recognition
            from utils.face_recognition_interface import encode_student_faces, validate_student_images
            
            # Validate that faces can be detected
            if not validate_student_images(roll_number):
                flash('Could not detect faces in uploaded images. Please upload clear face images.', 'error')
                return render_template('auth/register.html')
            
            # Encode and store face encodings
            if not encode_student_faces(roll_number):
                flash('Failed to process face images. Please try again with clearer images.', 'error')
                return render_template('auth/register.html')
            
            # Create user document
            user_data = {
                'name': name,
                'email': email,
                'hashed_password': generate_password_hash(password),
                'role': 'student',
                'roll_number': roll_number,
                'year': year,
                'division': division
            }
        else:
            # Professor registration
            user_data = {
                'name': name,
                'email': email,
                'hashed_password': generate_password_hash(password),
                'role': 'professor'
            }
        
        # Insert user into database
        result = db.users.insert_one(user_data)
        
        flash('Registration successful! Please login.', 'success')
        return redirect(url_for('auth.login'))
    
    return render_template('auth/register.html')


@auth_bp.route('/logout')
@login_required
def logout():
    """User logout route"""
    logout_user()
    flash('You have been logged out', 'info')
    return redirect(url_for('auth.login'))

