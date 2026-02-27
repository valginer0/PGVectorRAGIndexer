"""
Settings tab for Docker management and configuration.
"""

import logging
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QTextEdit, QMessageBox, QGridLayout, QFileDialog,
    QLineEdit, QRadioButton, QButtonGroup, QScrollArea, QCheckBox,
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
        # Outer layout holds a scroll area so content doesn't get compressed
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 12, 16, 12)

        self._scroll.setWidget(container)
        outer.addWidget(self._scroll)

        # Title
        header_layout = QHBoxLayout()
        title = QLabel("Settings & Management")
        title.setProperty("class", "header")
        header_layout.addWidget(title)
        header_layout.addStretch()

        layout.addLayout(header_layout)
        
        # Compact group-box margins for this tab (override QSS margin-top: 1.5em)
        _compact_gb = "QGroupBox { margin-top: 0.8em; padding-top: 8px; }"

        # Statistics
        if self.api_client:
            stats_group = QGroupBox("Database Statistics")
            stats_group.setStyleSheet(_compact_gb)
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

        # Backend connection settings (#1)
        self._build_backend_panel(layout)

        # Usage analytics (#14)
        self._build_analytics_panel(layout)

        # Docker controls
        self._docker_group = QGroupBox("Docker Container Management")
        self._docker_group.setStyleSheet(_compact_gb)
        docker_group = self._docker_group
        docker_layout = QVBoxLayout(docker_group)
        
        restart_btn = QPushButton("Restart Containers")
        restart_btn.setIcon(qta.icon('fa5s.redo', color='white'))
        restart_btn.clicked.connect(self.restart_containers)
        restart_btn.setMinimumHeight(40)
        restart_btn.setStyleSheet("background-color: #f59e0b; border: 1px solid #f59e0b;") # Warning color
        docker_layout.addWidget(restart_btn)

        update_backend_btn = QPushButton("Update Backend (Pull Latest)")
        update_backend_btn.setIcon(qta.icon('fa5s.download', color='white'))
        update_backend_btn.clicked.connect(self.update_backend)
        update_backend_btn.setMinimumHeight(40)
        update_backend_btn.setStyleSheet("background-color: #3b82f6; border: 1px solid #3b82f6;") # Info/Blue color
        docker_layout.addWidget(update_backend_btn)
        
        logs_btn = QPushButton("View Application Logs")
        logs_btn.setIcon(qta.icon('fa5s.file-alt', color='white'))
        logs_btn.clicked.connect(self.view_logs)
        logs_btn.setMinimumHeight(40)
        docker_layout.addWidget(logs_btn)
        
        layout.addWidget(docker_group)
        
        # Logs display
        self._logs_group = QGroupBox("Container Logs")
        self._logs_group.setStyleSheet(_compact_gb)
        logs_group = self._logs_group
        logs_layout = QVBoxLayout(logs_group)
        
        self.logs_text = QTextEdit()
        self.logs_text.setReadOnly(True)
        self.logs_text.setMaximumHeight(120)
        self.logs_text.setPlaceholderText("Click 'View Application Logs' to load logs...")
        logs_layout.addWidget(self.logs_text)
        
        logs_group.setVisible(False)  # Hidden until user clicks "View Application Logs"
        layout.addWidget(logs_group)

    # ------------------------------------------------------------------
    # Backend connection panel (#1)
    # ------------------------------------------------------------------

    def _build_backend_panel(self, parent_layout):
        """Build the Backend Connection settings group box."""
        from desktop_app.utils.app_config import (
            get_backend_mode, get_backend_url, get_api_key,
            BACKEND_MODE_LOCAL, BACKEND_MODE_REMOTE, DEFAULT_LOCAL_URL,
        )

        _compact_gb = "QGroupBox { margin-top: 0.8em; padding-top: 8px; }"
        backend_group = QGroupBox("Backend Connection")
        backend_group.setStyleSheet(_compact_gb)
        grid = QGridLayout(backend_group)
        grid.setSpacing(8)

        # Row 0 — Mode radio buttons
        grid.addWidget(QLabel("Mode:"), 0, 0)
        mode_layout = QHBoxLayout()
        self._radio_local = QRadioButton("Local Docker")
        self._radio_remote = QRadioButton("Remote Server")
        self._mode_group = QButtonGroup(self)
        self._mode_group.addButton(self._radio_local)
        self._mode_group.addButton(self._radio_remote)
        mode_layout.addWidget(self._radio_local)
        mode_layout.addWidget(self._radio_remote)
        mode_layout.addStretch()
        grid.addLayout(mode_layout, 0, 1)

        # Row 1 — Backend URL
        grid.addWidget(QLabel("Backend URL:"), 1, 0)
        self._url_input = QLineEdit()
        self._url_input.setPlaceholderText("e.g. https://my-server.example.com:8000")
        grid.addWidget(self._url_input, 1, 1)

        # Row 2 — API Key
        grid.addWidget(QLabel("API Key:"), 2, 0)
        self._api_key_input = QLineEdit()
        self._api_key_input.setPlaceholderText("Required for remote connections")
        self._api_key_input.setEchoMode(QLineEdit.Password)
        grid.addWidget(self._api_key_input, 2, 1)

        # Row 3 — Buttons
        btn_layout = QHBoxLayout()
        self._test_conn_btn = QPushButton("Test Connection")
        self._test_conn_btn.setIcon(qta.icon('fa5s.plug', color='white'))
        self._test_conn_btn.clicked.connect(self._test_connection)
        btn_layout.addWidget(self._test_conn_btn)

        self._save_backend_btn = QPushButton("Save")
        self._save_backend_btn.setIcon(qta.icon('fa5s.save', color='white'))
        self._save_backend_btn.setProperty("class", "primary")
        self._save_backend_btn.clicked.connect(self._save_backend_settings)
        btn_layout.addWidget(self._save_backend_btn)

        btn_layout.addStretch()
        grid.addLayout(btn_layout, 3, 0, 1, 2)

        # Status label
        self._backend_status = QLabel("")
        self._backend_status.setStyleSheet("color: #9ca3af; font-style: italic;")
        grid.addWidget(self._backend_status, 4, 0, 1, 2)

        parent_layout.addWidget(backend_group)

        # Load saved values
        current_mode = get_backend_mode()
        if current_mode == BACKEND_MODE_REMOTE:
            self._radio_remote.setChecked(True)
        else:
            self._radio_local.setChecked(True)

        saved_url = get_backend_url()
        if saved_url and saved_url != DEFAULT_LOCAL_URL:
            self._url_input.setText(saved_url)

        saved_key = get_api_key()
        if saved_key:
            self._api_key_input.setText(saved_key)

        # Wire mode toggle
        self._radio_local.toggled.connect(self._on_backend_mode_changed)
        self._radio_remote.toggled.connect(self._on_backend_mode_changed)

        # Set initial visibility
        self._on_backend_mode_changed()

    # ------------------------------------------------------------------
    # Analytics panel (#14)
    # ------------------------------------------------------------------

    def _build_analytics_panel(self, parent_layout):
        """Build the Usage Analytics settings group box."""
        from desktop_app.utils.analytics import AnalyticsClient

        _compact_gb = "QGroupBox { margin-top: 0.8em; padding-top: 8px; }"
        group = QGroupBox("Usage Analytics")
        group.setStyleSheet(_compact_gb)
        vbox = QVBoxLayout(group)
        vbox.setSpacing(8)

        # Toggle
        self._analytics_checkbox = QCheckBox(
            "Help improve PGVectorRAGIndexer by sharing anonymous usage data"
        )
        from desktop_app.utils import app_config
        self._analytics_checkbox.setChecked(app_config.get("analytics_enabled", False))
        self._analytics_checkbox.toggled.connect(self._on_analytics_toggled)
        vbox.addWidget(self._analytics_checkbox)

        desc = QLabel(
            "We collect only event types, counts, and OS version. "
            "No document content, file names, or search queries."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-size: 12px;")
        vbox.addWidget(desc)

        # Event log viewer
        btn_row = QHBoxLayout()
        show_log_btn = QPushButton("View Event Log")
        show_log_btn.setIcon(qta.icon("fa5s.list", color="white"))
        show_log_btn.clicked.connect(self._show_analytics_log)
        btn_row.addWidget(show_log_btn)

        clear_log_btn = QPushButton("Clear Log")
        clear_log_btn.setIcon(qta.icon("fa5s.eraser", color="white"))
        clear_log_btn.clicked.connect(self._clear_analytics_log)
        btn_row.addWidget(clear_log_btn)

        btn_row.addStretch()
        vbox.addLayout(btn_row)

        self._analytics_log_text = QTextEdit()
        self._analytics_log_text.setReadOnly(True)
        self._analytics_log_text.setMaximumHeight(160)
        self._analytics_log_text.setPlaceholderText(
            "Click 'View Event Log' to see recorded events..."
        )
        self._analytics_log_text.setVisible(False)
        vbox.addWidget(self._analytics_log_text)

        parent_layout.addWidget(group)

    def _on_analytics_toggled(self, checked: bool):
        """Handle analytics toggle change."""
        main_win = self.parent()
        if main_win and hasattr(main_win, "_analytics"):
            main_win._analytics.set_enabled(checked)
        else:
            from desktop_app.utils import app_config
            app_config.set("analytics_enabled", checked)

    def _show_analytics_log(self):
        """Show the local analytics event log."""
        self._analytics_log_text.setVisible(True)
        main_win = self.parent()
        analytics = getattr(main_win, "_analytics", None) if main_win else None

        if analytics:
            events = analytics.get_event_log(limit=100)
        else:
            from desktop_app.utils.analytics import AnalyticsClient
            tmp = AnalyticsClient()
            events = tmp.get_event_log(limit=100)

        if not events:
            self._analytics_log_text.setPlainText("No events recorded yet.")
            return

        import json
        lines = []
        for ev in reversed(events):
            ts = ev.get("ts", "")[:19]
            name = ev.get("event", "?")
            props = ev.get("properties", {})
            prop_str = f"  {json.dumps(props)}" if props else ""
            lines.append(f"[{ts}] {name}{prop_str}")
        self._analytics_log_text.setPlainText("\n".join(lines))

        from PySide6.QtCore import QTimer
        QTimer.singleShot(50, lambda: self._scroll.ensureWidgetVisible(self._analytics_log_text))

    def _clear_analytics_log(self):
        """Clear the local analytics event log."""
        main_win = self.parent()
        analytics = getattr(main_win, "_analytics", None) if main_win else None
        if analytics:
            analytics.clear_event_log()
        else:
            from desktop_app.utils.analytics import _log_path
            path = _log_path()
            if path.exists():
                path.unlink()
        self._analytics_log_text.setPlainText("Log cleared.")

    def _on_backend_mode_changed(self):
        """Show/hide controls based on selected backend mode."""
        is_remote = self._radio_remote.isChecked()

        # URL and API key only relevant in remote mode
        self._url_input.setEnabled(is_remote)
        self._api_key_input.setEnabled(is_remote)
        self._test_conn_btn.setEnabled(is_remote)

        # Hide Docker controls in remote mode
        if hasattr(self, '_docker_group'):
            self._docker_group.setVisible(not is_remote)
        if hasattr(self, '_logs_group'):
            self._logs_group.setVisible(not is_remote)

        # Hide Docker status bar in main window
        main_win = self.parent()
        if main_win and hasattr(main_win, 'docker_status_label'):
            docker_bar = main_win.docker_status_label.parent()
            if docker_bar:
                docker_bar.setVisible(not is_remote)

    def _save_backend_settings(self):
        """Persist backend settings and reconfigure the API client."""
        from desktop_app.utils.app_config import (
            set_backend_mode, set_backend_url, set_api_key,
            BACKEND_MODE_LOCAL, BACKEND_MODE_REMOTE, DEFAULT_LOCAL_URL,
        )

        mode = BACKEND_MODE_REMOTE if self._radio_remote.isChecked() else BACKEND_MODE_LOCAL
        set_backend_mode(mode)

        if mode == BACKEND_MODE_REMOTE:
            url = self._url_input.text().strip()
            if not url:
                QMessageBox.warning(self, "Missing URL", "Please enter a backend URL.")
                return
            if not url.startswith(("http://", "https://")):
                QMessageBox.warning(self, "Invalid URL",
                                    "Backend URL must start with http:// or https://")
                return
            set_backend_url(url)

            api_key = self._api_key_input.text().strip()
            if not api_key:
                QMessageBox.warning(self, "Missing API Key",
                                    "An API key is required for remote connections.")
                return
            set_api_key(api_key)
        else:
            url = DEFAULT_LOCAL_URL
            set_api_key(None)

        # Reconfigure the live API client
        if self.api_client:
            self.api_client.base_url = url.rstrip('/')
            self.api_client.api_base = f"{self.api_client.base_url}/api/v1"
            if mode == BACKEND_MODE_REMOTE:
                self.api_client._api_key = self._api_key_input.text().strip()
            else:
                self.api_client._api_key = None

        self._backend_status.setText("Settings saved.")
        self._backend_status.setStyleSheet(f"color: {Theme.SUCCESS}; font-style: italic;")

        QMessageBox.information(
            self, "Backend Settings Saved",
            f"Mode: {mode.title()}\nURL: {url}\n\n"
            "The app will use these settings immediately.",
        )

    def _test_connection(self):
        """Test connectivity to the remote backend."""
        url = self._url_input.text().strip()
        if not url:
            self._backend_status.setText("Enter a URL first.")
            self._backend_status.setStyleSheet(f"color: {Theme.WARNING};")
            return

        if not url.startswith(("http://", "https://")):
            self._backend_status.setText("URL must start with http:// or https://")
            self._backend_status.setStyleSheet(f"color: {Theme.WARNING};")
            return

        self._backend_status.setText("Testing...")
        self._backend_status.setStyleSheet("color: #9ca3af;")
        self._test_conn_btn.setEnabled(False)

        import requests
        try:
            headers = {}
            api_key = self._api_key_input.text().strip()
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

            resp = requests.get(
                f"{url.rstrip('/')}/api/version",
                headers=headers,
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                server_ver = data.get("server_version", "?")
                self._backend_status.setText(
                    f"Connected — server v{server_ver}"
                )
                self._backend_status.setStyleSheet(f"color: {Theme.SUCCESS};")
            elif resp.status_code == 401:
                self._backend_status.setText("Authentication failed — check API key.")
                self._backend_status.setStyleSheet(f"color: {Theme.ERROR};")
            else:
                self._backend_status.setText(f"Server returned HTTP {resp.status_code}")
                self._backend_status.setStyleSheet(f"color: {Theme.WARNING};")
        except requests.ConnectionError:
            self._backend_status.setText("Connection refused — is the server running?")
            self._backend_status.setStyleSheet(f"color: {Theme.ERROR};")
        except requests.Timeout:
            self._backend_status.setText("Connection timed out.")
            self._backend_status.setStyleSheet(f"color: {Theme.ERROR};")
        except Exception as e:
            self._backend_status.setText(f"Error: {e}")
            self._backend_status.setStyleSheet(f"color: {Theme.ERROR};")
        finally:
            self._test_conn_btn.setEnabled(True)

    # ------------------------------------------------------------------
    # License panel
    # ------------------------------------------------------------------

    def _build_license_panel(self, parent_layout):
        """Build the License information group box."""
        _compact_gb = "QGroupBox { margin-top: 0.8em; padding-top: 8px; }"
        license_group = QGroupBox("License")
        license_group.setStyleSheet(_compact_gb)
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
        """Let the user paste a license JWT or browse for a .key file and install it."""
        from PySide6.QtWidgets import (
            QDialog, QVBoxLayout, QHBoxLayout, QLabel,
            QPlainTextEdit, QPushButton, QDialogButtonBox
        )

        dlg = QDialog(self)
        dlg.setWindowTitle("Enter License Key")
        dlg.setMinimumWidth(520)
        layout = QVBoxLayout(dlg)

        layout.addWidget(QLabel("Paste your license key (JWT) from the email:"))
        text_edit = QPlainTextEdit()
        text_edit.setPlaceholderText("eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...")
        text_edit.setFixedHeight(100)
        layout.addWidget(text_edit)

        # File-picker fallback
        file_row = QHBoxLayout()
        file_label = QLabel("Or browse for a .key file:")
        browse_btn = QPushButton("Browse…")
        file_row.addWidget(file_label)
        file_row.addWidget(browse_btn)
        file_row.addStretch()
        layout.addLayout(file_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        layout.addWidget(buttons)

        # When browsing, load the file content into the text box
        def _browse():
            from .shared import pick_open_file
            fp = pick_open_file(self, "Select License Key File", "License Key Files (*.key);;All Files (*)")
            if fp:
                try:
                    text_edit.setPlainText(open(fp, encoding="utf-8").read().strip())
                except Exception as ex:
                    text_edit.setPlainText("")
                    from PySide6.QtWidgets import QMessageBox
                    QMessageBox.warning(self, "Read Error", str(ex))

        browse_btn.clicked.connect(_browse)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)

        if dlg.exec() != QDialog.Accepted:
            return

        key_string = text_edit.toPlainText().strip()
        if not key_string:
            return

        try:
            from license import get_license_dir
            dest_dir = get_license_dir()
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest_file = dest_dir / "license.key"

            # Write the pasted/loaded key to the license file
            dest_file.write_text(key_string, encoding="utf-8")

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

    def update_backend(self):
        """Force pull latest images and restart containers."""
        reply = QMessageBox.question(
            self,
            "Update Backend?",
            "This will check for backend updates (docker pull) and restart containers.\n\n"
            "If an update is available, it will be downloaded. Existing data will be preserved.\n\n"
            "Proceed?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # Show a processing dialog or change button state? 
            # For now, let's just run it and show the result.
            self.setCursor(Qt.WaitCursor)
            try:
                success, message = self.docker_manager.start_containers(force_pull=True)
                if success:
                    QMessageBox.information(self, "Success", "Backend updated and restarted successfully.")
                    # Refresh parent status
                    if self.parent() and hasattr(self.parent(), 'check_docker_status'):
                        self.parent().check_docker_status()
                else:
                    QMessageBox.critical(self, "Update Failed", message)
            finally:
                self.restoreOverrideCursor()
    
    def view_logs(self):
        """View container logs."""
        self._logs_group.setVisible(True)
        logs = self.docker_manager.get_logs()
        self.logs_text.setPlainText(logs)
        # Scroll down so the logs panel is visible
        from PySide6.QtCore import QTimer
        QTimer.singleShot(50, lambda: self._scroll.ensureWidgetVisible(self._logs_group))
