"""
Script to install all required dependencies for the Attendance System
"""
import subprocess
import sys

def install_package(package):
    """Install a Python package using pip"""
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])
        print(f"✓ Successfully installed {package}")
        return True
    except subprocess.CalledProcessError:
        print(f"✗ Failed to install {package}")
        return False

def main():
    print("Installing dependencies for College Attendance System...")
    print("=" * 50)
    
    packages = [
        "Flask==3.0.0",
        "flask-login==0.6.3",
        "pymongo==4.6.1",
        "bcrypt==4.1.2",
        "python-dotenv==1.0.0",
        "Werkzeug==3.0.1",
        "face-recognition==1.3.0",
        "opencv-python==4.8.1.78",
        "numpy==1.24.3",
        "Pillow==10.1.0"
    ]
    
    failed = []
    for package in packages:
        if not install_package(package):
            failed.append(package)
    
    print("=" * 50)
    if failed:
        print(f"\nFailed to install {len(failed)} package(s):")
        for pkg in failed:
            print(f"  - {pkg}")
        print("\nPlease install them manually using: pip install <package>")
    else:
        print("\n✓ All dependencies installed successfully!")
        print("\nNote: face-recognition requires dlib, which may need additional setup:")
        print("  Windows: pip install dlib")
        print("  Linux/Mac: May require cmake and dlib installation")
        print("\nIf face-recognition installation fails, you can use an alternative:")
        print("  pip install face-recognition --no-deps")
        print("  Then install dlib separately based on your OS")

if __name__ == "__main__":
    main()

