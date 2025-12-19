"""
Dialog for displaying and managing encrypted PDFs encountered during upload.
"""

import sys
import os
import subprocess
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QListWidget, QListWidgetItem, QFileDialog, QMessageBox
)
from PySide6.QtCore import Qt


class EncryptedPDFsDialog(QDialog):
    """Dialog showing encrypted PDFs with clickable links to open them."""
    
    def __init__(self, encrypted_pdfs: list, parent=None):
        super().__init__(parent)
        self.encrypted_pdfs = encrypted_pdfs.copy()
        self.setWindowTitle("🔒 Encrypted PDFs")
        self.setMinimumSize(600, 400)
        self.setup_ui()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Header
        header = QLabel(f"Found {len(self.encrypted_pdfs)} password-protected PDF(s)")
        header.setStyleSheet("font-size: 14px; font-weight: bold; margin-bottom: 10px;")
        layout.addWidget(header)
        
        info = QLabel("Click a file to open it in your PDF viewer (e.g., Acrobat) where you can enter the password.")
        info.setWordWrap(True)
        info.setStyleSheet("color: #9ca3af; margin-bottom: 10px;")
        layout.addWidget(info)
        
        # List
        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet("""
            QListWidget::item {
                color: #6366f1;
                text-decoration: underline;
                padding: 6px;
            }
            QListWidget::item:hover {
                background: #374151;
            }
        """)
        self.list_widget.itemClicked.connect(self.open_file)
        
        for file_path in self.encrypted_pdfs:
            item = QListWidgetItem(file_path)
            item.setData(Qt.UserRole, file_path)
            item.setToolTip(f"Click to open: {file_path}")
            self.list_widget.addItem(item)
        
        layout.addWidget(self.list_widget)
        
        # Buttons
        btn_layout = QHBoxLayout()
        
        export_btn = QPushButton("📥 Export to CSV")
        export_btn.clicked.connect(self.export_list)
        btn_layout.addWidget(export_btn)
        
        btn_layout.addStretch()
        
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)
        
        layout.addLayout(btn_layout)
    
    def open_file(self, item: QListWidgetItem):
        """Open the file in system's default PDF viewer."""
        path = item.data(Qt.UserRole)
        if not path:
            return
        
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as e:
            QMessageBox.warning(
                self,
                "Open Failed",
                f"Could not open file:\n{path}\n\nError: {e}"
            )
    
    def export_list(self):
        """Export the list to CSV."""
        if not self.encrypted_pdfs:
            QMessageBox.information(self, "No Data", "No encrypted PDFs to export.")
            return
        
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Encrypted PDFs List",
            "encrypted_pdfs.csv",
            "CSV Files (*.csv)"
        )
        
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write("File Path\n")
                    for path in self.encrypted_pdfs:
                        f.write(f'"{path}"\n')
                QMessageBox.information(
                    self,
                    "Export Complete",
                    f"Exported {len(self.encrypted_pdfs)} files to:\n{file_path}"
                )
            except Exception as e:
                QMessageBox.warning(self, "Export Failed", f"Error: {e}")
