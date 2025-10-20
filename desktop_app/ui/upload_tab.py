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
        self.selected_files: list[Path] = []  # Changed to list for multi-file support
        self.upload_worker: Optional[UploadWorker] = None
        self.current_upload_index = 0
        
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
            "• Click 'Select Files' to choose one or more documents\n"
            "• Click 'Select Folder' to index all files in a directory (recursive)\n"
            "• The full path (e.g., C:\\Projects\\file.txt) is automatically captured\n"
            "• Upload to index the documents with their full paths preserved\n\n"
            "Supported formats: TXT, MD, PDF, DOCX, PPTX, HTML"
        )
        info_text.setWordWrap(True)
        info_layout.addWidget(info_text)
        layout.addWidget(info_box)
        
        # File selection
        file_group = QGroupBox("Select File")
        file_layout = QVBoxLayout(file_group)
        
        select_btn_layout = QHBoxLayout()
        
        self.select_files_btn = QPushButton("📁 Select Files")
        self.select_files_btn.clicked.connect(self.select_files)
        self.select_files_btn.setMinimumHeight(40)
        select_btn_layout.addWidget(self.select_files_btn)
        
        self.select_folder_btn = QPushButton("📂 Select Folder")
        self.select_folder_btn.clicked.connect(self.select_folder)
        self.select_folder_btn.setMinimumHeight(40)
        select_btn_layout.addWidget(self.select_folder_btn)
        
        file_layout.addLayout(select_btn_layout)
        
        self.file_path_label = QLabel("No files selected")
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
    
    def select_files(self):
        """Open file dialog to select multiple files."""
        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Documents to Upload",
            "",
            "Documents (*.txt *.md *.markdown *.pdf *.docx *.pptx *.html);;All Files (*)"
        )
        
        if file_paths:
            self.selected_files = [Path(fp) for fp in file_paths]
            count = len(self.selected_files)
            # Display the FULL paths
            if count == 1:
                self.file_path_label.setText(f"✓ Selected: {file_paths[0]}")
            else:
                preview = "\n".join(file_paths[:5])
                if count > 5:
                    preview += f"\n... and {count - 5} more files"
                self.file_path_label.setText(f"✓ Selected {count} files:\n{preview}")
            self.file_path_label.setStyleSheet("color: #059669; padding: 10px; background: #d1fae5; border-radius: 5px; font-weight: bold;")
            self.upload_btn.setEnabled(True)
            self.log(f"{count} file(s) selected")
    
    def select_folder(self):
        """Open folder dialog to select a directory and index all supported files."""
        folder_path = QFileDialog.getExistingDirectory(
            self,
            "Select Folder to Index (Recursive)",
            ""
        )
        
        if folder_path:
            # Find all supported files recursively
            supported_extensions = {'.txt', '.md', '.markdown', '.pdf', '.docx', '.pptx', '.html'}
            folder = Path(folder_path)
            found_files = []
            
            for ext in supported_extensions:
                found_files.extend(folder.rglob(f'*{ext}'))
            
            if not found_files:
                QMessageBox.warning(
                    self,
                    "No Files Found",
                    f"No supported files found in:\n{folder_path}\n\nSupported: TXT, MD, PDF, DOCX, PPTX, HTML"
                )
                return
            
            # Show confirmation dialog with smart preview
            count = len(found_files)
            
            # Build confirmation message based on file count
            if count <= 15:
                # Small number - show all files
                preview = "\n".join(str(f.relative_to(folder)) for f in found_files)
                message = (
                    f"Found {count} file(s) in:\n{folder_path}\n\n"
                    f"Files to index:\n{preview}\n\n"
                    f"Do you want to index all {count} file(s)?"
                )
            else:
                # Large number - show statistics and sample
                # Count by extension
                ext_counts = {}
                for f in found_files:
                    ext = f.suffix.lower()
                    ext_counts[ext] = ext_counts.get(ext, 0) + 1
                
                # Count by subdirectory depth
                subdir_counts = {}
                for f in found_files:
                    rel_path = f.relative_to(folder)
                    if len(rel_path.parts) > 1:
                        subdir = rel_path.parts[0]
                        subdir_counts[subdir] = subdir_counts.get(subdir, 0) + 1
                    else:
                        subdir_counts["(root)"] = subdir_counts.get("(root)", 0) + 1
                
                # Build statistics
                stats = "File types:\n"
                for ext, cnt in sorted(ext_counts.items()):
                    stats += f"  {ext}: {cnt} file(s)\n"
                
                if len(subdir_counts) > 1:
                    stats += "\nTop subdirectories:\n"
                    for subdir, cnt in sorted(subdir_counts.items(), key=lambda x: x[1], reverse=True)[:5]:
                        stats += f"  {subdir}: {cnt} file(s)\n"
                
                # Show sample files
                sample = "\n".join(str(f.relative_to(folder)) for f in found_files[:10])
                
                message = (
                    f"Found {count} file(s) in:\n{folder_path}\n\n"
                    f"{stats}\n"
                    f"Sample files (first 10):\n{sample}\n"
                    f"... and {count - 10} more files\n\n"
                    f"⚠️ Do you want to index all {count} file(s)?\n"
                    f"This may take several minutes."
                )
            
            reply = QMessageBox.question(
                self,
                "Confirm Folder Indexing",
                message,
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                self.selected_files = found_files
                self.file_path_label.setText(f"✓ Selected {count} files from folder:\n{folder_path}")
                self.file_path_label.setStyleSheet("color: #059669; padding: 10px; background: #d1fae5; border-radius: 5px; font-weight: bold;")
                self.upload_btn.setEnabled(True)
                self.log(f"Folder selected: {count} files found in {folder_path}")
    
    def upload_file(self):
        """Upload the selected files."""
        if not self.selected_files:
            QMessageBox.warning(self, "No Files", "Please select file(s) first.")
            return
        
        if not self.api_client.is_api_available():
            QMessageBox.critical(
                self,
                "API Not Available",
                "The API is not available. Please make sure Docker containers are running."
            )
            return
        
        # Disable buttons during upload
        self.select_files_btn.setEnabled(False)
        self.select_folder_btn.setEnabled(False)
        self.upload_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, len(self.selected_files))
        self.progress_bar.setValue(0)
        
        # Start uploading files one by one
        self.current_upload_index = 0
        self.upload_next_file()
    
    def upload_next_file(self):
        """Upload the next file in the queue."""
        if self.current_upload_index >= len(self.selected_files):
            # All files uploaded
            self.upload_all_finished()
            return
        
        file_path = self.selected_files[self.current_upload_index]
        full_path = str(file_path.resolve())
        
        self.log(f"[{self.current_upload_index + 1}/{len(self.selected_files)}] Uploading: {file_path.name}")
        
        # Start upload in background thread
        self.upload_worker = UploadWorker(
            self.api_client,
            file_path,
            full_path,
            self.force_reindex_cb.isChecked()
        )
        self.upload_worker.progress.connect(self.log)
        self.upload_worker.finished.connect(self.upload_finished)
        self.upload_worker.start()
    
    def upload_finished(self, success: bool, message: str):
        """Handle single file upload completion."""
        self.progress_bar.setValue(self.current_upload_index + 1)
        
        if success:
            self.log(f"✓ File {self.current_upload_index + 1} uploaded successfully")
        else:
            self.log(f"✗ File {self.current_upload_index + 1} failed: {message}")
        
        # Move to next file
        self.current_upload_index += 1
        self.upload_next_file()
    
    def upload_all_finished(self):
        """Handle completion of all uploads."""
        self.progress_bar.setVisible(False)
        self.select_files_btn.setEnabled(True)
        self.select_folder_btn.setEnabled(True)
        self.upload_btn.setEnabled(True)
        
        total = len(self.selected_files)
        self.log(f"\n{'='*50}")
        self.log(f"✓ All uploads completed! ({total} file(s))")
        self.log(f"{'='*50}")
        
        # Clear selection
        self.selected_files = []
        self.file_path_label.setText("No files selected")
        self.file_path_label.setStyleSheet("color: #666; padding: 10px; background: #f5f5f5; border-radius: 5px;")
        self.upload_btn.setEnabled(False)
    
    def log(self, message: str):
        """Add a message to the log."""
        self.log_text.append(message)
        # Auto-scroll to bottom
        self.log_text.verticalScrollBar().setValue(
            self.log_text.verticalScrollBar().maximum()
        )
