"""
Lazy-loading tree model for the hierarchical document browser.

Uses QAbstractItemModel with canFetchMore/fetchMore for on-demand
loading of tree levels from the API.
"""

import logging
from typing import Any, Optional

import qtawesome as qta
from PySide6.QtCore import QAbstractItemModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QIcon

from .workers import TreeWorker

logger = logging.getLogger(__name__)


class TreeNode:
    """A single node in the document tree (folder or file)."""

    __slots__ = (
        "name", "path", "node_type", "parent", "children", "row",
        "is_fetched", "is_fetching",
        "document_count", "latest_indexed_at",
        "document_id", "chunk_count", "indexed_at", "last_updated",
    )

    def __init__(
        self,
        name: str,
        path: str,
        node_type: str,
        parent: Optional["TreeNode"] = None,
    ):
        self.name = name
        self.path = path
        self.node_type = node_type  # "folder" or "file"
        self.parent = parent
        self.children: list["TreeNode"] = []
        self.row = 0  # index within parent.children

        # Fetch state (folders only)
        self.is_fetched = False
        self.is_fetching = False

        # Folder metadata
        self.document_count = 0
        self.latest_indexed_at: Optional[str] = None

        # File metadata
        self.document_id = ""
        self.chunk_count = 0
        self.indexed_at: Optional[str] = None
        self.last_updated: Optional[str] = None


# Column indices
COL_NAME = 0
COL_TYPE = 1
COL_CHUNKS = 2
COL_INDEXED = 3
_COLUMN_COUNT = 4
_HEADERS = ["Name", "Type", "Chunks", "Indexed"]


class DocumentTreeModel(QAbstractItemModel):
    """Lazy-loading tree model backed by the /documents/tree API."""

    # Emitted when a level starts/finishes loading (for status bar)
    loading = Signal(str)       # parent_path
    loaded = Signal(str, int)   # parent_path, child_count
    load_failed = Signal(str)   # error message

    def __init__(self, api_client, parent=None):
        super().__init__(parent)
        self._api = api_client
        self._root = TreeNode(name="", path="", node_type="root")
        self._root.is_fetched = False
        self._workers: list[TreeWorker] = []

        # Cache icons to avoid re-creating per call
        self._folder_icon: Optional[QIcon] = None
        self._file_icon: Optional[QIcon] = None

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def is_initialized(self) -> bool:
        return self._root.is_fetched

    def load_root(self) -> None:
        """Kick off the initial root-level fetch."""
        if self._root.is_fetched or self._root.is_fetching:
            return
        self._fetch_children(self._root)

    def refresh(self) -> None:
        """Clear all data and reload root."""
        self.beginResetModel()
        self._root.children.clear()
        self._root.is_fetched = False
        self._root.is_fetching = False
        self.endResetModel()
        self.load_root()

    def node_for_index(self, index: QModelIndex) -> TreeNode:
        """Return the TreeNode for a QModelIndex (root if invalid)."""
        if index.isValid():
            node = index.internalPointer()
            if node is not None:
                return node
        return self._root

    # ------------------------------------------------------------------
    # QAbstractItemModel overrides
    # ------------------------------------------------------------------

    def columnCount(self, parent=QModelIndex()) -> int:
        return _COLUMN_COUNT

    def rowCount(self, parent=QModelIndex()) -> int:
        node = self.node_for_index(parent)
        return len(node.children)

    def hasChildren(self, parent=QModelIndex()) -> bool:
        node = self.node_for_index(parent)
        if node is self._root:
            return True
        if node.node_type == "folder":
            return True  # assume folders always *may* have children
        return len(node.children) > 0

    def canFetchMore(self, parent=QModelIndex()) -> bool:
        node = self.node_for_index(parent)
        if node.node_type not in ("root", "folder"):
            return False
        return not node.is_fetched and not node.is_fetching

    def fetchMore(self, parent=QModelIndex()) -> None:
        node = self.node_for_index(parent)
        if node.is_fetched or node.is_fetching:
            return
        self._fetch_children(node)

    def index(self, row: int, column: int, parent=QModelIndex()) -> QModelIndex:
        if not self.hasIndex(row, column, parent):
            return QModelIndex()
        parent_node = self.node_for_index(parent)
        if row < len(parent_node.children):
            child = parent_node.children[row]
            return self.createIndex(row, column, child)
        return QModelIndex()

    def parent(self, index: QModelIndex) -> QModelIndex:
        if not index.isValid():
            return QModelIndex()
        child: TreeNode = index.internalPointer()
        if child is None or child.parent is None or child.parent is self._root:
            return QModelIndex()
        parent_node = child.parent
        return self.createIndex(parent_node.row, 0, parent_node)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid():
            return None
        node: TreeNode = index.internalPointer()
        if node is None:
            return None
        col = index.column()

        if role == Qt.DisplayRole:
            return self._display_data(node, col)

        if role == Qt.DecorationRole and col == COL_NAME:
            return self._icon_for(node)

        if role == Qt.ToolTipRole and col == COL_NAME:
            return node.path

        if role == Qt.UserRole:
            return node.path

        if role == Qt.UserRole + 1:
            return node.node_type

        if role == Qt.UserRole + 2:
            return node.document_id

        return None

    def headerData(self, section: int, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            if 0 <= section < len(_HEADERS):
                return _HEADERS[section]
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.NoItemFlags
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _display_data(self, node: TreeNode, col: int) -> Optional[str]:
        if col == COL_NAME:
            if node.is_fetching:
                return f"{node.name}  (loading...)"
            return node.name
        if col == COL_TYPE:
            if node.node_type == "folder":
                return "Folder"
            return "File"
        if col == COL_CHUNKS:
            if node.node_type == "folder":
                return str(node.document_count) if node.document_count else ""
            return str(node.chunk_count) if node.chunk_count else ""
        if col == COL_INDEXED:
            raw = node.latest_indexed_at if node.node_type == "folder" else node.indexed_at
            if raw:
                return self._format_date(raw)
            return ""
        return None

    @staticmethod
    def _format_date(iso_str: str) -> str:
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
            return dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            return iso_str[:16] if len(iso_str) > 16 else iso_str

    def _icon_for(self, node: TreeNode) -> QIcon:
        if node.node_type == "folder":
            if self._folder_icon is None:
                self._folder_icon = qta.icon("fa5s.folder", color="#f59e0b")
            return self._folder_icon
        if self._file_icon is None:
            self._file_icon = qta.icon("fa5s.file-alt", color="#6366f1")
        return self._file_icon

    # ------------------------------------------------------------------
    # Background fetch
    # ------------------------------------------------------------------

    def _fetch_children(self, node: TreeNode) -> None:
        node.is_fetching = True
        self.loading.emit(node.path)

        worker = TreeWorker(self._api, parent_path=node.path)
        worker.finished.connect(
            lambda ok, data, pp: self._on_children_loaded(ok, data, node)
        )
        self._workers.append(worker)
        worker.start()

    def _on_children_loaded(self, success: bool, data, node: TreeNode) -> None:
        node.is_fetching = False

        if not success:
            node.is_fetched = True  # don't retry automatically
            self.load_failed.emit(str(data))
            return

        children_data = data.get("children", [])

        # Build TreeNode children
        new_children: list[TreeNode] = []
        for i, child in enumerate(children_data):
            name = child.get("name", "")
            if not name:
                continue
            child_node = TreeNode(
                name=name,
                path=child.get("path", ""),
                node_type=child.get("type", "file"),
                parent=node,
            )
            child_node.row = i
            if child_node.node_type == "folder":
                child_node.document_count = child.get("document_count", 0)
                child_node.latest_indexed_at = child.get("latest_indexed_at")
            else:
                child_node.document_id = child.get("document_id", "")
                child_node.chunk_count = child.get("chunk_count", 0)
                child_node.indexed_at = child.get("indexed_at")
                child_node.last_updated = child.get("last_updated")
            new_children.append(child_node)

        # Fix row indices (we may have skipped empty names)
        for idx, ch in enumerate(new_children):
            ch.row = idx

        # Insert into model
        parent_index = self._node_to_index(node)
        if new_children:
            self.beginInsertRows(parent_index, 0, len(new_children) - 1)
            node.children = new_children
            node.is_fetched = True
            self.endInsertRows()
        else:
            node.children = []
            node.is_fetched = True
            # Notify view that this node no longer has children
            self.dataChanged.emit(parent_index, parent_index)

        total_folders = data.get("total_folders", 0)
        total_files = data.get("total_files", 0)
        self.loaded.emit(node.path, total_folders + total_files)

    def _node_to_index(self, node: TreeNode) -> QModelIndex:
        if node is self._root:
            return QModelIndex()
        return self.createIndex(node.row, 0, node)
