"""The central file list, used for both disk browsing and archive browsing.

Two widgets share one model: a multi-column :class:`FileListView` for the
Details view and a :class:`IconListView` for the icon and list views.
:class:`FileBrowser` stacks them, keeps one selection between them, and is what
the main window talks to.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from typing import Callable

from PyQt6.QtCore import (
    QAbstractTableModel,
    QMimeData,
    QModelIndex,
    QSize,
    Qt,
    QUrl,
    pyqtSignal,
)
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

from ..core import filetypes
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

#: The widths a fresh installation starts with, and what "Reset the interface"
#: puts back.  QHeaderView.reset() is the model-reset slot and does nothing to
#: section sizes, so resetting has to be spelled out.
DEFAULT_COLUMN_WIDTHS: tuple[tuple[int, int], ...] = (
    (COL_NAME, 230),
    (COL_SIZE, 85),
    (COL_PACKED, 85),
    (COL_TYPE, 120),
    (COL_MODIFIED, 120),
    (COL_CRC, 80),
)

# The Type column names an archive after the program that opens it, the way
# WinRAR's listing does -- "LinRAR archive" rather than "RAR archive" -- so
# these few override the shared table.  Everything else, and there are several
# hundred of them, comes from linrar.core.filetypes, which is also what the
# viewer asks; the column and the viewer can never disagree about what a file
# is because they are reading the same table.
_ARCHIVE_TYPES = {
    ".rar": "LinRAR archive", ".zip": "LinRAR ZIP archive",
    ".7z": "LinRAR archive", ".tar": "LinRAR archive",
    ".gz": "LinRAR archive", ".tgz": "LinRAR archive",
    ".bz2": "LinRAR archive", ".xz": "LinRAR archive",
    ".zst": "LinRAR archive", ".lz": "LinRAR archive", ".lz4": "LinRAR archive",
    ".lzma": "LinRAR archive", ".z": "LinRAR archive",
    ".arj": "LinRAR archive", ".lzh": "LinRAR archive",
    ".cbr": "LinRAR comic book archive", ".cbz": "LinRAR comic book archive",
}


@dataclass
class ListingItem:
    """One row: a disk entry, an archive member, or the ``..`` parent link.

    ``type_name`` and ``icon_name`` are worked out once per row and kept.  Qt
    asks the model for a cell's data every time it paints it, several roles at
    a time, and sorting by Type asks again for every comparison; recomputing
    an answer that cannot change was costing a folder of ten thousand files
    tens of thousands of table lookups per scroll.
    """

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
    #: Filled in on first use; never part of what a caller constructs.
    _type_name: Optional[str] = field(default=None, repr=False, compare=False)
    _icon_name: Optional[str] = field(default=None, repr=False, compare=False)

    @property
    def _identity(self) -> filetypes.FileType:
        """What this entry is.  Consults the disk only when the name cannot say.

        A member of an archive has no path to read, and a name with an
        extension needs no reading, so the overwhelming majority of rows are
        answered without any I/O at all.
        """
        if self.entry is None and self.path and not filetypes.extension_of(self.name):
            return filetypes.identify_file(self.path, self.name)
        return filetypes.by_name(self.name)

    @property
    def type_name(self) -> str:
        if self._type_name is None:
            self._type_name = self._compute_type_name()
        return self._type_name

    def _compute_type_name(self) -> str:
        if self.is_parent:
            return ""
        if self.is_dir:
            return "File folder"
        ext = os.path.splitext(self.name)[1].lower()
        if ext in _ARCHIVE_TYPES:
            return _ARCHIVE_TYPES[ext]
        return self._identity.label

    @property
    def icon_name(self) -> str:
        if self._icon_name is None:
            self._icon_name = self._compute_icon_name()
        return self._icon_name

    def _compute_icon_name(self) -> str:
        if self.is_parent:
            return "folder-up"
        if self.is_dir:
            return "folder"
        # The type table is asked first, and the archive test is the fallback
        # rather than the other way round.  Several extensions are both: an
        # .epub and a .jar are ZIP archives, an .iso is an archive LinRAR
        # opens, and for those the useful drawing is the one that says what
        # the file is *for*, not the one that says how it is stored.
        drawn = filetypes.icon_for(self.name, self._identity.kind)
        if drawn == "file" and looks_like_archive(self.name):
            return "archive-small"
        return drawn


class FileListModel(QAbstractTableModel):
    """Table model backing the browser, with WinRAR's folders-first ordering."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._items: list[ListingItem] = []
        self.archive_mode = False
        self._sort_column = COL_NAME
        self._sort_order = Qt.SortOrder.AscendingOrder
        #: Turns the rows being dragged into real paths on disk.  The main
        #: window installs one that unpacks archive members to a scratch
        #: folder; without it, only disk rows can be dragged out.
        self.drag_paths: Optional[Callable[[list[ListingItem]], list[str]]] = None

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

    # -- dragging out ------------------------------------------------------
    #
    # The views have always had dragging switched on, but a table model with
    # no mime data of its own hands the desktop Qt's private
    # "x-qabstractitemmodeldatalist", which nothing outside the application
    # understands: dropping into a file manager did precisely nothing.  These
    # three methods make a drag out of LinRAR carry real file URLs.

    def flags(self, index: QModelIndex):
        base = super().flags(index)
        if not index.isValid():
            return base
        item = self._items[index.row()]
        if item.is_parent:
            return base
        return base | Qt.ItemFlag.ItemIsDragEnabled

    def mimeTypes(self) -> list[str]:
        return ["text/uri-list"]

    def supportedDragActions(self):
        return Qt.DropAction.CopyAction

    def mimeData(self, indexes):
        rows = sorted({index.row() for index in indexes if index.isValid()})
        items = [
            self._items[row] for row in rows
            if 0 <= row < len(self._items) and not self._items[row].is_parent
        ]
        if not items:
            return None
        if self.archive_mode:
            if self.drag_paths is None:
                return None
            paths = self.drag_paths(items)
        else:
            paths = [item.path for item in items]
        paths = [p for p in paths if p]
        if not paths:
            return None
        data = QMimeData()
        data.setUrls([QUrl.fromLocalFile(path) for path in paths])
        # Both GNOME and KDE read the intended action from this, and without
        # it a drop into Nautilus is offered as a move out of a folder LinRAR
        # may not own.
        data.setData(
            "x-special/gnome-copied-files",
            b"copy\n"
            + "\n".join(
                QUrl.fromLocalFile(path).toString() for path in paths
            ).encode("utf-8"),
        )
        return data

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
        _configure_drag(self)
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
        # A restored header state counts as "once already done", or the widths
        # saved on the way out would be overwritten on the way back in, which
        # is exactly what used to happen, because the first listing is built
        # after the state is restored.
        if not self._columns_ready:
            self.apply_default_widths()

    def apply_default_widths(self) -> None:
        """Put every column back to the width LinRAR ships with."""
        self._columns_ready = True
        for column, width in DEFAULT_COLUMN_WIDTHS:
            self.setColumnWidth(column, width)

    def mark_columns_restored(self) -> None:
        """Note that the widths came from the user's saved header state."""
        self._columns_ready = True

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
        _configure_drag(self)
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
        restored = self.details.header().restoreState(state)
        if restored:
            self.details.mark_columns_restored()
        return restored

    def reset_columns(self) -> None:
        """Forget the saved widths and order, back to how LinRAR ships."""
        header = self.details.header()
        # Put every column back where it started: moveSection works in visual
        # positions, so each logical column is dragged to its own index.
        for logical in range(header.count()):
            visual = header.visualIndex(logical)
            if visual != logical:
                header.moveSection(visual, logical)
        header.setSortIndicator(COL_NAME, Qt.SortOrder.AscendingOrder)
        self.details.apply_default_widths()


class _RowDelegate(QStyledItemDelegate):
    """Adds the chosen breathing room to every row of the Details view."""

    def __init__(self, spacing: int, parent=None) -> None:
        super().__init__(parent)
        self._spacing = max(0, spacing)

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        size.setHeight(size.height() + self._spacing)
        return size


def _configure_drag(view: QAbstractItemView) -> None:
    """Drag out, never drop in.

    Dropping is the *window's* job: it decides between browsing a folder,
    opening an archive and adding files to one, and it can do that wherever
    the pointer lands.  A view that accepted drops itself would swallow them
    (the model has nothing to do with a dropped file) and the window would
    never see them, which is what used to happen over the file list.
    """
    view.setDragEnabled(True)
    view.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
    view.setDefaultDropAction(Qt.DropAction.CopyAction)
    view.setAcceptDrops(False)
    view.setDropIndicatorShown(False)


def _selection(view: QAbstractItemView) -> list[ListingItem]:
    """The rows the user has picked, in listing order.

    Read from the selection's *ranges* rather than from ``selectedIndexes``.
    That call materialises one QModelIndex per cell, so with six columns a
    Select All over ten thousand files built sixty thousand objects to answer
    a question about ten thousand rows, every time the selection changed.  The
    ranges give the same answer in one step per contiguous block.
    """
    model = view.model()
    if not isinstance(model, FileListModel):
        return []
    selection = view.selectionModel()
    if selection is None:
        return []
    rows: set[int] = set()
    for span in selection.selection():
        rows.update(range(span.top(), span.bottom() + 1))
    items = [model.item_at(row) for row in sorted(rows)]
    return [i for i in items if i is not None and not i.is_parent]


def _icon_size():
    return QSize(16, 16)
