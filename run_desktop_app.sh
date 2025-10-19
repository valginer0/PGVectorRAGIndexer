#!/bin/bash
# Launch script for PGVectorRAGIndexer Desktop Application

echo "=========================================="
echo "PGVectorRAGIndexer Desktop App"
echo "=========================================="
echo ""

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "Virtual environment not found. Creating..."
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Check if PySide6 is installed
if ! python -c "import PySide6" 2>/dev/null; then
    echo "Installing desktop app dependencies..."
    pip install -r requirements-desktop.txt
fi

echo "Starting desktop application..."
python -m desktop_app.main
