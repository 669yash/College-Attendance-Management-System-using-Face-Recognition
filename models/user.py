"""
User model for Flask-Login
"""
from flask_login import UserMixin


class User(UserMixin):
    """User class for Flask-Login authentication"""
    
    def __init__(self, user_id, email, role, roll_number=None):
        self.id = user_id
        self.email = email
        self.role = role
        self.roll_number = roll_number
    
    def is_student(self):
        """Check if user is a student"""
        return self.role == 'student'
    
    def is_professor(self):
        """Check if user is a professor"""
        return self.role == 'professor'

