"""
Build script for PGVectorRAGIndexer Windows Installer

Creates a standalone .exe using PyInstaller.
Run this on a Windows machine with PyInstaller installed:

    pip install pyinstaller
    python build_installer.py
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path


def build():
    """Build the installer executable."""
    
    # Paths
    script_dir = Path(__file__).parent
    main_script = script_dir / "installer_gui.py"
    dist_dir = script_dir / "dist"
    build_dir = script_dir / "build"
    
    print("=" * 60)
    print("PGVectorRAGIndexer Installer Builder")
    print("=" * 60)
    print()
    
    # Check PyInstaller is installed
    try:
        import PyInstaller
        print(f"✓ PyInstaller version: {PyInstaller.__version__}")
    except ImportError:
        print("✗ PyInstaller not found. Installing...")
        subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"])
    
    # Clean previous builds
    for dir_path in [dist_dir, build_dir]:
        if dir_path.exists():
            print(f"  Cleaning {dir_path}...")
            shutil.rmtree(dir_path)
    
    print()
    print("Building installer...")
    print()
    
    # PyInstaller command
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",                           # Single .exe file
        "--windowed",                          # No console window
        "--name", "PGVectorRAGIndexer-Setup",  # Output name
        "--clean",                             # Clean cache
        "--noconfirm",                         # Overwrite without asking
        "--add-data", "..\\VERSION;.",          # Include version file (relative to windows_installer dir)
        # Add icon if available
        # "--icon", "icon.ico",
        str(main_script)
    ]
    
    result = subprocess.run(cmd, cwd=script_dir)
    
    if result.returncode == 0:
        exe_path = dist_dir / "PGVectorRAGIndexer-Setup.exe"
        if exe_path.exists():
            size_mb = exe_path.stat().st_size / (1024 * 1024)
            print()
            print("=" * 60)
            print("✓ Build successful!")
            print(f"  Output: {exe_path}")
            print(f"  Size: {size_mb:.1f} MB")
            print("=" * 60)
        else:
            print("✗ Build completed but exe not found")
    else:
        print("✗ Build failed")
        sys.exit(1)


if __name__ == "__main__":
    build()
