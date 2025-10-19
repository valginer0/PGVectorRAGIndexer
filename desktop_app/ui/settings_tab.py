"""
Settings tab for Docker management and configuration.
"""

import logging
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QTextEdit, QMessageBox, QGridLayout
)
from PySide6.QtCore import QThread, Signal

import requests

logger = logging.getLogger(__name__)


class StatsWorker(QThread):
    """Worker thread for loading statistics."""
    
    finished = Signal(bool, object)  # success, stats or error message
    
    def __init__(self, api_client):
        super().__init__()
        self.api_client = api_client
    
    def run(self):
        """Load statistics."""
        try:
            stats = self.api_client.get_statistics()
            self.finished.emit(True, stats)
        except requests.RequestException as e:
            self.finished.emit(False, str(e))
        except Exception as e:
            self.finished.emit(False, str(e))


class SettingsTab(QWidget):
    """Tab for settings and Docker management."""
    
    def __init__(self, docker_manager, parent=None):
        super().__init__(parent)
        self.docker_manager = docker_manager
        # Get API client from parent
        self.api_client = None
        if parent and hasattr(parent, 'api_client'):
            self.api_client = parent.api_client
        self.stats_worker = None
        self.setup_ui()
    
    def setup_ui(self):
        """Setup the user interface."""
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        
        # Title
        header_layout = QHBoxLayout()
        title = QLabel("⚙️ Settings & Management")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        header_layout.addWidget(title)
        header_layout.addStretch()
        
        layout.addLayout(header_layout)
        
        # Statistics
        if self.api_client:
            stats_group = QGroupBox("Database Statistics")
            stats_layout = QVBoxLayout(stats_group)
            
            self.stats_grid = QGridLayout()
            
            # Placeholder labels
            self.total_docs_label = QLabel("--")
            self.total_chunks_label = QLabel("--")
            self.db_size_label = QLabel("--")
            
            self.stats_grid.addWidget(QLabel("Total Documents:"), 0, 0)
            self.stats_grid.addWidget(self.total_docs_label, 0, 1)
            
            self.stats_grid.addWidget(QLabel("Total Chunks:"), 1, 0)
            self.stats_grid.addWidget(self.total_chunks_label, 1, 1)
            
            self.stats_grid.addWidget(QLabel("Database Size:"), 2, 0)
            self.stats_grid.addWidget(self.db_size_label, 2, 1)
            
            stats_layout.addLayout(self.stats_grid)
            
            refresh_stats_btn = QPushButton("🔄 Refresh Statistics")
            refresh_stats_btn.clicked.connect(self.load_statistics)
            stats_layout.addWidget(refresh_stats_btn)
            
            layout.addWidget(stats_group)
            
            # Auto-load stats
            self.load_statistics()
        
        # Docker controls
        docker_group = QGroupBox("Docker Container Management")
        docker_layout = QVBoxLayout(docker_group)
        
        restart_btn = QPushButton("🔄 Restart Containers")
        restart_btn.clicked.connect(self.restart_containers)
        restart_btn.setMinimumHeight(35)
        docker_layout.addWidget(restart_btn)
        
        logs_btn = QPushButton("📋 View Application Logs")
        logs_btn.clicked.connect(self.view_logs)
        logs_btn.setMinimumHeight(35)
        docker_layout.addWidget(logs_btn)
        
        layout.addWidget(docker_group)
        
        # Logs display
        logs_group = QGroupBox("Container Logs")
        logs_layout = QVBoxLayout(logs_group)
        
        self.logs_text = QTextEdit()
        self.logs_text.setReadOnly(True)
        self.logs_text.setMaximumHeight(200)
        self.logs_text.setPlaceholderText("Click 'View Application Logs' to load logs...")
        logs_layout.addWidget(self.logs_text)
        
        layout.addWidget(logs_group)
        
        layout.addStretch()
    
    def load_statistics(self):
        """Load database statistics."""
        if not self.api_client or not self.api_client.is_api_available():
            QMessageBox.warning(
                self,
                "API Not Available",
                "Cannot load statistics. Please make sure Docker containers are running."
            )
            return
        
        # Start worker
        self.stats_worker = StatsWorker(self.api_client)
        self.stats_worker.finished.connect(self.stats_loaded)
        self.stats_worker.start()
    
    def stats_loaded(self, success: bool, data):
        """Handle statistics load completion."""
        if success:
            stats = data
            self.total_docs_label.setText(str(stats.get('total_documents', 0)))
            self.total_chunks_label.setText(str(stats.get('total_chunks', 0)))
            
            # Format database size
            db_size = stats.get('database_size_bytes', 0)
            if db_size > 1024 * 1024:
                size_str = f"{db_size / (1024 * 1024):.2f} MB"
            elif db_size > 1024:
                size_str = f"{db_size / 1024:.2f} KB"
            else:
                size_str = f"{db_size} bytes"
            
            self.db_size_label.setText(size_str)
        else:
            error_msg = data
            QMessageBox.critical(self, "Load Failed", f"Failed to load statistics: {error_msg}")
    
    def restart_containers(self):
        """Restart Docker containers."""
        reply = QMessageBox.question(
            self,
            "Restart Containers?",
            "Are you sure you want to restart the Docker containers?\n\nThis will temporarily stop the API.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            success, message = self.docker_manager.restart_containers()
            if success:
                QMessageBox.information(self, "Success", message)
                # Refresh parent status
                if self.parent() and hasattr(self.parent(), 'check_docker_status'):
                    self.parent().check_docker_status()
            else:
                QMessageBox.critical(self, "Error", message)
    
    def view_logs(self):
        """View container logs."""
        logs = self.docker_manager.get_logs()
        self.logs_text.setPlainText(logs)
