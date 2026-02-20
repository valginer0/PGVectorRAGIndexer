"""
First-run opt-in dialog for anonymous usage analytics.

Shown once when analytics_consent_shown is not yet set in config.
The user's choice is persisted and can be changed any time in Settings.
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
)
from PySide6.QtCore import Qt
import qtawesome as qta

from .styles.theme import Theme


class AnalyticsConsentDialog(QDialog):
    """One-time opt-in dialog for usage analytics."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Help Improve PGVectorRAGIndexer")
        self.setMinimumWidth(460)
        self.setModal(True)
        self._accepted = False
        self._build_ui()

    @property
    def user_accepted(self) -> bool:
        return self._accepted

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 20, 24, 20)

        # Icon + title
        title = QLabel("Help Improve PGVectorRAGIndexer")
        title.setStyleSheet("font-size: 16px; font-weight: 600;")
        layout.addWidget(title)

        # Explanation
        explanation = QLabel(
            "Share anonymous usage data to help us improve the app. "
            "We collect only event types (e.g. 'search completed'), "
            "counts, and your OS version.\n\n"
            "We never collect document content, file names, search "
            "queries, or any personally identifiable information.\n\n"
            "You can review exactly what is sent and turn this off "
            "at any time in Settings."
        )
        explanation.setWordWrap(True)
        explanation.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; line-height: 1.5;")
        layout.addWidget(explanation)

        # What we collect summary
        summary = QLabel(
            "<b>What we collect:</b><br>"
            "- Event types (app started, search completed, upload completed)<br>"
            "- Result counts and durations (no content)<br>"
            "- OS version and app version<br>"
            "- Anonymous install ID (random, not tied to you)"
        )
        summary.setWordWrap(True)
        summary.setStyleSheet(
            f"background-color: {Theme.SURFACE}; padding: 12px; "
            f"border-radius: 6px; color: {Theme.TEXT_SECONDARY};"
        )
        layout.addWidget(summary)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)

        no_btn = QPushButton("No Thanks")
        no_btn.setMinimumHeight(36)
        no_btn.clicked.connect(self._on_decline)
        btn_layout.addWidget(no_btn)

        btn_layout.addStretch()

        yes_btn = QPushButton("Yes, I'd Like to Help")
        yes_btn.setMinimumHeight(36)
        yes_btn.setProperty("class", "primary")
        yes_btn.setIcon(qta.icon("fa5s.chart-bar", color="white"))
        yes_btn.clicked.connect(self._on_accept)
        btn_layout.addWidget(yes_btn)

        layout.addLayout(btn_layout)

    def _on_accept(self):
        self._accepted = True
        self.accept()

    def _on_decline(self):
        self._accepted = False
        self.reject()
