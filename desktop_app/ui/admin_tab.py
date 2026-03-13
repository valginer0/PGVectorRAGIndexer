"""
Organization console tab — server-side governance visibility.

Shows Users & Roles, Permissions, Retention, Server Activity, and
an Overview of server identity/capabilities. Always added to the tab
bar; adapts content based on server probing + local license state.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QLabel,
    QFrame,
    QTabWidget,
    QComboBox,
    QFileDialog,
    QMessageBox,
    QStackedWidget,
    QSizePolicy,
    QLineEdit,
    QSpinBox,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QMenu,
    QApplication,
)
import qtawesome as qta

from desktop_app.utils.api_client import APIClient, CapabilityStatus
from desktop_app.utils.server_capabilities import ServerCapabilities
from desktop_app.utils.errors import APIError, APIConnectionError, APIAuthenticationError
from desktop_app.ui.styles.theme import Theme

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _status_color(status: CapabilityStatus) -> str:
    return {
        CapabilityStatus.AVAILABLE: Theme.SUCCESS,
        CapabilityStatus.UNAUTHORIZED: Theme.WARNING,
        CapabilityStatus.NOT_SUPPORTED: Theme.TEXT_SECONDARY,
        CapabilityStatus.UNREACHABLE: Theme.ERROR,
        CapabilityStatus.UNKNOWN: Theme.TEXT_SECONDARY,
    }.get(status, Theme.TEXT_SECONDARY)


def _status_label(status: CapabilityStatus) -> str:
    return {
        CapabilityStatus.AVAILABLE: "Available",
        CapabilityStatus.UNAUTHORIZED: "Unauthorized",
        CapabilityStatus.NOT_SUPPORTED: "Not supported",
        CapabilityStatus.UNREACHABLE: "Unreachable",
        CapabilityStatus.UNKNOWN: "Unknown",
    }.get(status, "Unknown")


def _format_timestamp(ts_str: Optional[str]) -> str:
    if not ts_str:
        return "—"
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, AttributeError):
        return ts_str


class _MessagePanel(QFrame):
    """Inline message with optional retry button — replaces popup dialogs."""

    def __init__(self, text: str, icon: str = "info", retry_callback=None, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        color = {
            "info": Theme.TEXT_SECONDARY,
            "warning": Theme.WARNING,
            "error": Theme.ERROR,
        }.get(icon, Theme.TEXT_SECONDARY)
        self.setStyleSheet(
            f"QFrame {{ background: {Theme.SURFACE}; border: 1px solid {Theme.BORDER}; "
            f"border-radius: 8px; padding: 16px; }}"
        )
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        label = QLabel(text)
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet(f"color: {color}; font-size: 14px;")
        layout.addWidget(label)
        if retry_callback:
            btn = QPushButton("Retry")
            btn.setFixedWidth(100)
            btn.clicked.connect(retry_callback)
            layout.addWidget(btn, alignment=Qt.AlignCenter)


# ---------------------------------------------------------------------------
# Sub-panels
# ---------------------------------------------------------------------------

class _OverviewPanel(QWidget):
    """Overview sub-tab: server version, edition, identity, capabilities."""

    def __init__(self, api_client: APIClient, capabilities: ServerCapabilities, parent=None):
        super().__init__(parent)
        self.api_client = api_client
        self._caps = capabilities
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(20, 20, 20, 20)

        # Info form
        self._form = QFormLayout()
        self._form.setSpacing(8)
        self._server_ver = QLabel("—")
        self._api_url = QLabel("—")
        self._edition = QLabel("—")
        self._identity = QLabel("—")
        self._auth_mode = QLabel("—")
        for lbl in (self._server_ver, self._api_url, self._edition, self._identity, self._auth_mode):
            lbl.setStyleSheet(f"color: {Theme.TEXT_PRIMARY}; font-size: 13px;")
        self._form.addRow(QLabel("Server Version:"), self._server_ver)
        self._form.addRow(QLabel("API URL:"), self._api_url)
        self._form.addRow(QLabel("Edition:"), self._edition)
        self._form.addRow(QLabel("Current User:"), self._identity)
        self._form.addRow(QLabel("Auth Mode:"), self._auth_mode)
        layout.addLayout(self._form)

        # Capability status table
        cap_label = QLabel("Server Capabilities")
        cap_label.setStyleSheet(f"color: {Theme.TEXT_PRIMARY}; font-size: 14px; font-weight: bold;")
        layout.addWidget(cap_label)

        self._cap_table = QTableWidget()
        self._cap_table.setColumnCount(2)
        self._cap_table.setHorizontalHeaderLabels(["Capability", "Status"])
        self._cap_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._cap_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._cap_table.verticalHeader().setVisible(False)
        self._cap_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._cap_table.setSelectionMode(QTableWidget.NoSelection)
        self._cap_table.setMaximumHeight(280)
        layout.addWidget(self._cap_table)

        # Compliance export button (admin only)
        self._export_row = QHBoxLayout()
        self._export_compliance_btn = QPushButton("Export Compliance Report")
        self._export_compliance_btn.clicked.connect(self._on_export_compliance)
        self._export_row.addWidget(self._export_compliance_btn)
        self._export_row.addStretch()
        self._export_widget = QWidget()
        self._export_widget.setLayout(self._export_row)
        layout.addWidget(self._export_widget)

        # CLI tips — features also available from the command line
        cli_frame = QFrame()
        cli_frame.setFrameShape(QFrame.StyledPanel)
        cli_frame.setStyleSheet(
            f"QFrame {{ background: {Theme.SURFACE}; border: 1px solid {Theme.BORDER}; "
            f"border-radius: 6px; padding: 12px; }}"
        )
        cli_layout = QVBoxLayout(cli_frame)
        cli_layout.setSpacing(4)
        cli_title = QLabel("CLI Tools")
        cli_title.setStyleSheet(f"color: {Theme.TEXT_PRIMARY}; font-size: 13px; font-weight: bold; border: none;")
        cli_layout.addWidget(cli_title)
        cli_hints = [
            ("API key management", "python pgvector_admin.py create-key | list-keys | revoke-key | rotate-key"),
            ("Bulk reindex", "python scripts/reindex_all.py [--dry-run] [--batch-size N]"),
            ("Index documents", "python indexer_v2.py --path <file-or-dir>"),
            ("Search from terminal", "python retriever_v2.py --query 'your query'"),
        ]
        for label, cmd in cli_hints:
            row = QHBoxLayout()
            name_lbl = QLabel(f"{label}:")
            name_lbl.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-size: 12px; border: none;")
            name_lbl.setFixedWidth(140)
            cmd_lbl = QLabel(cmd)
            cmd_lbl.setStyleSheet(
                f"color: {Theme.TEXT_PRIMARY}; font-size: 11px; font-family: monospace; border: none;"
            )
            cmd_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            row.addWidget(name_lbl)
            row.addWidget(cmd_lbl, 1)
            cli_layout.addLayout(row)
        cli_note = QLabel("Run from the project root directory. See docs/USAGE_GUIDE.md for details.")
        cli_note.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-size: 11px; font-style: italic; border: none;")
        cli_layout.addWidget(cli_note)
        layout.addWidget(cli_frame)

        layout.addStretch()

    def _on_export_compliance(self):
        try:
            data = self.api_client.export_compliance_report()
            path, _ = QFileDialog.getSaveFileName(
                self, "Save Compliance Report", "compliance_report.zip", "ZIP Files (*.zip)"
            )
            if path:
                with open(path, "wb") as f:
                    f.write(data)
                QMessageBox.information(self, "Export Complete", f"Report saved to {path}")
        except APIAuthenticationError:
            QMessageBox.warning(self, "Permission Denied", "Admin permission required to export compliance report.")
        except APIError as e:
            QMessageBox.warning(self, "Export Failed", f"Failed to export report: {e}")

    def refresh(self):
        self._export_widget.setVisible(self._caps.is_admin())
        self._api_url.setText(self.api_client.base_url or "—")

        # Server version
        ver = getattr(self.api_client, '_server_version', None)
        if not ver:
            ver = getattr(self.api_client._system, '_server_version', None)
        self._server_ver.setText(ver or "—")

        # Edition
        try:
            from desktop_app.utils.edition import get_edition_display
            from desktop_app.utils.app_config import is_remote_mode
            if is_remote_mode():
                try:
                    license_data = self.api_client.get_license_info()
                    dto = get_edition_display(data=license_data)
                except Exception:
                    dto = get_edition_display()
            else:
                dto = get_edition_display()
            self._edition.setText(dto.edition_label)
        except Exception:
            self._edition.setText("Unknown")

        # Identity from /me
        identity = self._caps.get_identity()
        if identity:
            user = identity.get("user")
            if user:
                self._identity.setText(f"{user.get('display_name') or user.get('email', '—')} ({user.get('role', '—')})")
            else:
                role = identity.get("role", "—")
                self._identity.setText(f"No linked user (effective: {role})")
            self._auth_mode.setText(identity.get("auth_mode", "—"))
        else:
            self._identity.setText("—")
            self._auth_mode.setText("—")

        # Capabilities table
        from desktop_app.utils.server_capabilities import _PROBES
        cap_names = [k for k in _PROBES if k != "me"]
        self._cap_table.setRowCount(len(cap_names))
        for i, name in enumerate(cap_names):
            status = self._caps.get(name)
            name_item = QTableWidgetItem(name.replace("_", " ").title())
            name_item.setFlags(Qt.ItemIsEnabled)
            self._cap_table.setItem(i, 0, name_item)

            status_item = QTableWidgetItem(_status_label(status))
            status_item.setForeground(QColor(_status_color(status)))
            status_item.setFlags(Qt.ItemIsEnabled)
            self._cap_table.setItem(i, 1, status_item)


class _UsersRolesPanel(QWidget):
    """Users & Roles sub-tab."""

    def __init__(self, api_client: APIClient, capabilities: ServerCapabilities, parent=None):
        super().__init__(parent)
        self.api_client = api_client
        self._caps = capabilities
        self._setup_ui()

    def _setup_ui(self):
        self._stack = QStackedWidget()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._stack)

        # Page 0: message placeholder
        self._msg_page = QWidget()
        msg_layout = QVBoxLayout(self._msg_page)
        self._msg_label = _MessagePanel("Loading...", parent=self._msg_page)
        msg_layout.addWidget(self._msg_label)
        self._stack.addWidget(self._msg_page)

        # Page 1: content
        self._content = QWidget()
        content_layout = QVBoxLayout(self._content)
        content_layout.setSpacing(16)
        content_layout.setContentsMargins(20, 20, 20, 20)

        # Users section
        users_label = QLabel("Users")
        users_label.setStyleSheet(f"color: {Theme.TEXT_PRIMARY}; font-size: 14px; font-weight: bold;")
        content_layout.addWidget(users_label)

        self._users_table = QTableWidget()
        self._users_table.setColumnCount(6)
        self._users_table.setHorizontalHeaderLabels(["Email", "Name", "Role", "Active", "Last Login", "Auth Provider"])
        self._users_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for col in range(1, 6):
            self._users_table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeToContents)
        self._users_table.verticalHeader().setVisible(False)
        self._users_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._users_table.setSelectionBehavior(QTableWidget.SelectRows)
        self._users_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        content_layout.addWidget(self._users_table, stretch=3)

        # Admin actions row (hidden for non-admins)
        self._admin_row = QHBoxLayout()
        self._add_user_btn = QPushButton("Add User")
        self._add_user_btn.clicked.connect(self._on_add_user)
        self._admin_row.addWidget(self._add_user_btn)

        self._role_combo = QComboBox()
        self._role_combo.setMinimumWidth(120)
        self._change_role_btn = QPushButton("Change Role")
        self._change_role_btn.clicked.connect(self._on_change_role)
        self._admin_row.addWidget(QLabel("Assign role:"))
        self._admin_row.addWidget(self._role_combo)
        self._admin_row.addWidget(self._change_role_btn)
        self._admin_row.addStretch()
        self._admin_widget = QWidget()
        self._admin_widget.setLayout(self._admin_row)
        content_layout.addWidget(self._admin_widget)

        # Context menu on users table
        self._users_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self._users_table.customContextMenuRequested.connect(self._on_users_context_menu)

        # Roles section
        roles_label = QLabel("Roles")
        roles_label.setStyleSheet(f"color: {Theme.TEXT_PRIMARY}; font-size: 14px; font-weight: bold;")
        content_layout.addWidget(roles_label)

        self._roles_table = QTableWidget()
        self._roles_table.setColumnCount(3)
        self._roles_table.setHorizontalHeaderLabels(["Role", "Description", "Permissions"])
        self._roles_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self._roles_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self._roles_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._roles_table.verticalHeader().setVisible(False)
        self._roles_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._roles_table.setSelectionBehavior(QTableWidget.SelectRows)
        self._roles_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        content_layout.addWidget(self._roles_table, stretch=2)

        # Role detail
        self._role_detail = QLabel("")
        self._role_detail.setWordWrap(True)
        self._role_detail.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-size: 12px; padding: 8px;")
        content_layout.addWidget(self._role_detail)
        self._roles_table.currentCellChanged.connect(self._on_role_selected)

        self._stack.addWidget(self._content)

    def refresh(self):
        users_ok = self._caps.is_available("users")
        roles_ok = self._caps.is_available("roles")
        if not users_ok and not roles_ok:
            status = self._caps.get("users")
            if status == CapabilityStatus.NOT_SUPPORTED:
                self._show_message("Users/Roles not available on this server version.", "info")
            elif status == CapabilityStatus.UNAUTHORIZED:
                self._show_message("API key required or insufficient permissions.", "warning")
            elif status == CapabilityStatus.UNREACHABLE:
                self._show_message("Server unreachable.", "error", retry=self.refresh)
            else:
                self._show_message("Users/Roles not available.", "info")
            return

        self._stack.setCurrentWidget(self._content)
        self._admin_widget.setVisible(self._caps.is_admin())

        # Load users
        try:
            data = self.api_client.list_users(active_only=False)
            users = data.get("users", [])
            self._users_table.setRowCount(len(users))
            for i, u in enumerate(users):
                self._users_table.setItem(i, 0, QTableWidgetItem(u.get("email", "—")))
                self._users_table.setItem(i, 1, QTableWidgetItem(u.get("display_name", "—")))
                self._users_table.setItem(i, 2, QTableWidgetItem(u.get("role", "—")))
                active = "Yes" if u.get("is_active", True) else "No"
                active_item = QTableWidgetItem(active)
                active_item.setForeground(QColor(Theme.SUCCESS if active == "Yes" else Theme.ERROR))
                self._users_table.setItem(i, 3, active_item)
                self._users_table.setItem(i, 4, QTableWidgetItem(_format_timestamp(u.get("last_login_at"))))
                self._users_table.setItem(i, 5, QTableWidgetItem(u.get("auth_provider", "—")))
                # Store user_id in first column's data
                self._users_table.item(i, 0).setData(Qt.UserRole, u.get("id"))
        except APIConnectionError:
            self._show_message("Server unreachable.", "error", retry=self.refresh)
            return
        except APIAuthenticationError:
            self._show_message("Insufficient permissions to list users.", "warning")
            return
        except APIError as e:
            self._show_message(f"Error loading users: {e}", "error", retry=self.refresh)
            return

        # Load roles
        try:
            data = self.api_client.list_roles()
            roles = data.get("roles", [])
            self._roles_table.setRowCount(len(roles))
            self._role_combo.clear()
            for i, r in enumerate(roles):
                name = r.get("name", "—")
                self._roles_table.setItem(i, 0, QTableWidgetItem(name))
                self._roles_table.setItem(i, 1, QTableWidgetItem(r.get("description", "—")))
                perms = r.get("permissions", [])
                self._roles_table.setItem(i, 2, QTableWidgetItem(str(len(perms))))
                # Store permissions in data role
                self._roles_table.item(i, 0).setData(Qt.UserRole, perms)
                self._role_combo.addItem(name)
        except Exception as e:
            logger.warning("Failed to load roles: %s", e)

    def _show_message(self, text, icon="info", retry=None):
        # Replace message page content
        old = self._msg_page.layout().itemAt(0)
        if old and old.widget():
            old.widget().deleteLater()
        self._msg_label = _MessagePanel(text, icon=icon, retry_callback=retry, parent=self._msg_page)
        self._msg_page.layout().addWidget(self._msg_label)
        self._stack.setCurrentWidget(self._msg_page)

    def _on_role_selected(self, row, col, prev_row, prev_col):
        if row < 0:
            self._role_detail.setText("")
            return
        item = self._roles_table.item(row, 0)
        if not item:
            return
        perms = item.data(Qt.UserRole)
        if perms:
            self._role_detail.setText(f"Permissions: {', '.join(perms)}")
        else:
            self._role_detail.setText("No permissions")

    def _on_change_role(self):
        row = self._users_table.currentRow()
        if row < 0:
            self._show_message("Select a user first.", icon="info")
            return
        user_id = self._users_table.item(row, 0).data(Qt.UserRole)
        email = self._users_table.item(row, 0).text()
        new_role = self._role_combo.currentText()
        if not new_role:
            return

        reply = QMessageBox.question(
            self, "Confirm Role Change",
            f"Change {email}'s role to '{new_role}'?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        try:
            self.api_client.change_user_role(user_id, new_role)
            self.refresh()
        except APIAuthenticationError:
            self._show_message("Admin permission required to change roles.", icon="warning")
        except APIError as e:
            self._show_message(f"Failed to change role: {e}", icon="error", retry=self.refresh)

    def _on_add_user(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Add User")
        dialog.setMinimumWidth(350)
        form = QFormLayout(dialog)

        email_edit = QLineEdit()
        email_edit.setPlaceholderText("user@example.com")
        form.addRow("Email:", email_edit)

        name_edit = QLineEdit()
        name_edit.setPlaceholderText("Display Name")
        form.addRow("Display Name:", name_edit)

        role_combo = QComboBox()
        for i in range(self._role_combo.count()):
            role_combo.addItem(self._role_combo.itemText(i))
        if role_combo.count() > 0:
            # Default to 'user' if available
            idx = role_combo.findText("user")
            if idx >= 0:
                role_combo.setCurrentIndex(idx)
        form.addRow("Role:", role_combo)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)

        if dialog.exec() != QDialog.Accepted:
            return
        email = email_edit.text().strip()
        name = name_edit.text().strip()
        role = role_combo.currentText()
        if not email:
            QMessageBox.warning(self, "Validation", "Email is required.")
            return
        try:
            self.api_client.create_user(email=email, display_name=name or None, role=role)
            self.refresh()
        except APIAuthenticationError:
            self._show_message("Admin permission required.", icon="warning")
        except APIError as e:
            self._show_message(f"Failed to create user: {e}", icon="error")

    def _on_users_context_menu(self, pos):
        if not self._caps.is_admin():
            return
        row = self._users_table.rowAt(pos.y())
        if row < 0:
            return
        user_id = self._users_table.item(row, 0).data(Qt.UserRole)
        email = self._users_table.item(row, 0).text()
        is_active = self._users_table.item(row, 3).text() == "Yes"

        menu = QMenu(self)
        if is_active:
            deactivate_action = menu.addAction("Deactivate User")
        else:
            activate_action = menu.addAction("Activate User")
        menu.addSeparator()
        delete_action = menu.addAction("Delete User")

        chosen = menu.exec(self._users_table.viewport().mapToGlobal(pos))
        if chosen is None:
            return

        if is_active and chosen.text() == "Deactivate User":
            self._toggle_user_active(user_id, email, False)
        elif not is_active and chosen.text() == "Activate User":
            self._toggle_user_active(user_id, email, True)
        elif chosen.text() == "Delete User":
            self._delete_user(user_id, email)

    def _toggle_user_active(self, user_id, email, activate):
        action = "activate" if activate else "deactivate"
        reply = QMessageBox.question(
            self, f"Confirm {action.title()}",
            f"Are you sure you want to {action} {email}?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        try:
            self.api_client.update_user(user_id, is_active=activate)
            self.refresh()
        except APIAuthenticationError:
            self._show_message("Admin permission required.", icon="warning")
        except APIError as e:
            self._show_message(f"Failed to {action} user: {e}", icon="error")

    def _delete_user(self, user_id, email):
        reply = QMessageBox.warning(
            self, "Confirm Delete",
            f"Permanently delete user {email}?\n\nThis action cannot be undone.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        try:
            self.api_client.delete_user(user_id)
            self.refresh()
        except APIAuthenticationError:
            self._show_message("Admin permission required.", icon="warning")
        except APIError as e:
            self._show_message(f"Failed to delete user: {e}", icon="error")


class _PermissionsPanel(QWidget):
    """Permissions Reference sub-tab."""

    def __init__(self, api_client: APIClient, capabilities: ServerCapabilities, parent=None):
        super().__init__(parent)
        self.api_client = api_client
        self._caps = capabilities
        self._setup_ui()

    def _setup_ui(self):
        self._stack = QStackedWidget()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._stack)

        self._msg_page = QWidget()
        QVBoxLayout(self._msg_page)
        self._stack.addWidget(self._msg_page)

        self._content = QWidget()
        content_layout = QVBoxLayout(self._content)
        content_layout.setContentsMargins(20, 20, 20, 20)

        self._table = QTableWidget()
        self._table.setColumnCount(3)
        self._table.setHorizontalHeaderLabels(["Permission", "Description", "Category"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionMode(QTableWidget.NoSelection)
        content_layout.addWidget(self._table)

        self._stack.addWidget(self._content)

    def _show_message(self, text, icon="info", retry=None):
        old = self._msg_page.layout().itemAt(0)
        if old and old.widget():
            old.widget().deleteLater()
        panel = _MessagePanel(text, icon=icon, retry_callback=retry, parent=self._msg_page)
        self._msg_page.layout().addWidget(panel)
        self._stack.setCurrentWidget(self._msg_page)

    def refresh(self):
        status = self._caps.get("permissions")
        if status == CapabilityStatus.NOT_SUPPORTED:
            self._show_message("Permissions not available on this server version.", "info")
            return
        if status == CapabilityStatus.UNAUTHORIZED:
            self._show_message("API key required or insufficient permissions.", "warning")
            return
        if status == CapabilityStatus.UNREACHABLE:
            self._show_message("Server unreachable.", "error", retry=self.refresh)
            return
        if not self._caps.is_available("permissions"):
            return
        try:
            data = self.api_client.list_permissions()
            perms = data.get("permissions", [])
            # Server returns {"permission": ..., "description": ...}.
            # Derive category from the permission name (e.g. "documents.read" → "documents").
            for p in perms:
                if "category" not in p and "permission" in p:
                    parts = p["permission"].rsplit(".", 1)
                    p["category"] = parts[0] if len(parts) > 1 else ""
            perms.sort(key=lambda p: (p.get("category", ""), p.get("permission", "")))
            self._table.setRowCount(len(perms))
            for i, p in enumerate(perms):
                self._table.setItem(i, 0, QTableWidgetItem(p.get("permission", p.get("id", "—"))))
                self._table.setItem(i, 1, QTableWidgetItem(p.get("description", "—")))
                self._table.setItem(i, 2, QTableWidgetItem(p.get("category", "—")))
            self._stack.setCurrentWidget(self._content)
        except APIConnectionError:
            self._show_message("Server unreachable.", "error", retry=self.refresh)
        except APIAuthenticationError:
            self._show_message("Insufficient permissions.", "warning")
        except APIError as e:
            self._show_message(f"Error loading permissions: {e}", "error", retry=self.refresh)


class _RetentionPanel(QWidget):
    """Retention status sub-tab (read-only)."""

    def __init__(self, api_client: APIClient, capabilities: ServerCapabilities, parent=None):
        super().__init__(parent)
        self.api_client = api_client
        self._caps = capabilities
        self._setup_ui()

    def _setup_ui(self):
        self._stack = QStackedWidget()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._stack)

        self._msg_page = QWidget()
        QVBoxLayout(self._msg_page)
        self._stack.addWidget(self._msg_page)

        self._content = QWidget()
        content_layout = QVBoxLayout(self._content)
        content_layout.setSpacing(16)
        content_layout.setContentsMargins(20, 20, 20, 20)

        # Policy
        policy_label = QLabel("Retention Policy")
        policy_label.setStyleSheet(f"color: {Theme.TEXT_PRIMARY}; font-size: 14px; font-weight: bold;")
        content_layout.addWidget(policy_label)

        self._policy_form = QFormLayout()
        self._activity_days = QLabel("—")
        self._runs_days = QLabel("—")
        self._quarantine_days = QLabel("—")
        self._saml_cleanup = QLabel("—")
        for lbl in (self._activity_days, self._runs_days, self._quarantine_days, self._saml_cleanup):
            lbl.setStyleSheet(f"color: {Theme.TEXT_PRIMARY}; font-size: 13px;")
        self._policy_form.addRow("Activity Log:", self._activity_days)
        self._policy_form.addRow("Indexing Runs:", self._runs_days)
        self._policy_form.addRow("Quarantine:", self._quarantine_days)
        self._policy_form.addRow("SAML Sessions:", self._saml_cleanup)
        content_layout.addLayout(self._policy_form)

        # Status
        status_label = QLabel("Execution Status")
        status_label.setStyleSheet(f"color: {Theme.TEXT_PRIMARY}; font-size: 14px; font-weight: bold;")
        content_layout.addWidget(status_label)

        self._status_form = QFormLayout()
        self._ret_enabled = QLabel("—")
        self._last_run = QLabel("—")
        self._next_run = QLabel("—")
        self._run_status = QLabel("—")
        for lbl in (self._ret_enabled, self._last_run, self._next_run, self._run_status):
            lbl.setStyleSheet(f"color: {Theme.TEXT_PRIMARY}; font-size: 13px;")
        self._status_form.addRow("Enabled:", self._ret_enabled)
        self._status_form.addRow("Last Run:", self._last_run)
        self._status_form.addRow("Next Run:", self._next_run)
        self._status_form.addRow("Status:", self._run_status)
        content_layout.addLayout(self._status_form)

        # Admin: Run Now controls
        self._run_section = QWidget()
        run_layout = QVBoxLayout(self._run_section)
        run_layout.setContentsMargins(0, 8, 0, 0)
        run_label = QLabel("Manual Cleanup")
        run_label.setStyleSheet(f"color: {Theme.TEXT_PRIMARY}; font-size: 14px; font-weight: bold;")
        run_layout.addWidget(run_label)

        run_form = QFormLayout()
        self._run_activity = QSpinBox()
        self._run_activity.setRange(0, 9999)
        self._run_activity.setSuffix(" days")
        self._run_activity.setSpecialValueText("Use default")
        run_form.addRow("Activity Log:", self._run_activity)

        self._run_quarantine = QSpinBox()
        self._run_quarantine.setRange(0, 9999)
        self._run_quarantine.setSuffix(" days")
        self._run_quarantine.setSpecialValueText("Use default")
        run_form.addRow("Quarantine:", self._run_quarantine)

        self._run_indexing = QSpinBox()
        self._run_indexing.setRange(0, 9999)
        self._run_indexing.setSuffix(" days")
        self._run_indexing.setSpecialValueText("Use default")
        run_form.addRow("Indexing Runs:", self._run_indexing)

        self._run_saml = QCheckBox("Clean up SAML sessions")
        self._run_saml.setChecked(True)
        run_form.addRow(self._run_saml)
        run_layout.addLayout(run_form)

        run_btn_row = QHBoxLayout()
        self._run_now_btn = QPushButton("Run Now")
        self._run_now_btn.clicked.connect(self._on_run_retention)
        run_btn_row.addWidget(self._run_now_btn)
        run_btn_row.addStretch()
        run_layout.addLayout(run_btn_row)

        content_layout.addWidget(self._run_section)
        content_layout.addStretch()

        self._stack.addWidget(self._content)

    def _show_message(self, text, icon="info", retry=None):
        old = self._msg_page.layout().itemAt(0)
        if old and old.widget():
            old.widget().deleteLater()
        panel = _MessagePanel(text, icon=icon, retry_callback=retry, parent=self._msg_page)
        self._msg_page.layout().addWidget(panel)
        self._stack.setCurrentWidget(self._msg_page)

    def _on_run_retention(self):
        kwargs = {"cleanup_saml_sessions": self._run_saml.isChecked()}
        if self._run_activity.value() > 0:
            kwargs["activity_days"] = self._run_activity.value()
        if self._run_quarantine.value() > 0:
            kwargs["quarantine_days"] = self._run_quarantine.value()
        if self._run_indexing.value() > 0:
            kwargs["indexing_runs_days"] = self._run_indexing.value()

        reply = QMessageBox.question(
            self, "Confirm Retention Run",
            "Run retention cleanup now with the specified parameters?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        try:
            result = self.api_client.run_retention(**kwargs)
            removed = result.get("removed", {})
            summary = ", ".join(f"{k}: {v}" for k, v in removed.items()) if removed else "No records removed"
            self._show_message(f"Retention run complete. {summary}", icon="info")
            QTimer.singleShot(2000, self.refresh)
        except APIAuthenticationError:
            self._show_message("Insufficient permissions to run retention.", icon="warning")
        except APIError as e:
            self._show_message(f"Retention run failed: {e}", icon="error")

    def refresh(self):
        status = self._caps.get("retention")
        if status == CapabilityStatus.NOT_SUPPORTED:
            self._show_message("Retention not available on this server version.", "info")
            return
        if status == CapabilityStatus.UNAUTHORIZED:
            self._show_message("API key required or insufficient permissions.", "warning")
            return
        if status == CapabilityStatus.UNREACHABLE:
            self._show_message("Server unreachable.", "error", retry=self.refresh)
            return
        if not self._caps.is_available("retention"):
            return

        self._stack.setCurrentWidget(self._content)
        # Matches backend: POST /retention/run requires Team edition + API key,
        # not admin. Any authenticated Team user may trigger manual cleanup.
        # If this should be restricted further, tighten the backend too.
        self._run_section.setVisible(self._caps.is_available("retention"))

        try:
            data = self.api_client.get_retention_policy()
            policy = data.get("policy", data)
            self._activity_days.setText(f"{policy.get('activity_days', '—')} days")
            self._runs_days.setText(f"{policy.get('indexing_runs_days', '—')} days")
            self._quarantine_days.setText(f"{policy.get('quarantine_days', '—')} days")
            self._saml_cleanup.setText("Yes" if policy.get("cleanup_saml_sessions") else "No")
        except APIConnectionError:
            self._show_message("Server unreachable.", "error", retry=self.refresh)
            return
        except APIAuthenticationError:
            self._show_message("Insufficient permissions.", "warning")
            return
        except APIError as e:
            self._show_message(f"Error loading retention policy: {e}", "error", retry=self.refresh)
            return

        try:
            data = self.api_client.get_retention_status()
            self._ret_enabled.setText("Yes" if data.get("enabled") else "No")
            self._last_run.setText(_format_timestamp(data.get("last_run_at")))
            self._next_run.setText(_format_timestamp(data.get("next_run_at")))
            self._run_status.setText(data.get("status", "—"))
        except APIConnectionError:
            self._show_message("Server unreachable.", "error", retry=self.refresh)
        except APIAuthenticationError:
            self._show_message("Insufficient permissions.", "warning")
        except APIError as e:
            self._show_message(f"Error loading retention status: {e}", "error", retry=self.refresh)


class _ActivityPanel(QWidget):
    """Server Activity sub-tab (audit log, not local file opens)."""

    def __init__(self, api_client: APIClient, capabilities: ServerCapabilities, parent=None):
        super().__init__(parent)
        self.api_client = api_client
        self._caps = capabilities
        self._offset = 0
        self._setup_ui()

    def _setup_ui(self):
        self._stack = QStackedWidget()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._stack)

        self._msg_page = QWidget()
        QVBoxLayout(self._msg_page)
        self._stack.addWidget(self._msg_page)

        self._content = QWidget()
        content_layout = QVBoxLayout(self._content)
        content_layout.setSpacing(12)
        content_layout.setContentsMargins(20, 20, 20, 20)

        # Filters
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Action:"))
        self._action_filter = QComboBox()
        self._action_filter.addItem("All")
        self._action_filter.setMinimumWidth(150)
        filter_row.addWidget(self._action_filter)
        filter_row.addStretch()

        self._export_btn = QPushButton("Export CSV")
        self._export_btn.clicked.connect(self._on_export)
        filter_row.addWidget(self._export_btn)

        self._filter_btn = QPushButton("Apply")
        self._filter_btn.clicked.connect(self._apply_filter)
        filter_row.addWidget(self._filter_btn)
        content_layout.addLayout(filter_row)

        # Table
        self._table = QTableWidget()
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels(["Timestamp", "Action", "Client ID", "User ID", "Details"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        content_layout.addWidget(self._table)

        # Load more
        self._load_more_btn = QPushButton("Load More")
        self._load_more_btn.clicked.connect(self._load_more)
        content_layout.addWidget(self._load_more_btn, alignment=Qt.AlignCenter)

        self._stack.addWidget(self._content)

    def _show_message(self, text, icon="info", retry=None):
        old = self._msg_page.layout().itemAt(0)
        if old and old.widget():
            old.widget().deleteLater()
        panel = _MessagePanel(text, icon=icon, retry_callback=retry, parent=self._msg_page)
        self._msg_page.layout().addWidget(panel)
        self._stack.setCurrentWidget(self._msg_page)

    def refresh(self):
        status = self._caps.get("activity")
        if status == CapabilityStatus.NOT_SUPPORTED:
            self._show_message("Activity log not available on this server version.", "info")
            return
        if status == CapabilityStatus.UNAUTHORIZED:
            self._show_message("API key required or insufficient permissions.", "warning")
            return
        if status == CapabilityStatus.UNREACHABLE:
            self._show_message("Server unreachable.", "error", retry=self.refresh)
            return
        if not self._caps.is_available("activity"):
            return
        self._stack.setCurrentWidget(self._content)
        self._offset = 0
        self._table.setRowCount(0)

        # Load action types for filter
        try:
            data = self.api_client.get_activity_action_types()
            actions = data.get("actions", [])
            self._action_filter.clear()
            self._action_filter.addItem("All")
            for a in sorted(actions):
                self._action_filter.addItem(a)
        except Exception:
            pass

        self._load_entries()

    def _load_entries(self, append=False):
        action = self._action_filter.currentText()
        action_param = action if action != "All" else None
        try:
            data = self.api_client.get_activity_log(
                limit=100, offset=self._offset, action=action_param
            )
            entries = data.get("entries", [])
            start = self._table.rowCount() if append else 0
            if not append:
                self._table.setRowCount(0)
            self._table.setRowCount(start + len(entries))
            for i, e in enumerate(entries):
                row = start + i
                self._table.setItem(row, 0, QTableWidgetItem(_format_timestamp(e.get("ts"))))
                self._table.setItem(row, 1, QTableWidgetItem(e.get("action", "—")))
                self._table.setItem(row, 2, QTableWidgetItem(e.get("client_id") or "—"))
                self._table.setItem(row, 3, QTableWidgetItem(e.get("user_id") or "—"))
                details = e.get("details")
                detail_str = str(details) if details else "—"
                if len(detail_str) > 100:
                    detail_str = detail_str[:100] + "..."
                self._table.setItem(row, 4, QTableWidgetItem(detail_str))
            self._load_more_btn.setVisible(len(entries) == 100)
        except APIConnectionError:
            if not append:
                self._show_message("Server unreachable.", "error", retry=self.refresh)
        except APIAuthenticationError:
            if not append:
                self._show_message("Insufficient permissions.", "warning")
        except APIError as e:
            if not append:
                self._show_message(f"Error loading activity: {e}", "error", retry=self.refresh)

    def _apply_filter(self):
        self._offset = 0
        self._load_entries()

    def _load_more(self):
        self._offset += 100
        self._load_entries(append=True)

    def _on_export(self):
        action = self._action_filter.currentText()
        action_param = action if action != "All" else None
        try:
            csv_data = self.api_client.export_activity_csv(action=action_param)
            path, _ = QFileDialog.getSaveFileName(
                self, "Save Activity Log", "activity_log.csv", "CSV Files (*.csv)"
            )
            if path:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(csv_data)
                self._show_message(f"Activity log saved to {path}", icon="info")
        except Exception as e:
            self._show_message(f"Export failed: {e}", icon="error")


class _ApiKeysPanel(QWidget):
    """API Keys management sub-tab."""

    def __init__(self, api_client: APIClient, capabilities: ServerCapabilities, parent=None):
        super().__init__(parent)
        self.api_client = api_client
        self._caps = capabilities
        self._setup_ui()

    def _setup_ui(self):
        self._stack = QStackedWidget()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._stack)

        self._msg_page = QWidget()
        QVBoxLayout(self._msg_page)
        self._stack.addWidget(self._msg_page)

        self._content = QWidget()
        content_layout = QVBoxLayout(self._content)
        content_layout.setSpacing(12)
        content_layout.setContentsMargins(20, 20, 20, 20)

        # Header row
        header_row = QHBoxLayout()
        title = QLabel("API Keys")
        title.setStyleSheet(f"color: {Theme.TEXT_PRIMARY}; font-size: 14px; font-weight: bold;")
        header_row.addWidget(title)
        header_row.addStretch()
        self._create_btn = QPushButton("Create Key")
        self._create_btn.clicked.connect(self._on_create_key)
        header_row.addWidget(self._create_btn)
        content_layout.addLayout(header_row)

        # Table
        self._table = QTableWidget()
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels(["Name", "Prefix", "Created", "Last Used", "Status"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for col in range(1, 5):
            self._table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeToContents)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setContextMenuPolicy(Qt.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_context_menu)
        content_layout.addWidget(self._table)

        self._stack.addWidget(self._content)

    def _show_message(self, text, icon="info", retry=None):
        old = self._msg_page.layout().itemAt(0)
        if old and old.widget():
            old.widget().deleteLater()
        panel = _MessagePanel(text, icon=icon, retry_callback=retry, parent=self._msg_page)
        self._msg_page.layout().addWidget(panel)
        self._stack.setCurrentWidget(self._msg_page)

    def refresh(self):
        status = self._caps.get("keys")
        if status == CapabilityStatus.NOT_SUPPORTED:
            self._show_message("API key management not available on this server version.", "info")
            return
        if status == CapabilityStatus.UNAUTHORIZED:
            self._show_message("API key required or insufficient permissions.", "warning")
            return
        if status == CapabilityStatus.UNREACHABLE:
            self._show_message("Server unreachable.", "error", retry=self.refresh)
            return
        if not self._caps.is_available("keys"):
            return

        self._stack.setCurrentWidget(self._content)
        self._create_btn.setVisible(self._caps.has_permission("keys.manage"))

        try:
            data = self.api_client.list_keys()
            keys = data.get("keys", [])
            self._table.setRowCount(len(keys))
            for i, k in enumerate(keys):
                self._table.setItem(i, 0, QTableWidgetItem(k.get("name", "—")))
                self._table.setItem(i, 1, QTableWidgetItem(k.get("prefix", "—")))
                self._table.setItem(i, 2, QTableWidgetItem(_format_timestamp(k.get("created_at"))))
                self._table.setItem(i, 3, QTableWidgetItem(_format_timestamp(k.get("last_used_at"))))
                # Backend returns "active" (bool); older responses may use "status" (string)
                if "active" in k:
                    is_active = bool(k["active"])
                else:
                    is_active = k.get("status", "active").lower() == "active"
                status_item = QTableWidgetItem("Active" if is_active else "Revoked")
                color = Theme.SUCCESS if is_active else Theme.ERROR
                status_item.setForeground(QColor(color))
                self._table.setItem(i, 4, status_item)
                # Store key ID
                self._table.item(i, 0).setData(Qt.UserRole, k.get("id"))
        except APIConnectionError:
            self._show_message("Server unreachable.", "error", retry=self.refresh)
        except APIAuthenticationError:
            self._show_message("Insufficient permissions.", "warning")
        except APIError as e:
            self._show_message(f"Error loading keys: {e}", "error", retry=self.refresh)

    def _on_create_key(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Create API Key")
        dialog.setMinimumWidth(300)
        form = QFormLayout(dialog)
        name_edit = QLineEdit()
        name_edit.setPlaceholderText("Key name (e.g. 'CI Pipeline')")
        form.addRow("Name:", name_edit)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)

        if dialog.exec() != QDialog.Accepted:
            return
        name = name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Validation", "Key name is required.")
            return
        try:
            result = self.api_client.create_key(name)
            full_key = result.get("key") or result.get("api_key", "")
            # Show key in a dialog with copy button
            key_dialog = QDialog(self)
            key_dialog.setWindowTitle("New API Key Created")
            key_dialog.setMinimumWidth(450)
            kd_layout = QVBoxLayout(key_dialog)
            kd_layout.addWidget(QLabel("Copy this key now — it will not be shown again:"))
            key_field = QLineEdit(full_key)
            key_field.setReadOnly(True)
            key_field.setStyleSheet("font-family: monospace; font-size: 13px; padding: 8px;")
            kd_layout.addWidget(key_field)
            copy_btn = QPushButton("Copy to Clipboard")
            copy_btn.clicked.connect(lambda: QApplication.clipboard().setText(full_key))
            kd_layout.addWidget(copy_btn)
            close_btn = QPushButton("Close")
            close_btn.clicked.connect(key_dialog.accept)
            kd_layout.addWidget(close_btn)
            key_dialog.exec()
            self.refresh()
        except APIAuthenticationError:
            self._show_message("Insufficient permissions (keys.manage required).", icon="warning")
        except APIError as e:
            self._show_message(f"Failed to create key: {e}", icon="error")

    def _on_context_menu(self, pos):
        if not self._caps.has_permission("keys.manage"):
            return
        row = self._table.rowAt(pos.y())
        if row < 0:
            return
        key_id = self._table.item(row, 0).data(Qt.UserRole)
        key_name = self._table.item(row, 0).text()
        status_text = self._table.item(row, 4).text().lower()

        menu = QMenu(self)
        if status_text == "active":
            revoke_action = menu.addAction("Revoke Key")
            rotate_action = menu.addAction("Rotate Key")
        else:
            revoke_action = rotate_action = None

        chosen = menu.exec(self._table.viewport().mapToGlobal(pos))
        if chosen is None:
            return

        if chosen == revoke_action:
            self._revoke_key(key_id, key_name)
        elif chosen == rotate_action:
            self._rotate_key(key_id, key_name)

    def _revoke_key(self, key_id, key_name):
        reply = QMessageBox.warning(
            self, "Confirm Revoke",
            f"Revoke API key '{key_name}'?\n\nThis takes effect immediately.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        try:
            self.api_client.revoke_key(key_id)
            self.refresh()
        except APIError as e:
            self._show_message(f"Failed to revoke key: {e}", icon="error")

    def _rotate_key(self, key_id, key_name):
        reply = QMessageBox.question(
            self, "Confirm Rotate",
            f"Rotate API key '{key_name}'?\n\nThe old key will remain valid for a 24-hour grace period.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        try:
            result = self.api_client.rotate_key(key_id)
            new_key = result.get("key") or result.get("api_key", "")
            key_dialog = QDialog(self)
            key_dialog.setWindowTitle("Key Rotated")
            key_dialog.setMinimumWidth(450)
            kd_layout = QVBoxLayout(key_dialog)
            kd_layout.addWidget(QLabel("New key (old key valid for 24h):"))
            key_field = QLineEdit(new_key)
            key_field.setReadOnly(True)
            key_field.setStyleSheet("font-family: monospace; font-size: 13px; padding: 8px;")
            kd_layout.addWidget(key_field)
            copy_btn = QPushButton("Copy to Clipboard")
            copy_btn.clicked.connect(lambda: QApplication.clipboard().setText(new_key))
            kd_layout.addWidget(copy_btn)
            close_btn = QPushButton("Close")
            close_btn.clicked.connect(key_dialog.accept)
            kd_layout.addWidget(close_btn)
            key_dialog.exec()
            self.refresh()
        except APIError as e:
            self._show_message(f"Failed to rotate key: {e}", icon="error")


class _ScimPanel(QWidget):
    """SCIM Provisioning visibility sub-tab."""

    def __init__(self, api_client: APIClient, capabilities: ServerCapabilities, parent=None):
        super().__init__(parent)
        self.api_client = api_client
        self._caps = capabilities
        self._setup_ui()

    def _setup_ui(self):
        self._stack = QStackedWidget()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._stack)

        self._msg_page = QWidget()
        QVBoxLayout(self._msg_page)
        self._stack.addWidget(self._msg_page)

        self._content = QWidget()
        content_layout = QVBoxLayout(self._content)
        content_layout.setSpacing(16)
        content_layout.setContentsMargins(20, 20, 20, 20)

        # Status card
        status_label = QLabel("SCIM Status")
        status_label.setStyleSheet(f"color: {Theme.TEXT_PRIMARY}; font-size: 14px; font-weight: bold;")
        content_layout.addWidget(status_label)

        self._status_form = QFormLayout()
        self._scim_enabled = QLabel("—")
        self._scim_default_role = QLabel("—")
        self._scim_endpoint = QLineEdit()
        self._scim_endpoint.setReadOnly(True)
        self._scim_endpoint.setStyleSheet("font-family: monospace; font-size: 12px;")
        for lbl in (self._scim_enabled, self._scim_default_role):
            lbl.setStyleSheet(f"color: {Theme.TEXT_PRIMARY}; font-size: 13px;")
        self._status_form.addRow("Enabled:", self._scim_enabled)
        self._status_form.addRow("Default Role:", self._scim_default_role)
        self._status_form.addRow("Endpoint URL:", self._scim_endpoint)
        content_layout.addLayout(self._status_form)

        # Copy endpoint button
        copy_row = QHBoxLayout()
        copy_btn = QPushButton("Copy Endpoint URL")
        copy_btn.clicked.connect(lambda: QApplication.clipboard().setText(self._scim_endpoint.text()))
        copy_row.addWidget(copy_btn)
        copy_row.addStretch()
        content_layout.addLayout(copy_row)

        # Recent provisioning events
        events_label = QLabel("Recent Provisioning Events")
        events_label.setStyleSheet(f"color: {Theme.TEXT_PRIMARY}; font-size: 14px; font-weight: bold;")
        content_layout.addWidget(events_label)

        self._events_table = QTableWidget()
        self._events_table.setColumnCount(4)
        self._events_table.setHorizontalHeaderLabels(["Timestamp", "Action", "User ID", "Details"])
        self._events_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self._events_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._events_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._events_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self._events_table.verticalHeader().setVisible(False)
        self._events_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._events_table.setSelectionBehavior(QTableWidget.SelectRows)
        content_layout.addWidget(self._events_table)

        self._stack.addWidget(self._content)

    def _show_message(self, text, icon="info", retry=None):
        old = self._msg_page.layout().itemAt(0)
        if old and old.widget():
            old.widget().deleteLater()
        panel = _MessagePanel(text, icon=icon, retry_callback=retry, parent=self._msg_page)
        self._msg_page.layout().addWidget(panel)
        self._stack.setCurrentWidget(self._msg_page)

    def refresh(self):
        status = self._caps.get("scim")
        if status == CapabilityStatus.NOT_SUPPORTED:
            self._show_message("SCIM provisioning is not enabled on this server.", "info")
            return
        if status == CapabilityStatus.UNAUTHORIZED:
            self._show_message("Insufficient permissions to view SCIM status.", "warning")
            return
        if status == CapabilityStatus.UNREACHABLE:
            self._show_message("Server unreachable.", "error", retry=self.refresh)
            return
        if not self._caps.is_available("scim"):
            self._show_message("SCIM provisioning is not available.", "info")
            return

        self._stack.setCurrentWidget(self._content)

        # Build endpoint URL from API base
        base = self.api_client.base_url or ""
        # Strip trailing /api/v1 to get server root
        server_root = base.rsplit("/api", 1)[0] if "/api" in base else base
        self._scim_endpoint.setText(f"{server_root}/scim/v2/Users")

        # Fetch SCIM config from ServiceProviderConfig
        try:
            from desktop_app.utils.api_client_core.base_client import BaseAPIClient
            scim_url = f"{server_root}/scim/v2/ServiceProviderConfig"
            response = self.api_client._base.request("GET", scim_url, timeout=5)
            config = response.json()
            self._scim_enabled.setText("Yes")
            self._scim_default_role.setText(config.get("defaultRole", "—"))
        except Exception:
            self._scim_enabled.setText("Yes (config unavailable)")
            self._scim_default_role.setText("—")

        # Fetch recent SCIM provisioning events from activity log
        try:
            data = self.api_client.get_activity_log(
                limit=50, offset=0, action=None
            )
            scim_actions = {"user.scim_provisioned", "user.scim_updated", "user.scim_patched", "user.scim_deprovisioned"}
            entries = [e for e in data.get("entries", []) if e.get("action") in scim_actions]
            self._events_table.setRowCount(len(entries))
            for i, e in enumerate(entries):
                self._events_table.setItem(i, 0, QTableWidgetItem(_format_timestamp(e.get("ts"))))
                self._events_table.setItem(i, 1, QTableWidgetItem(e.get("action", "—")))
                self._events_table.setItem(i, 2, QTableWidgetItem(e.get("user_id") or "—"))
                details = e.get("details")
                detail_str = str(details) if details else "—"
                if len(detail_str) > 100:
                    detail_str = detail_str[:100] + "..."
                self._events_table.setItem(i, 3, QTableWidgetItem(detail_str))
        except Exception as e:
            logger.warning("Failed to load SCIM events: %s", e)
            self._events_table.setRowCount(0)


# ---------------------------------------------------------------------------
# Main Organization Tab
# ---------------------------------------------------------------------------

class OrganizationTab(QWidget):
    """Organization console tab — always present, adapts to server capabilities."""
    AUTO_RETRY_DELAY_MS = 2500
    MAX_AUTO_RETRY_ATTEMPTS = 4

    def __init__(self, api_client: APIClient, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.api_client = api_client
        self._caps = ServerCapabilities(api_client)
        self._auto_retry_scheduled = False
        self._auto_retry_attempts = 0
        self._transient_retry_window_active = True
        self._awaiting_backend_healthy_reprobe = True
        self._setup_ui()

    def _setup_ui(self):
        self._outer_stack = QStackedWidget()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._outer_stack)

        # Page 0: Gated / unreachable / loading placeholder
        self._placeholder = QWidget()
        ph_layout = QVBoxLayout(self._placeholder)
        self._loading_label = QLabel("Loading organization features...")
        self._loading_label.setAlignment(Qt.AlignCenter)
        self._loading_label.setStyleSheet("color: #9ca3af; font-size: 14px; padding: 40px;")
        ph_layout.addStretch()
        ph_layout.addWidget(self._loading_label)
        ph_layout.addStretch()
        self._outer_stack.addWidget(self._placeholder)

        # Page 1: Sub-tabs
        self._tabs_page = QWidget()
        tabs_layout = QVBoxLayout(self._tabs_page)
        tabs_layout.setContentsMargins(0, 0, 0, 0)

        # Title row with refresh
        title_row = QHBoxLayout()
        title = QLabel("Organization")
        title.setProperty("class", "header")
        title_row.addWidget(title)
        title_row.addStretch()
        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.clicked.connect(self._on_refresh)
        title_row.addWidget(self._refresh_btn)
        tabs_layout.addLayout(title_row)

        self._sub_tabs = QTabWidget()
        tabs_layout.addWidget(self._sub_tabs)

        # Sub-panels
        self._overview = _OverviewPanel(self.api_client, self._caps)
        self._users_roles = _UsersRolesPanel(self.api_client, self._caps)
        self._permissions = _PermissionsPanel(self.api_client, self._caps)
        self._retention = _RetentionPanel(self.api_client, self._caps)
        self._activity = _ActivityPanel(self.api_client, self._caps)
        self._api_keys = _ApiKeysPanel(self.api_client, self._caps)
        self._scim = _ScimPanel(self.api_client, self._caps)

        self._sub_tabs.addTab(self._overview, "Overview")
        # Other tabs added dynamically based on capabilities

        self._outer_stack.addWidget(self._tabs_page)

    def probe_and_refresh(self):
        """Probe server capabilities and populate the tab."""
        logger.info("OrganizationTab.probe_and_refresh() called")
        self._refresh_btn.setEnabled(False)
        self._refresh_btn.setText("Loading...")
        try:
            # Force the backend to re-read its license from disk before we probe.
            # This ensures the Organization tab reflects the *current* license state
            # even if the backend server process wasn't restarted.
            try:
                reload_url = f"{self.api_client._base.api_base}/license/reload"
                self.api_client._base.request("POST", reload_url)
                # Also clear the desktop app's own in-process license cache
                # so the Settings tab reads fresh data from disk
                from license import reset_license
                reset_license()
                logger.info("Backend + local license cache refreshed before probe")
            except Exception as e:
                logger.debug("License reload before probe failed (non-fatal): %s", e)
            
            self._caps.probe_all()
            logger.info("probe_and_refresh: probe complete, updating visibility")
            self._update_visibility()
            logger.info("probe_and_refresh: done, page index=%d", self._outer_stack.currentIndex())
        except Exception as e:
            logger.error(f"Organization tab probe failed: {e}", exc_info=True)
            if self._transient_retry_window_active and self._auto_retry_attempts < self.MAX_AUTO_RETRY_ATTEMPTS:
                # Still in startup — show a gentle loading message and auto-retry
                self._show_placeholder("Loading organization features...")
                self._schedule_auto_retry()
            else:
                self._show_placeholder(
                    f"Failed to load organization features: {e}",
                    show_retry=True,
                )
        finally:
            self._refresh_btn.setEnabled(True)
            self._refresh_btn.setText("Refresh")

    def _begin_transient_retry_window(self):
        self._auto_retry_scheduled = False
        self._auto_retry_attempts = 0
        self._transient_retry_window_active = True
        self._awaiting_backend_healthy_reprobe = True

    def _on_refresh(self):
        self._auto_retry_scheduled = False
        self._auto_retry_attempts = 0
        self._transient_retry_window_active = False
        self._caps.invalidate()
        self.probe_and_refresh()

    def show_server_offline(self):
        """Show a 'server not available' placeholder.

        Called by MainWindow when the health check reports the API
        is not reachable, so the tab does not sit on 'Loading...' forever.
        """
        # Don't overwrite real content if the tab already loaded successfully
        if self._outer_stack.currentWidget() is self._tabs_page:
            return
        self._show_placeholder(
            "Cannot connect to server. Organization features will appear "
            "once the server is running.",
            show_retry=True,
        )

    def on_backend_healthy(self):
        """Reprobe once when the health worker reports the backend is healthy again.

        This covers the gap where the API health endpoint turns green before
        the organization/license endpoints are fully ready, leaving the tab on
        a transient placeholder state after the initial startup probe.
        """
        if self._outer_stack.currentWidget() is self._tabs_page:
            return
        if not self._awaiting_backend_healthy_reprobe:
            return
        if self._auto_retry_scheduled:
            return

        self._awaiting_backend_healthy_reprobe = False
        self._begin_transient_retry_window()
        self._caps.invalidate()
        self.probe_and_refresh()

    def on_settings_changed(self):
        """Called when backend URL or API key changes in Settings.

        Invalidates all cached capability state and re-probes the server.
        """
        self._begin_transient_retry_window()
        self._caps.invalidate()
        self.probe_and_refresh()

    def _schedule_auto_retry(self):
        if not self._transient_retry_window_active:
            return
        if self._auto_retry_scheduled:
            return
        if self._auto_retry_attempts >= self.MAX_AUTO_RETRY_ATTEMPTS:
            self._transient_retry_window_active = False
            return
        self._auto_retry_scheduled = True
        self._auto_retry_attempts += 1
        QTimer.singleShot(self.AUTO_RETRY_DELAY_MS, self._auto_retry_probe)

    def _auto_retry_probe(self):
        self._auto_retry_scheduled = False
        self._caps.invalidate()
        self.probe_and_refresh()

    def _update_visibility(self):
        from desktop_app.utils.edition import is_feature_available

        has_any = self._caps.any_available()
        has_auth_issue = self._caps.any_unauthorized()
        
        # Check if the auth issue was specifically an edition denial from the backend
        has_edition_denial = False
        from desktop_app.utils.server_capabilities import _PROBES
        for cap_name in _PROBES:
            result = self._caps.get_result(cap_name)
            if result and getattr(result, "error_code", None) == "LIC_3006":
                has_edition_denial = True
                break

        # If the server explicitly rejected due to edition constraints -> gated (upgrade path)
        if has_edition_denial:
            if self._transient_retry_window_active and self._auto_retry_attempts < self.MAX_AUTO_RETRY_ATTEMPTS:
                self._show_placeholder("Loading organization features...")
            else:
                self._show_placeholder(
                    "Organization Console features are available with a Team or Organization license.",
                    show_learn_more=True,
                )
            self._schedule_auto_retry()
            return

        # Generic Auth failures take priority — server is reachable but rejecting us for permission
        if not has_any and has_auth_issue:
            if self._transient_retry_window_active and self._auto_retry_attempts < self.MAX_AUTO_RETRY_ATTEMPTS:
                self._show_placeholder("Loading organization features...")
            else:
                self._show_placeholder(
                    "Authentication required. Check your API key in Settings, "
                    "or contact your administrator if permissions are insufficient.",
                    show_retry=True,
                )
            self._schedule_auto_retry()
            return

        # Connectivity / Support failures
        if not has_any:
            if self._caps.all_unreachable_or_unknown():
                if self._transient_retry_window_active and self._auto_retry_attempts < self.MAX_AUTO_RETRY_ATTEMPTS:
                    # Still in startup — show a gentle loading message instead of
                    # flashing a scary "Cannot connect" error with a Retry button.
                    self._show_placeholder("Loading organization features...")
                else:
                    self._show_placeholder(
                        "Cannot connect to server. Organization features will appear once the server is running.",
                        show_retry=True,
                    )
                self._schedule_auto_retry()
            else:
                self._show_placeholder(
                    "This server version does not support organization management features.",
                )
            return

        # At least one capability available — show tabs
        self._auto_retry_scheduled = False
        self._auto_retry_attempts = 0
        self._transient_retry_window_active = False
        self._awaiting_backend_healthy_reprobe = False
        self._outer_stack.setCurrentWidget(self._tabs_page)

        # Rebuild sub-tabs (remove all except Overview which is always index 0)
        while self._sub_tabs.count() > 1:
            self._sub_tabs.removeTab(1)

        if self._caps.is_available("users") or self._caps.is_available("roles"):
            self._sub_tabs.addTab(self._users_roles, "Users & Roles")
        if self._caps.is_available("permissions"):
            self._sub_tabs.addTab(self._permissions, "Permissions")
        if self._caps.is_available("keys"):
            self._sub_tabs.addTab(self._api_keys, "API Keys")
        if self._caps.is_available("retention"):
            self._sub_tabs.addTab(self._retention, "Retention")
        if self._caps.is_available("activity"):
            self._sub_tabs.addTab(self._activity, "Activity")
        if self._caps.is_available("scim"):
            self._sub_tabs.addTab(self._scim, "SCIM")

        # Refresh all visible panels
        self._overview.refresh()
        if self._caps.is_available("users") or self._caps.is_available("roles"):
            self._users_roles.refresh()
        if self._caps.is_available("permissions"):
            self._permissions.refresh()
        if self._caps.is_available("keys"):
            self._api_keys.refresh()
        if self._caps.is_available("retention"):
            self._retention.refresh()
        if self._caps.is_available("activity"):
            self._activity.refresh()
        if self._caps.is_available("scim"):
            self._scim.refresh()

    def _show_placeholder(self, text, show_learn_more=False, show_retry=False):
        # Clear old placeholder content
        old_layout = self._placeholder.layout()
        while old_layout.count():
            item = old_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if show_learn_more:
            try:
                from desktop_app.ui.gated_feature import GatedFeatureWidget
                widget = GatedFeatureWidget(
                    feature_name="Organization Console",
                    description=text,
                )
            except Exception:
                # Fallback when qtawesome fonts are unavailable (e.g. CI runners)
                widget = QLabel(text)
                widget.setAlignment(Qt.AlignCenter)
                widget.setWordWrap(True)
                widget.setStyleSheet("color: #9ca3af; font-size: 14px; padding: 40px;")
            old_layout.addWidget(widget)
        else:
            retry_cb = self._on_refresh if show_retry else None
            panel = _MessagePanel(text, icon="info", retry_callback=retry_cb)
            old_layout.addWidget(panel)

        self._outer_stack.setCurrentWidget(self._placeholder)
