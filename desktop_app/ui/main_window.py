"""
Main window for the desktop application.
"""

import logging
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QStatusBar, QPushButton, QLabel,
    QMessageBox, QFileDialog
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon

from .upload_tab import UploadTab
from .search_tab import SearchTab
from .documents_tab import DocumentsTab
from .settings_tab import SettingsTab
from ..utils.docker_manager import DockerManager
from ..utils.api_client import APIClient

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Main application window."""
    
    def __init__(self):
        super().__init__()
        
        # Get project path (parent of desktop_app directory)
        self.project_path = Path(__file__).parent.parent.parent
        
        # Initialize managers
        self.docker_manager = DockerManager(self.project_path)
        self.api_client = APIClient()
        
        # Setup UI
        self.setup_ui()
        
        # Check Docker and API status
        QTimer.singleShot(500, self.check_initial_status)
    
    def setup_ui(self):
        """Setup the user interface."""
        self.setWindowTitle("PGVectorRAGIndexer - Document Management")
        self.setMinimumSize(1000, 700)
        
        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Main layout
        layout = QVBoxLayout(central_widget)
        
        # Docker status bar at top
        self.create_docker_status_bar(layout)
        
        # Tab widget
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        
        # Create tabs
        self.upload_tab = UploadTab(self.api_client, self)
        self.search_tab = SearchTab(self.api_client, self)
        self.documents_tab = DocumentsTab(self.api_client, self)
        self.settings_tab = SettingsTab(self.docker_manager, self)
        
        self.tabs.addTab(self.upload_tab, "📤 Upload")
        self.tabs.addTab(self.search_tab, "🔍 Search")
        self.tabs.addTab(self.documents_tab, "📚 Documents")
        self.tabs.addTab(self.settings_tab, "⚙️ Settings")
        
        # Status bar at bottom
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")
    
    def create_docker_status_bar(self, parent_layout):
        """Create the Docker status indicator bar."""
        status_widget = QWidget()
        status_layout = QHBoxLayout(status_widget)
        status_layout.setContentsMargins(10, 5, 10, 5)
        
        # Docker status indicator
        self.docker_status_label = QLabel("🔴 Docker: Checking...")
        self.docker_status_label.setStyleSheet("font-weight: bold;")
        status_layout.addWidget(self.docker_status_label)
        
        # API status indicator
        self.api_status_label = QLabel("🔴 API: Checking...")
        self.api_status_label.setStyleSheet("font-weight: bold;")
        status_layout.addWidget(self.api_status_label)
        
        status_layout.addStretch()
        
        # Start/Stop button
        self.docker_control_btn = QPushButton("Start Containers")
        self.docker_control_btn.clicked.connect(self.toggle_docker)
        status_layout.addWidget(self.docker_control_btn)
        
        # Refresh button
        refresh_btn = QPushButton("🔄 Refresh Status")
        refresh_btn.clicked.connect(self.check_docker_status)
        status_layout.addWidget(refresh_btn)
        
        parent_layout.addWidget(status_widget)
    
    def check_initial_status(self):
        """Check Docker and API status on startup."""
        self.check_docker_status()
        
        # If containers are not running, ask to start them
        db_running, app_running = self.docker_manager.get_container_status()
        if not (db_running and app_running):
            reply = QMessageBox.question(
                self,
                "Start Containers?",
                "Docker containers are not running. Would you like to start them?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )
            
            if reply == QMessageBox.Yes:
                self.start_docker()
    
    def check_docker_status(self):
        """Check and update Docker and API status."""
        # Check Docker
        if not self.docker_manager.is_docker_available():
            self.docker_status_label.setText("🔴 Docker: Not Available")
            self.api_status_label.setText("🔴 API: Not Available")
            self.docker_control_btn.setEnabled(False)
            self.status_bar.showMessage("Docker is not available. Please install Docker Desktop.")
            return
        
        # Check containers
        db_running, app_running = self.docker_manager.get_container_status()
        
        if db_running and app_running:
            self.docker_status_label.setText("🟢 Docker: Running")
            self.docker_control_btn.setText("Stop Containers")
        else:
            self.docker_status_label.setText("🔴 Docker: Stopped")
            self.docker_control_btn.setText("Start Containers")
        
        # Check API
        if self.api_client.is_api_available():
            self.api_status_label.setText("🟢 API: Ready")
            self.status_bar.showMessage("Ready - All systems operational")
        else:
            self.api_status_label.setText("🔴 API: Not Available")
            if db_running and app_running:
                self.status_bar.showMessage("Containers running but API not ready. Please wait...")
            else:
                self.status_bar.showMessage("API not available. Please start containers.")
    
    def toggle_docker(self):
        """Toggle Docker containers on/off."""
        db_running, app_running = self.docker_manager.get_container_status()
        
        if db_running and app_running:
            self.stop_docker()
        else:
            self.start_docker()
    
    def start_docker(self):
        """Start Docker containers."""
        self.status_bar.showMessage("Starting Docker containers...")
        self.docker_control_btn.setEnabled(False)
        
        success, message = self.docker_manager.start_containers()
        
        if success:
            QMessageBox.information(self, "Success", message)
            # Wait a bit for API to be ready, then check status
            QTimer.singleShot(3000, self.check_docker_status)
        else:
            QMessageBox.critical(self, "Error", message)
        
        self.docker_control_btn.setEnabled(True)
        self.check_docker_status()
    
    def stop_docker(self):
        """Stop Docker containers."""
        reply = QMessageBox.question(
            self,
            "Stop Containers?",
            "Are you sure you want to stop the Docker containers?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.status_bar.showMessage("Stopping Docker containers...")
            self.docker_control_btn.setEnabled(False)
            
            success, message = self.docker_manager.stop_containers()
            
            if success:
                QMessageBox.information(self, "Success", message)
            else:
                QMessageBox.critical(self, "Error", message)
            
            self.docker_control_btn.setEnabled(True)
            self.check_docker_status()
