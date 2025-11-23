"""
Complete Face Recognition System for Attendance Marking

This module implements a working face recognition system using face_recognition library.
It encodes student faces during registration and matches them in classroom images.
"""

import os
import pickle
import numpy as np
from pathlib import Path
from typing import Dict, List, Tuple

# Try to import face_recognition, fallback if not available
try:
    import face_recognition
    FACE_RECOGNITION_AVAILABLE = True
except ImportError:
    FACE_RECOGNITION_AVAILABLE = False
    print("Warning: face_recognition library not available. Please install it for full functionality.")
    print("Install with: pip install face-recognition")

try:
    from PIL import Image
except ImportError:
    Image = None

try:
    import cv2
except ImportError:
    cv2 = None

from config import STUDENTS_FOLDER, CLASSROOM_FOLDER, MONGODB_URI, DATABASE_NAME
from pymongo import MongoClient

# MongoDB connection for storing encodings
client = MongoClient(MONGODB_URI)
db = client[DATABASE_NAME]

# Face recognition settings
FACE_ENCODING_TOLERANCE = 0.6  # Lower = more strict (0.0 to 1.0)
MIN_FACE_DETECTIONS = 2  # Minimum number of images where face must be detected


def encode_student_faces(roll_number: str) -> bool:
    """
    Encode all face images for a student and store in database
    
    Args:
        roll_number: Student's roll number
    
    Returns:
        bool: True if encoding successful, False otherwise
    """
    if not FACE_RECOGNITION_AVAILABLE:
        print("Error: face_recognition library not available. Cannot encode faces.")
        return False
    
    student_folder = STUDENTS_FOLDER / roll_number
    
    if not student_folder.exists():
        return False
    
    # Get all image files
    image_files = []
    for ext in ['*.jpg', '*.jpeg', '*.png', '*.gif']:
        image_files.extend(student_folder.glob(ext))
    
    if len(image_files) < 4:
        return False
    
    # Encode faces from all images
    all_encodings = []
    
    for image_path in image_files:
        try:
            # Load image
            image = face_recognition.load_image_file(str(image_path))
            
            # Find face locations
            face_locations = face_recognition.face_locations(image, model='hog')
            
            if len(face_locations) > 0:
                # Get encodings for all faces found
                encodings = face_recognition.face_encodings(image, face_locations)
                all_encodings.extend(encodings)
        except Exception as e:
            print(f"Error encoding face from {image_path}: {e}")
            continue
    
    if len(all_encodings) < MIN_FACE_DETECTIONS:
        print(f"Warning: Only found {len(all_encodings)} face(s) for {roll_number}, need at least {MIN_FACE_DETECTIONS}")
        return False
    
    # Calculate average encoding (more robust than single encoding)
    if len(all_encodings) > 1:
        avg_encoding = np.mean(all_encodings, axis=0)
    else:
        avg_encoding = all_encodings[0]
    
    # Convert numpy array to list for MongoDB storage
    encoding_list = avg_encoding.tolist()
    
    # Store in database
    db.face_encodings.update_one(
        {'roll_number': roll_number},
        {
            '$set': {
                'roll_number': roll_number,
                'encoding': encoding_list,
                'num_images': len(image_files),
                'num_faces_detected': len(all_encodings)
            }
        },
        upsert=True
    )
    
    print(f"Successfully encoded faces for {roll_number} from {len(image_files)} images")
    return True


def load_all_student_encodings() -> Dict[str, np.ndarray]:
    """
    Load all student face encodings from database
    
    Returns:
        dict: Dictionary mapping roll_number to face encoding array
    """
    encodings_dict = {}
    
    try:
        encoding_records = db.face_encodings.find({})
        
        for record in encoding_records:
            roll_number = record['roll_number']
            encoding_array = np.array(record['encoding'])
            encodings_dict[roll_number] = encoding_array
        
        print(f"Loaded {len(encodings_dict)} student face encodings")
    except Exception as e:
        print(f"Error loading encodings: {e}")
    
    return encodings_dict


def detect_faces_in_image(image_path: str) -> List[np.ndarray]:
    """
    Detect and encode all faces in a classroom image
    
    Args:
        image_path: Path to classroom image
    
    Returns:
        list: List of face encodings found in the image
    """
    if not FACE_RECOGNITION_AVAILABLE:
        return []
    
    try:
        # Load image
        image = face_recognition.load_image_file(image_path)
        
        # Find face locations (using HOG model for speed, can use 'cnn' for accuracy)
        face_locations = face_recognition.face_locations(image, model='hog')
        
        if len(face_locations) == 0:
            return []
        
        # Get encodings for all faces
        face_encodings = face_recognition.face_encodings(image, face_locations)
        
        return face_encodings
    except Exception as e:
        print(f"Error detecting faces in {image_path}: {e}")
        return []


def match_faces(classroom_encodings: List[np.ndarray], 
                student_encodings: Dict[str, np.ndarray]) -> Dict[str, int]:
    """
    Match classroom face encodings with student encodings
    
    Args:
        classroom_encodings: List of face encodings from classroom images
        student_encodings: Dictionary of student roll_number -> encoding
    
    Returns:
        dict: Dictionary mapping roll_number to number of matches
    """
    matches = {}
    
    for roll_number, student_encoding in student_encodings.items():
        match_count = 0
        
        for classroom_encoding in classroom_encodings:
            # Compare faces
            distance = face_recognition.face_distance([student_encoding], classroom_encoding)[0]
            
            # If distance is below tolerance, it's a match
            if distance <= FACE_ENCODING_TOLERANCE:
                match_count += 1
        
        if match_count > 0:
            matches[roll_number] = match_count
    
    return matches


def mark_attendance_from_classroom_images(class_id, classroom_images_path, timestamp):
    """
    Complete face recognition workflow to mark attendance from classroom images
    
    Args:
        class_id: ID of the class
        classroom_images_path: Path to folder containing classroom images
        timestamp: Timestamp when images were captured
    
    Returns:
        dict: Dictionary with student_roll as key and status as value
              Example: {'2024001': 'present', '2024002': 'absent', ...}
    """
    print(f"\n=== Processing Attendance for Class {class_id} ===")
    
    # Load all student encodings
    student_encodings = load_all_student_encodings()
    
    if len(student_encodings) == 0:
        print("No student encodings found in database")
        return {}
    
    # Get all classroom images
    classroom_folder = Path(classroom_images_path)
    image_files = []
    for ext in ['*.jpg', '*.jpeg', '*.png', '*.gif']:
        image_files.extend(classroom_folder.glob(ext))
    
    if len(image_files) == 0:
        print("No classroom images found")
        return {}
    
    print(f"Processing {len(image_files)} classroom images...")
    
    # Detect faces in all classroom images
    all_classroom_encodings = []
    for image_path in image_files:
        print(f"  Processing {image_path.name}...")
        encodings = detect_faces_in_image(str(image_path))
        all_classroom_encodings.extend(encodings)
        print(f"    Found {len(encodings)} face(s)")
    
    print(f"Total faces detected in classroom: {len(all_classroom_encodings)}")
    
    if len(all_classroom_encodings) == 0:
        print("No faces detected in classroom images")
        return {}
    
    # Match faces with students
    matches = match_faces(all_classroom_encodings, student_encodings)
    
    print(f"\nFace Recognition Results:")
    print(f"  Students matched: {len(matches)}")
    for roll_num, match_count in matches.items():
        print(f"    - {roll_num}: {match_count} match(es)")
    
    # Get all students in the class to determine attendance
    from bson import ObjectId
    
    # Handle class_id - it might be string or ObjectId
    if isinstance(class_id, str):
        try:
            class_id_obj = ObjectId(class_id)
        except:
            print(f"[ERROR] Invalid class_id format: {class_id}")
            return {}
    else:
        class_id_obj = class_id
    
    class_info = db.classes.find_one({'_id': class_id_obj})
    if not class_info:
        print(f"[ERROR] Class not found: {class_id}")
        return {}
    
    print(f"\nClass Info:")
    print(f"  Class: {class_info.get('class_name')}")
    print(f"  Year: {class_info.get('year')}")
    print(f"  Division: {class_info.get('division')}")
    
    # Get all students in this class (based on year and division)
    students = list(db.users.find({
        'role': 'student',
        'year': class_info['year'],
        'division': class_info['division']
    }))
    
    print(f"\nStudents in class (year={class_info['year']}, division={class_info['division']}): {len(students)}")
    
    # Also get all students who were matched (in case year/division doesn't match)
    matched_roll_numbers = list(matches.keys())
    if matched_roll_numbers:
        matched_students = list(db.users.find({
            'role': 'student',
            'roll_number': {'$in': matched_roll_numbers}
        }))
        print(f"Matched students (from face recognition): {len(matched_students)}")
        for ms in matched_students:
            print(f"  - {ms['roll_number']}: {ms['name']} (Year: {ms.get('year')}, Division: {ms.get('division')})")
    
    # Create attendance results - include ALL students in class
    attendance_results = {}
    
    # First, mark all students in the class
    for student in students:
        roll_number = student['roll_number']
        
        # Student is present if their face was matched in at least one image
        if roll_number in matches:
            attendance_results[roll_number] = 'present'
            print(f"  [OK] {roll_number} ({student['name']}): PRESENT ({matches[roll_number]} match(es))")
        else:
            attendance_results[roll_number] = 'absent'
            print(f"  [ABSENT] {roll_number} ({student['name']}): ABSENT")
    
    # If no students found in class but we have matches, include matched students anyway
    if len(students) == 0 and len(matches) > 0:
        print(f"\n[WARNING] No students found in class, but {len(matches)} student(s) were matched by face recognition")
        print(f"  Including matched students in attendance results...")
        for roll_number in matches.keys():
            matched_student = db.users.find_one({'roll_number': roll_number, 'role': 'student'})
            if matched_student:
                attendance_results[roll_number] = 'present'
                print(f"  [OK] {roll_number} ({matched_student['name']}): PRESENT ({matches[roll_number]} match(es))")
    
    print(f"\nFinal attendance_results dictionary: {attendance_results}")
    print(f"Number of results: {len(attendance_results)}")
    print(f"=== Attendance Processing Complete ===\n")
    
    return attendance_results


def get_student_face_embeddings(roll_number):
    """
    Get face embeddings for a student from their uploaded images
    
    Args:
        roll_number: Student's roll number
    
    Returns:
        list: List of image paths (for compatibility)
    """
    student_folder = STUDENTS_FOLDER / roll_number
    
    if not student_folder.exists():
        return []
    
    # Get all image files from student folder
    image_files = []
    for ext in ['*.jpg', '*.jpeg', '*.png', '*.gif']:
        image_files.extend(student_folder.glob(ext))
    
    return [str(img) for img in image_files]


def validate_student_images(roll_number):
    """
    Validate that student has uploaded sufficient face images (4-5)
    and that faces can be detected in them
    
    Args:
        roll_number: Student's roll number
    
    Returns:
        bool: True if student has 4-5 images with detectable faces, False otherwise
    """
    if not FACE_RECOGNITION_AVAILABLE:
        # Basic validation without face detection
        student_folder = STUDENTS_FOLDER / roll_number
        if not student_folder.exists():
            return False
        image_files = []
        for ext in ['*.jpg', '*.jpeg', '*.png', '*.gif']:
            image_files.extend(student_folder.glob(ext))
        return 4 <= len(image_files) <= 5
    
    student_folder = STUDENTS_FOLDER / roll_number
    
    if not student_folder.exists():
        return False
    
    # Get all image files
    image_files = []
    for ext in ['*.jpg', '*.jpeg', '*.png', '*.gif']:
        image_files.extend(student_folder.glob(ext))
    
    if not (4 <= len(image_files) <= 5):
        return False
    
    # Check if faces can be detected in at least some images
    faces_detected = 0
    for image_path in image_files:
        try:
            image = face_recognition.load_image_file(str(image_path))
            face_locations = face_recognition.face_locations(image, model='hog')
            if len(face_locations) > 0:
                faces_detected += 1
        except:
            continue
    
    # Require faces in at least 3 out of 4-5 images
    return faces_detected >= 3
