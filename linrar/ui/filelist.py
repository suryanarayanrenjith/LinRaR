"""The central file list, used for both disk browsing and archive browsing.

Two widgets share one model: a multi-column :class:`FileListView` for the
Details view and a :class:`IconListView` for the icon and list views.
:class:`FileBrowser` stacks them, keeps one selection between them, and is what
the main window talks to.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QListView,
    QStackedLayout,
    QStyledItemDelegate,
    QTreeView,
    QWidget,
)

from ..core.models import ArchiveEntry, format_size
from ..core.registry import looks_like_archive
from . import icons, theme

COL_NAME, COL_SIZE, COL_PACKED, COL_TYPE, COL_MODIFIED, COL_CRC = range(6)
HEADERS = ["Name", "Size", "Packed", "Type", "Modified", "CRC32"]

# -- view modes, in the order the menus offer them --
DETAILS, LIST, SMALL_ICONS, LARGE_ICONS, TILES = (
    "details", "list", "small", "large", "tiles"
)
VIEW_MODES = (DETAILS, LIST, SMALL_ICONS, LARGE_ICONS, TILES)
VIEW_LABELS = {
    DETAILS: "&Details",
    LIST: "&List",
    SMALL_ICONS: "S&mall icons",
    LARGE_ICONS: "Lar&ge icons",
    TILES: "&Tiles",
}
#: icon size, grid size (None = let the view decide) and flow, per mode
_VIEW_GEOMETRY = {
    LIST: (16, None, QListView.Flow.TopToBottom, QListView.ViewMode.ListMode),
    SMALL_ICONS: (16, QSize(190, 22), QListView.Flow.LeftToRight,
                  QListView.ViewMode.ListMode),
    LARGE_ICONS: (48, QSize(104, 82), QListView.Flow.LeftToRight,
                  QListView.ViewMode.IconMode),
    # Tiles keep the icon on the left with the name beside it, as Windows does,
    # which is ListMode with a big grid rather than IconMode.
    TILES: (32, QSize(210, 42), QListView.Flow.LeftToRight,
            QListView.ViewMode.ListMode),
}

#: row heights offered by the Customize dialog, in extra pixels per row
ROW_SPACING = {"compact": 0, "normal": 4, "relaxed": 10}

# Descriptions shown in the Type column, mirroring a Windows shell listing.
_TYPES = {
    ".txt": "Text Document", ".log": "Text Document", ".md": "Markdown File",
    ".pdf": "PDF Document", ".doc": "Word Document", ".docx": "Word Document",
    ".xls": "Excel Worksheet", ".xlsx": "Excel Worksheet",
    ".ppt": "PowerPoint Presentation", ".pptx": "PowerPoint Presentation",
    ".jpg": "JPEG Image", ".jpeg": "JPEG Image", ".png": "PNG Image",
    ".gif": "GIF Image", ".bmp": "Bitmap Image", ".svg": "SVG Image",
    ".webp": "WebP Image", ".ico": "Icon",
    ".mp3": "MP3 Audio", ".wav": "Wave Audio", ".flac": "FLAC Audio",
    ".ogg": "OGG Audio", ".m4a": "MPEG-4 Audio",
    ".mp4": "MP4 Video", ".mkv": "Matroska Video", ".avi": "AVI Video",
    ".mov": "QuickTime Video", ".webm": "WebM Video",
    ".rar": "LinRAR archive", ".zip": "LinRAR ZIP archive",
    ".7z": "LinRAR archive", ".tar": "LinRAR archive",
    ".gz": "LinRAR archive", ".bz2": "LinRAR archive", ".xz": "LinRAR archive",
    ".iso": "Disc Image File", ".deb": "Debian Package", ".rpm": "RPM Package",
    ".appimage": "AppImage", ".sh": "Shell Script", ".py": "Python File",
    ".c": "C Source", ".h": "C Header", ".cpp": "C++ Source",
    ".js": "JavaScript File", ".ts": "TypeScript File", ".json": "JSON File",
    ".html": "HTML Document", ".htm": "HTML Document", ".css": "Cascading Style Sheet",
    ".xml": "XML Document", ".yml": "YAML File", ".yaml": "YAML File",
    ".so": "Shared Library", ".ttf": "TrueType Font", ".otf": "OpenType Font",
}


@dataclass
class ListingItem:
    """One row: a disk entry, an archive member, or the ``..`` parent link."""

    name: str
    path: str
    is_dir: bool = False
    is_parent: bool = False
    size: int = 0
    packed: int = 0
    mtime: Optional[datetime] = None
    crc: str = ""
    encrypted: bool = False
    is_link: bool = False
    entry: Optional[ArchiveEntry] = None

    @property
    def type_name(self) -> str:
        if self.is_parent:
            return ""
        if self.is_dir:
            return "File folder"
        ext = os.path.splitext(self.name)[1].lower()
        if ext in _TYPES:
            return _TYPES[ext]
        if ext:
            return f"{ext[1:].upper()} File"
        return "File"

    @property
    def icon_name(self) -> str:
        if self.is_parent:
            return "folder-up"
        if self.is_dir:
            return "folder"
        if looks_like_archive(self.name):
            return "archive-small"
        return "file"


class FileListModel(QAbstractTableModel):
    """Table model backing the browser, with WinRAR's folders-first ordering."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._items: list[ListingItem] = []
        self.archive_mode = False
        self._sort_column = COL_NAME
        self._sort_order = Qt.SortOrder.AscendingOrder

    # -- population --------------------------------------------------------

    def set_items(self, items: list[ListingItem], archive_mode: bool) -> None:
        self.beginResetModel()
        self._items = list(items)
        self.archive_mode = archive_mode
        self._apply_sort()
        self.endResetModel()

    def item_at(self, row: int) -> Optional[ListingItem]:
        if 0 <= row < len(self._items):
            return self._items[row]
        return None

    @property
    def items(self) -> list[ListingItem]:
        return self._items

    # -- QAbstractTableModel ----------------------------------------------

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._items)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation != Qt.Orientation.Horizontal:
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return HEADERS[section]
        if role == Qt.ItemDataRole.TextAlignmentRole and section in (
            COL_SIZE,
            COL_PACKED,
        ):
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        item = self._items[index.row()]
        column = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            return self._display(item, column)

        if role == Qt.ItemDataRole.DecorationRole and column == COL_NAME:
            return icons.icon(item.icon_name)

        if role == Qt.ItemDataRole.TextAlignmentRole and column in (
            COL_SIZE,
            COL_PACKED,
        ):
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        if role == Qt.ItemDataRole.ForegroundRole:
            if item.is_parent:
                return QColor(theme.current().text_dim)
            if item.encrypted:
                # WinRAR tints encrypted members.
                return QColor(theme.current().ok)
            if item.is_link:
                return QColor(theme.current().info)

        if role == Qt.ItemDataRole.FontRole and item.is_dir and not item.is_parent:
            font = QFont()
            font.setBold(False)
            return font

        if role == Qt.ItemDataRole.ToolTipRole:
            return self._tooltip(item)

        return None

    def _display(self, item: ListingItem, column: int):
        if column == COL_NAME:
            # WinRAR marks encrypted entries with a trailing asterisk.
            return item.name + ("*" if item.encrypted else "")
        if column == COL_SIZE:
            return "" if item.is_parent or item.is_dir else format_size(item.size)
        if column == COL_PACKED:
            if not self.archive_mode or item.is_parent or item.is_dir:
                return ""
            return format_size(item.packed)
        if column == COL_TYPE:
            return item.type_name
        if column == COL_MODIFIED:
            if item.is_parent or item.mtime is None:
                return ""
            return item.mtime.strftime("%d/%m/%Y %H:%M")
        if column == COL_CRC:
            if not self.archive_mode or item.is_parent or item.is_dir:
                return ""
            return item.crc
        return ""

    @staticmethod
    def _tooltip(item: ListingItem) -> str:
        if item.is_parent:
            return "Go to the parent folder"
        parts = [item.name]
        if not item.is_dir:
            parts.append(f"Size: {format_size(item.size)} bytes")
        if item.encrypted:
            parts.append("Encrypted")
        if item.is_link and item.entry and item.entry.link_target:
            parts.append(f"Link to: {item.entry.link_target}")
        return "\n".join(parts)

    # -- sorting -----------------------------------------------------------

    def sort(self, column: int, order=Qt.SortOrder.AscendingOrder) -> None:
        self.layoutAboutToBeChanged.emit()
        self._sort_column = column
        self._sort_order = order
        self._apply_sort()
        self.layoutChanged.emit()

    def _apply_sort(self) -> None:
        reverse = self._sort_order == Qt.SortOrder.DescendingOrder
        column = self._sort_column

        def key(item: ListingItem):
            if column == COL_SIZE:
                primary = item.size
            elif column == COL_PACKED:
                primary = item.packed
            elif column == COL_MODIFIED:
                primary = item.mtime.timestamp() if item.mtime else 0.0
            elif column == COL_TYPE:
                primary = item.type_name.lower()
            elif column == COL_CRC:
                primary = item.crc.lower()
            else:
                primary = item.name.lower()
            return primary

        files = [i for i in self._items if not i.is_parent]
        parents = [i for i in self._items if i.is_parent]
        try:
            files.sort(key=key, reverse=reverse)
        except TypeError:
            files.sort(key=lambda i: i.name.lower(), reverse=reverse)
        # Folders always precede files, and ".." always comes first.
        files.sort(key=lambda i: not i.is_dir)
        self._items = parents + files


class FileListView(QTreeView):
    """Flat, multi-column list view configured to look like WinRAR's."""

    activatedItem = pyqtSignal(object)
    contextRequested = pyqtSignal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setRootIsDecorated(False)
        self.setUniformRowHeights(True)
        self.setExpandsOnDoubleClick(False)
        self.setAlternatingRowColors(False)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setSortingEnabled(True)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.setIconSize(_icon_size())
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self._columns_ready = False

        header = self.header()
        header.setStretchLastSection(False)
        header.setSectionsMovable(True)
        header.setHighlightSections(False)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft)

        self.doubleClicked.connect(self._on_double_click)

    def _on_double_click(self, index: QModelIndex) -> None:
        model = self.model()
        if isinstance(model, FileListModel):
            item = model.item_at(index.row())
            if item is not None:
                self.activatedItem.emit(item)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            index = self.currentIndex()
            if index.isValid():
                self._on_double_click(index)
                return
        super().keyPressEvent(event)

    def configure_columns(self, archive_mode: bool) -> None:
        """Show the packed/CRC columns only while inside an archive."""
        header = self.header()
        self.setColumnHidden(COL_PACKED, not archive_mode)
        self.setColumnHidden(COL_CRC, not archive_mode)
        for column in range(len(HEADERS)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
        # Apply sensible defaults once; after that the user's own widths win.
        if not self._columns_ready:
            self._columns_ready = True
            for column, width in (
                (COL_NAME, 230),
                (COL_SIZE, 85),
                (COL_PACKED, 85),
                (COL_TYPE, 120),
                (COL_MODIFIED, 120),
                (COL_CRC, 80),
            ):
                self.setColumnWidth(column, width)

    def selected_items(self) -> list[ListingItem]:
        return _selection(self)


class IconListView(QListView):
    """The icon, small-icon and list views, over the same model."""

    activatedItem = pyqtSignal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setUniformItemSizes(True)
        self.setWordWrap(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setSpacing(2)
        self.doubleClicked.connect(self._on_double_click)

    def apply_mode(self, mode: str) -> None:
        size, grid, flow, view_mode = _VIEW_GEOMETRY.get(
            mode, _VIEW_GEOMETRY[LIST]
        )
        self.setViewMode(view_mode)
        self.setFlow(flow)
        self.setWrapping(mode != LIST)
        self.setIconSize(QSize(size, size))
        self.setGridSize(grid or QSize())
        self.setSpacing(4 if view_mode == QListView.ViewMode.IconMode else 1)

    def _on_double_click(self, index: QModelIndex) -> None:
        model = self.model()
        if isinstance(model, FileListModel):
            item = model.item_at(index.row())
            if item is not None:
                self.activatedItem.emit(item)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            index = self.currentIndex()
            if index.isValid():
                self._on_double_click(index)
                return
        super().keyPressEvent(event)

    def selected_items(self) -> list[ListingItem]:
        return _selection(self)


class FileBrowser(QWidget):
    """The file pane: one model, five views, one selection.

    Presents the same surface the main window used to call on the tree view
    directly, so switching the view mode is invisible to everything else.
    """

    activatedItem = pyqtSignal(object)
    # customContextMenuRequested is QWidget's own signal; the child views
    # forward theirs into it, and viewport() resolves to whichever is on top,
    # so the position the main window receives always maps correctly.

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.details = FileListView()
        self.icons = IconListView()
        self._mode = DETAILS

        self._stack = QStackedLayout(self)
        self._stack.setContentsMargins(0, 0, 0, 0)
        self._stack.addWidget(self.details)
        self._stack.addWidget(self.icons)

        for view in (self.details, self.icons):
            view.activatedItem.connect(self.activatedItem)
            view.customContextMenuRequested.connect(
                self.customContextMenuRequested
            )
        self.icons.apply_mode(LIST)

    # -- view mode ---------------------------------------------------------

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def view(self) -> QAbstractItemView:
        """Whichever view is on top."""
        return self.details if self._mode == DETAILS else self.icons

    def set_mode(self, mode: str) -> None:
        mode = mode if mode in VIEW_MODES else DETAILS
        self._mode = mode
        if mode == DETAILS:
            self._stack.setCurrentWidget(self.details)
        else:
            self.icons.apply_mode(mode)
            self._stack.setCurrentWidget(self.icons)

    def set_row_spacing(self, spacing: int) -> None:
        self.details.setItemDelegate(_RowDelegate(spacing, self.details))

    def set_grid_lines(self, enabled: bool) -> None:
        # A tree view has no grid, so the effect is drawn as row separators.
        self.details.setProperty("gridLines", "on" if enabled else "off")
        self.details.style().unpolish(self.details)
        self.details.style().polish(self.details)

    def set_alternating(self, enabled: bool) -> None:
        for view in (self.details, self.icons):
            view.setAlternatingRowColors(enabled)

    # -- delegation --------------------------------------------------------

    def setModel(self, model) -> None:
        self.details.setModel(model)
        self.icons.setModel(model)
        # One selection, so switching view keeps whatever was picked.
        self.icons.setSelectionModel(self.details.selectionModel())

    def model(self):
        return self.details.model()

    def selectionModel(self):
        return self.details.selectionModel()

    def selected_items(self) -> list[ListingItem]:
        return self.details.selected_items()

    def selectAll(self) -> None:
        self.view.selectAll()

    def currentIndex(self) -> QModelIndex:
        return self.view.currentIndex()

    def viewport(self):
        return self.view.viewport()

    def setDragEnabled(self, enabled: bool) -> None:
        for view in (self.details, self.icons):
            view.setDragEnabled(enabled)

    def sortByColumn(self, column: int, order) -> None:
        self.details.sortByColumn(column, order)

    def setColumnHidden(self, column: int, hidden: bool) -> None:
        self.details.setColumnHidden(column, hidden)

    def isColumnHidden(self, column: int) -> bool:
        return self.details.isColumnHidden(column)

    def configure_columns(self, archive_mode: bool) -> None:
        self.details.configure_columns(archive_mode)

    def header_state(self) -> bytes:
        return bytes(self.details.header().saveState())

    def restore_header_state(self, state) -> bool:
        if not state:
            return False
        return self.details.header().restoreState(state)


class _RowDelegate(QStyledItemDelegate):
    """Adds the chosen breathing room to every row of the Details view."""

    def __init__(self, spacing: int, parent=None) -> None:
        super().__init__(parent)
        self._spacing = max(0, spacing)

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        size.setHeight(size.height() + self._spacing)
        return size


def _selection(view: QAbstractItemView) -> list[ListingItem]:
    model = view.model()
    if not isinstance(model, FileListModel):
        return []
    rows = {index.row() for index in view.selectedIndexes()}
    items = [model.item_at(row) for row in sorted(rows)]
    return [i for i in items if i is not None and not i.is_parent]


def _icon_size():
    return QSize(16, 16)
