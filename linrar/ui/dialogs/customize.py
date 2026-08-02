"""Customize: the toolbar, the file list and the window layout in one sheet.

Everything here writes straight to :data:`SETTINGS`; the main window reads them
back when :meth:`applied` fires, so Apply shows the result without closing.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...core.settings import DEFAULT_TOOLBAR, SETTINGS
from .. import filelist, icons, policy

_KEY_ROLE = Qt.ItemDataRole.UserRole
_SEPARATOR = "|"


class CustomizeDialog(QDialog):
    """Options > Customize."""

    #: Emitted when Apply is pressed, after the settings have been written.
    applied = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Customize LinRAR")
        self.setWindowIcon(icons.icon("settings"))
        self.resize(620, 560)

        self.window_ref = parent

        #: Keys an administrator locked, collected as the tabs are built.
        self.locked: list[str] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(9)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_toolbar_tab(), "Toolbar")
        self.tabs.addTab(self._build_list_tab(), "File list")
        self.tabs.addTab(self._build_layout_tab(), "Layout")
        self.lock_banner = policy.banner(self.locked, self)
        if self.lock_banner is not None:
            layout.addWidget(self.lock_banner)
        layout.addWidget(self.tabs, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Apply
            | QDialogButtonBox.StandardButton.RestoreDefaults
        )
        buttons.accepted.connect(self._on_ok)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(
            self._on_apply
        )
        buttons.button(
            QDialogButtonBox.StandardButton.RestoreDefaults
        ).clicked.connect(self._restore_defaults)
        layout.addWidget(buttons)

    # -- toolbar tab -------------------------------------------------------

    def _build_toolbar_tab(self) -> QWidget:
        from ..main_window import (
            TOOLBAR_CATALOGUE,
            TOOLBAR_ICON_SIZES,
            TOOLBAR_STYLE_LABELS,
        )

        self._catalogue = TOOLBAR_CATALOGUE
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        hint = QLabel(
            "Pick the buttons the toolbar shows and the order they appear in. "
            "Drag inside the right-hand list to rearrange."
        )
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        columns = QHBoxLayout()
        columns.setSpacing(8)

        available_box = QVBoxLayout()
        available_box.addWidget(QLabel("Available buttons"))
        self.available_list = QListWidget()
        self.available_list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.available_list.itemDoubleClicked.connect(lambda _i: self._add())
        available_box.addWidget(self.available_list, 1)
        columns.addLayout(available_box, 1)

        middle = QVBoxLayout()
        middle.addStretch(1)
        self._arrange_buttons: list[QPushButton] = []
        for label, slot in (
            ("Add →", self._add),
            ("← Remove", self._remove),
            ("Separator", self._add_separator),
        ):
            button = QPushButton(label)
            button.setMinimumWidth(96)
            button.clicked.connect(slot)
            middle.addWidget(button)
            self._arrange_buttons.append(button)
        middle.addSpacing(10)
        for label, slot in (("Move up", self._move_up),
                            ("Move down", self._move_down)):
            button = QPushButton(label)
            button.setMinimumWidth(96)
            button.clicked.connect(slot)
            middle.addWidget(button)
            self._arrange_buttons.append(button)
        middle.addStretch(1)
        columns.addLayout(middle, 0)

        shown_box = QVBoxLayout()
        shown_box.addWidget(QLabel("Shown on the toolbar"))
        self.shown_list = QListWidget()
        self.shown_list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.shown_list.setDragDropMode(
            QAbstractItemView.DragDropMode.InternalMove
        )
        self.shown_list.itemDoubleClicked.connect(lambda _i: self._remove())
        shown_box.addWidget(self.shown_list, 1)
        columns.addLayout(shown_box, 1)
        layout.addLayout(columns, 1)

        appearance = QGroupBox("Buttons")
        form = QFormLayout(appearance)
        self.icon_size_combo = QComboBox()
        for size in TOOLBAR_ICON_SIZES:
            self.icon_size_combo.addItem(f"{size} × {size} pixels", size)
        current_size = int(SETTINGS.get("toolbar/icon_size"))
        index = self.icon_size_combo.findData(current_size)
        self.icon_size_combo.setCurrentIndex(max(index, 0))
        form.addRow("Icon size", self.icon_size_combo)

        self.style_combo = QComboBox()
        for key, label in TOOLBAR_STYLE_LABELS.items():
            self.style_combo.addItem(label, key)
        index = self.style_combo.findData(SETTINGS.get("toolbar/style"))
        self.style_combo.setCurrentIndex(max(index, 0))
        form.addRow("Captions", self.style_combo)
        layout.addWidget(appearance)

        self.locked += policy.guard_all({
            "toolbar/icon_size": self.icon_size_combo,
            "toolbar/style": self.style_combo,
        })
        if SETTINGS.is_locked("toolbar/items"):
            # The two lists and every button between them are one setting.
            for widget in (self.available_list, self.shown_list,
                           *self._arrange_buttons):
                policy.guard(widget, "toolbar/items")
            self.locked.append("toolbar/items")

        self._fill_toolbar_lists(SETTINGS.string_list("toolbar/items"))
        return page

    def _fill_toolbar_lists(self, items: list[str]) -> None:
        captions = {key: caption for key, _attr, caption in self._catalogue}
        self.shown_list.clear()
        self.available_list.clear()
        for key in items:
            if key == _SEPARATOR:
                self.shown_list.addItem(_make_item(_SEPARATOR, captions))
            elif key in captions:
                self.shown_list.addItem(_make_item(key, captions))
        used = {key for key in items if key != _SEPARATOR}
        for key, _attr, _caption in self._catalogue:
            if key not in used:
                self.available_list.addItem(_make_item(key, captions))

    def _current_items(self) -> list[str]:
        return [
            self.shown_list.item(row).data(_KEY_ROLE)
            for row in range(self.shown_list.count())
        ]

    def _add(self) -> None:
        for item in self.available_list.selectedItems():
            self.shown_list.addItem(
                self.available_list.takeItem(self.available_list.row(item))
            )

    def _remove(self) -> None:
        captions = {key: caption for key, _attr, caption in self._catalogue}
        for item in self.shown_list.selectedItems():
            key = item.data(_KEY_ROLE)
            self.shown_list.takeItem(self.shown_list.row(item))
            if key != _SEPARATOR:
                self.available_list.addItem(_make_item(key, captions))

    def _add_separator(self) -> None:
        captions = {key: caption for key, _attr, caption in self._catalogue}
        row = self.shown_list.currentRow()
        item = _make_item(_SEPARATOR, captions)
        self.shown_list.insertItem(
            row + 1 if row >= 0 else self.shown_list.count(), item
        )
        self.shown_list.setCurrentItem(item)

    def _move_up(self) -> None:
        self._move(-1)

    def _move_down(self) -> None:
        self._move(1)

    def _move(self, delta: int) -> None:
        row = self.shown_list.currentRow()
        target = row + delta
        if row < 0 or not 0 <= target < self.shown_list.count():
            return
        item = self.shown_list.takeItem(row)
        self.shown_list.insertItem(target, item)
        self.shown_list.setCurrentRow(target)

    # -- file list tab -----------------------------------------------------

    def _build_list_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        mode_box = QGroupBox("View")
        mode_layout = QVBoxLayout(mode_box)
        mode_layout.setSpacing(3)
        self.mode_buttons: dict[str, QRadioButton] = {}
        current_mode = SETTINGS.get("view/mode")
        for name in filelist.VIEW_MODES:
            button = QRadioButton(filelist.VIEW_LABELS[name].replace("&", ""))
            button.setChecked(name == current_mode)
            mode_layout.addWidget(button)
            self.mode_buttons[name] = button
        layout.addWidget(mode_box)

        rows_box = QGroupBox("Rows")
        rows_form = QFormLayout(rows_box)
        self.row_height_combo = QComboBox()
        for key, label in (("compact", "Compact"), ("normal", "Normal"),
                           ("relaxed", "Relaxed")):
            self.row_height_combo.addItem(label, key)
        index = self.row_height_combo.findData(SETTINGS.get("view/row_height"))
        self.row_height_combo.setCurrentIndex(max(index, 0))
        rows_form.addRow("Row height", self.row_height_combo)

        self.grid_check = QCheckBox("Draw a line between rows")
        self.grid_check.setChecked(bool(SETTINGS.get("view/grid_lines")))
        rows_form.addRow(self.grid_check)
        self.alternate_check = QCheckBox("Shade every other row")
        self.alternate_check.setChecked(
            bool(SETTINGS.get("view/alternate_rows"))
        )
        rows_form.addRow(self.alternate_check)
        self.hidden_check = QCheckBox("Show hidden files and folders")
        self.hidden_check.setChecked(bool(SETTINGS.get("view/show_hidden")))
        rows_form.addRow(self.hidden_check)
        layout.addWidget(rows_box)

        columns_box = QGroupBox("Columns (Details view)")
        columns_layout = QVBoxLayout(columns_box)
        columns_layout.setSpacing(3)
        self.column_checks: dict[int, QCheckBox] = {}
        browser = getattr(self.window_ref, "list_view", None)
        for column, label in enumerate(filelist.HEADERS):
            if column == 0:
                continue  # Name is mandatory
            check = QCheckBox(label)
            if browser is not None:
                check.setChecked(not browser.isColumnHidden(column))
            columns_layout.addWidget(check)
            self.column_checks[column] = check
        layout.addWidget(columns_box)

        self.locked += policy.guard_all({
            "view/row_height": self.row_height_combo,
            "view/grid_lines": self.grid_check,
            "view/alternate_rows": self.alternate_check,
            "view/show_hidden": self.hidden_check,
        })
        if SETTINGS.is_locked("view/mode"):
            for button in self.mode_buttons.values():
                policy.guard(button, "view/mode")
            self.locked.append("view/mode")

        layout.addStretch(1)
        return page

    # -- layout tab --------------------------------------------------------

    def _build_layout_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        bars = QGroupBox("Bars")
        bars_layout = QVBoxLayout(bars)
        bars_layout.setSpacing(3)
        self.toolbar_check = QCheckBox("Toolbar")
        self.toolbar_check.setChecked(bool(SETTINGS.get("view/show_toolbar")))
        self.address_check = QCheckBox("Address bar")
        self.address_check.setChecked(bool(SETTINGS.get("view/show_address")))
        self.status_check = QCheckBox("Status bar")
        self.status_check.setChecked(bool(SETTINGS.get("view/show_status")))
        for check in (self.toolbar_check, self.address_check, self.status_check):
            bars_layout.addWidget(check)
        bars_form = QFormLayout()
        self.toolbar_area_combo = QComboBox()
        self.toolbar_area_combo.addItem("Top of the window", "top")
        self.toolbar_area_combo.addItem("Bottom of the window", "bottom")
        index = self.toolbar_area_combo.findData(
            SETTINGS.get("view/toolbar_area")
        )
        self.toolbar_area_combo.setCurrentIndex(max(index, 0))
        bars_form.addRow("Toolbar position", self.toolbar_area_combo)
        bars_layout.addLayout(bars_form)
        layout.addWidget(bars)

        panes = QGroupBox("Panes")
        panes_form = QFormLayout(panes)
        self.tree_check = QCheckBox("Show the folder tree")
        self.tree_check.setChecked(bool(SETTINGS.get("view/show_tree")))
        panes_form.addRow(self.tree_check)
        self.tree_side_combo = QComboBox()
        self.tree_side_combo.addItem("Left of the file list", "left")
        self.tree_side_combo.addItem("Right of the file list", "right")
        index = self.tree_side_combo.findData(SETTINGS.get("view/tree_side"))
        self.tree_side_combo.setCurrentIndex(max(index, 0))
        panes_form.addRow("Folder tree", self.tree_side_combo)

        self.comment_check = QCheckBox("Show the comment pane")
        self.comment_check.setChecked(bool(SETTINGS.get("view/show_comment")))
        panes_form.addRow(self.comment_check)
        self.comment_side_combo = QComboBox()
        self.comment_side_combo.addItem("Below the file list", "bottom")
        self.comment_side_combo.addItem("Above the file list", "top")
        index = self.comment_side_combo.findData(
            SETTINGS.get("view/comment_side")
        )
        self.comment_side_combo.setCurrentIndex(max(index, 0))
        panes_form.addRow("Comment pane", self.comment_side_combo)
        layout.addWidget(panes)

        note = QLabel(
            "Window size, splitter positions and column widths are remembered "
            "as you change them. Restore Defaults puts all of it back."
        )
        note.setObjectName("Hint")
        note.setWordWrap(True)
        layout.addWidget(note)

        self.locked += policy.guard_all({
            "view/show_toolbar": self.toolbar_check,
            "view/show_address": self.address_check,
            "view/show_status": self.status_check,
            "view/toolbar_area": self.toolbar_area_combo,
            "view/show_tree": self.tree_check,
            "view/tree_side": self.tree_side_combo,
            "view/show_comment": self.comment_check,
            "view/comment_side": self.comment_side_combo,
        })

        layout.addStretch(1)
        return page

    # -- result ------------------------------------------------------------

    def _save(self) -> None:
        items = self._current_items()
        # A toolbar of nothing but separators would leave a blank bar.
        if not [key for key in items if key != _SEPARATOR]:
            items = list(DEFAULT_TOOLBAR)
        SETTINGS.set("toolbar/items", items)
        SETTINGS.set("toolbar/icon_size", self.icon_size_combo.currentData())
        SETTINGS.set("toolbar/style", self.style_combo.currentData())

        for name, button in self.mode_buttons.items():
            if button.isChecked():
                SETTINGS.set("view/mode", name)
                break
        SETTINGS.set("view/row_height", self.row_height_combo.currentData())
        SETTINGS.set("view/grid_lines", self.grid_check.isChecked())
        SETTINGS.set("view/alternate_rows", self.alternate_check.isChecked())
        SETTINGS.set("view/show_hidden", self.hidden_check.isChecked())

        browser = getattr(self.window_ref, "list_view", None)
        if browser is not None:
            for column, check in self.column_checks.items():
                browser.setColumnHidden(column, not check.isChecked())

        SETTINGS.set("view/show_toolbar", self.toolbar_check.isChecked())
        SETTINGS.set("view/show_address", self.address_check.isChecked())
        SETTINGS.set("view/show_status", self.status_check.isChecked())
        SETTINGS.set("view/toolbar_area", self.toolbar_area_combo.currentData())
        SETTINGS.set("view/show_tree", self.tree_check.isChecked())
        SETTINGS.set("view/tree_side", self.tree_side_combo.currentData())
        SETTINGS.set("view/show_comment", self.comment_check.isChecked())
        SETTINGS.set("view/comment_side", self.comment_side_combo.currentData())
        SETTINGS.sync()

    def _on_apply(self) -> None:
        self._save()
        self.applied.emit()

    def _on_ok(self) -> None:
        self._save()
        self.accept()

    def _restore_defaults(self) -> None:
        SETTINGS.reset(
            "toolbar/items", "toolbar/icon_size", "toolbar/style",
            "view/mode", "view/tree_side", "view/comment_side",
            "view/show_toolbar", "view/show_address", "view/show_status",
            "view/toolbar_area", "view/row_height", "view/grid_lines",
            "view/alternate_rows", "view/show_tree", "view/show_comment",
        )
        SETTINGS.sync()
        self._reload()
        self.applied.emit()

    def _reload(self) -> None:
        """Pull every control back from the settings after a reset."""
        self._fill_toolbar_lists(SETTINGS.string_list("toolbar/items"))
        self.icon_size_combo.setCurrentIndex(
            max(self.icon_size_combo.findData(
                int(SETTINGS.get("toolbar/icon_size"))), 0)
        )
        self.style_combo.setCurrentIndex(
            max(self.style_combo.findData(SETTINGS.get("toolbar/style")), 0)
        )
        for name, button in self.mode_buttons.items():
            button.setChecked(name == SETTINGS.get("view/mode"))
        self.row_height_combo.setCurrentIndex(
            max(self.row_height_combo.findData(
                SETTINGS.get("view/row_height")), 0)
        )
        self.grid_check.setChecked(bool(SETTINGS.get("view/grid_lines")))
        self.alternate_check.setChecked(
            bool(SETTINGS.get("view/alternate_rows"))
        )
        self.toolbar_check.setChecked(bool(SETTINGS.get("view/show_toolbar")))
        self.address_check.setChecked(bool(SETTINGS.get("view/show_address")))
        self.status_check.setChecked(bool(SETTINGS.get("view/show_status")))
        self.toolbar_area_combo.setCurrentIndex(
            max(self.toolbar_area_combo.findData(
                SETTINGS.get("view/toolbar_area")), 0)
        )
        self.tree_check.setChecked(bool(SETTINGS.get("view/show_tree")))
        self.tree_side_combo.setCurrentIndex(
            max(self.tree_side_combo.findData(SETTINGS.get("view/tree_side")), 0)
        )
        self.comment_check.setChecked(bool(SETTINGS.get("view/show_comment")))
        self.comment_side_combo.setCurrentIndex(
            max(self.comment_side_combo.findData(
                SETTINGS.get("view/comment_side")), 0)
        )


def _make_item(key: str, captions: dict[str, str]) -> QListWidgetItem:
    if key == _SEPARATOR:
        item = QListWidgetItem("—  Separator  —")
    else:
        item = QListWidgetItem(icons.icon(_ICONS.get(key, "")), captions[key])
    item.setData(_KEY_ROLE, key)
    return item


#: The toolbar catalogue keeps captions; the icons live here so the picker can
#: show the same glyph the button will.
_ICONS = {
    "add": "add", "extract_to": "extract-to", "extract_here": "extract",
    "test": "test", "view": "view", "delete": "delete", "rename": "file",
    "find": "find", "wizard": "wizard", "info": "info", "properties": "info",
    "repair": "repair", "comment": "comment", "protect": "protect",
    "lock": "lock", "sfx": "sfx", "convert": "convert", "report": "view",
    "open": "archive-small", "close": "archive-small", "up": "up",
    "refresh": "refresh", "new_folder": "folder", "change_folder": "disk",
    "favorite": "folder", "password": "key", "passwords": "key",
    "profiles": "add", "benchmark": "test", "dependencies": "package",
    "settings": "settings", "customize": "settings", "help": "help",
}
