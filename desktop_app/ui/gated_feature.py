"""
Gated feature placeholder widget.

Shows a locked-feature placeholder for Team-only features that are
not available in the current edition. Styled to be visible but
non-intrusive per V5 spec.

Usage:
    widget = GatedFeatureWidget(
        feature_name="Scheduled Indexing",
        description="Automatically re-index folders on a schedule.",
    )
"""

import logging

from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
)
from PySide6.QtCore import Qt
import qtawesome as qta

from desktop_app.ui.styles.theme import Theme

logger = logging.getLogger(__name__)

# Pricing page URL (same as edition.py, duplicated to avoid circular import)
_PRICING_URL = "https://ragvault.net/pricing"


class GatedFeatureWidget(QFrame):
    """Placeholder widget shown in place of a Team-only feature.

    Displays a lock icon, feature name, description, and a
    "Learn more" link to the pricing page.
    """

    def __init__(
        self,
        feature_name: str,
        description: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self.feature_name = feature_name
        self.description = description
        self._setup_ui()

    def _setup_ui(self):
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet(
            f"GatedFeatureWidget {{"
            f"  background-color: {Theme.SURFACE};"
            f"  border: 1px dashed {Theme.BORDER};"
            f"  border-radius: 8px;"
            f"  padding: 24px;"
            f"}}"
        )

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(12)

        # Lock icon + title row
        title_row = QHBoxLayout()
        title_row.setAlignment(Qt.AlignCenter)

        lock_icon = QLabel()
        lock_icon.setPixmap(
            qta.icon("fa5s.lock", color=Theme.TEXT_SECONDARY).pixmap(20, 20)
        )
        title_row.addWidget(lock_icon)

        title_label = QLabel(f"  {self.feature_name}")
        title_label.setStyleSheet(
            f"color: {Theme.TEXT_SECONDARY}; font-size: 15px; font-weight: 600;"
        )
        title_row.addWidget(title_label)

        layout.addLayout(title_row)

        # "Team feature" subtitle
        subtitle = QLabel("Team feature — requires a license")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet(
            f"color: {Theme.TEXT_SECONDARY}; font-size: 13px;"
        )
        layout.addWidget(subtitle)

        # Description (if provided)
        if self.description:
            desc_label = QLabel(self.description)
            desc_label.setAlignment(Qt.AlignCenter)
            desc_label.setWordWrap(True)
            desc_label.setStyleSheet(
                f"color: {Theme.TEXT_SECONDARY}; font-size: 12px;"
            )
            layout.addWidget(desc_label)

        # "Learn more" link button
        learn_more = QPushButton("Learn more →")
        learn_more.setFlat(True)
        learn_more.setCursor(Qt.PointingHandCursor)
        learn_more.setStyleSheet(
            f"color: {Theme.PRIMARY}; font-size: 13px; "
            f"text-decoration: underline; border: none; padding: 4px;"
        )
        learn_more.clicked.connect(self._open_pricing)
        layout.addWidget(learn_more, alignment=Qt.AlignCenter)

    def _open_pricing(self):
        import webbrowser
        webbrowser.open(_PRICING_URL)
