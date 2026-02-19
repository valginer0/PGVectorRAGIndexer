"""
Upload Results Dialog - A resizable dialog for viewing upload results and errors.
"""
import logging
from typing import List, Dict, Any
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QTabWidget, QWidget, QHeaderView, QAbstractItemView,
    QFileDialog, QMessageBox
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

logger = logging.getLogger(__name__)


class UploadResultsDialog(QDialog):
    """
    A resizable dialog for viewing upload results with filtering and export.
    
    Features:
    - Resizable (min 700x500)
    - Scrollable table with File, Error Type, Details columns
    - Filter tabs: All, Encrypted PDFs, Other Errors
    - Export errors to CSV
    """
    
    def __init__(self, failed_uploads: List[Dict[str, Any]], parent=None):
        super().__init__(parent)
        self.failed_uploads = failed_uploads
        self.setWindowTitle("Upload Results")
        self.setMinimumSize(700, 500)
        self.resize(800, 600)  # Default size
        
        self._setup_ui()
        self._populate_tables()
    
    def _setup_ui(self):
        """Setup the dialog UI."""
        layout = QVBoxLayout(self)
        
        # Summary label
        total = len(self.failed_uploads)
        encrypted_count = sum(1 for f in self.failed_uploads if self._is_encrypted_error(f))
        other_count = total - encrypted_count
        
        summary = QLabel(f"<b>{total} file(s) failed to upload</b> "
                        f"(🔒 {encrypted_count} encrypted, ⚠️ {other_count} other errors)")
        summary.setStyleSheet("font-size: 14px; padding: 10px; color: #ef4444;")
        layout.addWidget(summary)
        
        # Tab widget for filtering
        self.tabs = QTabWidget()
        
        # All errors tab
        self.all_table = self._create_table()
        self.tabs.addTab(self.all_table, f"All ({total})")
        
        # Encrypted PDFs tab
        self.encrypted_table = self._create_table()
        self.tabs.addTab(self.encrypted_table, f"🔒 Encrypted ({encrypted_count})")
        
        # Other errors tab
        self.other_table = self._create_table()
        self.tabs.addTab(self.other_table, f"⚠️ Other ({other_count})")
        
        layout.addWidget(self.tabs)
        
        # Button row
        button_layout = QHBoxLayout()
        
        export_btn = QPushButton("📥 Export to CSV")
        export_btn.clicked.connect(self._export_to_csv)
        button_layout.addWidget(export_btn)
        
        button_layout.addStretch()
        
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        close_btn.setDefault(True)
        button_layout.addWidget(close_btn)
        
        layout.addLayout(button_layout)
    
    def _create_table(self) -> QTableWidget:
        """Create a styled table widget."""
        table = QTableWidget()
        table.setColumnCount(3)
        table.setHorizontalHeaderLabels(["File Path", "Error Type", "Details"])
        
        # Style
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        
        # Column sizing
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)  # File path stretches
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)  # Error type
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)  # Details
        
        # Enable word wrap for details
        table.setWordWrap(True)
        
        return table
    
    def _is_encrypted_error(self, failure: Dict[str, Any]) -> bool:
        """Check if error is an encrypted PDF error."""
        error = failure.get('error', '').lower()
        return 'encrypted' in error or 'password' in error or '403' in error
    
    def _get_error_type(self, failure: Dict[str, Any]) -> str:
        """Categorize the error type."""
        error = failure.get('error', '').lower()
        
        if 'encrypted' in error or 'password' in error or '403' in error:
            return "🔒 Encrypted PDF"
        elif 'timeout' in error:
            return "⏱️ Timeout"
        elif '413' in error:
            return "📏 Too Large"
        elif 'empty' in error or 'no content' in error:
            return "📭 Empty"
        elif 'unsupported' in error:
            return "❌ Unsupported"
        elif '.doc' in failure.get('file', '').lower() and 'convert' in error:
            return "📄 Legacy .doc"
        else:
            return "⚠️ Error"
    
    def _populate_tables(self):
        """Populate all tables with data."""
        all_data = []
        encrypted_data = []
        other_data = []
        
        for failure in self.failed_uploads:
            file_path = failure.get('file', 'Unknown')
            error_type = self._get_error_type(failure)
            details = failure.get('error', 'Unknown error')
            
            row_data = (file_path, error_type, details)
            all_data.append(row_data)
            
            if self._is_encrypted_error(failure):
                encrypted_data.append(row_data)
            else:
                other_data.append(row_data)
        
        self._fill_table(self.all_table, all_data)
        self._fill_table(self.encrypted_table, encrypted_data)
        self._fill_table(self.other_table, other_data)
    
    def _fill_table(self, table: QTableWidget, data: List[tuple]):
        """Fill a table with data rows."""
        table.setRowCount(len(data))
        
        for row, (file_path, error_type, details) in enumerate(data):
            # File path
            file_item = QTableWidgetItem(file_path)
            file_item.setToolTip(file_path)  # Full path on hover
            table.setItem(row, 0, file_item)
            
            # Error type
            type_item = QTableWidgetItem(error_type)
            table.setItem(row, 1, type_item)
            
            # Details (truncate if too long)
            details_short = details[:100] + "..." if len(details) > 100 else details
            details_item = QTableWidgetItem(details_short)
            details_item.setToolTip(details)  # Full details on hover
            table.setItem(row, 2, details_item)
        
        # Resize rows to content
        for row in range(table.rowCount()):
            table.resizeRowToContents(row)
    
    def _export_to_csv(self):
        """Export error list to CSV file."""
        from .shared import default_start_dir
        from pathlib import Path
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Upload Errors",
            str(Path(default_start_dir()) / "upload_errors.csv"),
            "CSV Files (*.csv)"
        )
        
        if not file_path:
            return
        
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write("File Path,Error Type,Details\n")
                for failure in self.failed_uploads:
                    file = failure.get('file', '').replace('"', '""')
                    error_type = self._get_error_type(failure)
                    details = failure.get('error', '').replace('"', '""')
                    f.write(f'"{file}","{error_type}","{details}"\n')
            
            QMessageBox.information(
                self,
                "Export Complete",
                f"Exported {len(self.failed_uploads)} errors to:\n{file_path}"
            )
        except Exception as e:
            logger.error(f"Failed to export: {e}")
            QMessageBox.warning(
                self,
                "Export Failed",
                f"Failed to export: {e}"
            )
