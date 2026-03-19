"""
First-Run Onboarding Wizard for PGVectorRAGIndexer.

Shown once on first launch. Guides the user through five steps:
  1. Connect  — choose local Docker or remote server
  2. Verify   — test the connection and confirm the server is running
  3. License  — optionally activate a license key
  4. Index    — index bundled sample docs or a chosen folder
  5. Search   — run a first search and see it work

State persisted in app_config ('wizard_complete').
Re-accessible from Settings → "Run Setup Wizard".
"""

import logging
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QStackedWidget, QWidget, QLineEdit, QRadioButton,
    QProgressBar, QTextEdit, QFrame, QScrollArea, QFileDialog,
    QSizePolicy,
)
import qtawesome as qta

from desktop_app.ui.styles.theme import Theme
from desktop_app.utils.api_client import APIClient
from desktop_app.utils import app_config

logger = logging.getLogger(__name__)

SAMPLE_DATA_DIR = Path(__file__).parent.parent / "sample_data"

# Module-level strong-reference pool for detached workers.
# Workers are created with no C++ parent, so setParent(None) is a no-op and
# the only Python reference is the dialog attribute.  Adding to this set keeps
# the QThread wrapper alive after the dialog is GC'd; the finished signal
# removes it so it can be collected once the OS thread has exited.
_LIVE_WORKERS: set = set()


# ---------------------------------------------------------------------------
# Background workers
# ---------------------------------------------------------------------------

class _VerifyWorker(QThread):
    """Tests connectivity to the backend in a background thread."""

    result = Signal(bool, str, str)  # success, status_message, server_version

    def __init__(self, api_client: APIClient):
        super().__init__()
        self._client = api_client

    def run(self):
        try:
            health = self._client.get_health()
            if self.isInterruptionRequested():
                return
            status = health.get("status", "unknown")
            if status in ("healthy", "initializing"):
                ver = (
                    health.get("server_version")
                    or health.get("version", "")
                    or ""
                )
                self.result.emit(True, status, ver)
            else:
                err = health.get("error", "Server not responding")
                self.result.emit(False, err, "")
        except Exception as exc:
            if not self.isInterruptionRequested():
                self.result.emit(False, str(exc), "")


class _IndexWorker(QThread):
    """Uploads a list of files to the backend, emitting progress signals."""

    progress = Signal(int, int, str)  # current_index, total, filename
    finished = Signal(int, int)       # indexed_count, failed_count

    def __init__(self, api_client: APIClient, files: list):
        super().__init__()
        self._client = api_client
        self._files = files

    def run(self):
        indexed = 0
        failed = 0
        total = len(self._files)
        for i, path in enumerate(self._files):
            if self.isInterruptionRequested():
                break
            self.progress.emit(i, total, path.name)
            try:
                self._client.upload_document(path)
                indexed += 1
            except Exception as exc:
                logger.warning("Wizard: upload failed for %s: %s", path.name, exc)
                failed += 1
        if not self.isInterruptionRequested():
            self.finished.emit(indexed, failed)


class _SearchWorker(QThread):
    """Runs a search query in a background thread."""

    result = Signal(list)
    error = Signal(str)

    def __init__(self, api_client: APIClient, query: str):
        super().__init__()
        self._client = api_client
        self._query = query

    def run(self):
        try:
            results = self._client.search(self._query, top_k=5, min_score=0.1)
            if not self.isInterruptionRequested():
                self.result.emit(results)
        except Exception as exc:
            if not self.isInterruptionRequested():
                self.error.emit(str(exc))


# ---------------------------------------------------------------------------
# Wizard
# ---------------------------------------------------------------------------

class OnboardingWizard(QDialog):
    """
    Multi-step setup wizard.

    Shown once on first launch; re-accessible via Settings → "Run Setup Wizard".
    """

    settings_changed = Signal()  # emitted when connection settings are saved

    _PAGE_WELCOME = 0
    _PAGE_CONNECT = 1
    _PAGE_VERIFY  = 2
    _PAGE_LICENSE = 3
    _PAGE_INDEX   = 4
    _PAGE_SEARCH  = 5

    _STEP_LABELS = ["Connect", "Verify", "License", "Index", "Search"]

    def __init__(
        self,
        api_client: APIClient,
        docker_manager,
        parent=None,
    ):
        super().__init__(parent)
        self._api_client = api_client
        self._docker_manager = docker_manager

        self._verify_worker: Optional[_VerifyWorker] = None
        self._index_worker: Optional[_IndexWorker] = None
        self._search_worker: Optional[_SearchWorker] = None

        self._verify_ok = False
        self._index_done = False

        self.setWindowTitle("Setup Wizard")
        self.setMinimumWidth(580)
        self.setMinimumHeight(560)
        self.setModal(True)

        self._setup_ui()
        self._go_to_page(self._PAGE_WELCOME)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        # ---- Step indicator (hidden on welcome page) ----
        self._indicator_container = QWidget()
        self._indicator_container.setStyleSheet(
            f"background: {Theme.SURFACE}; border-bottom: 1px solid {Theme.BORDER};"
        )
        ind_layout = QHBoxLayout(self._indicator_container)
        ind_layout.setContentsMargins(32, 14, 32, 14)
        ind_layout.setSpacing(0)

        self._dots: list[QLabel] = []
        self._dot_labels: list[QLabel] = []

        for i, name in enumerate(self._STEP_LABELS):
            # Step bubble + label column
            col = QVBoxLayout()
            col.setAlignment(Qt.AlignHCenter)
            col.setSpacing(3)

            dot = QLabel(str(i + 1))
            dot.setAlignment(Qt.AlignCenter)
            dot.setFixedSize(24, 24)
            dot.setStyleSheet(self._dot_style_inactive())
            self._dots.append(dot)

            lbl = QLabel(name)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet(f"font-size: 11px; color: {Theme.TEXT_SECONDARY};")
            self._dot_labels.append(lbl)

            col.addWidget(dot)
            col.addWidget(lbl)

            step_w = QWidget()
            step_w.setLayout(col)
            ind_layout.addWidget(step_w)

            # Connector line between steps
            if i < len(self._STEP_LABELS) - 1:
                connector = QFrame()
                connector.setFrameShape(QFrame.HLine)
                connector.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                connector.setStyleSheet(f"color: {Theme.BORDER};")
                connector.setFixedHeight(2)
                ind_layout.addWidget(connector, stretch=1)

        root.addWidget(self._indicator_container)

        # ---- Page stack ----
        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_welcome_page())   # 0
        self._stack.addWidget(self._build_connect_page())   # 1
        self._stack.addWidget(self._build_verify_page())    # 2
        self._stack.addWidget(self._build_license_page())   # 3
        self._stack.addWidget(self._build_index_page())     # 4
        self._stack.addWidget(self._build_search_page())    # 5
        root.addWidget(self._stack, stretch=1)

        # ---- Bottom nav bar ----
        nav_container = QWidget()
        nav_container.setStyleSheet(
            f"background: {Theme.SURFACE}; border-top: 1px solid {Theme.BORDER};"
        )
        nav = QHBoxLayout(nav_container)
        nav.setContentsMargins(24, 14, 24, 14)
        nav.setSpacing(10)

        self._back_btn = QPushButton("← Back")
        self._back_btn.setMinimumHeight(36)
        self._back_btn.clicked.connect(self._on_back)
        nav.addWidget(self._back_btn)

        nav.addStretch()

        self._skip_btn = QPushButton("Skip")
        self._skip_btn.setMinimumHeight(36)
        self._skip_btn.clicked.connect(self._on_skip)
        nav.addWidget(self._skip_btn)

        self._next_btn = QPushButton("Next →")
        self._next_btn.setMinimumHeight(36)
        self._next_btn.setMinimumWidth(110)
        self._next_btn.setProperty("class", "primary")
        self._next_btn.clicked.connect(self._on_next)
        nav.addWidget(self._next_btn)

        root.addWidget(nav_container)

    # ------------------------------------------------------------------
    # Page builders
    # ------------------------------------------------------------------

    def _build_welcome_page(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(56, 56, 56, 32)
        layout.setSpacing(20)
        layout.setAlignment(Qt.AlignCenter)

        icon_lbl = QLabel()
        icon_lbl.setPixmap(qta.icon("fa5s.rocket", color=Theme.PRIMARY).pixmap(72, 72))
        icon_lbl.setAlignment(Qt.AlignCenter)
        layout.addWidget(icon_lbl)

        title = QLabel("Welcome to PGVectorRAGIndexer")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(
            f"font-size: 22px; font-weight: 700; color: {Theme.TEXT_PRIMARY};"
        )
        layout.addWidget(title)

        subtitle = QLabel(
            "Let's get you set up in just a few simple steps.\n"
            "It takes about 2 minutes — and you can skip anything you like."
        )
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet(
            f"font-size: 14px; color: {Theme.TEXT_SECONDARY}; line-height: 1.6;"
        )
        layout.addWidget(subtitle)

        layout.addStretch()
        return w

    def _build_connect_page(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(36, 28, 36, 16)
        layout.setSpacing(14)

        self._add_step_heading(layout, "Connect to Your Server",
                               "Where is the PGVectorRAGIndexer server running?")

        # --- Local option ---
        self._radio_local = QRadioButton(
            "On this computer  (Docker — recommended for most users)"
        )
        self._radio_local.setStyleSheet(
            f"font-size: 13px; color: {Theme.TEXT_PRIMARY}; font-weight: 500;"
        )
        self._radio_local.setChecked(
            app_config.get_backend_mode() == app_config.BACKEND_MODE_LOCAL
        )
        layout.addWidget(self._radio_local)

        local_note = QLabel(
            "    Docker Desktop must be running.  "
            "PGVectorRAGIndexer manages the server containers for you automatically."
        )
        local_note.setWordWrap(True)
        local_note.setStyleSheet(
            f"font-size: 12px; color: {Theme.TEXT_SECONDARY}; margin-left: 4px;"
        )
        layout.addWidget(local_note)

        # Separator
        layout.addSpacing(6)

        # --- Remote option ---
        self._radio_remote = QRadioButton(
            "On another server  (enter a URL + API key)"
        )
        self._radio_remote.setStyleSheet(
            f"font-size: 13px; color: {Theme.TEXT_PRIMARY}; font-weight: 500;"
        )
        self._radio_remote.setChecked(
            app_config.get_backend_mode() == app_config.BACKEND_MODE_REMOTE
        )
        layout.addWidget(self._radio_remote)

        # Remote sub-fields
        self._remote_fields = QWidget()
        rf = QVBoxLayout(self._remote_fields)
        rf.setContentsMargins(20, 6, 0, 0)
        rf.setSpacing(8)

        url_row = QHBoxLayout()
        url_lbl = QLabel("Server URL:")
        url_lbl.setFixedWidth(90)
        url_lbl.setStyleSheet(f"font-size: 13px; color: {Theme.TEXT_SECONDARY};")
        self._url_edit = QLineEdit()
        self._url_edit.setPlaceholderText("https://your-server.example.com")
        saved_url = app_config.get("backend_url", "")
        if app_config.is_remote_mode() and saved_url:
            self._url_edit.setText(saved_url)
        url_row.addWidget(url_lbl)
        url_row.addWidget(self._url_edit)
        rf.addLayout(url_row)

        key_row = QHBoxLayout()
        key_lbl = QLabel("API Key:")
        key_lbl.setFixedWidth(90)
        key_lbl.setStyleSheet(f"font-size: 13px; color: {Theme.TEXT_SECONDARY};")
        self._key_edit = QLineEdit()
        self._key_edit.setPlaceholderText("Leave blank if authentication is disabled")
        self._key_edit.setEchoMode(QLineEdit.Password)
        if app_config.is_remote_mode():
            self._key_edit.setText(app_config.get_api_key() or "")
        key_row.addWidget(key_lbl)
        key_row.addWidget(self._key_edit)
        rf.addLayout(key_row)

        layout.addWidget(self._remote_fields)

        self._connect_error_lbl = QLabel("")
        self._connect_error_lbl.setWordWrap(True)
        self._connect_error_lbl.setStyleSheet(
            f"font-size: 12px; color: {Theme.ERROR}; padding: 4px;"
        )
        self._connect_error_lbl.setVisible(False)
        layout.addWidget(self._connect_error_lbl)

        layout.addStretch()

        self._radio_local.toggled.connect(self._on_mode_toggled)
        self._on_mode_toggled()
        return w

    def _build_verify_page(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(36, 28, 36, 16)
        layout.setSpacing(16)

        self._add_step_heading(layout, "Verify Connection",
                               "Making sure the server is reachable…")

        self._verify_icon_lbl = QLabel()
        self._verify_icon_lbl.setAlignment(Qt.AlignCenter)
        self._verify_icon_lbl.setFixedHeight(72)
        layout.addWidget(self._verify_icon_lbl)

        self._verify_status_lbl = QLabel("Connecting…")
        self._verify_status_lbl.setAlignment(Qt.AlignCenter)
        self._verify_status_lbl.setWordWrap(True)
        self._verify_status_lbl.setStyleSheet(
            f"font-size: 15px; font-weight: 500; color: {Theme.TEXT_PRIMARY};"
        )
        layout.addWidget(self._verify_status_lbl)

        self._verify_detail_lbl = QLabel("")
        self._verify_detail_lbl.setAlignment(Qt.AlignCenter)
        self._verify_detail_lbl.setWordWrap(True)
        self._verify_detail_lbl.setStyleSheet(
            f"font-size: 12px; color: {Theme.TEXT_SECONDARY}; "
            f"background: {Theme.SURFACE}; border-radius: 6px; padding: 10px;"
        )
        self._verify_detail_lbl.setVisible(False)
        layout.addWidget(self._verify_detail_lbl)

        self._retry_btn = QPushButton("Try Again")
        self._retry_btn.setVisible(False)
        self._retry_btn.setMinimumWidth(120)
        self._retry_btn.clicked.connect(self._start_verify)
        layout.addWidget(self._retry_btn, alignment=Qt.AlignCenter)

        layout.addStretch()
        return w

    def _build_license_page(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(36, 28, 36, 16)
        layout.setSpacing(14)

        self._add_step_heading(
            layout,
            "License Key  (Optional)",
            "PGVectorRAGIndexer is free as Community edition — no key required."
        )

        desc = QLabel(
            "If you purchased a Team or Organization plan, paste your license key below "
            "to unlock additional users and admin features."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(
            f"font-size: 13px; color: {Theme.TEXT_SECONDARY}; line-height: 1.5;"
        )
        layout.addWidget(desc)

        self._license_edit = QTextEdit()
        self._license_edit.setPlaceholderText("Paste your license key here…")
        self._license_edit.setMaximumHeight(88)
        self._license_edit.setStyleSheet(
            f"font-family: monospace; font-size: 11px; "
            f"background: {Theme.SURFACE}; color: {Theme.TEXT_PRIMARY}; "
            f"border: 1px solid {Theme.BORDER}; border-radius: 6px; padding: 8px;"
        )
        layout.addWidget(self._license_edit)

        activate_row = QHBoxLayout()
        self._activate_btn = QPushButton("Activate License")
        self._activate_btn.setProperty("class", "primary")
        self._activate_btn.setMinimumWidth(150)
        self._activate_btn.clicked.connect(self._on_activate_license)
        activate_row.addWidget(self._activate_btn)
        activate_row.addStretch()
        layout.addLayout(activate_row)

        self._license_result_lbl = QLabel("")
        self._license_result_lbl.setWordWrap(True)
        self._license_result_lbl.setStyleSheet(
            f"font-size: 13px; padding: 8px; border-radius: 6px;"
        )
        self._license_result_lbl.setVisible(False)
        layout.addWidget(self._license_result_lbl)

        no_key_note = QLabel(
            "No key? No problem. You can activate a license at any time in Settings."
        )
        no_key_note.setWordWrap(True)
        no_key_note.setStyleSheet(
            f"font-size: 12px; color: {Theme.TEXT_SECONDARY}; font-style: italic;"
        )
        layout.addWidget(no_key_note)

        layout.addStretch()
        return w

    def _build_index_page(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(36, 28, 36, 16)
        layout.setSpacing(14)

        self._add_step_heading(
            layout,
            "Index Some Documents",
            "Search needs documents. Let's add a few now."
        )

        desc = QLabel(
            "Choose the bundled sample articles (fastest, takes about 10 seconds), "
            "or point to a folder of your own documents."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(
            f"font-size: 13px; color: {Theme.TEXT_SECONDARY}; line-height: 1.5;"
        )
        layout.addWidget(desc)

        self._radio_samples = QRadioButton(
            "Use bundled sample documents  "
            "(5 short articles — ideal for a quick demo)"
        )
        self._radio_samples.setStyleSheet(
            f"font-size: 13px; color: {Theme.TEXT_PRIMARY}; font-weight: 500;"
        )
        self._radio_samples.setChecked(True)
        layout.addWidget(self._radio_samples)

        self._radio_own_folder = QRadioButton("Choose a folder from my computer")
        self._radio_own_folder.setStyleSheet(
            f"font-size: 13px; color: {Theme.TEXT_PRIMARY}; font-weight: 500;"
        )
        layout.addWidget(self._radio_own_folder)

        folder_row = QHBoxLayout()
        folder_row.setContentsMargins(20, 0, 0, 0)
        self._folder_edit = QLineEdit()
        self._folder_edit.setPlaceholderText("No folder selected yet")
        self._folder_edit.setReadOnly(True)
        self._browse_btn = QPushButton("Browse…")
        self._browse_btn.setFixedWidth(90)
        self._browse_btn.clicked.connect(self._on_browse_folder)
        folder_row.addWidget(self._folder_edit)
        folder_row.addWidget(self._browse_btn)
        self._folder_row_w = QWidget()
        self._folder_row_w.setLayout(folder_row)
        self._folder_row_w.setEnabled(False)
        layout.addWidget(self._folder_row_w)

        self._radio_samples.toggled.connect(
            lambda checked: self._folder_row_w.setEnabled(not checked)
        )

        self._index_btn = QPushButton("Start Indexing")
        self._index_btn.setProperty("class", "primary")
        self._index_btn.setMinimumWidth(140)
        self._index_btn.clicked.connect(self._on_start_index)
        layout.addWidget(self._index_btn, alignment=Qt.AlignLeft)

        self._index_progress = QProgressBar()
        self._index_progress.setRange(0, 100)
        self._index_progress.setTextVisible(True)
        self._index_progress.setVisible(False)
        layout.addWidget(self._index_progress)

        self._index_status_lbl = QLabel("")
        self._index_status_lbl.setWordWrap(True)
        self._index_status_lbl.setStyleSheet(
            f"font-size: 13px; color: {Theme.TEXT_SECONDARY};"
        )
        layout.addWidget(self._index_status_lbl)

        layout.addStretch()
        return w

    def _build_search_page(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(36, 28, 36, 16)
        layout.setSpacing(14)

        self._add_step_heading(
            layout,
            "Try a Search",
            "Let's make sure everything is working."
        )

        desc = QLabel(
            "Hit Search to run your first query.  "
            "Change the question to anything you like."
        )
        desc.setStyleSheet(f"font-size: 13px; color: {Theme.TEXT_SECONDARY};")
        layout.addWidget(desc)

        query_row = QHBoxLayout()
        self._query_edit = QLineEdit("What is retrieval-augmented generation?")
        self._query_edit.setStyleSheet(
            f"font-size: 13px; padding: 8px; border-radius: 6px;"
        )
        self._search_btn = QPushButton("Search")
        self._search_btn.setProperty("class", "primary")
        self._search_btn.setMinimumWidth(90)
        self._search_btn.clicked.connect(self._on_run_search)
        query_row.addWidget(self._query_edit)
        query_row.addWidget(self._search_btn)
        layout.addLayout(query_row)

        # Results area
        self._results_scroll = QScrollArea()
        self._results_scroll.setWidgetResizable(True)
        self._results_scroll.setFrameShape(QFrame.NoFrame)
        self._results_scroll.setMinimumHeight(150)
        self._results_scroll.setStyleSheet(
            f"background: transparent;"
        )
        self._results_container = QWidget()
        self._results_layout = QVBoxLayout(self._results_container)
        self._results_layout.setSpacing(8)
        self._results_layout.setContentsMargins(0, 0, 0, 0)
        self._results_layout.addStretch()
        self._results_scroll.setWidget(self._results_container)
        layout.addWidget(self._results_scroll, stretch=1)

        self._search_outcome_lbl = QLabel("")
        self._search_outcome_lbl.setAlignment(Qt.AlignCenter)
        self._search_outcome_lbl.setWordWrap(True)
        self._search_outcome_lbl.setStyleSheet(
            f"font-size: 15px; font-weight: 600; padding: 8px;"
        )
        layout.addWidget(self._search_outcome_lbl)

        return w

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _add_step_heading(layout: QVBoxLayout, title: str, subtitle: str):
        t = QLabel(title)
        t.setStyleSheet(
            f"font-size: 17px; font-weight: 700; color: {Theme.TEXT_PRIMARY};"
        )
        layout.addWidget(t)
        if subtitle:
            s = QLabel(subtitle)
            s.setWordWrap(True)
            s.setStyleSheet(
                f"font-size: 13px; color: {Theme.TEXT_SECONDARY};"
            )
            layout.addWidget(s)
        layout.addSpacing(4)

    @staticmethod
    def _dot_style_inactive() -> str:
        return (
            f"background: {Theme.BORDER}; color: {Theme.TEXT_SECONDARY}; "
            f"border-radius: 12px; font-size: 11px; font-weight: 600;"
        )

    @staticmethod
    def _dot_style_active() -> str:
        return (
            f"background: {Theme.PRIMARY}; color: white; "
            f"border-radius: 12px; font-size: 11px; font-weight: 600;"
        )

    @staticmethod
    def _dot_style_done() -> str:
        return (
            f"background: {Theme.SUCCESS}; color: white; "
            f"border-radius: 12px; font-size: 11px; font-weight: 600;"
        )

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _go_to_page(self, page: int):
        self._current_page = page
        self._stack.setCurrentIndex(page)

        # Indicator visibility
        self._indicator_container.setVisible(page != self._PAGE_WELCOME)

        # Update step dots
        content_idx = page - 1  # 0-based index into dots array
        for i, dot in enumerate(self._dots):
            if i < content_idx:
                dot.setText("✓")
                dot.setStyleSheet(self._dot_style_done())
                self._dot_labels[i].setStyleSheet(
                    f"font-size: 11px; color: {Theme.SUCCESS};"
                )
            elif i == content_idx:
                dot.setText(str(i + 1))
                dot.setStyleSheet(self._dot_style_active())
                self._dot_labels[i].setStyleSheet(
                    f"font-size: 11px; color: {Theme.TEXT_PRIMARY}; font-weight: 600;"
                )
            else:
                dot.setText(str(i + 1))
                dot.setStyleSheet(self._dot_style_inactive())
                self._dot_labels[i].setStyleSheet(
                    f"font-size: 11px; color: {Theme.TEXT_SECONDARY};"
                )

        # Configure nav buttons per page
        is_welcome = page == self._PAGE_WELCOME
        is_last = page == self._PAGE_SEARCH

        self._back_btn.setVisible(not is_welcome)
        self._back_btn.setEnabled(page > self._PAGE_CONNECT)

        self._skip_btn.setVisible(not is_last)
        self._skip_btn.setText("Skip Setup" if is_welcome else "Skip this step")

        if is_welcome:
            self._next_btn.setText("Let's Go  →")
            self._next_btn.setEnabled(True)
        elif is_last:
            self._next_btn.setText("Finish  ✓")
            self._next_btn.setEnabled(True)
        elif page == self._PAGE_VERIFY:
            self._next_btn.setText("Next  →")
            self._next_btn.setEnabled(False)  # enabled after verify succeeds
        elif page == self._PAGE_INDEX:
            self._next_btn.setText("Next  →")
            self._next_btn.setEnabled(self._index_done)
        else:
            self._next_btn.setText("Next  →")
            self._next_btn.setEnabled(True)

        # Side effects when entering a page
        if page == self._PAGE_VERIFY:
            self._start_verify()

    def _on_next(self):
        p = self._current_page
        if p == self._PAGE_WELCOME:
            self._go_to_page(self._PAGE_CONNECT)
        elif p == self._PAGE_CONNECT:
            if self._radio_remote.isChecked():
                url = self._url_edit.text().strip()
                if not url:
                    self._connect_error_lbl.setText(
                        "Please enter the server URL before continuing."
                    )
                    self._connect_error_lbl.setVisible(True)
                    return
            self._connect_error_lbl.setVisible(False)
            self._save_connection_settings()
            self._go_to_page(self._PAGE_VERIFY)
        elif p == self._PAGE_VERIFY:
            if self._verify_ok:
                self._go_to_page(self._PAGE_LICENSE)
        elif p == self._PAGE_LICENSE:
            self._go_to_page(self._PAGE_INDEX)
        elif p == self._PAGE_INDEX:
            self._go_to_page(self._PAGE_SEARCH)
        elif p == self._PAGE_SEARCH:
            self._on_finish()

    def _on_back(self):
        if self._current_page > self._PAGE_WELCOME:
            self._go_to_page(self._current_page - 1)

    def _on_skip(self):
        p = self._current_page
        if p == self._PAGE_WELCOME:
            self._on_finish()
        elif p == self._PAGE_VERIFY:
            # Let them proceed even if verify didn't succeed
            self._verify_ok = True
            self._go_to_page(self._PAGE_LICENSE)
        elif p == self._PAGE_INDEX:
            self._index_done = True
            self._go_to_page(self._PAGE_SEARCH)
        elif p < self._PAGE_SEARCH:
            self._go_to_page(p + 1)

    def _on_finish(self):
        app_config.set("wizard_complete", True)
        self._stop_all_workers()
        self.accept()

    def closeEvent(self, event):  # noqa: N802
        """Stop any background workers before Qt destroys the dialog."""
        self._stop_all_workers()
        super().closeEvent(event)

    def _stop_all_workers(self):
        """Interrupt and keep-alive all running background threads.

        quit()/wait() have no effect: these workers run pure blocking Python
        and never enter a Qt event loop.  setParent(None) is also a no-op
        because the workers were created without a C++ parent.

        The actual fix:
          1. Disconnect all signals — no callbacks fire on the dead dialog.
          2. requestInterruption() — loop guards and post-call checks skip emits.
          3. Add to _LIVE_WORKERS — module-level set holds the only remaining
             strong Python reference, preventing GC from destroying the QThread
             wrapper while the OS thread is still alive.
          4. On finished, remove from the set so the wrapper can be collected.
        """
        for worker in (self._verify_worker, self._index_worker, self._search_worker):
            if worker and worker.isRunning():
                try:
                    worker.disconnect()  # prevent signals firing on dead dialog
                except RuntimeError:
                    pass
                worker.requestInterruption()  # loop guards will see this
                _LIVE_WORKERS.add(worker)     # keep Python object alive past dialog GC
                worker.finished.connect(      # release once the OS thread has exited
                    lambda w=worker: _LIVE_WORKERS.discard(w)
                )

    # ------------------------------------------------------------------
    # Connect page logic
    # ------------------------------------------------------------------

    def _on_mode_toggled(self):
        self._remote_fields.setVisible(self._radio_remote.isChecked())

    def _save_connection_settings(self):
        if self._radio_local.isChecked():
            app_config.set_backend_mode(app_config.BACKEND_MODE_LOCAL)
            app_config.set_api_key(None)
            local_url = app_config.DEFAULT_LOCAL_URL
            self._api_client.base_url = local_url
            if hasattr(self._api_client, "_base"):
                self._api_client._base.base_url = local_url
                self._api_client._base.api_key = None
            self.settings_changed.emit()
        else:
            url = self._url_edit.text().strip().rstrip("/")
            key = self._key_edit.text().strip()
            if url:
                app_config.set_backend_mode(app_config.BACKEND_MODE_REMOTE)
                app_config.set_backend_url(url)
                app_config.set_api_key(key or None)
                self._api_client.base_url = url
                if hasattr(self._api_client, "_base"):
                    self._api_client._base.base_url = url
                    self._api_client._base.api_key = key or None
                self.settings_changed.emit()

    # ------------------------------------------------------------------
    # Verify page logic
    # ------------------------------------------------------------------

    def _start_verify(self):
        self._verify_ok = False
        self._next_btn.setEnabled(False)
        self._retry_btn.setVisible(False)
        self._verify_detail_lbl.setVisible(False)
        self._verify_status_lbl.setText("Connecting to server…")
        self._verify_icon_lbl.setPixmap(
            qta.icon("fa5s.circle-notch", color=Theme.TEXT_SECONDARY).pixmap(56, 56)
        )

        if self._verify_worker and self._verify_worker.isRunning():
            return

        self._verify_worker = _VerifyWorker(self._api_client)
        self._verify_worker.result.connect(self._on_verify_result)
        self._verify_worker.start()

    def _on_verify_result(self, success: bool, message: str, version: str):
        if success:
            self._verify_ok = True
            self._verify_icon_lbl.setPixmap(
                qta.icon("fa5s.check-circle", color=Theme.SUCCESS).pixmap(56, 56)
            )
            if message == "initializing":
                self._verify_status_lbl.setText(
                    "Server is warming up — this is normal right after starting."
                )
                self._verify_detail_lbl.setText(
                    "The server will be fully ready in a few seconds. "
                    "You can continue now."
                )
            else:
                self._verify_status_lbl.setText("Connected successfully!")
                ver_text = f"Server version: {version}" if version else ""
                self._verify_detail_lbl.setText(ver_text)

            self._verify_detail_lbl.setVisible(True)
            self._next_btn.setEnabled(True)
        else:
            self._verify_ok = False
            self._verify_icon_lbl.setPixmap(
                qta.icon("fa5s.times-circle", color=Theme.ERROR).pixmap(56, 56)
            )
            self._verify_status_lbl.setText("Could not connect to the server.")

            msg = message.lower()
            if "refused" in msg or "connect" in msg or "failed" in msg:
                if app_config.is_remote_mode():
                    hint = (
                        "Check that the server URL is correct and the server is running. "
                        "Go back to change the URL."
                    )
                else:
                    hint = (
                        "Make sure Docker Desktop is running, then click Try Again. "
                        "If Docker is running, click Try Again — "
                        "it may still be starting up."
                    )
            elif "timeout" in msg:
                hint = (
                    "Connection timed out. The server may be starting up. "
                    "Wait a moment and click Try Again."
                )
            elif "401" in msg or "auth" in msg or "key" in msg:
                hint = (
                    "Authentication failed. Go back and enter the correct API key."
                )
            else:
                hint = message[:160] if message else "Unknown error."

            self._verify_detail_lbl.setText(hint)
            self._verify_detail_lbl.setVisible(True)
            self._retry_btn.setVisible(True)

    # ------------------------------------------------------------------
    # License page logic
    # ------------------------------------------------------------------

    def _on_activate_license(self):
        key = self._license_edit.toPlainText().strip()
        if not key:
            self._show_license_result(
                "Please paste your license key above.", success=False
            )
            return

        self._activate_btn.setEnabled(False)
        self._activate_btn.setText("Activating…")
        self._license_result_lbl.setVisible(False)

        try:
            from desktop_app.utils.license_service import LicenseService, LicenseServiceError

            svc = LicenseService(api_client=self._api_client)
            svc.install_license(key)
            info = svc.get_current_license_info()
            edition = (
                getattr(info.edition, "value", str(info.edition))
                .replace("_", " ")
                .title()
            )
            self._show_license_result(
                f"✓  License activated — {edition} edition.", success=True
            )
        except Exception as exc:
            self._show_license_result(str(exc), success=False)
        finally:
            self._activate_btn.setEnabled(True)
            self._activate_btn.setText("Activate License")

    def _show_license_result(self, text: str, success: bool):
        color = Theme.SUCCESS if success else Theme.ERROR
        self._license_result_lbl.setText(text)
        self._license_result_lbl.setStyleSheet(
            f"color: {color}; font-size: 13px; padding: 8px; "
            f"background: {Theme.SURFACE}; border-radius: 6px; "
            f"border: 1px solid {color};"
        )
        self._license_result_lbl.setVisible(True)

    # ------------------------------------------------------------------
    # Index page logic
    # ------------------------------------------------------------------

    def _on_browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select a folder to index")
        if folder:
            self._folder_edit.setText(folder)

    def _on_start_index(self):
        if self._radio_samples.isChecked():
            files = self._collect_sample_files()
            if not files:
                self._index_status_lbl.setText(
                    "Sample documents not found in the installation. "
                    "Please choose a folder or skip this step."
                )
                return
        else:
            folder = self._folder_edit.text().strip()
            if not folder:
                self._index_status_lbl.setText(
                    "Please click Browse… and choose a folder first."
                )
                return
            supported = {".txt", ".md", ".pdf", ".docx", ".html", ".rst"}
            files = sorted(
                p
                for p in Path(folder).rglob("*")
                if p.is_file() and p.suffix.lower() in supported
            )[:20]  # cap wizard at 20 files
            if not files:
                self._index_status_lbl.setText(
                    "No supported files found in that folder "
                    "(.txt, .md, .pdf, .docx, .html). "
                    "Choose a different folder or use the bundled samples."
                )
                return

        self._index_btn.setEnabled(False)
        self._index_progress.setVisible(True)
        self._index_progress.setValue(0)
        self._index_status_lbl.setText(
            f"Indexing {len(files)} document(s) — please wait…"
        )

        self._index_worker = _IndexWorker(self._api_client, files)
        self._index_worker.progress.connect(self._on_index_progress)
        self._index_worker.finished.connect(self._on_index_finished)
        self._index_worker.start()

    def _on_index_progress(self, current: int, total: int, filename: str):
        pct = int(100 * (current + 1) / total) if total else 0
        self._index_progress.setValue(pct)
        self._index_status_lbl.setText(
            f"Indexing:  {filename}  ({current + 1} of {total})"
        )

    def _on_index_finished(self, indexed: int, failed: int):
        self._index_progress.setValue(100)
        self._index_btn.setEnabled(True)
        self._index_done = True
        self._next_btn.setEnabled(True)

        if failed == 0:
            self._index_status_lbl.setText(
                f"✓  {indexed} document(s) indexed successfully.  "
                f"Click Next to try a search."
            )
            self._index_status_lbl.setStyleSheet(
                f"font-size: 13px; color: {Theme.SUCCESS};"
            )
        else:
            self._index_status_lbl.setText(
                f"Done: {indexed} indexed, {failed} failed.  "
                f"You can still try a search, or skip to the next step."
            )
            self._index_status_lbl.setStyleSheet(
                f"font-size: 13px; color: {Theme.WARNING};"
            )

    @staticmethod
    def _collect_sample_files() -> list:
        if not SAMPLE_DATA_DIR.exists():
            return []
        return sorted(
            p
            for p in SAMPLE_DATA_DIR.iterdir()
            if p.is_file() and p.suffix in {".txt", ".md"}
        )

    # ------------------------------------------------------------------
    # Search page logic
    # ------------------------------------------------------------------

    def _on_run_search(self):
        query = self._query_edit.text().strip()
        if not query:
            return

        self._search_btn.setEnabled(False)
        self._search_btn.setText("Searching…")
        self._next_btn.setEnabled(False)  # prevent Finish while search in flight
        self._search_outcome_lbl.setText("")

        # Clear previous results (keep the stretch at the end)
        while self._results_layout.count() > 1:
            item = self._results_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._search_worker = _SearchWorker(self._api_client, query)
        self._search_worker.result.connect(self._on_search_result)
        self._search_worker.error.connect(self._on_search_error)
        self._search_worker.start()

    def _on_search_result(self, results: list):
        self._search_btn.setEnabled(True)
        self._search_btn.setText("Search")
        self._next_btn.setEnabled(True)

        if not results:
            self._search_outcome_lbl.setText(
                "No results yet — the server may still be indexing.\n"
                "Wait a few seconds and search again."
            )
            self._search_outcome_lbl.setStyleSheet(
                f"font-size: 13px; color: {Theme.TEXT_SECONDARY};"
            )
            return

        for r in results[:3]:
            self._results_layout.insertWidget(
                self._results_layout.count() - 1,  # before stretch
                self._make_result_card(r)
            )

        self._search_outcome_lbl.setText("🎉  It works!  You're ready to go.")
        self._search_outcome_lbl.setStyleSheet(
            f"font-size: 16px; font-weight: 700; color: {Theme.SUCCESS};"
        )

    def _on_search_error(self, error: str):
        self._search_btn.setEnabled(True)
        self._search_btn.setText("Search")
        self._next_btn.setEnabled(True)
        self._search_outcome_lbl.setText(
            f"Search failed: {error}\n"
            "Make sure the server is running and at least one document is indexed."
        )
        self._search_outcome_lbl.setStyleSheet(
            f"font-size: 13px; color: {Theme.ERROR};"
        )

    @staticmethod
    def _make_result_card(result: dict) -> QFrame:
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ background: {Theme.SURFACE}; "
            f"border: 1px solid {Theme.BORDER}; border-radius: 8px; padding: 10px; }}"
        )
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(4)
        card_layout.setContentsMargins(12, 10, 12, 10)

        source = result.get("source_uri") or result.get("document_id") or "—"
        title_text = Path(source).name if source and source != "—" else source
        title_lbl = QLabel(title_text)
        title_lbl.setStyleSheet(
            f"font-size: 13px; font-weight: 600; color: {Theme.TEXT_PRIMARY}; "
            f"border: none; background: transparent;"
        )
        card_layout.addWidget(title_lbl)

        snippet = (result.get("content") or result.get("text") or "")[:220]
        if snippet:
            snippet_lbl = QLabel(snippet + ("…" if len(snippet) >= 220 else ""))
            snippet_lbl.setWordWrap(True)
            snippet_lbl.setStyleSheet(
                f"font-size: 12px; color: {Theme.TEXT_SECONDARY}; "
                f"border: none; background: transparent;"
            )
            card_layout.addWidget(snippet_lbl)

        score = result.get("score") or result.get("similarity")
        if score is not None:
            score_lbl = QLabel(f"Relevance: {float(score):.0%}")
            score_lbl.setStyleSheet(
                f"font-size: 11px; color: {Theme.TEXT_SECONDARY}; "
                f"border: none; background: transparent;"
            )
            card_layout.addWidget(score_lbl)

        return card
