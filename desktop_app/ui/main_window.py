"""
Main window for the desktop application.
"""

import logging
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QStatusBar, QPushButton, QLabel,
    QMessageBox, QFileDialog, QProgressDialog
)
from PySide6.QtCore import Qt, QTimer, QThread, Signal, QSize
from PySide6.QtGui import QIcon

import qtawesome as qta

from .upload_tab import UploadTab
from .search_tab import SearchTab
from .documents_tab import DocumentsTab
from .manage_tab import ManageTab
from .settings_tab import SettingsTab
from .recent_activity_tab import RecentActivityTab
from .source_open_manager import SourceOpenManager
from ..utils.docker_manager import DockerManager
from ..utils.api_client import APIClient

logger = logging.getLogger(__name__)


class DockerStartWorker(QThread):
    """Worker thread for starting Docker containers."""
    
    finished = Signal(bool, str)  # success, message
    
    def __init__(self, docker_manager):
        super().__init__()
        self.docker_manager = docker_manager
    
    def run(self):
        """Start containers."""
        success, message = self.docker_manager.start_containers()
        self.finished.emit(success, message)


class MainWindow(QMainWindow):
    """Main application window."""
    
    def __init__(self):
        super().__init__()
        
        # Get project path (parent of desktop_app directory)
        self.project_path = Path(__file__).parent.parent.parent
        
        # Initialize managers
        self.docker_manager = DockerManager(self.project_path)
        self.api_client = APIClient()
        self.source_manager = SourceOpenManager(self.api_client, parent=self, project_root=self.project_path)
        
        # Setup UI
        self.setup_ui()
        
        # Check Docker and API status
        QTimer.singleShot(500, self.check_initial_status)
    
    def setup_ui(self):
        """Setup the user interface."""
        self.setWindowTitle("PGVectorRAGIndexer - Document Management")
        # Height: Need ~880px for content + safety margin
        self.setMinimumSize(1100, 950)
        
        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Main layout
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)
        
        # Docker status bar at top
        self.create_docker_status_bar(layout)
        
        # Tab widget
        self.tabs = QTabWidget()
        self.tabs.setIconSize(qta.icon('fa5s.home').actualSize(QSize(20, 20))) # Dummy size init
        layout.addWidget(self.tabs)
        
        # Create tabs
        self.upload_tab = UploadTab(self.api_client, self)
        self.search_tab = SearchTab(self.api_client, self, source_manager=self.source_manager)
        self.documents_tab = DocumentsTab(self.api_client, self)
        self.documents_tab.source_manager = self.source_manager
        self.manage_tab = ManageTab(self.api_client, source_manager=self.source_manager)
        self.settings_tab = SettingsTab(self.docker_manager, self)
        self.recent_tab = RecentActivityTab(self.source_manager, self)

        # Add tabs with icons (ordered by typical workflow)
        self.tabs.addTab(self.upload_tab, qta.icon('fa5s.cloud-upload-alt', color='#9ca3af'), "Upload")
        self.tabs.addTab(self.search_tab, qta.icon('fa5s.search', color='#9ca3af'), "Search")
        self.tabs.addTab(self.documents_tab, qta.icon('fa5s.book', color='#9ca3af'), "Documents")
        self.tabs.addTab(self.recent_tab, qta.icon('fa5s.clock', color='#9ca3af'), "Recent")
        self.tabs.addTab(self.manage_tab, qta.icon('fa5s.trash-alt', color='#9ca3af'), "Manage")
        self.tabs.addTab(self.settings_tab, qta.icon('fa5s.cog', color='#9ca3af'), "Settings")
        
        # Status bar at bottom
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")

    def create_docker_status_bar(self, parent_layout):
        """Create the Docker status indicator bar."""
        status_widget = QWidget()
        status_widget.setObjectName("dockerStatus")
        status_widget.setStyleSheet("""
            #dockerStatus {
                background-color: #1f2937;
                border-radius: 8px;
                border: 1px solid #374151;
            }
        """)
        status_layout = QHBoxLayout(status_widget)
        status_layout.setContentsMargins(15, 10, 15, 10)
        
        # Docker status indicator
        self.docker_status_label = QLabel("Docker: Checking...")
        self.docker_status_icon = QLabel()
        self.docker_status_icon.setPixmap(qta.icon('fa5s.circle', color='#ef4444').pixmap(16, 16))
        
        status_layout.addWidget(self.docker_status_icon)
        status_layout.addWidget(self.docker_status_label)
        status_layout.addSpacing(20)
        
        # API status indicator
        self.api_status_label = QLabel("API: Checking...")
        self.api_status_icon = QLabel()
        self.api_status_icon.setPixmap(qta.icon('fa5s.circle', color='#ef4444').pixmap(16, 16))
        
        status_layout.addWidget(self.api_status_icon)
        status_layout.addWidget(self.api_status_label)
        
        status_layout.addStretch()
        
        # Start/Stop button
        self.docker_control_btn = QPushButton("Start Containers")
        self.docker_control_btn.setIcon(qta.icon('fa5s.play', color='white'))
        self.docker_control_btn.setProperty("class", "primary")
        self.docker_control_btn.clicked.connect(self.toggle_docker)
        status_layout.addWidget(self.docker_control_btn)
        
        # Refresh button
        refresh_btn = QPushButton("Refresh Status")
        refresh_btn.setIcon(qta.icon('fa5s.sync-alt', color='white'))
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
            self.docker_status_label.setText("Docker: Not Available")
            self.docker_status_icon.setPixmap(qta.icon('fa5s.times-circle', color='#ef4444').pixmap(16, 16))
            self.api_status_label.setText("API: Not Available")
            self.api_status_icon.setPixmap(qta.icon('fa5s.times-circle', color='#ef4444').pixmap(16, 16))
            self.docker_control_btn.setEnabled(False)
            self.status_bar.showMessage("Docker is not available. Please install Docker Desktop.")
            return
        
        # Check containers
        db_running, app_running = self.docker_manager.get_container_status()
        
        if db_running and app_running:
            self.docker_status_label.setText("Docker: Running")
            self.docker_status_icon.setPixmap(qta.icon('fa5s.check-circle', color='#10b981').pixmap(16, 16))
            self.docker_control_btn.setText("Stop Containers")
            self.docker_control_btn.setIcon(qta.icon('fa5s.stop', color='white'))
            self.docker_control_btn.setProperty("class", "danger")
        else:
            self.docker_status_label.setText("Docker: Stopped")
            self.docker_status_icon.setPixmap(qta.icon('fa5s.stop-circle', color='#ef4444').pixmap(16, 16))
            self.docker_control_btn.setText("Start Containers")
            self.docker_control_btn.setIcon(qta.icon('fa5s.play', color='white'))
            self.docker_control_btn.setProperty("class", "primary")
        
        # Force style update
        self.docker_control_btn.style().unpolish(self.docker_control_btn)
        self.docker_control_btn.style().polish(self.docker_control_btn)
        
        # Check API
        if self.api_client.is_api_available():
            self.api_status_label.setText("API: Ready")
            self.api_status_icon.setPixmap(qta.icon('fa5s.check-circle', color='#10b981').pixmap(16, 16))
            self.status_bar.showMessage("Ready - All systems operational")
        else:
            self.api_status_label.setText("API: Not Available")
            self.api_status_icon.setPixmap(qta.icon('fa5s.times-circle', color='#ef4444').pixmap(16, 16))
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
        
        # Create progress dialog
        self.progress_dialog = QProgressDialog(
            "Starting Docker containers...\n\nThis may take up to 90 seconds.\nPlease wait while the database and application initialize.\n\nThe window will remain responsive.",
            None,  # No cancel button
            0, 0,  # Indeterminate progress
            self
        )
        self.progress_dialog.setWindowTitle("Starting Containers")
        self.progress_dialog.setMinimumDuration(0)
        self.progress_dialog.setWindowModality(Qt.WindowModal)
        self.progress_dialog.show()
        
        # Start worker thread
        self.docker_start_worker = DockerStartWorker(self.docker_manager)
        self.docker_start_worker.finished.connect(self.docker_start_finished)
        self.docker_start_worker.start()
    
    def docker_start_finished(self, success: bool, message: str):
        """Handle Docker start completion."""
        # Close progress dialog
        if hasattr(self, 'progress_dialog'):
            self.progress_dialog.close()
        
        # Re-enable button
        self.docker_control_btn.setEnabled(True)
        
        if success:
            QMessageBox.information(self, "Success", message)
            # Wait a bit for API to be ready, then check status
            QTimer.singleShot(3000, self.check_docker_status)
        else:
            QMessageBox.critical(self, "Error", message)
        
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
