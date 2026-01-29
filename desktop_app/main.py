"""
PGVectorRAGIndexer Desktop Application

A native desktop application for managing document indexing and search
with full file path preservation.
"""

import sys
import logging
from pathlib import Path

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from .ui.main_window import MainWindow

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Import version from central module
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from version import __version__


def main():
    """Main entry point for the desktop application."""
    # Enable high DPI scaling
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    
    app = QApplication(sys.argv)
    app.setApplicationName("PGVectorRAGIndexer")
    app.setOrganizationName("ValginerSoft")
    app.setApplicationVersion(__version__)
    
    # Create and show main window
    # Create and show main window
    window = MainWindow()
    
    # Load and apply QSS
    try:
        import os
        style_path = os.path.join(os.path.dirname(__file__), "ui", "styles", "main.qss")
        if os.path.exists(style_path):
            with open(style_path, "r") as f:
                app.setStyleSheet(f.read())
            logger.info(f"Loaded stylesheet from {style_path}")
        else:
            logger.warning(f"Stylesheet not found at {style_path}")
    except Exception as e:
        logger.error(f"Failed to load stylesheet: {e}")

    window.show()
    
    logger.info("Desktop application started")
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
