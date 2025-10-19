"""
Upload tab for selecting and uploading documents with full path preservation.
"""

import logging
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QFileDialog, QCheckBox, QTextEdit,
    QProgressBar, QMessageBox, QGroupBox
)
from PySide6.QtCore import Qt, QThread, Signal

import requests

logger = logging.getLogger(__name__)


class UploadWorker(QThread):
    """Worker thread for uploading files."""
    
    progress = Signal(str)
    finished = Signal(bool, str)
    
    def __init__(self, api_client, file_path: Path, full_path: str, force_reindex: bool):
        super().__init__()
        self.api_client = api_client
        self.file_path = file_path
        self.full_path = full_path
        self.force_reindex = force_reindex
    
    def run(self):
        """Upload the file."""
        try:
            self.progress.emit(f"Uploading {self.file_path.name}...")
            
            result = self.api_client.upload_document(
                self.file_path,
                custom_source_uri=self.full_path,
                force_reindex=self.force_reindex
            )
            
            doc_id = result.get('document_id', 'unknown')
            chunks = result.get('chunks_indexed', 0)
            
            self.progress.emit(f"✓ Uploaded successfully! Document ID: {doc_id}, Chunks: {chunks}")
            self.finished.emit(True, f"Document uploaded successfully!\n\nDocument ID: {doc_id}\nChunks indexed: {chunks}\nPath preserved: {self.full_path}")
            
        except requests.RequestException as e:
            error_msg = f"Upload failed: {str(e)}"
            logger.error(error_msg)
            self.progress.emit(f"✗ {error_msg}")
            self.finished.emit(False, error_msg)
        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"
            logger.error(error_msg)
            self.progress.emit(f"✗ {error_msg}")
            self.finished.emit(False, error_msg)


class UploadTab(QWidget):
    """Tab for uploading documents."""
    
    def __init__(self, api_client, parent=None):
        super().__init__(parent)
        self.api_client = api_client
        self.selected_file: Optional[Path] = None
        self.upload_worker: Optional[UploadWorker] = None
        
        self.setup_ui()
    
    def setup_ui(self):
        """Setup the user interface."""
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        
        # Title
        title = QLabel("📤 Upload Documents")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(title)
        
        # Instructions
        info_box = QGroupBox("ℹ️ How It Works")
        info_layout = QVBoxLayout(info_box)
        info_text = QLabel(
            "This desktop app automatically preserves the full file path!\n\n"
            "• Click 'Select File' to choose a document\n"
            "• The full path (e.g., C:\\Projects\\file.txt) is automatically captured\n"
            "• Upload to index the document with its full path preserved\n"
            "• Later you can edit the source file and re-index it\n\n"
            "Supported formats: TXT, MD, PDF, DOCX, PPTX, HTML"
        )
        info_text.setWordWrap(True)
        info_layout.addWidget(info_text)
        layout.addWidget(info_box)
        
        # File selection
        file_group = QGroupBox("Select File")
        file_layout = QVBoxLayout(file_group)
        
        select_btn_layout = QHBoxLayout()
        self.select_file_btn = QPushButton("📁 Select File")
        self.select_file_btn.clicked.connect(self.select_file)
        self.select_file_btn.setMinimumHeight(40)
        select_btn_layout.addWidget(self.select_file_btn)
        file_layout.addLayout(select_btn_layout)
        
        self.file_path_label = QLabel("No file selected")
        self.file_path_label.setStyleSheet("color: #666; padding: 10px; background: #f5f5f5; border-radius: 5px;")
        self.file_path_label.setWordWrap(True)
        file_layout.addWidget(self.file_path_label)
        
        layout.addWidget(file_group)
        
        # Options
        options_group = QGroupBox("Options")
        options_layout = QVBoxLayout(options_group)
        
        self.force_reindex_cb = QCheckBox("Force reindex if document already exists")
        self.force_reindex_cb.setToolTip("Check this to reindex the document even if it already exists in the database")
        options_layout.addWidget(self.force_reindex_cb)
        
        layout.addWidget(options_group)
        
        # Upload button
        self.upload_btn = QPushButton("📤 Upload and Index")
        self.upload_btn.clicked.connect(self.upload_file)
        self.upload_btn.setEnabled(False)
        self.upload_btn.setMinimumHeight(50)
        self.upload_btn.setStyleSheet("""
            QPushButton {
                background-color: #2563eb;
                color: white;
                font-size: 14px;
                font-weight: bold;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #1d4ed8;
            }
            QPushButton:disabled {
                background-color: #9ca3af;
            }
        """)
        layout.addWidget(self.upload_btn)
        
        # Progress
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        
        # Status log
        log_group = QGroupBox("Upload Log")
        log_layout = QVBoxLayout(log_group)
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(150)
        log_layout.addWidget(self.log_text)
        
        layout.addWidget(log_group)
        
        layout.addStretch()
    
    def select_file(self):
        """Open file dialog to select a file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Document to Upload",
            "",
            "Documents (*.txt *.md *.markdown *.pdf *.docx *.pptx *.html);;All Files (*)"
        )
        
        if file_path:
            self.selected_file = Path(file_path)
            # Display the FULL path - this is what gets preserved!
            self.file_path_label.setText(f"✓ Selected: {file_path}")
            self.file_path_label.setStyleSheet("color: #059669; padding: 10px; background: #d1fae5; border-radius: 5px; font-weight: bold;")
            self.upload_btn.setEnabled(True)
            self.log(f"File selected: {file_path}")
    
    def upload_file(self):
        """Upload the selected file."""
        if not self.selected_file:
            QMessageBox.warning(self, "No File", "Please select a file first.")
            return
        
        if not self.api_client.is_api_available():
            QMessageBox.critical(
                self,
                "API Not Available",
                "The API is not available. Please make sure Docker containers are running."
            )
            return
        
        # Get the full path as string
        full_path = str(self.selected_file.absolute())
        
        # Disable UI during upload
        self.select_file_btn.setEnabled(False)
        self.upload_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # Indeterminate progress
        
        # Create and start worker thread
        self.upload_worker = UploadWorker(
            self.api_client,
            self.selected_file,
            full_path,
            self.force_reindex_cb.isChecked()
        )
        self.upload_worker.progress.connect(self.log)
        self.upload_worker.finished.connect(self.upload_finished)
        self.upload_worker.start()
    
    def upload_finished(self, success: bool, message: str):
        """Handle upload completion."""
        # Re-enable UI
        self.select_file_btn.setEnabled(True)
        self.upload_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        
        if success:
            QMessageBox.information(self, "Success", message)
            # Clear selection
            self.selected_file = None
            self.file_path_label.setText("No file selected")
            self.file_path_label.setStyleSheet("color: #666; padding: 10px; background: #f5f5f5; border-radius: 5px;")
            self.upload_btn.setEnabled(False)
        else:
            QMessageBox.critical(self, "Upload Failed", message)
    
    def log(self, message: str):
        """Add a message to the log."""
        self.log_text.append(message)
        # Auto-scroll to bottom
        self.log_text.verticalScrollBar().setValue(
            self.log_text.verticalScrollBar().maximum()
        )
