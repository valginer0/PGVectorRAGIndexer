"""
Upload tab for selecting and uploading documents with full path preservation.
"""

import logging
import time
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QFileDialog, QCheckBox, QTextEdit,
    QProgressBar, QMessageBox, QGroupBox, QLineEdit, QComboBox
)
import qtawesome as qta
from PySide6.QtCore import Qt, QThread, Signal, QSize
from .workers import UploadWorker
from .shared import populate_document_type_combo

# ... imports ...

class UploadTab(QWidget):
    """Tab for uploading documents."""
    SUPPORTED_EXTENSIONS = {
        '.txt', '.md', '.markdown', '.pdf', '.doc', '.docx', '.pptx', '.html'
    }

    def __init__(self, api_client, parent=None):
        super().__init__(parent)
        self.api_client = api_client
        self.selected_files: list[Path] = []  # Changed to list for multi-file support
        self.upload_worker: Optional[UploadWorker] = None
        self.current_upload_index = 0
        self.upload_started_at: Optional[float] = None
        self.success_count = 0
        self.failure_count = 0
        self.failed_uploads: list[dict] = []
        
        self.setup_ui()
    
    def setup_ui(self):
        """Setup the user interface."""
        layout = QVBoxLayout(self)
        layout.setSpacing(20)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Title
        title = QLabel("Upload Documents")
        title.setProperty("class", "header")
        layout.addWidget(title)
        
        # Instructions
        info_box = QGroupBox("How It Works")
        info_layout = QVBoxLayout(info_box)
        info_text = QLabel(
            "This desktop app automatically preserves the full file path!\n\n"
            "• Click 'Select Files' to choose one or more documents\n"
            "• Click 'Select Folder' to index all files in a directory (recursive)\n"
            "• The full path (e.g., C:\\Projects\\file.txt) is automatically captured\n"
            "• Upload to index the documents with their full paths preserved\n\n"
            "Supported formats: TXT, MD, PDF, DOC, DOCX, PPTX, HTML"
        )
        info_text.setWordWrap(True)
        info_text.setStyleSheet("color: #9ca3af;")
        info_layout.addWidget(info_text)
        layout.addWidget(info_box)
        
        # File selection
        file_group = QGroupBox("Select File")
        file_layout = QVBoxLayout(file_group)
        
        select_btn_layout = QHBoxLayout()
        
        self.select_files_btn = QPushButton("Select Files")
        self.select_files_btn.setIcon(qta.icon('fa5s.file-alt', color='white'))
        self.select_files_btn.clicked.connect(self.select_files)
        self.select_files_btn.setMinimumHeight(40)
        select_btn_layout.addWidget(self.select_files_btn)
        
        self.select_folder_btn = QPushButton("Select Folder")
        self.select_folder_btn.setIcon(qta.icon('fa5s.folder-open', color='white'))
        self.select_folder_btn.clicked.connect(self.select_folder)
        self.select_folder_btn.setMinimumHeight(40)
        select_btn_layout.addWidget(self.select_folder_btn)
        
        file_layout.addLayout(select_btn_layout)
        
        self.file_path_label = QLabel("No files selected")
        self.file_path_label.setStyleSheet("color: #9ca3af; padding: 10px; background: #1f2937; border-radius: 5px; border: 1px dashed #374151;")
        self.file_path_label.setWordWrap(True)
        self.file_path_label.setAlignment(Qt.AlignCenter)
        file_layout.addWidget(self.file_path_label)
        
        layout.addWidget(file_group)
        
        # Options
        options_group = QGroupBox("Options")
        options_layout = QVBoxLayout(options_group)
        
        # Document Type
        type_layout = QHBoxLayout()
        type_label = QLabel("Document Type:")
        type_label.setMinimumWidth(120)
        type_layout.addWidget(type_label)
        
        self.document_type_combo = QComboBox()
        self.document_type_combo.setEditable(True)
        self.document_type_combo.setToolTip("Arbitrary tag (e.g. 'Invoice', 'Memo'). Leave empty to ignore.")
        self.document_type_combo.setPlaceholderText("Type or select tag (optional)")
        self.document_type_combo.setMinimumWidth(200)
        type_layout.addWidget(self.document_type_combo)
        
        refresh_types_btn = QPushButton()
        refresh_types_btn.setIcon(qta.icon('fa5s.sync-alt', color='#9ca3af'))
        refresh_types_btn.clicked.connect(self.load_document_types)
        refresh_types_btn.setToolTip("Refresh available document types")
        refresh_types_btn.setFixedSize(30, 30)
        type_layout.addWidget(refresh_types_btn)
        
        # Load initial types
        self.load_document_types()
        
        options_layout.addLayout(type_layout)
        

        
        layout.addWidget(options_group)
        
        # Upload button
        self.upload_btn = QPushButton("Upload and Index")
        self.upload_btn.setIcon(qta.icon('fa5s.cloud-upload-alt', color='white'))
        self.upload_btn.clicked.connect(self.upload_file)
        self.upload_btn.setEnabled(False)
        self.upload_btn.setMinimumHeight(50)
        self.upload_btn.setProperty("class", "primary")
        layout.addWidget(self.upload_btn)
        
        # Progress
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # Stats Label
        self.stats_label = QLabel("")
        self.stats_label.setAlignment(Qt.AlignCenter)
        self.stats_label.setStyleSheet("font-weight: bold; margin-top: 5px;")
        self.stats_label.setVisible(False)
        layout.addWidget(self.stats_label)
        
        # View Errors Button
        self.view_errors_btn = QPushButton("View Failures")
        self.view_errors_btn.setIcon(qta.icon('fa5s.exclamation-triangle', color='white'))
        self.view_errors_btn.setProperty("class", "danger")
        self.view_errors_btn.clicked.connect(self.show_errors_dialog)
        self.view_errors_btn.setVisible(False)
        layout.addWidget(self.view_errors_btn)
        
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
        documents_filter = self._build_documents_filter()
        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Documents to Upload",
            "",
            f"{documents_filter};;All Files (*)"
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
            self.file_path_label.setStyleSheet("color: #10b981; padding: 10px; background: #1f2937; border-radius: 5px; border: 1px solid #10b981; font-weight: bold;")
            self.upload_btn.setEnabled(True)
            self.log(f"{count} file(s) selected")
            self.stats_label.setVisible(False)
            self.view_errors_btn.setVisible(False)
    
    def select_folder(self):
        """Open folder dialog to select a directory and index all supported files."""
        documents_filter = self._build_documents_filter()
        dialog = QFileDialog(self, "Select Folder to Index (Recursive)")
        dialog.setFileMode(QFileDialog.Directory)
        dialog.setOption(QFileDialog.ShowDirsOnly, False)
        dialog.setOption(QFileDialog.DontUseNativeDialog, True)
        dialog.setNameFilter(f"{documents_filter};;All Files (*)")

        if not dialog.exec():
            return

        selected = dialog.selectedFiles()
        if not selected:
            return

        folder_path = selected[0]
        folder = Path(folder_path)
        found_files = self._find_supported_files(folder)

        if not found_files:
            QMessageBox.warning(
                self,
                "No Files Found",
                f"No supported files found in:\n{folder_path}\n\nSupported: TXT, MD, PDF, DOC, DOCX, PPTX, HTML"
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
            self.file_path_label.setStyleSheet("color: #10b981; padding: 10px; background: #1f2937; border-radius: 5px; border: 1px solid #10b981; font-weight: bold;")
            self.upload_btn.setEnabled(True)
            self.log(f"Folder selected: {count} files found in {folder_path}")
            self.stats_label.setVisible(False)
            self.view_errors_btn.setVisible(False)
    
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
        self.upload_started_at = time.perf_counter()
        
        # Reset stats
        self.success_count = 0
        self.failure_count = 0
        self.failed_uploads = []
        self.stats_label.setText("Starting upload...")
        self.stats_label.setStyleSheet("color: #6366f1; font-weight: bold;")
        self.stats_label.setVisible(True)
        self.view_errors_btn.setVisible(False)
        
        # Prepare files data
        files_data = []
        document_type = self.document_type_combo.currentText().strip() or None
        force_reindex = False
        
        for file_path in self.selected_files:
            files_data.append({
                'path': file_path,
                'full_path': str(file_path.resolve()),
                'force_reindex': force_reindex,
                'document_type': document_type
            })
            
        self.log(f"Starting upload of {len(files_data)} files...")
        
        # Start upload worker
        self.upload_worker = UploadWorker(self.api_client, files_data)
        self.upload_worker.progress.connect(self.log)
        self.upload_worker.file_finished.connect(self.on_file_finished)
        self.upload_worker.all_finished.connect(self.on_all_finished)
        self.upload_worker.start()
    
    def on_file_finished(self, index: int, success: bool, message: str):
        """Handle single file upload completion."""
        self.progress_bar.setValue(index + 1)
        
        if success:
            self.success_count += 1
            self.log(f"✓ File {index + 1} uploaded successfully")
        else:
            self.failure_count += 1
            
            # Enhance error message
            enhanced_msg = message
            if "timed out" in message.lower():
                enhanced_msg += "\n   ➜ Hint: File might be too large or server is busy."
            elif "413" in message:
                enhanced_msg += "\n   ➜ Hint: File exceeds server size limit."
            elif "400" in message:
                enhanced_msg += "\n   ➜ Hint: File might be empty or corrupted."
            elif "connection" in message.lower():
                enhanced_msg += "\n   ➜ Hint: Check your network or Docker status."
                
            self.log(f"✗ File {index + 1} failed: {message}")
            
            # Store failure details with full path
            file_path = str(self.selected_files[index])
            self.failed_uploads.append({
                "file": file_path,
                "error": enhanced_msg
            })
        
        # Update stats label
        self.stats_label.setText(f"Success: {self.success_count} | Failed: {self.failure_count}")
        if self.failure_count > 0:
            self.stats_label.setStyleSheet("color: #ef4444; font-weight: bold;") # Red if any failures
            self.view_errors_btn.setVisible(True)
        else:
            self.stats_label.setStyleSheet("color: #10b981; font-weight: bold;") # Green if all good
            
    def on_all_finished(self, ):
        """Handle completion of all uploads."""
        self.progress_bar.setVisible(False)
        self.select_files_btn.setEnabled(True)
        self.select_folder_btn.setEnabled(True)
        self.upload_btn.setEnabled(True)
        
        total = len(self.selected_files)
        self.log(f"\n{'='*50}")
        self.log(f"✓ All uploads completed! ({total} file(s))")
        if self.upload_started_at is not None:
            elapsed = time.perf_counter() - self.upload_started_at
            self.log(f"Total upload time: {self._format_elapsed(elapsed)}")
            self.upload_started_at = None
        self.log(f"{'='*50}")
        
        # Clear selection
        self.selected_files = []
        self.file_path_label.setText("No files selected")
        self.file_path_label.setStyleSheet("color: #9ca3af; padding: 10px; background: #1f2937; border-radius: 5px; border: 1px dashed #374151;")
        self.upload_btn.setEnabled(False)
        
        # Cleanup worker
        if self.upload_worker:
            self.upload_worker.deleteLater()
            self.upload_worker = None
            
    def show_errors_dialog(self):
        """Show a dialog with details of failed uploads."""
        if not self.failed_uploads:
            return
            
        msg = QMessageBox(self)
        msg.setWindowTitle("Upload Failures")
        msg.setIcon(QMessageBox.Warning)
        msg.setText(f"{len(self.failed_uploads)} file(s) failed to upload.")
        
        # Build detailed list
        details = ""
        for i, failure in enumerate(self.failed_uploads, 1):
            details += f"{i}. {failure['file']}\n"
            details += f"   Error: {failure['error']}\n\n"
            
        msg.setDetailedText(details)
        
        # Hack to force detailed text to be visible/expanded if possible, 
        # or just encourage user to click "Show Details"
        msg.setInformativeText("Click 'Show Details' to see the reasons.")
        
        msg.exec()
    
    def log(self, message: str):
        """Add a message to the log."""
        self.log_text.append(message)
        # Auto-scroll to bottom
        self.log_text.verticalScrollBar().setValue(
            self.log_text.verticalScrollBar().maximum()
        )

    @staticmethod
    def _format_elapsed(seconds: float) -> str:
        total_seconds = int(seconds)
        hours, remainder = divmod(total_seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d} ({seconds:.2f}s)"

    @classmethod
    def _build_documents_filter(cls) -> str:
        patterns = " ".join(sorted(f"*{ext}" for ext in cls.SUPPORTED_EXTENSIONS))
        return f"Documents ({patterns})"

    @classmethod
    def _find_supported_files(cls, folder: Path) -> list[Path]:
        files: list[Path] = []
        for path in folder.rglob('*'):
            if path.is_file() and path.suffix.lower() in cls.SUPPORTED_EXTENSIONS:
                if not path.name.startswith('~$'):
                    files.append(path)
        return files

    def load_document_types(self) -> None:
        """Populate the document type combo from the API."""
        if not hasattr(self, "document_type_combo"):
            return

        populate_document_type_combo(
            self.document_type_combo,
            self.api_client,
            logging.getLogger(__name__),
            blank_option="",
            log_context="Upload tab"
        )
