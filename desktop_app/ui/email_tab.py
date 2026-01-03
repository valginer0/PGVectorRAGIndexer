"""
Email connector tab for indexing Outlook/Exchange emails.

This tab is only visible when EMAIL_ENABLED=true in the config.
"""

import logging
from typing import Optional
from datetime import datetime

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QProgressBar, QTableWidget, QTableWidgetItem,
    QHeaderView, QMessageBox, QComboBox, QSpinBox, QCheckBox
)
from PySide6.QtCore import Qt, QThread, Signal

import qtawesome as qta

logger = logging.getLogger(__name__)


class AuthWorker(QThread):
    """Worker thread for OAuth authentication."""
    
    finished = Signal(bool, str)  # success, message
    
    def __init__(self, ingestor):
        super().__init__()
        self.ingestor = ingestor
    
    def run(self):
        """Run authentication."""
        try:
            success = self.ingestor.authenticate()
            if success:
                self.finished.emit(True, "Authentication successful!")
            else:
                self.finished.emit(False, "Authentication failed.")
        except Exception as e:
            self.finished.emit(False, str(e))


class SyncWorker(QThread):
    """Worker thread for syncing emails."""
    
    progress = Signal(int, str)  # count, status message
    finished = Signal(bool, dict)  # success, stats
    
    def __init__(self, indexer, folder: str, limit: int):
        super().__init__()
        self.indexer = indexer
        self.folder = folder
        self.limit = limit
    
    def run(self):
        """Run sync."""
        try:
            stats = self.indexer.index_folder(
                folder=self.folder,
                limit=self.limit
            )
            self.finished.emit(True, stats)
        except Exception as e:
            self.finished.emit(False, {'error': str(e)})


class EmailTab(QWidget):
    """
    Tab for connecting and syncing Outlook/Exchange emails.
    
    Only visible when EMAIL_ENABLED=true.
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self._ingestor = None
        self._indexer = None
        self._authenticated = False
        
        self.setup_ui()
    
    def setup_ui(self):
        """Setup the user interface."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)
        
        # Title
        title = QLabel("Email Connector")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #f9fafb;")
        layout.addWidget(title)
        
        subtitle = QLabel("Connect your Outlook or Exchange account to index emails for semantic search.")
        subtitle.setStyleSheet("color: #9ca3af; margin-bottom: 10px;")
        layout.addWidget(subtitle)
        
        # Connection status group
        self.create_connection_group(layout)
        
        # Sync options group
        self.create_sync_group(layout)
        
        # Sync status/results
        self.create_status_group(layout)
        
        layout.addStretch()
    
    def create_connection_group(self, parent_layout):
        """Create the connection status group."""
        group = QGroupBox("Connection Status")
        group_layout = QVBoxLayout(group)
        
        # Status row
        status_row = QHBoxLayout()
        
        self.status_icon = QLabel()
        self.status_icon.setPixmap(qta.icon('fa5s.circle', color='#6b7280').pixmap(16, 16))
        status_row.addWidget(self.status_icon)
        
        self.status_label = QLabel("Not connected")
        self.status_label.setStyleSheet("color: #9ca3af;")
        status_row.addWidget(self.status_label)
        
        status_row.addStretch()
        
        # Connect button
        self.connect_btn = QPushButton("Connect Outlook")
        self.connect_btn.setIcon(qta.icon('fa5s.sign-in-alt', color='white'))
        self.connect_btn.setProperty("class", "primary")
        self.connect_btn.clicked.connect(self.start_authentication)
        status_row.addWidget(self.connect_btn)
        
        # Disconnect button (hidden initially)
        self.disconnect_btn = QPushButton("Disconnect")
        self.disconnect_btn.setIcon(qta.icon('fa5s.sign-out-alt', color='white'))
        self.disconnect_btn.clicked.connect(self.disconnect)
        self.disconnect_btn.hide()
        status_row.addWidget(self.disconnect_btn)
        
        group_layout.addLayout(status_row)
        parent_layout.addWidget(group)
    
    def create_sync_group(self, parent_layout):
        """Create the sync options group."""
        group = QGroupBox("Sync Options")
        group_layout = QVBoxLayout(group)
        
        # Folder selection
        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("Folder:"))
        self.folder_combo = QComboBox()
        self.folder_combo.addItems(["Inbox", "Sent Items", "Drafts"])
        self.folder_combo.setMinimumWidth(200)
        folder_row.addWidget(self.folder_combo)
        folder_row.addStretch()
        group_layout.addLayout(folder_row)
        
        # Limit
        limit_row = QHBoxLayout()
        limit_row.addWidget(QLabel("Max emails:"))
        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(10, 1000)
        self.limit_spin.setValue(100)
        self.limit_spin.setSingleStep(50)
        limit_row.addWidget(self.limit_spin)
        limit_row.addStretch()
        group_layout.addLayout(limit_row)
        
        # Sync button
        btn_row = QHBoxLayout()
        self.sync_btn = QPushButton("Start Sync")
        self.sync_btn.setIcon(qta.icon('fa5s.sync', color='white'))
        self.sync_btn.setProperty("class", "primary")
        self.sync_btn.clicked.connect(self.start_sync)
        self.sync_btn.setEnabled(False)  # Disabled until connected
        btn_row.addWidget(self.sync_btn)
        btn_row.addStretch()
        group_layout.addLayout(btn_row)
        
        parent_layout.addWidget(group)
    
    def create_status_group(self, parent_layout):
        """Create the sync status group."""
        group = QGroupBox("Sync Status")
        group_layout = QVBoxLayout(group)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        group_layout.addWidget(self.progress_bar)
        
        # Status message
        self.sync_status_label = QLabel("No sync in progress.")
        self.sync_status_label.setStyleSheet("color: #9ca3af;")
        group_layout.addWidget(self.sync_status_label)
        
        # Results summary
        self.results_label = QLabel("")
        self.results_label.setStyleSheet("color: #10b981;")
        group_layout.addWidget(self.results_label)
        
        parent_layout.addWidget(group)
    
    def _get_ingestor(self):
        """Lazy-load the ingestor."""
        if self._ingestor is None:
            try:
                from config import get_config
                from connectors.email.ingestor import CloudIngestor
                
                config = get_config()
                self._ingestor = CloudIngestor(
                    client_id=config.email.client_id,
                    tenant_id=config.email.tenant_id
                )
            except Exception as e:
                logger.error(f"Failed to create ingestor: {e}")
                raise
        return self._ingestor
    
    def start_authentication(self):
        """Start OAuth authentication flow."""
        try:
            ingestor = self._get_ingestor()
        except Exception as e:
            QMessageBox.critical(
                self,
                "Configuration Error",
                f"Email connector not properly configured:\n{e}\n\n"
                "Please check EMAIL_CLIENT_ID in your .env file."
            )
            return
        
        self.connect_btn.setEnabled(False)
        self.connect_btn.setText("Authenticating...")
        self.status_label.setText("Opening browser for authentication...")
        
        # Note: Device code flow prints to console
        # User must check the console for the code
        QMessageBox.information(
            self,
            "Authentication",
            "Check your terminal/console for the authentication code.\n\n"
            "You will see a URL and a code to enter.\n"
            "Open the URL in your browser and enter the code."
        )
        
        self.auth_worker = AuthWorker(ingestor)
        self.auth_worker.finished.connect(self.auth_finished)
        self.auth_worker.start()
    
    def auth_finished(self, success: bool, message: str):
        """Handle authentication completion."""
        self.connect_btn.setEnabled(True)
        
        if success:
            self._authenticated = True
            self.status_icon.setPixmap(qta.icon('fa5s.check-circle', color='#10b981').pixmap(16, 16))
            self.status_label.setText("Connected")
            self.status_label.setStyleSheet("color: #10b981;")
            self.connect_btn.hide()
            self.disconnect_btn.show()
            self.sync_btn.setEnabled(True)
            
            # Load folders
            self._load_folders()
            
            QMessageBox.information(self, "Success", message)
        else:
            self.connect_btn.setText("Connect Outlook")
            self.status_label.setText(f"Authentication failed: {message}")
            self.status_label.setStyleSheet("color: #ef4444;")
            QMessageBox.warning(self, "Authentication Failed", message)
    
    def _load_folders(self):
        """Load available mail folders."""
        try:
            folders = self._ingestor.get_folders()
            self.folder_combo.clear()
            for folder in folders:
                self.folder_combo.addItem(folder.get('name', 'Unknown'))
        except Exception as e:
            logger.error(f"Failed to load folders: {e}")
    
    def disconnect(self):
        """Disconnect from email account."""
        if self._ingestor:
            self._ingestor.logout()
        
        self._authenticated = False
        self._ingestor = None
        
        self.status_icon.setPixmap(qta.icon('fa5s.circle', color='#6b7280').pixmap(16, 16))
        self.status_label.setText("Not connected")
        self.status_label.setStyleSheet("color: #9ca3af;")
        self.connect_btn.setText("Connect Outlook")
        self.connect_btn.show()
        self.disconnect_btn.hide()
        self.sync_btn.setEnabled(False)
        
        self.folder_combo.clear()
        self.folder_combo.addItems(["Inbox", "Sent Items", "Drafts"])
    
    def start_sync(self):
        """Start email sync."""
        if not self._authenticated:
            QMessageBox.warning(self, "Not Connected", "Please connect to Outlook first.")
            return
        
        # Get indexer
        try:
            from connectors.email.indexer import EmailIndexer
            from connectors.email.processor import EmailProcessor
            from database import get_db_manager
            from embeddings import get_embedding_service
            
            processor = EmailProcessor()
            db_manager = get_db_manager()
            embedding_service = get_embedding_service()
            
            self._indexer = EmailIndexer(
                ingestor=self._ingestor,
                processor=processor,
                embedding_manager=embedding_service,
                database_manager=db_manager
            )
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to initialize indexer: {e}")
            return
        
        folder = self.folder_combo.currentText()
        limit = self.limit_spin.value()
        
        self.sync_btn.setEnabled(False)
        self.sync_btn.setText("Syncing...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # Indeterminate
        self.sync_status_label.setText(f"Syncing {folder}...")
        self.results_label.setText("")
        
        self.sync_worker = SyncWorker(self._indexer, folder, limit)
        self.sync_worker.finished.connect(self.sync_finished)
        self.sync_worker.start()
    
    def sync_finished(self, success: bool, stats: dict):
        """Handle sync completion."""
        self.sync_btn.setEnabled(True)
        self.sync_btn.setText("Start Sync")
        self.progress_bar.setVisible(False)
        
        if success:
            indexed = stats.get('indexed', 0)
            skipped = stats.get('skipped', 0)
            errors = stats.get('errors', 0)
            
            self.sync_status_label.setText("Sync complete!")
            self.sync_status_label.setStyleSheet("color: #10b981;")
            self.results_label.setText(
                f"Indexed: {indexed} chunks | Skipped: {skipped} | Errors: {errors}"
            )
            
            QMessageBox.information(
                self,
                "Sync Complete",
                f"Email sync completed!\n\n"
                f"Indexed: {indexed} chunks\n"
                f"Skipped: {skipped}\n"
                f"Errors: {errors}"
            )
        else:
            error = stats.get('error', 'Unknown error')
            self.sync_status_label.setText(f"Sync failed: {error}")
            self.sync_status_label.setStyleSheet("color: #ef4444;")
            QMessageBox.warning(self, "Sync Failed", error)
