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
from .health_tab import HealthTab
from .watched_folders_tab import WatchedFoldersTab
from .source_open_manager import SourceOpenManager
from ..utils.docker_manager import DockerManager
from ..utils.api_client import APIClient
from ..utils.analytics import AnalyticsClient

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

        # Load saved backend config
        from desktop_app.utils.app_config import (
            get_backend_url, get_api_key, is_remote_mode,
        )
        self._remote_mode = is_remote_mode()
        self.api_client = APIClient(
            base_url=get_backend_url(),
            api_key=get_api_key() if self._remote_mode else None,
        )
        self.source_manager = SourceOpenManager(self.api_client, parent=self, project_root=self.project_path)

        # Usage analytics (#14) — opt-in, off by default
        from version import __version__
        self._analytics = AnalyticsClient(app_version=__version__)
        self._analytics.set_api_client(self.api_client)

        # Track if initial data load has occurred
        self.initial_load_done = False

        # Setup UI
        self.setup_ui()

        # Show analytics consent dialog on first run
        self._maybe_show_analytics_consent()

        # Check Docker and API status
        QTimer.singleShot(500, self.check_initial_status)
    
    def setup_ui(self):
        """Setup the user interface."""
        self.setWindowTitle("PGVectorRAGIndexer - Document Management")
        # Height: Need enough room for Settings tab content
        self.setMinimumSize(1100, 1000)
        
        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Main layout
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)
        
        # Docker status bar at top
        self.create_docker_status_bar(layout)
        
        # License expiry banner (hidden by default)
        self._create_license_banner(layout)

        # Remote mode banner (hidden by default)
        self._create_remote_banner(layout)
        
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
        self.health_tab = HealthTab(self.api_client, self)
        self.watched_folders_tab = WatchedFoldersTab(self.api_client, self)

        # Initialize in-app folder scheduler (#6)
        from desktop_app.utils.folder_scheduler import FolderScheduler
        self._folder_scheduler = FolderScheduler(self.api_client, parent=self)
        self.watched_folders_tab.set_scheduler(self._folder_scheduler)

        # Add tabs with icons (ordered by typical workflow)
        self.tabs.addTab(self.upload_tab, qta.icon('fa5s.cloud-upload-alt', color='#9ca3af'), "Upload")
        self.tabs.addTab(self.search_tab, qta.icon('fa5s.search', color='#9ca3af'), "Search")
        self.tabs.addTab(self.documents_tab, qta.icon('fa5s.book', color='#9ca3af'), "Documents")
        self.tabs.addTab(self.recent_tab, qta.icon('fa5s.clock', color='#9ca3af'), "Recent")
        self.tabs.addTab(self.health_tab, qta.icon('fa5s.heartbeat', color='#9ca3af'), "Health")
        self.tabs.addTab(self.watched_folders_tab, qta.icon('fa5s.folder-open', color='#9ca3af'), "Folders")
        self.tabs.addTab(self.manage_tab, qta.icon('fa5s.trash-alt', color='#9ca3af'), "Manage")
        self.tabs.addTab(self.settings_tab, qta.icon('fa5s.cog', color='#9ca3af'), "Settings")
        
        # Status bar at bottom
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")

        # Wire analytics signals (#14)
        self._wire_analytics_signals()

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
    
    def _create_license_banner(self, parent_layout):
        """Create a license expiry warning banner (hidden by default)."""
        self._license_banner = QWidget()
        self._license_banner.setObjectName("licenseBanner")
        self._license_banner.setVisible(False)

        banner_layout = QHBoxLayout(self._license_banner)
        banner_layout.setContentsMargins(15, 8, 15, 8)

        self._license_banner_icon = QLabel()
        banner_layout.addWidget(self._license_banner_icon)

        self._license_banner_text = QLabel()
        self._license_banner_text.setWordWrap(True)
        banner_layout.addWidget(self._license_banner_text, 1)

        renew_btn = QPushButton("Renew")
        renew_btn.setFlat(True)
        renew_btn.setCursor(Qt.PointingHandCursor)
        renew_btn.setStyleSheet("color: white; text-decoration: underline; border: none;")
        renew_btn.clicked.connect(self._open_pricing)
        banner_layout.addWidget(renew_btn)

        parent_layout.addWidget(self._license_banner)

    def _update_license_banner(self):
        """Show or hide the license expiry banner based on current license."""
        try:
            from desktop_app.utils.edition import get_edition_display
            info = get_edition_display()
        except Exception:
            self._license_banner.setVisible(False)
            return

        if not info["is_team"]:
            # Community edition or no license — check for warning text
            if info["warning_text"] and "expired" in info["warning_text"].lower():
                self._license_banner.setStyleSheet(
                    "#licenseBanner { background-color: #991b1b; border-radius: 6px; }"
                )
                self._license_banner_icon.setPixmap(
                    qta.icon('fa5s.exclamation-triangle', color='white').pixmap(16, 16)
                )
                self._license_banner_text.setText(info["warning_text"])
                self._license_banner_text.setStyleSheet("color: white;")
                self._license_banner.setVisible(True)
            else:
                self._license_banner.setVisible(False)
            return

        # Team edition — check expiry
        if info["expiry_warning"]:
            days = info["days_left"]
            self._license_banner.setStyleSheet(
                "#licenseBanner { background-color: #92400e; border-radius: 6px; }"
            )
            self._license_banner_icon.setPixmap(
                qta.icon('fa5s.clock', color='white').pixmap(16, 16)
            )
            self._license_banner_text.setText(
                f"Team license expires in {days} days. Renew to avoid interruption."
            )
            self._license_banner_text.setStyleSheet("color: white;")
            self._license_banner.setVisible(True)
        else:
            self._license_banner.setVisible(False)

    def _open_pricing(self):
        """Open the pricing page."""
        from desktop_app.utils.edition import open_pricing_page
        open_pricing_page()

    def _create_remote_banner(self, parent_layout):
        """Create a remote-mode info banner (hidden by default)."""
        self._remote_banner = QWidget()
        self._remote_banner.setObjectName("remoteBanner")
        self._remote_banner.setVisible(False)
        self._remote_banner.setStyleSheet(
            "#remoteBanner { background-color: #1e3a5f; border-radius: 6px; "
            "border: 1px solid #2563eb; }"
        )

        banner_layout = QHBoxLayout(self._remote_banner)
        banner_layout.setContentsMargins(15, 8, 15, 8)

        icon_label = QLabel()
        icon_label.setPixmap(
            qta.icon('fa5s.cloud', color='#60a5fa').pixmap(16, 16)
        )
        banner_layout.addWidget(icon_label)

        self._remote_banner_text = QLabel()
        self._remote_banner_text.setWordWrap(True)
        self._remote_banner_text.setStyleSheet("color: #bfdbfe;")
        banner_layout.addWidget(self._remote_banner_text, 1)

        self._remote_auth_badge = QLabel()
        self._remote_auth_badge.setStyleSheet(
            "color: white; font-weight: 600; padding: 2px 8px; "
            "border-radius: 4px; font-size: 11px;"
        )
        banner_layout.addWidget(self._remote_auth_badge)

        parent_layout.addWidget(self._remote_banner)

    def _update_remote_banner(self):
        """Show or hide the remote-mode banner based on current config."""
        if not self._remote_mode:
            self._remote_banner.setVisible(False)
            return

        from desktop_app.utils.app_config import get_backend_url, get_api_key
        url = get_backend_url()
        has_key = bool(get_api_key())

        self._remote_banner_text.setText(
            f"Remote mode — connected to <b>{url}</b>"
        )

        if has_key:
            self._remote_auth_badge.setText("🔒 Authenticated")
            self._remote_auth_badge.setStyleSheet(
                "color: white; font-weight: 600; padding: 2px 8px; "
                "border-radius: 4px; font-size: 11px; background-color: #166534;"
            )
        else:
            self._remote_auth_badge.setText("⚠ No API Key")
            self._remote_auth_badge.setStyleSheet(
                "color: white; font-weight: 600; padding: 2px 8px; "
                "border-radius: 4px; font-size: 11px; background-color: #92400e;"
            )

        self._remote_banner.setVisible(True)

    def _register_client(self):
        """Register this desktop client with the server (#8)."""
        try:
            from desktop_app.utils.app_config import get, set as config_set
            from client_identity import generate_client_id, get_os_type, get_default_display_name

            client_id = get("client_id")
            if not client_id:
                client_id = generate_client_id()
                config_set("client_id", client_id)
                logger.info("Generated new client_id: %s", client_id)

            display_name = get("client_display_name") or get_default_display_name()
            os_type = get_os_type()

            self.api_client.register_client(
                client_id=client_id,
                display_name=display_name,
                os_type=os_type,
                app_version=getattr(self, '_app_version', None),
            )
            logger.info("Client registered: %s (%s)", display_name, client_id[:8])
        except Exception as e:
            logger.warning("Client registration failed (non-fatal): %s", e)

    def check_initial_status(self):
        """Check Docker and API status on startup."""
        if self._remote_mode:
            # In remote mode, skip Docker entirely — just check API
            self._update_remote_banner()
            self.check_api_status()
            return

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
            
            # Trigger initial load if not done
            if not self.initial_load_done:
                self.on_api_ready()
        else:
            self.api_status_label.setText("API: Not Available")
            self.api_status_icon.setPixmap(qta.icon('fa5s.times-circle', color='#ef4444').pixmap(16, 16))
            if db_running and app_running:
                self.status_bar.showMessage("Containers running but API not ready. Please wait...")
                # Poll again until ready
                QTimer.singleShot(2000, self.check_docker_status)
            else:
                self.status_bar.showMessage("API not available. Please start containers.")
    
    def check_api_status(self):
        """Check API availability (used in remote mode where Docker is irrelevant)."""
        if self.api_client.is_api_available():
            self.status_bar.showMessage("Ready — connected to remote server")
            if not self.initial_load_done:
                self.on_api_ready()
        else:
            self.status_bar.showMessage("Remote server not reachable. Check Settings.")
            # Retry after a delay
            QTimer.singleShot(5000, self.check_api_status)

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

    def on_api_ready(self):
        """Called when API becomes available for the first time."""
        logger.info("API is ready, performing initial data load...")
        self.initial_load_done = True
        
        # Check version compatibility
        compatible, version_msg = self.api_client.check_version_compatibility()
        if not compatible:
            QMessageBox.warning(
                self,
                "Version Mismatch",
                version_msg,
            )
        
        # Update license expiry banner
        self._update_license_banner()

        # Update remote mode banner
        self._update_remote_banner()

        # Register client identity (#8)
        self._register_client()

        # Analytics: track app started + daily active
        self._analytics.track_app_started()
        self._analytics.track_daily_active()

        # Load data for tabs
        try:
            # Documents Tab
            if hasattr(self, 'documents_tab'):
                self.documents_tab.load_documents()
            
            # Upload Tab (Document Types)
            if hasattr(self, 'upload_tab'):
                self.upload_tab.load_document_types()
                
            # Search Tab (Document Types)
            if hasattr(self, 'search_tab'):
                self.search_tab.load_document_types()

            # Health Dashboard
            if hasattr(self, 'health_tab'):
                self.health_tab.refresh()

            # Watched Folders (#6)
            if hasattr(self, 'watched_folders_tab'):
                self.watched_folders_tab.load_folders()
            if hasattr(self, '_folder_scheduler'):
                try:
                    from desktop_app.utils.app_config import get
                    cid = get("client_id")
                    if cid:
                        self._folder_scheduler.set_client_id(cid)
                except Exception:
                    pass
                
            logger.info("Initial data load complete")
        except Exception as e:
            logger.error(f"Error during initial data load: {e}")

    # ------------------------------------------------------------------
    # Analytics (#14)
    # ------------------------------------------------------------------

    def _maybe_show_analytics_consent(self):
        """Show the opt-in analytics dialog on first launch."""
        from desktop_app.utils import app_config
        if app_config.get("analytics_consent_shown"):
            return  # already asked

        from .analytics_consent_dialog import AnalyticsConsentDialog
        dialog = AnalyticsConsentDialog(self)
        dialog.exec()

        self._analytics.set_enabled(dialog.user_accepted)
        app_config.set("analytics_consent_shown", True)

        # Sync checkbox in Settings tab if it exists
        if hasattr(self, "settings_tab") and hasattr(self.settings_tab, "_analytics_checkbox"):
            self.settings_tab._analytics_checkbox.setChecked(dialog.user_accepted)

    def _wire_analytics_signals(self):
        """Connect existing signals to analytics tracking."""
        # Tab changes
        self.tabs.currentChanged.connect(
            lambda idx: self._analytics.track_tab_opened(self.tabs.tabText(idx))
        )
