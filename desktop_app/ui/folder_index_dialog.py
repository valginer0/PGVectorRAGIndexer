"""
Dialog for folder indexing with exclusion pattern support.
"""

import fnmatch
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QDialogButtonBox, QFrame, QWidget, QApplication
)
from PySide6.QtCore import Qt
import qtawesome as qta


# Common exclusion patterns for development projects
DEFAULT_EXCLUSION_PATTERNS = [
    '**/node_modules/**',
    '**/.git/**',
    '**/__pycache__/**',
    '**/venv/**',
    '**/.venv/**',
    '**/build/**',
    '**/dist/**',
    '**/.idea/**',
    '**/.vscode/**',
    '*.log',
    '*.tmp',
    '*.pyc',
]


# Name of the ignore file (similar to .gitignore)
IGNORE_FILE_NAME = '.pgvector-ignore'


class FolderIndexDialog(QDialog):
    """Dialog for confirming folder indexing with exclusion patterns."""
    
    def __init__(
        self, 
        folder: Path, 
        files: list[Path], 
        supported_extensions: set[str],
        parent=None
    ):
        super().__init__(parent)
        self.folder = folder
        self.all_files = files
        self.supported_extensions = supported_extensions
        self.filtered_files = files.copy()
        self.exclusion_expanded = False
        self.ignore_files = []  # Paths to .pgvector-ignore files if found
        
        self.setWindowTitle("Folder Indexing")
        self.setMinimumWidth(600)
        self.setMinimumHeight(500)
        self.resize(650, 550)
        
        # Copy parent's stylesheet if available
        if parent:
            self.setStyleSheet(parent.styleSheet())
        
        # Check for .pgvector-ignore files (local + global home directory)
        self.ignore_patterns, self.ignore_files = self.load_ignore_patterns(folder)
        
        self.setup_ui()
        
        # If ignore file found, auto-expand and load patterns
        if self.ignore_patterns:
            self.patterns_edit.setPlainText('\n'.join(self.ignore_patterns))
            self.exclusion_expanded = True
            self.exclusion_content.setVisible(True)
            self.toggle_btn.setText("▼  Exclusion Patterns (loaded from .pgvector-ignore)")
        
        self.update_file_count()
    
    @staticmethod
    def load_ignore_patterns(folder: Path) -> tuple[list[str], list[Path]]:
        """
        Load patterns from .pgvector-ignore files.
        
        Searches in:
        1. The folder itself and parent directories (local)
        2. User's home directory (global)
        
        Returns (combined_patterns_list, list_of_ignore_file_paths).
        """
        all_patterns = []
        found_files = []
        
        # Helper to read patterns from a file
        def read_patterns(ignore_file: Path) -> list[str]:
            try:
                content = ignore_file.read_text(encoding='utf-8')
                patterns = []
                for line in content.splitlines():
                    line = line.strip()
                    # Skip empty lines and comments
                    if line and not line.startswith('#'):
                        patterns.append(line)
                return patterns
            except Exception:
                return []
        
        # 1. Check in folder and parent directories (local)
        current = folder
        for _ in range(10):  # Limit depth to prevent infinite loop
            ignore_file = current / IGNORE_FILE_NAME
            if ignore_file.exists() and ignore_file.is_file():
                patterns = read_patterns(ignore_file)
                if patterns:
                    all_patterns.extend(patterns)
                    found_files.append(ignore_file)
                    break  # Stop at first local file found
            
            # Move to parent directory
            parent = current.parent
            if parent == current:  # Reached root
                break
            current = parent
        
        # 2. Check in user's home directory (global)
        home_ignore = Path.home() / IGNORE_FILE_NAME
        if home_ignore.exists() and home_ignore.is_file():
            # Don't add if same as local file
            if home_ignore not in found_files:
                patterns = read_patterns(home_ignore)
                if patterns:
                    all_patterns.extend(patterns)
                    found_files.append(home_ignore)
        
        # Remove duplicates while preserving order
        seen = set()
        unique_patterns = []
        for p in all_patterns:
            if p not in seen:
                seen.add(p)
                unique_patterns.append(p)
        
        return unique_patterns, found_files if found_files else []
    
    def setup_ui(self):
        """Setup the dialog UI."""
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Header with folder path
        header = QLabel(f"<b>Folder:</b> {self.folder}")
        header.setWordWrap(True)
        header.setMinimumHeight(40)
        layout.addWidget(header)
        
        # File statistics
        self.stats_label = QLabel()
        self.stats_label.setMinimumHeight(50)
        layout.addWidget(self.stats_label)
        
        # Separator
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        separator.setMinimumHeight(2)
        layout.addWidget(separator)
        
        # Toggle button for exclusion patterns
        toggle_text = "▶  Exclusion Patterns (click to expand)"
        self.toggle_btn = QPushButton(toggle_text)
        self.toggle_btn.setMinimumHeight(50)
        self.toggle_btn.setCursor(Qt.PointingHandCursor)
        self.toggle_btn.clicked.connect(self.toggle_exclusion_section)
        layout.addWidget(self.toggle_btn)
        
        # Ignore file indicator (shown when .pgvector-ignore is loaded)
        self.ignore_file_label = QLabel()
        self.ignore_file_label.setMinimumHeight(30)
        self.ignore_file_label.setVisible(False)
        layout.addWidget(self.ignore_file_label)
        
        # Exclusion content container (hidden by default)
        self.exclusion_content = QWidget()
        exclusion_layout = QVBoxLayout(self.exclusion_content)
        exclusion_layout.setContentsMargins(0, 15, 0, 0)
        exclusion_layout.setSpacing(12)
        
        # Buttons row
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        
        load_defaults_btn = QPushButton("Load Common Patterns")
        load_defaults_btn.setIcon(qta.icon('fa5s.magic', color='white'))
        load_defaults_btn.setMinimumHeight(40)
        load_defaults_btn.setMinimumWidth(180)
        load_defaults_btn.clicked.connect(self.load_default_patterns)
        load_defaults_btn.setToolTip(
            "Load common patterns to exclude:\n"
            "node_modules, .git, __pycache__, venv, build, etc."
        )
        btn_layout.addWidget(load_defaults_btn)
        
        clear_btn = QPushButton("Clear")
        clear_btn.setIcon(qta.icon('fa5s.eraser', color='#9ca3af'))
        clear_btn.setMinimumHeight(40)
        clear_btn.setMinimumWidth(100)
        clear_btn.clicked.connect(self.clear_patterns)
        btn_layout.addWidget(clear_btn)
        
        btn_layout.addStretch()
        exclusion_layout.addLayout(btn_layout)
        
        # Info label
        info_label = QLabel(
            "Enter patterns to exclude (one per line). Examples:\n"
            "  • **/folder/** — exclude folder anywhere in the tree\n"
            "  • *.log — exclude all .log files"
        )
        info_label.setMinimumHeight(60)
        exclusion_layout.addWidget(info_label)
        
        # Patterns text edit
        self.patterns_edit = QTextEdit()
        self.patterns_edit.setPlaceholderText(
            "Enter patterns here, one per line...\n\n"
            "Or click 'Load Common Patterns' to start with defaults."
        )
        self.patterns_edit.setMinimumHeight(120)
        self.patterns_edit.textChanged.connect(self.on_patterns_changed)
        exclusion_layout.addWidget(self.patterns_edit)
        
        # Exclusion result label
        self.exclusion_result_label = QLabel("")
        self.exclusion_result_label.setMinimumHeight(30)
        exclusion_layout.addWidget(self.exclusion_result_label)
        
        self.exclusion_content.setVisible(False)
        layout.addWidget(self.exclusion_content)
        
        # Show ignore file indicator if patterns were loaded
        if self.ignore_files:
            # Format list of source files
            sources = ', '.join(f.name for f in self.ignore_files)
            self.ignore_file_label.setText(
                f"📄 Loaded from: {sources} "
                f"({len(self.ignore_patterns)} patterns)"
            )
            self.ignore_file_label.setVisible(True)
        
        # Spacer
        layout.addStretch()
        
        # File count summary (prominent)
        self.summary_label = QLabel()
        self.summary_label.setAlignment(Qt.AlignCenter)
        self.summary_label.setMinimumHeight(60)
        layout.addWidget(self.summary_label)
        
        # Dialog buttons
        button_layout = QHBoxLayout()
        button_layout.setSpacing(15)
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setMinimumHeight(50)
        cancel_btn.setMinimumWidth(130)
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        
        button_layout.addStretch()
        
        self.index_btn = QPushButton("Index Files")
        self.index_btn.setIcon(qta.icon('fa5s.cloud-upload-alt', color='white'))
        self.index_btn.setProperty("class", "primary")
        self.index_btn.setMinimumHeight(50)
        self.index_btn.setMinimumWidth(200)
        self.index_btn.clicked.connect(self.accept)
        button_layout.addWidget(self.index_btn)
        
        layout.addLayout(button_layout)
    
    def toggle_exclusion_section(self):
        """Toggle the exclusion patterns section visibility."""
        self.exclusion_expanded = not self.exclusion_expanded
        self.exclusion_content.setVisible(self.exclusion_expanded)
        
        if self.exclusion_expanded:
            self.toggle_btn.setText("▼  Exclusion Patterns (click to collapse)")
            # Resize dialog to fit content
            self.resize(650, 750)
        else:
            self.toggle_btn.setText("▶  Exclusion Patterns (click to expand)")
            self.resize(650, 550)
            # When collapsed, reset to all files
            self.filtered_files = self.all_files.copy()
            self.update_summary_label()
    
    def load_default_patterns(self):
        """Load default exclusion patterns, merging with existing ones."""
        # Get existing patterns
        existing_text = self.patterns_edit.toPlainText().strip()
        existing_patterns = set(
            line.strip() for line in existing_text.splitlines() 
            if line.strip() and not line.strip().startswith('#')
        )
        
        # Merge with defaults (existing patterns first, then new ones)
        all_patterns = list(existing_patterns)
        for pattern in DEFAULT_EXCLUSION_PATTERNS:
            if pattern not in existing_patterns:
                all_patterns.append(pattern)
        
        self.patterns_edit.setPlainText('\n'.join(all_patterns))
    
    def clear_patterns(self):
        """Clear all patterns."""
        self.patterns_edit.clear()
    
    def get_patterns(self) -> list[str]:
        """Get current exclusion patterns as a list."""
        text = self.patterns_edit.toPlainText()
        return [p.strip() for p in text.split('\n') if p.strip()]
    
    def on_patterns_changed(self):
        """Handle pattern text changes - update file count."""
        self.update_file_count()
    
    def update_file_count(self):
        """Recalculate filtered files based on current patterns."""
        patterns = self.get_patterns() if self.exclusion_expanded else []
        
        if patterns:
            self.filtered_files = [
                f for f in self.all_files
                if not self._matches_any_pattern(f, patterns)
            ]
            excluded_count = len(self.all_files) - len(self.filtered_files)
            self.exclusion_result_label.setText(
                f"📊 {excluded_count} file(s) will be excluded"
            )
        else:
            self.filtered_files = self.all_files.copy()
            self.exclusion_result_label.setText("")
        
        self.update_summary_label()
    
    def update_summary_label(self):
        """Update the summary label with current file count."""
        count = len(self.filtered_files)
        total = len(self.all_files)
        
        if count == total:
            self.summary_label.setText(f"📁 {count} files to index")
        else:
            excluded = total - count
            self.summary_label.setText(f"📁 {count} files to index ({excluded} excluded)")
        
        self.index_btn.setText(f"Index {count} Files")
        self.index_btn.setEnabled(count > 0)
        
        # Update stats
        self._update_stats_label()
    
    def _update_stats_label(self):
        """Update the file type statistics label."""
        # Count by extension
        ext_counts = {}
        for f in self.filtered_files:
            ext = f.suffix.lower()
            ext_counts[ext] = ext_counts.get(ext, 0) + 1
        
        if ext_counts:
            stats_parts = [f"{ext}: {cnt}" for ext, cnt in sorted(ext_counts.items())]
            self.stats_label.setText(
                f"<b>File types:</b> {', '.join(stats_parts)}"
            )
        else:
            self.stats_label.setText("<b>No files to index</b>")
    
    @staticmethod
    def _matches_any_pattern(path: Path, patterns: list[str]) -> bool:
        """Check if path matches any exclusion pattern."""
        path_str = str(path)
        for pattern in patterns:
            # Match against full path
            if fnmatch.fnmatch(path_str, pattern):
                return True
            # Also check just the filename for simple patterns like *.log
            if fnmatch.fnmatch(path.name, pattern):
                return True
            # Check each path component for patterns like **/folder/**
            for part in path.parts:
                if fnmatch.fnmatch(part, pattern.strip('*/')):
                    return True
        return False
    
    def get_filtered_files(self) -> list[Path]:
        """Get the list of files after applying exclusion filters."""
        return self.filtered_files
