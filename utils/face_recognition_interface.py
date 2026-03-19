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
from datetime import datetime

# Try to import face_recognition, fallback if not available
try:
    import face_recognition
    FACE_RECOGNITION_AVAILABLE = True
except ImportError:
    FACE_RECOGNITION_AVAILABLE = False
    print("Warning: face_recognition library not available. Please install it for full functionality.")
    print("Install with: pip install face-recognition")

try:
    from PIL import Image, ImageDraw
except ImportError:
    Image = None

try:
    import cv2
except ImportError:
    cv2 = None

from config import (
    STUDENTS_FOLDER,
    CLASSROOM_FOLDER,
    MONGODB_URI,
    DATABASE_NAME,
    FACE_MATCH_TOLERANCE,
    UNKNOWN_FACE_THRESHOLD,
    MIN_CONFIDENCE_MARGIN,
    FACE_DETECTION_MODEL,
    MIN_MATCHES_FOR_PRESENT,
    FACE_DETECTION_WORKERS,
)
from pymongo import MongoClient

# MongoDB connection for storing encodings
client = MongoClient(MONGODB_URI)
db = client[DATABASE_NAME]

# Face recognition settings
MIN_FACE_DETECTIONS = 2


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

def load_encodings_for_roll_numbers(roll_numbers: List[str]) -> Dict[str, np.ndarray]:
    encodings_dict = {}
    try:
        records = db.face_encodings.find({'roll_number': {'$in': roll_numbers}})
        for record in records:
            encodings_dict[record['roll_number']] = np.array(record['encoding'])
    except Exception as e:
        pass
    return encodings_dict


def detect_faces_in_image(image_path: str):
    if not FACE_RECOGNITION_AVAILABLE:
        return [], []
    try:
        image = face_recognition.load_image_file(image_path)
        face_locations = face_recognition.face_locations(image, model=FACE_DETECTION_MODEL)
        if len(face_locations) == 0:
            return [], []
        face_encodings = face_recognition.face_encodings(image, face_locations)
        return face_encodings, face_locations
    except Exception as e:
        print(f"Error detecting faces in {image_path}: {e}")
        return [], []


def match_faces(classroom_encodings: List[np.ndarray],
                student_encodings: Dict[str, np.ndarray]) -> Tuple[Dict[str, int], Dict[str, int]]:
    """
    Best-match assignment of classroom faces to registered students with unknown rejection.

    Args:
        classroom_encodings: List of face encodings from classroom images
        student_encodings: Dictionary of student roll_number -> encoding

    Returns:
        (matches, metrics):
          - matches: roll_number -> number of accepted matches
          - metrics: {'unknown_faces': int, 'ambiguous_matches': int, 'weak_matches': int}
    """
    matches: Dict[str, int] = {}
    metrics = {
        'unknown_faces': 0,
        'ambiguous_matches': 0,
        'weak_matches': 0,
    }

    if not classroom_encodings or not student_encodings:
        return matches, metrics

    # Precompute student encodings list for vectorized distance computation
    rolls = list(student_encodings.keys())
    student_vecs = np.stack([student_encodings[r] for r in rolls]) if rolls else np.empty((0, 128))

    for classroom_encoding in classroom_encodings:
        # Compute distances to all students
        try:
            distances = face_recognition.face_distance(student_vecs, classroom_encoding)
        except Exception:
            # Fallback to per-student if vectorized fails
            distances = np.array([
                face_recognition.face_distance([student_encodings[r]], classroom_encoding)[0]
                for r in rolls
            ])

        if distances.size == 0:
            metrics['unknown_faces'] += 1
            continue

        # Find best and second-best matches
        order = np.argsort(distances)
        best_idx = order[0]
        best_roll = rolls[best_idx]
        best_dist = distances[best_idx]
        second_best_dist = distances[order[1]] if distances.size > 1 else None

        # Reject if distance exceeds match tolerance
        if best_dist > FACE_MATCH_TOLERANCE:
            metrics['unknown_faces'] += 1
            continue

        # If second best is too close, mark ambiguous and skip
        if second_best_dist is not None and (second_best_dist - best_dist) < MIN_CONFIDENCE_MARGIN:
            metrics['ambiguous_matches'] += 1
            continue

        # Weak match warning zone (optional): near unknown threshold
        if best_dist > UNKNOWN_FACE_THRESHOLD:
            metrics['weak_matches'] += 1
            # Still reject to avoid false positives
            metrics['unknown_faces'] += 1
            continue

        # Accept best match
        matches[best_roll] = matches.get(best_roll, 0) + 1

    return matches, metrics


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
    
    from bson import ObjectId
    if isinstance(class_id, str):
        try:
            class_id_obj = ObjectId(class_id)
        except:
            return {}
    else:
        class_id_obj = class_id
    class_info = db.classes.find_one({'_id': class_id_obj})
    if not class_info:
        return {}
    students = list(db.users.find({
        'role': 'student',
        'year': class_info['year'],
        'division': class_info['division']
    }))
    class_roll_numbers = [s['roll_number'] for s in students]
    student_encodings = load_encodings_for_roll_numbers(class_roll_numbers)
    if len(student_encodings) == 0:
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
    
    rolls = list(student_encodings.keys())
    student_vecs = np.stack([student_encodings[r] for r in rolls]) if rolls else np.empty((0, 128))
    matches: Dict[str, int] = {}
    metrics = {
        'unknown_faces': 0,
        'ambiguous_matches': 0,
        'weak_matches': 0,
    }
    for image_path in image_files:
        print(f"  Processing {image_path.name}...")
        encodings, locations = detect_faces_in_image(str(image_path))
        print(f"    Found {len(encodings)} face(s)")
        unknown_locations = []
        for enc, loc in zip(encodings, locations):
            if student_vecs.size == 0:
                metrics['unknown_faces'] += 1
                unknown_locations.append(loc)
                continue
            try:
                distances = face_recognition.face_distance(student_vecs, enc)
            except Exception:
                distances = np.array([
                    face_recognition.face_distance([student_encodings[r]], enc)[0]
                    for r in rolls
                ])
            if distances.size == 0:
                metrics['unknown_faces'] += 1
                unknown_locations.append(loc)
                continue
            order = np.argsort(distances)
            best_idx = order[0]
            best_roll = rolls[best_idx]
            best_dist = distances[best_idx]
            second_best_dist = distances[order[1]] if distances.size > 1 else None
            if best_dist > FACE_MATCH_TOLERANCE:
                metrics['unknown_faces'] += 1
                unknown_locations.append(loc)
                continue
            if second_best_dist is not None and (second_best_dist - best_dist) < MIN_CONFIDENCE_MARGIN:
                metrics['ambiguous_matches'] += 1
                unknown_locations.append(loc)
                continue
            if best_dist > UNKNOWN_FACE_THRESHOLD:
                metrics['weak_matches'] += 1
                metrics['unknown_faces'] += 1
                unknown_locations.append(loc)
                continue
            matches[best_roll] = matches.get(best_roll, 0) + 1
        if unknown_locations:
            annotated_name = f"annotated_{image_path.name}"
            annotated_path = classroom_folder / annotated_name
            try:
                if Image is not None:
                    im = Image.open(str(image_path))
                    dr = ImageDraw.Draw(im)
                    for top, right, bottom, left in unknown_locations:
                        dr.rectangle([(left, top), (right, bottom)], outline=(255, 0, 0), width=3)
                    im.save(str(annotated_path))
                elif cv2 is not None:
                    im = cv2.imread(str(image_path))
                    for top, right, bottom, left in unknown_locations:
                        cv2.rectangle(im, (left, top), (right, bottom), (0, 0, 255), 3)
                    cv2.imwrite(str(annotated_path), im)
            except Exception as e:
                pass
    
    print(f"\nFace Recognition Results:")
    print(f"  Students matched: {len(matches)}")
    print(f"  Unknown faces rejected: {metrics.get('unknown_faces', 0)}")
    print(f"  Ambiguous matches skipped: {metrics.get('ambiguous_matches', 0)}")
    print(f"  Weak matches rejected: {metrics.get('weak_matches', 0)}")
    for roll_num, match_count in matches.items():
        print(f"    - {roll_num}: {match_count} match(es)")
    
    print(f"\nClass Info:")
    print(f"  Class: {class_info.get('class_name')}")
    print(f"  Year: {class_info.get('year')}")
    print(f"  Division: {class_info.get('division')}")
    
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
        if roll_number in matches and matches[roll_number] >= MIN_MATCHES_FOR_PRESENT:
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
    
    return {
        'attendance': attendance_results,
        'metrics': metrics,
    }


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

def process_unregistered_from_image(image_path: str, save_folder: Path, location: str, camera_serial: str) -> Dict[str, int]:
    if not FACE_RECOGNITION_AVAILABLE:
        return {'unknown_faces': 0}
    encodings, locations = detect_faces_in_image(str(image_path))
    students = load_all_student_encodings()
    rolls = list(students.keys())
    student_vecs = np.stack([students[r] for r in rolls]) if rolls else np.empty((0, 128))
    unknown_locations = []
    for enc, loc in zip(encodings, locations):
        if student_vecs.size == 0:
            unknown_locations.append(loc)
            continue
        try:
            distances = face_recognition.face_distance(student_vecs, enc)
        except Exception:
            distances = np.array([
                face_recognition.face_distance([students[r]], enc)[0] for r in rolls
            ])
        if distances.size == 0:
            unknown_locations.append(loc)
            continue
        order = np.argsort(distances)
        best_dist = distances[order[0]]
        second_best = distances[order[1]] if distances.size > 1 else None
        if best_dist > FACE_MATCH_TOLERANCE:
            unknown_locations.append(loc)
            continue
        if second_best is not None and (second_best - best_dist) < MIN_CONFIDENCE_MARGIN:
            unknown_locations.append(loc)
            continue
        if best_dist > UNKNOWN_FACE_THRESHOLD:
            unknown_locations.append(loc)
            continue
    annotated_path = None
    if unknown_locations:
        try:
            ip = Path(image_path)
            save_folder.mkdir(parents=True, exist_ok=True)
            annotated_path = save_folder / f"annotated_{ip.name}"
            if Image is not None:
                im = Image.open(str(ip))
                dr = ImageDraw.Draw(im)
                for top, right, bottom, left in unknown_locations:
                    dr.rectangle([(left, top), (right, bottom)], outline=(255, 0, 0), width=3)
                im.save(str(annotated_path))
            elif cv2 is not None:
                im = cv2.imread(str(ip))
                for top, right, bottom, left in unknown_locations:
                    cv2.rectangle(im, (left, top), (right, bottom), (0, 0, 255), 3)
                cv2.imwrite(str(annotated_path), im)
        except Exception:
            annotated_path = None
    if unknown_locations:
        try:
            db.unregistered_detections.insert_one({
                'image_path': str(annotated_path or image_path),
                'raw_image_path': str(image_path),
                'location': location,
                'camera_serial': camera_serial,
                'timestamp': datetime.now()
            })
        except Exception:
            pass
    return {'unknown_faces': len(unknown_locations)}
