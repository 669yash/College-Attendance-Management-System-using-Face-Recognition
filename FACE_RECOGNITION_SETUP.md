# Face Recognition Setup Guide

## Complete Working Face Recognition System

This system uses the `face_recognition` library, which is built on dlib. Follow these steps for complete setup.

## Installation Steps

### Option 1: Automatic Installation (Recommended)

Run the installation script:
```bash
python install_dependencies.py
```

### Option 2: Manual Installation

#### Step 1: Install Basic Dependencies
```bash
pip install Flask==3.0.0 flask-login==0.6.3 pymongo==4.6.1 bcrypt==4.1.2 python-dotenv==1.0.0 Werkzeug==3.0.1
```

#### Step 2: Install Image Processing Libraries
```bash
pip install numpy==1.24.3 Pillow==10.1.0 opencv-python==4.8.1.78
```

#### Step 3: Install Face Recognition Library

**For Windows:**
```bash
pip install cmake
pip install dlib
pip install face-recognition
```

**For Linux (Ubuntu/Debian):**
```bash
sudo apt-get update
sudo apt-get install build-essential cmake
sudo apt-get install libopenblas-dev liblapack-dev
pip install dlib
pip install face-recognition
```

**For macOS:**
```bash
brew install cmake
pip install dlib
pip install face-recognition
```

**If dlib installation fails**, you can try:
```bash
# For Windows with Visual Studio Build Tools
pip install dlib-binary
pip install face-recognition
```

## How It Works

### 1. Student Registration
- Student uploads 4-5 face images
- System detects faces in each image
- Creates face encodings (128-dimensional vectors)
- Averages encodings from all images for robustness
- Stores encodings in MongoDB `face_encodings` collection

### 2. Attendance Marking
- Professor uploads 4-5 classroom images
- System detects all faces in classroom images
- Compares each detected face with stored student encodings
- Uses distance metric (tolerance: 0.6) to match faces
- Marks students as "present" if their face is matched
- Marks students as "absent" if no match found

### 3. Face Matching Algorithm
- Uses Euclidean distance between face encodings
- Tolerance of 0.6 (lower = more strict)
- Matches are counted across all classroom images
- Student is marked present if matched in at least one image

## Configuration

You can adjust face recognition settings in `utils/face_recognition_interface.py`:

```python
FACE_ENCODING_TOLERANCE = 0.6  # Lower = more strict (0.0 to 1.0)
MIN_FACE_DETECTIONS = 2  # Minimum faces needed during registration
```

## Testing the System

### Test Student Registration
1. Register a student with 4-5 clear face images
2. Check console for: "Successfully encoded faces for [roll_number]"
3. Verify in MongoDB: `db.face_encodings.find({"roll_number": "YOUR_ROLL"})`

### Test Attendance Marking
1. Create a class as professor
2. Upload 4-5 classroom images containing student faces
3. Check console for face detection and matching results
4. Verify attendance records in database

## Troubleshooting

### Issue: "face_recognition library not available"
**Solution:** Install face-recognition library (see Step 3 above)

### Issue: "dlib installation fails"
**Solution:** 
- Windows: Install Visual Studio Build Tools, then `pip install dlib`
- Linux: Install cmake and required libraries first
- Alternative: Use pre-built wheels: `pip install dlib-binary`

### Issue: "No faces detected"
**Solution:**
- Ensure images are clear and well-lit
- Faces should be front-facing
- Avoid blurry or side-profile images
- Check image format (JPG, PNG supported)

### Issue: "Low accuracy in matching"
**Solution:**
- Adjust `FACE_ENCODING_TOLERANCE` (try 0.5 for stricter matching)
- Ensure student registration images are high quality
- Use multiple angles/lighting in registration images
- Ensure classroom images are clear

## Performance Notes

- **HOG Model**: Fast, good for real-time (default)
- **CNN Model**: More accurate but slower (change `model='hog'` to `model='cnn'`)

To use CNN model (more accurate):
```python
face_locations = face_recognition.face_locations(image, model='cnn')
```

## Database Schema

The system creates a `face_encodings` collection:

```json
{
  "_id": ObjectId,
  "roll_number": "string",
  "encoding": [128 float values],
  "num_images": number,
  "num_faces_detected": number
}
```

## Production Recommendations

1. **Image Quality**: Require high-resolution images (min 640x480)
2. **Lighting**: Ensure consistent lighting in classroom
3. **Camera Position**: Fixed camera position for better results
4. **Multiple Angles**: Use multiple classroom images from different angles
5. **Tolerance Tuning**: Adjust tolerance based on your environment
6. **Error Handling**: Add retry logic for failed face detections
7. **Caching**: Cache encodings in memory for faster processing

## Alternative Solutions

If face_recognition library cannot be installed, you can:
1. Use cloud-based face recognition APIs (AWS Rekognition, Azure Face API)
2. Use TensorFlow/Keras custom models
3. Use simpler OpenCV-based detection (less accurate)

The system includes fallback mechanisms in `utils/face_recognition_fallback.py`.

