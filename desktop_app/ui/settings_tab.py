"""
Settings tab for Docker management and configuration.
"""

import logging
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QTextEdit, QMessageBox, QGridLayout, QFileDialog
)
import qtawesome as qta
from PySide6.QtCore import QThread, Signal, QSize, Qt
from .workers import StatsWorker
from .styles.theme import Theme

# ... imports ...

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
        layout.setSpacing(20)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Title
        header_layout = QHBoxLayout()
        title = QLabel("Settings & Management")
        title.setProperty("class", "header")
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
            
            refresh_stats_btn = QPushButton("Refresh Statistics")
            refresh_stats_btn.setIcon(qta.icon('fa5s.sync-alt', color='white'))
            refresh_stats_btn.clicked.connect(self.load_statistics)
            stats_layout.addWidget(refresh_stats_btn)
            
            layout.addWidget(stats_group)
            
            # Don't auto-load stats on startup - wait for user to click refresh
            # This prevents premature API calls before containers are ready
            # self.load_statistics()
        
        # License panel
        self._build_license_panel(layout)

        # Docker controls
        docker_group = QGroupBox("Docker Container Management")
        docker_layout = QVBoxLayout(docker_group)
        
        restart_btn = QPushButton("Restart Containers")
        restart_btn.setIcon(qta.icon('fa5s.redo', color='white'))
        restart_btn.clicked.connect(self.restart_containers)
        restart_btn.setMinimumHeight(40)
        restart_btn.setStyleSheet("background-color: #f59e0b; border: 1px solid #f59e0b;") # Warning color
        docker_layout.addWidget(restart_btn)
        
        logs_btn = QPushButton("View Application Logs")
        logs_btn.setIcon(qta.icon('fa5s.file-alt', color='white'))
        logs_btn.clicked.connect(self.view_logs)
        logs_btn.setMinimumHeight(40)
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
    
    # ------------------------------------------------------------------
    # License panel
    # ------------------------------------------------------------------

    def _build_license_panel(self, parent_layout):
        """Build the License information group box."""
        license_group = QGroupBox("License")
        grid = QGridLayout(license_group)
        grid.setSpacing(8)

        # Row 0 — Edition badge
        grid.addWidget(QLabel("Edition:"), 0, 0)
        self._edition_badge = QLabel("--")
        self._edition_badge.setStyleSheet("font-weight: 600;")
        grid.addWidget(self._edition_badge, 0, 1)

        # Row 1 — Organization
        grid.addWidget(QLabel("Organization:"), 1, 0)
        self._org_label = QLabel("--")
        grid.addWidget(self._org_label, 1, 1)

        # Row 2 — Expiry
        grid.addWidget(QLabel("Expires:"), 2, 0)
        self._expiry_label = QLabel("--")
        grid.addWidget(self._expiry_label, 2, 1)

        # Row 3 — Seats
        grid.addWidget(QLabel("Seats:"), 3, 0)
        self._seats_label = QLabel("--")
        grid.addWidget(self._seats_label, 3, 1)

        # Buttons row
        btn_layout = QHBoxLayout()

        self._enter_key_btn = QPushButton("Enter License Key")
        self._enter_key_btn.setIcon(qta.icon('fa5s.key', color='white'))
        self._enter_key_btn.clicked.connect(self._enter_license_key)
        btn_layout.addWidget(self._enter_key_btn)

        self._upgrade_btn = QPushButton("Upgrade to Team →")
        self._upgrade_btn.setFlat(True)
        self._upgrade_btn.setCursor(Qt.PointingHandCursor)
        self._upgrade_btn.setStyleSheet(
            f"color: {Theme.PRIMARY}; text-decoration: underline; border: none;"
        )
        self._upgrade_btn.clicked.connect(self._open_pricing)
        btn_layout.addWidget(self._upgrade_btn)

        btn_layout.addStretch()
        grid.addLayout(btn_layout, 4, 0, 1, 2)

        parent_layout.addWidget(license_group)

        # Populate with current license info
        self._refresh_license_panel()

    def _refresh_license_panel(self):
        """Update the license panel with current license info."""
        try:
            from desktop_app.utils.edition import get_edition_display
            info = get_edition_display()
        except Exception as e:
            logging.getLogger(__name__).debug("Could not load license info: %s", e)
            self._edition_badge.setText("Community Edition")
            self._edition_badge.setStyleSheet(f"font-weight: 600; color: {Theme.TEXT_SECONDARY};")
            self._org_label.setText("—")
            self._expiry_label.setText("—")
            self._seats_label.setText("—")
            self._upgrade_btn.setVisible(True)
            return

        # Edition badge
        if info["is_team"]:
            self._edition_badge.setText("Team Edition ✓")
            self._edition_badge.setStyleSheet(f"font-weight: 600; color: {Theme.SUCCESS};")
            self._upgrade_btn.setVisible(False)
        else:
            self._edition_badge.setText("Community Edition")
            self._edition_badge.setStyleSheet(f"font-weight: 600; color: {Theme.TEXT_SECONDARY};")
            self._upgrade_btn.setVisible(True)

        # Org
        self._org_label.setText(info["org_name"] if info["org_name"] else "—")

        # Expiry
        if info["is_team"]:
            days = info["days_left"]
            if info["expiry_warning"]:
                self._expiry_label.setText(f"{days} days remaining")
                self._expiry_label.setStyleSheet(f"color: {Theme.WARNING}; font-weight: 600;")
            else:
                self._expiry_label.setText(f"{days} days remaining")
                self._expiry_label.setStyleSheet("")
        else:
            self._expiry_label.setText("—")
            self._expiry_label.setStyleSheet("")

        # Seats
        if info["is_team"] and info["seats"] > 0:
            self._seats_label.setText(f"Licensed for {info['seats']} seats")
        else:
            self._seats_label.setText("—")

        # Warning text (e.g., expiry warning, invalid key)
        if info["warning_text"]:
            logging.getLogger(__name__).info("License warning: %s", info["warning_text"])

    def _enter_license_key(self):
        """Let the user browse for a .key file and install it."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select License Key File",
            "",
            "License Key Files (*.key);;All Files (*)",
        )
        if not file_path:
            return

        try:
            from license import get_license_dir
            dest_dir = get_license_dir()
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest_file = dest_dir / "license.key"

            # Copy the key file
            import shutil
            shutil.copy2(file_path, dest_file)

            # Secure file permissions
            from license import secure_license_file
            secure_license_file(dest_file)

            # Reload license
            from license import reset_license
            reset_license()
            self._refresh_license_panel()

            QMessageBox.information(
                self,
                "License Installed",
                f"License key installed to:\n{dest_file}\n\n"
                "Restart the application for full effect.",
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                "License Error",
                f"Failed to install license key:\n{e}",
            )

    def _open_pricing(self):
        """Open the pricing page."""
        from desktop_app.utils.edition import open_pricing_page
        open_pricing_page()

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
            # Show a more helpful error message
            QMessageBox.warning(
                self, 
                "Statistics Not Available", 
                f"Failed to load statistics.\n\nError: {error_msg}\n\nThe API may still be starting up. Please:\n1. Wait a moment\n2. Check that the API status is green\n3. Try 'Refresh Statistics' again"
            )
    
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
