"""
Helper utility functions
"""
import os
from werkzeug.utils import secure_filename
from config import ALLOWED_EXTENSIONS, UPLOAD_FOLDER, STUDENTS_FOLDER
from datetime import datetime


def allowed_file(filename):
    """Check if file extension is allowed"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def save_uploaded_file(file, folder_path, filename=None):
    """
    Save uploaded file to specified folder
    
    Args:
        file: FileStorage object from Flask
        folder_path: Path object where file should be saved
        filename: Optional custom filename (if provided, extension check is skipped)
    
    Returns:
        str: Path to saved file or None if failed
    """
    try:
        if not file:
            print(f"[ERROR] No file provided to save_uploaded_file")
            return None
        
        if not file.filename:
            print(f"[ERROR] File has no filename")
            return None
        
        # Check if file extension is allowed (only if no custom filename provided)
        if filename is None:
            if not allowed_file(file.filename):
                print(f"[ERROR] File extension not allowed: {file.filename}")
                return None
        else:
            # If custom filename provided, check its extension instead
            if not allowed_file(filename):
                print(f"[ERROR] Custom filename extension not allowed: {filename}")
                return None
        
        # Create folder if it doesn't exist
        folder_path.mkdir(parents=True, exist_ok=True)
        print(f"[DEBUG] Saving file to: {folder_path}")
        
        # Generate filename
        if not filename:
            filename = secure_filename(file.filename)
        else:
            # Ensure custom filename is secure
            filename = secure_filename(filename)
        
        file_path = folder_path / filename
        
        # Save file
        file.save(str(file_path))
        
        # Verify file was saved
        if file_path.exists():
            file_size = file_path.stat().st_size
            print(f"[DEBUG] Successfully saved: {file_path} ({file_size} bytes)")
            return str(file_path)
        else:
            print(f"[ERROR] File save failed - file does not exist: {file_path}")
            return None
            
    except Exception as e:
        print(f"[ERROR] Exception saving file: {e}")
        import traceback
        traceback.print_exc()
        return None


def ensure_directory(path):
    """Ensure directory exists, create if it doesn't"""
    path.mkdir(parents=True, exist_ok=True)


def log_activity(db, actor_id, role, action, details=None, class_id=None, student_roll=None):
    try:
        doc = {
            'actor_id': actor_id,
            'role': role,
            'action': action,
            'timestamp': datetime.utcnow(),
            'details': details or {},
        }
        if class_id is not None:
            doc['class_id'] = class_id
        if student_roll is not None:
            doc['student_roll'] = student_roll
        db.activity_logs.insert_one(doc)
    except Exception as e:
        try:
            print(f"[WARN] Failed to write activity log: {e}")
        except Exception:
            pass


def clear_student_images(roll_number: str):
    try:
        folder = STUDENTS_FOLDER / roll_number
        if folder.exists():
            for ext in ['*.jpg', '*.jpeg', '*.png', '*.gif']:
                for p in folder.glob(ext):
                    try:
                        p.unlink()
                    except Exception:
                        pass
        else:
            folder.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

