"""
Authentication routes for login and registration
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from pymongo import MongoClient
from bson import ObjectId
from config import MONGODB_URI, DATABASE_NAME, LOGIN_BASE_COOLDOWN_SECONDS
from utils.helpers import save_uploaded_file, ensure_directory
from utils.face_recognition_interface import validate_student_images
from config import STUDENTS_FOLDER
import smtplib
import ssl
import re
import random
from datetime import datetime, timedelta
from config import MAIL_SERVER, MAIL_PORT, MAIL_USE_TLS, MAIL_USERNAME, MAIL_PASSWORD, MAIL_SENDER, OTP_EXPIRY_MINUTES, REQUIRE_PROFESSOR_DOMAIN, ALLOWED_PROFESSOR_EMAIL_DOMAIN, PROFESSOR_INVITE_CODE, OTP_RESEND_COOLDOWN_SECONDS
from utils.helpers import log_activity
from models.user import User
import re

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
        elif current_user.role == 'admin':
            return redirect(url_for('admin.unregistered'))
    
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        if not email or not password:
            flash('Please fill in all fields', 'error')
            return render_template('auth/login.html', email=email)
        now = datetime.utcnow()
        attempts = db.login_attempts.find_one({'email': email})
        if attempts and attempts.get('lock_until') and attempts['lock_until'] > now:
            remain = int((attempts['lock_until'] - now).total_seconds())
            flash(f'Too many failed attempts. Try again in {remain} seconds.', 'error')
            return render_template('auth/login.html', email=email, cooldown_remaining=remain, tries_left=0)
        
        # Find user in database
        user_data = db.users.find_one({'email': email})
        
        if user_data and check_password_hash(user_data['hashed_password'], password):
            if not user_data.get('email_verified', True):
                flash('Please verify your email before logging in.', 'error')
                return render_template('auth/login.html')
            # Create User object for flask_login
            user = User(
                str(user_data['_id']),
                user_data['email'],
                user_data['role'],
                user_data.get('roll_number')
            )
            login_user(user)
            db.login_attempts.delete_one({'email': email})
            try:
                session.permanent = True
                session['last_activity'] = datetime.utcnow().timestamp()
                session['boot_token'] = current_app.config.get('BOOT_TOKEN')
            except Exception:
                pass
            
            # Redirect based on role
            if user_data['role'] == 'student':
                return redirect(url_for('students.dashboard'))
            elif user_data['role'] == 'professor':
                return redirect(url_for('professors.dashboard'))
            elif user_data['role'] == 'admin':
                return redirect(url_for('admin.unregistered'))
        else:
            prev_failed = 0
            prev_cooldown = LOGIN_BASE_COOLDOWN_SECONDS
            if attempts:
                prev_failed = int(attempts.get('failed_count', 0))
                prev_cooldown = int(attempts.get('cooldown_seconds', LOGIN_BASE_COOLDOWN_SECONDS))
            new_failed = prev_failed + 1
            if new_failed < 3:
                db.login_attempts.update_one(
                    {'email': email},
                    {'$set': {'failed_count': new_failed, 'cooldown_seconds': prev_cooldown}},
                    upsert=True
                )
                tries_left = 3 - new_failed
                flash(f'Invalid email or password. Attempts left: {tries_left}', 'error')
                return render_template('auth/login.html', email=email, tries_left=tries_left)
            else:
                lock_until = now + timedelta(seconds=prev_cooldown)
                next_cooldown = prev_cooldown * 2
                db.login_attempts.update_one(
                    {'email': email},
                    {'$set': {'failed_count': 0, 'lock_until': lock_until, 'cooldown_seconds': next_cooldown}},
                    upsert=True
                )
                flash(f'Too many failed attempts. Try again in {prev_cooldown} seconds.', 'error')
                return render_template('auth/login.html', email=email, cooldown_remaining=prev_cooldown, tries_left=0)
        
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
        professor_code = request.form.get('professor_code')
        admin_key = request.form.get('admin_key')
        
        if not all([role, name, email, password]):
            flash('Please fill in all required fields', 'error')
            return render_template('auth/register.html')
        if not re.match(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^A-Za-z0-9]).{8,}$", password or ""):
            flash('Password must be 8+ chars with uppercase, lowercase, number, and special character', 'error')
            return render_template('auth/register.html')
        
        if not is_valid_email(email):
            flash('Please enter a valid email address', 'error')
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
            if REQUIRE_PROFESSOR_DOMAIN and ALLOWED_PROFESSOR_EMAIL_DOMAIN:
                if not email.lower().endswith(ALLOWED_PROFESSOR_EMAIL_DOMAIN.lower()):
                    flash('Professor registration requires an institutional email address', 'error')
                    return render_template('auth/register.html')
            now = datetime.utcnow()
            code_input = (professor_code or '').strip()
            invite = None
            if code_input:
                invite = db.invite_codes.find_one({
                    'code': code_input,
                    'active': True,
                    'valid_from': {'$lte': now},
                    'valid_until': {'$gte': now}
                })
            valid_env = PROFESSOR_INVITE_CODE and code_input == PROFESSOR_INVITE_CODE
            if role == 'admin':
                from config import ADMIN_REGISTRATION_KEY
                if not admin_key or admin_key != ADMIN_REGISTRATION_KEY:
                    flash('Invalid admin registration key', 'error')
                    return render_template('auth/register.html')
            elif not (invite or valid_env):
                flash('Invalid professor verification code', 'error')
                return render_template('auth/register.html')
            pending_prof = {
                'name': name,
                'email': email,
                'hashed_password': generate_password_hash(password),
                'role': 'admin' if role == 'admin' else 'professor'
            }
            if invite and 'department' in invite:
                pending_prof['department'] = invite['department']
            if invite and 'term' in invite:
                pending_prof['term'] = invite['term']

        otp = f"{random.randint(100000, 999999)}"
        otp_hash = generate_password_hash(otp)
        expires_at = datetime.utcnow() + timedelta(minutes=OTP_EXPIRY_MINUTES)

        now = datetime.utcnow()
        pending_doc = {
            'email': email,
            'data': user_data if role == 'student' else pending_prof,
            'otp_hash': otp_hash,
            'expires_at': expires_at,
            'created_at': now,
            'last_sent_at': now
        }
        db.email_verifications.delete_many({'email': email})
        db.email_verifications.insert_one(pending_doc)

        if not send_otp_email(email, otp):
            flash('Failed to send verification email. Please contact support or try again later.', 'error')
            return render_template('auth/register.html')

        flash('Verification code sent to your email. Please enter the OTP to complete registration.', 'info')
        return redirect(url_for('auth.verify_email', email=email))
    
    return render_template('auth/register.html')


@auth_bp.route('/verify-email', methods=['GET', 'POST'])
def verify_email():
    email = request.args.get('email') or request.form.get('email')
    if request.method == 'POST':
        otp = request.form.get('otp')
        if not email or not otp:
            flash('Email and OTP are required', 'error')
            return render_template('auth/verify_email.html', email=email)
        pending = db.email_verifications.find_one({'email': email})
        if not pending:
            flash('No pending verification for this email', 'error')
            return render_template('auth/verify_email.html', email=email)
        if pending['expires_at'] < datetime.utcnow():
            db.email_verifications.delete_one({'_id': pending['_id']})
            flash('OTP has expired. Please register again.', 'error')
            return redirect(url_for('auth.register'))
        if not check_password_hash(pending['otp_hash'], otp):
            flash('Invalid OTP', 'error')
            return render_template('auth/verify_email.html', email=email)

        data = pending['data']
        data['email_verified'] = True
        result = db.users.insert_one(data)
        db.email_verifications.delete_one({'_id': pending['_id']})
        flash('Email verified and registration completed. Please login.', 'success')
        return redirect(url_for('auth.login'))
    return render_template('auth/verify_email.html', email=email)


@auth_bp.route('/resend-otp', methods=['POST'])
def resend_otp():
    email = request.form.get('email')
    if not email:
        flash('Email is required', 'error')
        return redirect(url_for('auth.register'))
    pending = db.email_verifications.find_one({'email': email})
    if not pending:
        flash('No pending verification for this email', 'error')
        return redirect(url_for('auth.register'))
    last = pending.get('last_sent_at')
    now = datetime.utcnow()
    if last and (now - last).total_seconds() < OTP_RESEND_COOLDOWN_SECONDS:
        remain = int(OTP_RESEND_COOLDOWN_SECONDS - (now - last).total_seconds())
        flash(f'Please wait {remain} seconds before resending OTP.', 'warning')
        return redirect(url_for('auth.verify_email', email=email))
    otp = f"{random.randint(100000, 999999)}"
    otp_hash = generate_password_hash(otp)
    expires_at = now + timedelta(minutes=OTP_EXPIRY_MINUTES)
    db.email_verifications.update_one({'_id': pending['_id']}, {
        '$set': {
            'otp_hash': otp_hash,
            'expires_at': expires_at,
            'last_sent_at': now
        }
    })
    if not send_otp_email(email, otp):
        flash('Failed to send verification email. Please try again later.', 'error')
        return redirect(url_for('auth.verify_email', email=email))
    flash('OTP resent. Please check your email.', 'success')
    return redirect(url_for('auth.verify_email', email=email))


@auth_bp.route('/logout')
@login_required
def logout():
    """User logout route"""
    logout_user()
    flash('You have been logged out', 'info')
    return redirect(url_for('auth.login'))


@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email')
        if not is_valid_email(email):
            flash('Please enter a valid email address', 'error')
            return render_template('auth/forgot_password.html')
        user = db.users.find_one({'email': email})
        if not user:
            flash('If the email exists, a reset code has been sent.', 'info')
            return render_template('auth/forgot_password.html')
        now = datetime.utcnow()
        otp = f"{random.randint(100000, 999999)}"
        otp_hash = generate_password_hash(otp)
        expires_at = now + timedelta(minutes=OTP_EXPIRY_MINUTES)
        db.password_resets.delete_many({'email': email})
        db.password_resets.insert_one({
            'email': email,
            'otp_hash': otp_hash,
            'expires_at': expires_at,
            'created_at': now,
            'last_sent_at': now
        })
        if not send_password_reset_email(email, otp):
            flash('Failed to send reset email. Please try again later.', 'error')
            return render_template('auth/forgot_password.html')
        try:
            log_activity(db, actor_id=user.get('_id'), role=user.get('role', 'user'), action='request_password_reset', details={'email': email})
        except Exception:
            pass
        flash('Reset code sent. Please check your email.', 'success')
        return redirect(url_for('auth.reset_password', email=email))
    return render_template('auth/forgot_password.html')


@auth_bp.route('/resend-reset-otp', methods=['POST'])
def resend_reset_otp():
    email = request.form.get('email')
    pending = db.password_resets.find_one({'email': email})
    if not pending:
        flash('No reset pending for this email.', 'error')
        return redirect(url_for('auth.forgot_password'))
    last = pending.get('last_sent_at')
    now = datetime.utcnow()
    if last and (now - last).total_seconds() < OTP_RESEND_COOLDOWN_SECONDS:
        remain = int(OTP_RESEND_COOLDOWN_SECONDS - (now - last).total_seconds())
        flash(f'Please wait {remain} seconds before resending reset code.', 'warning')
        return redirect(url_for('auth.reset_password', email=email))
    otp = f"{random.randint(100000, 999999)}"
    otp_hash = generate_password_hash(otp)
    expires_at = now + timedelta(minutes=OTP_EXPIRY_MINUTES)
    db.password_resets.update_one({'_id': pending['_id']}, {
        '$set': {
            'otp_hash': otp_hash,
            'expires_at': expires_at,
            'last_sent_at': now
        }
    })
    if not send_password_reset_email(email, otp):
        flash('Failed to send reset email. Please try again later.', 'error')
        return redirect(url_for('auth.reset_password', email=email))
    flash('Reset code resent. Please check your email.', 'success')
    return redirect(url_for('auth.reset_password', email=email))


@auth_bp.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    email = request.args.get('email') or request.form.get('email')
    if request.method == 'POST':
        otp = request.form.get('otp')
        new_password = request.form.get('new_password') or request.form.get('password')
        if not (email and otp and new_password):
            flash('Email, code and new password are required', 'error')
            return render_template('auth/reset_password.html', email=email)
        pending = db.password_resets.find_one({'email': email})
        if not pending:
            flash('No reset pending for this email', 'error')
            return redirect(url_for('auth.forgot_password'))
        if pending['expires_at'] < datetime.utcnow():
            db.password_resets.delete_one({'_id': pending['_id']})
            flash('Reset code has expired. Please request again.', 'error')
            return redirect(url_for('auth.forgot_password'))
        if not check_password_hash(pending['otp_hash'], otp):
            flash('Invalid reset code', 'error')
            return render_template('auth/reset_password.html', email=email)
        if not re.match(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^A-Za-z0-9]).{8,}$", new_password or ""):
            flash('Password must be 8+ chars with uppercase, lowercase, number, and special character', 'error')
            return render_template('auth/reset_password.html', email=email)
        user = db.users.find_one({'email': email})
        if not user:
            flash('User not found', 'error')
            return redirect(url_for('auth.forgot_password'))
        try:
            prev_hash = user.get('hashed_password')
            # Disallow same as current password
            if prev_hash and check_password_hash(prev_hash, new_password):
                flash('Use a new password that you have not used before.', 'error')
                return render_template('auth/reset_password.html', email=email)
            # Disallow any password in history
            history = user.get('password_history') or []
            for h in history:
                if h and check_password_hash(h, new_password):
                    flash('Use a new password that you have not used before.', 'error')
                    return render_template('auth/reset_password.html', email=email)
        except Exception:
            pass
        # Update password and append previous hash to history (cap to last 5)
        try:
            new_hash = generate_password_hash(new_password)
            history = user.get('password_history') or []
            if prev_hash:
                history = [prev_hash] + history
            history = history[:5]
            db.users.update_one({'_id': user['_id']}, {'$set': {'hashed_password': new_hash, 'password_history': history}})
        except Exception:
            db.users.update_one({'_id': user['_id']}, {'$set': {'hashed_password': generate_password_hash(new_password)}})
        db.password_resets.delete_one({'_id': pending['_id']})
        try:
            log_activity(db, actor_id=user['_id'], role=user.get('role', 'user'), action='reset_password', details={'email': email})
        except Exception:
            pass
        flash('Password reset successful. Please login.', 'success')
        return redirect(url_for('auth.login'))
    return render_template('auth/reset_password.html', email=email)


def send_password_reset_email(recipient_email: str, otp_code: str) -> bool:
    try:
        if not MAIL_SERVER or not MAIL_USERNAME or not MAIL_PASSWORD:
            return False
        message = f"From: {MAIL_SENDER}\r\nTo: {recipient_email}\r\nSubject: Password Reset Code\r\n\r\nYour password reset code is: {otp_code}. It expires in {OTP_EXPIRY_MINUTES} minutes."
        if MAIL_USE_TLS:
            context = ssl.create_default_context()
            with smtplib.SMTP(MAIL_SERVER, MAIL_PORT) as server:
                server.starttls(context=context)
                server.login(MAIL_USERNAME, MAIL_PASSWORD)
                server.sendmail(MAIL_SENDER, recipient_email, message)
        else:
            with smtplib.SMTP(MAIL_SERVER, MAIL_PORT) as server:
                server.login(MAIL_USERNAME, MAIL_PASSWORD)
                server.sendmail(MAIL_SENDER, recipient_email, message)
        return True
    except Exception:
        return False

def send_otp_email(recipient_email: str, otp_code: str) -> bool:
    try:
        if not MAIL_SERVER or not MAIL_USERNAME or not MAIL_PASSWORD:
            return False
        message = f"From: {MAIL_SENDER}\r\nTo: {recipient_email}\r\nSubject: Email Verification OTP\r\n\r\nYour verification code is: {otp_code}. It expires in {OTP_EXPIRY_MINUTES} minutes."
        if MAIL_USE_TLS:
            context = ssl.create_default_context()
            with smtplib.SMTP(MAIL_SERVER, MAIL_PORT) as server:
                server.starttls(context=context)
                server.login(MAIL_USERNAME, MAIL_PASSWORD)
                server.sendmail(MAIL_SENDER, recipient_email, message)
        else:
            with smtplib.SMTP(MAIL_SERVER, MAIL_PORT) as server:
                server.login(MAIL_USERNAME, MAIL_PASSWORD)
                server.sendmail(MAIL_SENDER, recipient_email, message)
        return True
    except Exception:
        return False

def is_valid_email(email: str) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email or ""))
