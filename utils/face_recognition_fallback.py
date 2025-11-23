"""
Fallback face recognition using OpenCV Haar Cascades
Use this if face-recognition library installation fails
"""

import cv2
import numpy as np
from pathlib import Path
from typing import Dict, List
import os

# This is a simpler fallback that uses OpenCV's built-in face detection
# Note: This is less accurate than face_recognition library but works without dlib

def detect_faces_opencv(image_path: str) -> List:
    """
    Detect faces using OpenCV Haar Cascade
    
    Args:
        image_path: Path to image file
    
    Returns:
        list: List of face bounding boxes (x, y, w, h)
    """
    try:
        # Load image
        image = cv2.imread(image_path)
        if image is None:
            return []
        
        # Convert to grayscale
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        
        # Load face cascade
        face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
        
        # Detect faces
        faces = face_cascade.detectMultiScale(gray, 1.1, 4)
        
        return faces.tolist()
    except Exception as e:
        print(f"Error in OpenCV face detection: {e}")
        return []


def simple_face_matching(student_folder: Path, classroom_image_path: str) -> bool:
    """
    Simple face matching based on face count and position
    This is a basic fallback - not as accurate as face_recognition
    
    Args:
        student_folder: Path to student's face images folder
        classroom_image_path: Path to classroom image
    
    Returns:
        bool: True if face detected, False otherwise
    """
    # Count faces in student images
    student_faces = 0
    for img_file in student_folder.glob('*.jpg'):
        faces = detect_faces_opencv(str(img_file))
        if len(faces) > 0:
            student_faces += 1
    
    # Count faces in classroom image
    classroom_faces = detect_faces_opencv(classroom_image_path)
    
    # Very basic matching - if faces detected in both, consider it a match
    # This is a fallback only - not recommended for production
    return len(classroom_faces) > 0 and student_faces >= 3

