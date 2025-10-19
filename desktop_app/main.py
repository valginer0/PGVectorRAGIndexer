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


def main():
    """Main entry point for the desktop application."""
    # Enable high DPI scaling
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    
    app = QApplication(sys.argv)
    app.setApplicationName("PGVectorRAGIndexer")
    app.setOrganizationName("ValginerSoft")
    app.setApplicationVersion("2.2.0")
    
    # Create and show main window
    window = MainWindow()
    window.show()
    
    logger.info("Desktop application started")
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
