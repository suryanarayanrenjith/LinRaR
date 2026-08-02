"""The LinRAR main window: file manager and archive browser in one."""

from __future__ import annotations

import fnmatch
import getpass
import os
import shlex
import shutil
import tempfile
from datetime import datetime
from typing import Callable, Optional

from PyQt6.QtCore import QSize, Qt, QUrl
from PyQt6.QtGui import QAction, QActionGroup, QDesktopServices, QKeySequence
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QLineEdit,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QSplitter,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..core.backends.base import TaskContext
from ..core.models import (
    ArchiveFormat,
    ArchiveInfo,
    CompressOptions,
    ExtractOptions,
    OperationError,
    OverwriteMode,
    PasswordRequired,
    format_size,
)
from ..core import sfx
from ..core.profiles import PROFILES, Profile
from ..core import elevation, packages
from ..core.registry import REGISTRY, detect_format, looks_like_archive
from ..core.settings import DEFAULT_TOOLBAR, SETTINGS
from ..core.tasks import Task
from . import icons, policy, theme
from .dialogs.archive import ArchiveDialog
from .dialogs.conflict import resolve_conflicts
from .dialogs.convert import ConvertDialog
from .dialogs.customize import CustomizeDialog
from .dialogs.dependencies import DependenciesDialog
from .dialogs.extract import ExtractDialog
from .dialogs.sfx import SfxDialog
from .dialogs.tools import (
    FavoritesDialog,
    PasswordManagerDialog,
    ProfileDialog,
    PropertiesDialog,
    ReportDialog,
)
from .dialogs.wizard import WizardDialog
from .dialogs.misc import (
    AboutDialog,
    BenchmarkDialog,
    CommentDialog,
    FindDialog,
    HelpDialog,
    InfoDialog,
    SettingsDialog,
    ViewerDialog,
)
from .dialogs.password import PasswordDialog
from .dialogs.progress import ProgressDialog
from . import filelist
from .filelist import FileBrowser, FileListModel, ListingItem
from .foldertree import FolderTree

#: Everything the toolbar can hold: key, action attribute, short caption.
#: The Customize dialog offers exactly this list, in this order.
TOOLBAR_CATALOGUE: list[tuple[str, str, str]] = [
    ("add", "act_add", "Add"),
    ("extract_to", "act_extract_to", "Extract To"),
    ("extract_here", "act_extract_here", "Extract"),
    ("test", "act_test", "Test"),
    ("view", "act_view", "View"),
    ("delete", "act_delete", "Delete"),
    ("rename", "act_rename", "Rename"),
    ("find", "act_find", "Find"),
    ("wizard", "act_wizard", "Wizard"),
    ("info", "act_info", "Info"),
    ("properties", "act_properties", "Properties"),
    ("repair", "act_repair", "Repair"),
    ("comment", "act_comment", "Comment"),
    ("protect", "act_protect", "Protect"),
    ("lock", "act_lock", "Lock"),
    ("sfx", "act_sfx", "SFX"),
    ("convert", "act_convert_archives", "Convert"),
    ("report", "act_report", "Report"),
    ("open", "act_open", "Open"),
    ("close", "act_close", "Close"),
    ("up", "act_up", "Up"),
    ("refresh", "act_refresh", "Refresh"),
    ("new_folder", "act_new_folder", "New Folder"),
    ("change_folder", "act_change_folder", "Folder"),
    ("favorite", "act_add_favorite", "Favorite"),
    ("password", "act_password", "Password"),
    ("passwords", "act_passwords", "Passwords"),
    ("profiles", "act_profiles", "Profiles"),
    ("benchmark", "act_benchmark", "Benchmark"),
    ("dependencies", "act_dependencies", "Deps"),
    ("settings", "act_settings", "Settings"),
    ("customize", "act_customize", "Customize"),
    ("help", "act_help_topics", "Help"),
    ("theme", "act_toggle_theme", "Theme"),
]

TOOLBAR_STYLES: dict[str, Qt.ToolButtonStyle] = {
    "under": Qt.ToolButtonStyle.ToolButtonTextUnderIcon,
    "beside": Qt.ToolButtonStyle.ToolButtonTextBesideIcon,
    "icon": Qt.ToolButtonStyle.ToolButtonIconOnly,
    "text": Qt.ToolButtonStyle.ToolButtonTextOnly,
}
TOOLBAR_STYLE_LABELS = {
    "under": "Text under the icon",
    "beside": "Text beside the icon",
    "icon": "Icon only",
    "text": "Text only",
}
TOOLBAR_ICON_SIZES = (16, 24, 32, 48)


class MainWindow(QMainWindow):
    """The application shell: a disk browser that turns into an archive browser."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("LinRAR")
        self.setWindowIcon(icons.icon("app"))
        self.resize(940, 620)
        self.setAcceptDrops(True)

        # -- state --
        self.current_folder: str = SETTINGS.get("places/last_folder")
        if not os.path.isdir(self.current_folder):
            self.current_folder = os.path.expanduser("~")
        self.archive_path: Optional[str] = None
        self.archive_info: Optional[ArchiveInfo] = None
        self.archive_folder: str = ""
        self.password: Optional[str] = None
        self._filter: Optional[Callable[[ListingItem], bool]] = None
        self._task: Optional[Task] = None
        self._background_tasks: list[Task] = []
        self._temp_dirs: list[str] = []
        self._pending_cut: list[str] = []
        self._pending_profile: Optional[Profile] = None

        # The body must exist before the menus: the file-list and column menus
        # are built from the live view.
        self._build_actions()
        self._build_body()
        self._build_menus()
        self._build_toolbar()
        self._build_status_bar()
        # Anything an administrator locked must not look clickable.
        self._apply_policy()

        geometry = SETTINGS.load_geometry("main")
        if geometry:
            self.restoreGeometry(geometry)
        splitter_state = SETTINGS.load_geometry("splitter")
        if splitter_state:
            self.splitter.restoreState(splitter_state)

        self.navigate_to(self.current_folder)
        # Every saved appearance choice is applied on the way in.
        self.apply_layout()
        self.apply_view_options()
        self.sort_by(
            int(SETTINGS.get("view/sort_column")),
            bool(SETTINGS.get("view/sort_descending")),
        )

    # ------------------------------------------------------------------
    # construction
    # ------------------------------------------------------------------

    def _act(
        self,
        text: str,
        icon: str = "",
        shortcut: str = "",
        slot: Optional[Callable] = None,
        tip: str = "",
        checkable: bool = False,
    ) -> QAction:
        action = QAction(text, self)
        if icon:
            action.setIcon(icons.icon(icon))
            # Remembered so every action can be re-iconed when the theme flips.
            action.setProperty("iconName", icon)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        if slot:
            action.triggered.connect(slot)
        action.setStatusTip(tip or text.replace("&", ""))
        action.setCheckable(checkable)
        return action

    def _build_actions(self) -> None:
        self.act_add = self._act(
            "&Add files to archive", "add", "Alt+A", self.cmd_add,
            "Add the selected files to an archive",
        )
        self.act_extract_to = self._act(
            "&Extract files", "extract-to", "Alt+E", self.cmd_extract_to,
            "Extract files to a folder you choose",
        )
        self.act_extract_here = self._act(
            "Extract to the current folder", "extract", "Alt+W",
            self.cmd_extract_here,
        )
        self.act_test = self._act(
            "&Test archived files", "test", "Alt+T", self.cmd_test,
            "Check the archive for errors",
        )
        self.act_view = self._act(
            "&View file", "view", "Alt+V", self.cmd_view,
            "Show the contents of the selected file",
        )
        self.act_delete = self._act(
            "&Delete files", "delete", "Del", self.cmd_delete,
        )
        self.act_rename = self._act("Rena&me file", "", "F2", self.cmd_rename)
        self.act_find = self._act(
            "&Find files", "find", "Ctrl+F", self.cmd_find,
        )
        self.act_wizard = self._act(
            "&Wizard", "wizard", "", self.cmd_wizard,
            "Step-by-step help with common tasks",
        )
        self.act_info = self._act(
            "&Information", "info", "Alt+I", self.cmd_info,
            "Show archive information",
        )
        self.act_repair = self._act(
            "Repai&r archive", "repair", "Alt+R", self.cmd_repair,
        )
        self.act_comment = self._act(
            "Add archive &comment", "comment", "Alt+M", self.cmd_comment,
        )
        self.act_protect = self._act(
            "&Protect archive", "protect", "Alt+P", self.cmd_protect,
            "Add a recovery record so damage can be repaired",
        )
        self.act_sfx = self._act(
            "Convert to &AppImage (SFX)", "sfx", "Alt+S", self.cmd_sfx,
            "Build a self-extracting, self-running AppImage",
        )
        self.act_sfx_stub = self._act(
            "Convert to RAR .sfx stub", "sfx", "", self.cmd_sfx_stub,
            "Use rar's own Linux self-extracting stub instead of an AppImage",
        )
        self.act_help_topics = self._act(
            "&Help topics", "help", "F1", self.cmd_help_topics,
            "How to use LinRAR",
        )
        self.act_shortcuts = self._act(
            "&Keyboard shortcuts", "", "Shift+F1", self.cmd_shortcuts
        )
        self.act_lock = self._act(
            "&Lock archive", "lock", "", self.cmd_lock,
            "Prevent any further changes to the archive",
        )
        self.act_convert = self._act(
            "Con&vert archive", "convert", "", self.cmd_convert,
            "Rebuild the archive in another format",
        )
        self.act_password = self._act(
            "Set defau&lt password", "key", "Ctrl+P", self.cmd_password,
        )

        self.act_open = self._act(
            "&Open archive...", "archive-small", "Ctrl+O", self.cmd_open_archive
        )
        self.act_close = self._act("&Close archive", "", "Ctrl+W", self.close_archive)
        self.act_up = self._act("&Up one level", "up", "Backspace", self.go_up)
        self.act_refresh = self._act("&Refresh", "refresh", "F5", self.refresh)
        self.act_select_all = self._act(
            "Select &all", "", "Ctrl+A", self.cmd_select_all
        )
        self.act_exit = self._act("E&xit", "", "Ctrl+Q", self.close)

        self.act_show_tree = self._act(
            "&Folder tree", "", "Ctrl+T", self.toggle_tree, checkable=True
        )
        self.act_show_tree.setChecked(SETTINGS.get("view/show_tree"))
        self.act_show_comment = self._act(
            "&Comment pane", "", "", self.toggle_comment, checkable=True
        )
        self.act_show_comment.setChecked(SETTINGS.get("view/show_comment"))
        self.act_toolbar_text = self._act(
            "Toolbar &button text", "", "", self.toggle_toolbar_text, checkable=True
        )
        self.act_toolbar_text.setChecked(SETTINGS.get("toolbar/style") != "icon")
        self.act_show_hidden = self._act(
            "Show &hidden files", "", "Ctrl+H", self.toggle_hidden, checkable=True
        )
        self.act_show_hidden.setChecked(SETTINGS.get("view/show_hidden"))

        # -- appearance --
        self.theme_actions: dict[str, QAction] = {}
        theme_group = QActionGroup(self)
        theme_group.setExclusive(True)
        for name, label in (
            (theme.LIGHT, "&Light theme"),
            (theme.DARK, "&Dark theme"),
        ):
            action = self._act(
                label, f"theme-{name}", "",
                lambda _checked=False, m=name: self.set_theme(m),
                f"Use the {theme.MODE_LABELS[name].lower()} colour scheme",
                checkable=True,
            )
            action.setChecked(name == theme.mode())
            theme_group.addAction(action)
            self.theme_actions[name] = action
        self.act_toggle_theme = self._act(
            "Switch theme", "theme-dark", "Ctrl+Shift+T", self.toggle_theme,
            "Switch between the light and dark theme",
        )

        self.act_settings = self._act("&Settings...", "", "Ctrl+S", self.cmd_settings)
        self.act_dependencies = self._act(
            "&Dependencies...", "package", "", self.cmd_dependencies,
            "Install or remove the command line tools LinRAR uses",
        )

        # -- selection (WinRAR's grey +, -, * on the numeric keypad) --
        self.act_select_group = self._act(
            "Select &group...", "", "+", self.cmd_select_group
        )
        self.act_deselect_group = self._act(
            "&Deselect group...", "", "-", self.cmd_deselect_group
        )
        self.act_invert = self._act(
            "&Invert selection", "", "*", self.cmd_invert_selection
        )

        # -- file manager operations --
        self.act_new_folder = self._act(
            "New &folder", "folder", "F7", self.cmd_new_folder
        )
        self.act_copy = self._act("&Copy", "", "Ctrl+C", self.cmd_copy)
        self.act_cut = self._act("Cu&t", "", "Ctrl+X", self.cmd_cut)
        self.act_paste = self._act("&Paste", "", "Ctrl+V", self.cmd_paste)
        self.act_copy_path = self._act(
            "Copy &path to clipboard", "", "Ctrl+Shift+C", self.cmd_copy_path
        )
        self.act_properties = self._act(
            "P&roperties", "info", "Alt+Return", self.cmd_properties
        )

        # -- new commands --
        self.act_convert_archives = self._act(
            "Con&vert archives...", "convert", "Alt+Q", self.cmd_convert_archives,
            "Convert archives to another format",
        )
        self.act_report = self._act(
            "&Generate report...", "view", "Alt+G", self.cmd_report,
            "Save a listing of the archive contents",
        )
        self.act_profiles = self._act(
            "Compression &profiles...", "add", "Alt+C", self.cmd_profiles
        )
        self.act_passwords = self._act(
            "&Organize passwords...", "key", "", self.cmd_passwords
        )
        self.act_organize_favorites = self._act(
            "&Organize favorites...", "folder", "Alt+O", self.cmd_organize_favorites
        )
        self.act_recovery_volumes = self._act(
            "Add recovery &volumes...", "protect", "", self.cmd_recovery_volumes,
            "Create .rev files that can rebuild missing volumes",
        )
        self.act_reconstruct = self._act(
            "&Reconstruct missing volumes", "repair", "", self.cmd_reconstruct,
            "Rebuild missing parts of a volume set from its .rev files",
        )
        self.act_save_as = self._act(
            "&Save file as...", "", "Ctrl+Shift+S", self.cmd_save_as,
            "Save the selected archived file to disk",
        )

        # -- file list view modes --
        self.view_mode_actions: dict[str, QAction] = {}
        view_group = QActionGroup(self)
        view_group.setExclusive(True)
        saved_mode = SETTINGS.get("view/mode")
        for index, name in enumerate(filelist.VIEW_MODES):
            action = self._act(
                filelist.VIEW_LABELS[name], "", f"Ctrl+{index + 1}",
                lambda _c=False, m=name: self.set_view_mode(m),
                f"Show the file list as {filelist.VIEW_LABELS[name].replace('&', '').lower()}",
                checkable=True,
            )
            action.setChecked(name == saved_mode)
            view_group.addAction(action)
            self.view_mode_actions[name] = action

        # -- customization --
        self.act_customize = self._act(
            "&Customize...", "settings", "Ctrl+U", self.cmd_customize,
            "Choose toolbar buttons, file list style and window layout",
        )
        self.act_reset_layout = self._act(
            "&Reset the interface", "refresh", "", self.cmd_reset_layout,
            "Put the toolbar, file list and layout back to their defaults",
        )
        self.act_show_toolbar = self._act(
            "&Toolbar", "", "", self.toggle_toolbar, checkable=True
        )
        self.act_show_toolbar.setChecked(SETTINGS.get("view/show_toolbar"))
        self.act_show_address = self._act(
            "&Address bar", "", "", self.toggle_address_bar, checkable=True
        )
        self.act_show_address.setChecked(SETTINGS.get("view/show_address"))
        self.act_show_status = self._act(
            "St&atus bar", "", "", self.toggle_status_bar, checkable=True
        )
        self.act_show_status.setChecked(SETTINGS.get("view/show_status"))
        self.act_grid_lines = self._act(
            "&Row separators", "", "", self.toggle_grid_lines, checkable=True
        )
        self.act_grid_lines.setChecked(SETTINGS.get("view/grid_lines"))
        self.act_alternate_rows = self._act(
            "A&lternating row colours", "", "", self.toggle_alternate_rows,
            checkable=True,
        )
        self.act_alternate_rows.setChecked(SETTINGS.get("view/alternate_rows"))

        self.tree_side_actions: dict[str, QAction] = {}
        tree_group = QActionGroup(self)
        for side, label in (("left", "Tree on the &left"),
                            ("right", "Tree on the &right")):
            action = self._act(
                label, "", "", lambda _c=False, s=side: self.set_tree_side(s),
                checkable=True,
            )
            action.setChecked(SETTINGS.get("view/tree_side") == side)
            tree_group.addAction(action)
            self.tree_side_actions[side] = action

        self.comment_side_actions: dict[str, QAction] = {}
        comment_group = QActionGroup(self)
        for side, label in (("bottom", "Comment pane at the &bottom"),
                            ("top", "Comment pane at the &top")):
            action = self._act(
                label, "", "",
                lambda _c=False, s=side: self.set_comment_side(s),
                checkable=True,
            )
            action.setChecked(SETTINGS.get("view/comment_side") == side)
            comment_group.addAction(action)
            self.comment_side_actions[side] = action
        self.act_benchmark = self._act("&Benchmark", "test", "", self.cmd_benchmark)
        self.act_about = self._act("&About LinRAR", "app", "", self.cmd_about)
        self.act_add_favorite = self._act(
            "&Add to favorites", "", "Ctrl+D", self.cmd_add_favorite
        )

    def _build_menus(self) -> None:
        bar = self.menuBar()

        file_menu = bar.addMenu("&File")
        file_menu.addAction(self.act_open)
        file_menu.addAction(self.act_close)
        file_menu.addSeparator()
        file_menu.addAction(self.act_up)
        file_menu.addAction(self.act_refresh)
        self.act_change_folder = self._act(
            "Change &folder...", "disk", "Ctrl+D", self.cmd_change_folder
        )
        file_menu.addAction(self.act_change_folder)
        file_menu.addSeparator()
        file_menu.addAction(self.act_select_all)
        file_menu.addAction(self.act_select_group)
        file_menu.addAction(self.act_deselect_group)
        file_menu.addAction(self.act_invert)
        file_menu.addSeparator()
        file_menu.addAction(self.act_copy_path)
        file_menu.addAction(self.act_password)
        file_menu.addSeparator()
        file_menu.addAction(self.act_exit)

        commands = bar.addMenu("&Commands")
        for action in (
            self.act_add,
            self.act_extract_to,
            self.act_extract_here,
            self.act_test,
            self.act_view,
            self.act_save_as,
            self.act_delete,
            self.act_rename,
        ):
            commands.addAction(action)
        commands.addSeparator()
        for action in (
            self.act_new_folder,
            self.act_copy,
            self.act_cut,
            self.act_paste,
        ):
            commands.addAction(action)
        commands.addSeparator()
        for action in (
            self.act_find,
            self.act_info,
            self.act_properties,
            self.act_comment,
        ):
            commands.addAction(action)
        commands.addSeparator()
        protect_menu = commands.addMenu(icons.icon("protect"), "Protect and repair")
        protect_menu.menuAction().setProperty("iconName", "protect")
        protect_menu.addAction(self.act_protect)
        protect_menu.addAction(self.act_recovery_volumes)
        protect_menu.addAction(self.act_reconstruct)
        protect_menu.addAction(self.act_repair)
        protect_menu.addAction(self.act_lock)
        commands.addAction(self.act_sfx)
        commands.addAction(self.act_sfx_stub)

        tools = bar.addMenu("&Tools")
        tools.addAction(self.act_wizard)
        tools.addSeparator()
        tools.addAction(self.act_convert_archives)
        tools.addAction(self.act_report)
        tools.addAction(self.act_repair)
        tools.addSeparator()
        tools.addAction(self.act_passwords)
        tools.addAction(self.act_profiles)
        tools.addSeparator()
        tools.addAction(self.act_benchmark)
        tools.addAction(self.act_dependencies)

        self.favorites_menu = bar.addMenu("Fa&vorites")
        self._rebuild_favorites()

        options = bar.addMenu("&Options")
        options.addAction(self.act_settings)
        options.addAction(self.act_customize)
        options.addAction(self.act_profiles)
        options.addSeparator()

        view_menu = options.addMenu("&File list")
        for action in self.view_mode_actions.values():
            view_menu.addAction(action)
        view_menu.addSeparator()
        self.sort_menu = view_menu.addMenu("&Sort by")
        self._build_sort_menu()
        self.columns_menu = view_menu.addMenu("&Columns")
        self._build_columns_menu()
        view_menu.addSeparator()
        view_menu.addAction(self.act_grid_lines)
        view_menu.addAction(self.act_alternate_rows)
        view_menu.addAction(self.act_show_hidden)

        layout_menu = options.addMenu("&Layout")
        layout_menu.addAction(self.act_show_toolbar)
        layout_menu.addAction(self.act_show_address)
        layout_menu.addAction(self.act_show_status)
        layout_menu.addSeparator()
        layout_menu.addAction(self.act_show_tree)
        for action in self.tree_side_actions.values():
            layout_menu.addAction(action)
        layout_menu.addSeparator()
        layout_menu.addAction(self.act_show_comment)
        for action in self.comment_side_actions.values():
            layout_menu.addAction(action)
        layout_menu.addSeparator()
        layout_menu.addAction(self.act_toolbar_text)
        layout_menu.addAction(self.act_reset_layout)

        theme_menu = options.addMenu(
            icons.icon(f"theme-{theme.mode()}"), "&Theme"
        )
        self.theme_menu = theme_menu
        for action in self.theme_actions.values():
            theme_menu.addAction(action)

        help_menu = bar.addMenu("&Help")
        help_menu.addAction(self.act_help_topics)
        help_menu.addAction(self.act_shortcuts)
        help_menu.addSeparator()
        help_menu.addAction(self.act_about)

        # The theme switch lives in the menu bar's corner: always in the same
        # place, whatever the user does to the toolbar.
        self.theme_button = QToolButton()
        self.theme_button.setObjectName("CornerButton")
        self.theme_button.setDefaultAction(self.act_toggle_theme)
        self.theme_button.setIconSize(QSize(18, 18))
        self.theme_button.setAutoRaise(True)
        self.theme_button.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonIconOnly
        )
        bar.setCornerWidget(self.theme_button, Qt.Corner.TopRightCorner)

    def _build_sort_menu(self) -> None:
        from .filelist import HEADERS

        self.sort_menu.clear()
        self.sort_actions: dict[int, QAction] = {}
        group = QActionGroup(self)
        current = int(SETTINGS.get("view/sort_column"))
        for column, label in enumerate(HEADERS):
            action = self.sort_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(column == current)
            action.triggered.connect(
                lambda _c=False, col=column: self.sort_by(col)
            )
            group.addAction(action)
            self.sort_actions[column] = action
        self.sort_menu.addSeparator()
        self.act_sort_descending = self.sort_menu.addAction("&Descending")
        self.act_sort_descending.setCheckable(True)
        self.act_sort_descending.setChecked(
            bool(SETTINGS.get("view/sort_descending"))
        )
        self.act_sort_descending.triggered.connect(
            lambda checked: self.sort_by(int(SETTINGS.get("view/sort_column")),
                                         checked)
        )

    def sort_by(self, column: int, descending: Optional[bool] = None) -> None:
        """Sort the listing, and remember the choice for the next launch."""
        if descending is None:
            descending = bool(SETTINGS.get("view/sort_descending"))
        SETTINGS.set("view/sort_column", column)
        SETTINGS.set("view/sort_descending", bool(descending))
        order = (
            Qt.SortOrder.DescendingOrder if descending
            else Qt.SortOrder.AscendingOrder
        )
        self.list_view.sortByColumn(column, order)
        action = getattr(self, "sort_actions", {}).get(column)
        if action is not None:
            action.setChecked(True)
        if hasattr(self, "act_sort_descending"):
            self.act_sort_descending.setChecked(bool(descending))

    def _on_sort_changed(self, column: int, order) -> None:
        """The user clicked a column header."""
        SETTINGS.set("view/sort_column", column)
        SETTINGS.set("view/sort_descending", order == Qt.SortOrder.DescendingOrder)
        action = getattr(self, "sort_actions", {}).get(column)
        if action is not None:
            action.setChecked(True)
        if hasattr(self, "act_sort_descending"):
            self.act_sort_descending.setChecked(
                order == Qt.SortOrder.DescendingOrder
            )

    def _build_columns_menu(self) -> None:
        from .filelist import HEADERS

        self.columns_menu.clear()
        for column, label in enumerate(HEADERS):
            if column == 0:
                continue  # the Name column is mandatory
            action = self.columns_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(not self.list_view.isColumnHidden(column))
            action.triggered.connect(
                lambda checked, col=column: self.list_view.setColumnHidden(
                    col, not checked
                )
            )

    def _build_toolbar(self) -> None:
        self.toolbar = QToolBar("Main")
        self.toolbar.setObjectName("MainToolBar")
        self.toolbar.setMovable(False)
        self.addToolBar(self.toolbar)

        # Every action the toolbar may show, by the key the settings store.
        self.action_registry: dict[str, QAction] = {
            key: getattr(self, attribute)
            for key, attribute, _caption in TOOLBAR_CATALOGUE
            if hasattr(self, attribute)
        }
        self.toolbar_captions: dict[str, str] = {
            key: caption for key, _attribute, caption in TOOLBAR_CATALOGUE
        }
        self.rebuild_toolbar()

    def rebuild_toolbar(self) -> None:
        """Fill the toolbar from the saved item list, order and button style."""
        self.toolbar.clear()

        size = int(SETTINGS.get("toolbar/icon_size"))
        self.toolbar.setIconSize(QSize(size, size))
        style = TOOLBAR_STYLES.get(
            SETTINGS.get("toolbar/style"),
            Qt.ToolButtonStyle.ToolButtonTextUnderIcon,
        )
        self.toolbar.setToolButtonStyle(style)

        items = SETTINGS.string_list("toolbar/items") or list(DEFAULT_TOOLBAR)
        for key in items:
            if key == "|":
                self.toolbar.addSeparator()
                continue
            action = self.action_registry.get(key)
            if action is None:
                continue  # a key from a newer version, or a dropped command
            # A QToolButton renders the action's *icon text*, so the short
            # caption has to go there; setting the button's text is overwritten.
            action.setIconText(
                self.toolbar_captions.get(key) or action.text().replace("&", "")
            )
            self.toolbar.addAction(action)
            button = self.toolbar.widgetForAction(action)
            if isinstance(button, QToolButton):
                button.setToolButtonStyle(style)
                if key == "dependencies":
                    # Called out on the bar: it is how missing tools get fixed.
                    button.setObjectName("DependencyButton")

        self.act_toggle_theme.setIconText("Theme")
        self._sync_theme_widgets()
        self.update_dependency_state()

    def update_dependency_state(self) -> None:
        """Flag the Dependencies button when a required tool is missing."""
        missing = [
            status.dependency.name
            for status in packages.all_statuses()
            if not status.installed and status.dependency.essential
        ]
        icon_name = "package-alert" if missing else "package"
        self.act_dependencies.setIcon(icons.icon(icon_name))
        self.act_dependencies.setProperty("iconName", icon_name)
        self.act_dependencies.setToolTip(
            "Missing: " + ", ".join(missing) + " — click to install"
            if missing
            else "Install or remove the command line tools LinRAR uses"
        )
        button = self.toolbar.widgetForAction(self.act_dependencies)
        if isinstance(button, QToolButton):
            button.setObjectName(
                "DependencyAlertButton" if missing else "DependencyButton"
            )
            button.style().unpolish(button)
            button.style().polish(button)

    def _build_body(self) -> None:
        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # -- address bar --
        address = QWidget()
        address.setObjectName("AddressBar")
        self.address_bar = address
        address_layout = QHBoxLayout(address)
        address_layout.setContentsMargins(4, 3, 4, 3)
        address_layout.setSpacing(4)

        self.up_button = QToolButton()
        self.up_button.setDefaultAction(self.act_up)
        self.up_button.setIconSize(QSize(20, 20))
        self.up_button.setAutoRaise(True)
        address_layout.addWidget(self.up_button)

        self.path_combo = QComboBox()
        self.path_combo.setEditable(True)
        self.path_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.path_combo.lineEdit().returnPressed.connect(self._on_path_entered)
        self.path_combo.activated.connect(self._on_path_activated)
        address_layout.addWidget(self.path_combo, 1)
        outer.addWidget(address)

        # -- splitter: tree | (list + comment) --
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.tree = FolderTree()
        self.tree.folderSelected.connect(self._on_tree_folder)
        self.splitter.addWidget(self.tree)

        right = QSplitter(Qt.Orientation.Vertical)
        self.list_view = FileBrowser()
        self.model = FileListModel(self)
        self.list_view.setModel(self.model)
        self.list_view.activatedItem.connect(self._on_item_activated)
        self.list_view.customContextMenuRequested.connect(self._show_context_menu)
        self.list_view.selectionModel().selectionChanged.connect(
            self._update_status
        )
        self.list_view.details.header().sortIndicatorChanged.connect(
            self._on_sort_changed
        )
        right.addWidget(self.list_view)

        self.comment_pane = QPlainTextEdit()
        self.comment_pane.setReadOnly(True)
        self.comment_pane.setMaximumHeight(120)
        self.comment_pane.setPlaceholderText("Archive comment")
        right.addWidget(self.comment_pane)
        right.setStretchFactor(0, 1)
        right.setStretchFactor(1, 0)
        self.right_splitter = right

        self.splitter.addWidget(right)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([210, 730])
        outer.addWidget(self.splitter, 1)

        self.setCentralWidget(central)

        self.tree.setVisible(SETTINGS.get("view/show_tree"))
        self.comment_pane.setVisible(SETTINGS.get("view/show_comment"))
        header_state = SETTINGS.load_geometry("columns")
        if header_state:
            self.list_view.restore_header_state(header_state)

    def _build_status_bar(self) -> None:
        bar = self.statusBar()

        # The two left-hand cells are live buttons, as they are in WinRAR.
        self.disk_button = self._status_button(
            "disk", "Change folder", self.cmd_change_folder
        )
        bar.addWidget(self.disk_button)
        self.key_button = self._status_button(
            "key", "No default password set", self.cmd_password
        )
        bar.addWidget(self.key_button)

        self.selection_label = QLabel("")
        self.selection_label.setObjectName("StatusPane")
        self.selection_label.setMinimumWidth(280)
        bar.addWidget(self.selection_label, 1)

        self.total_label = QLabel("")
        self.total_label.setObjectName("StatusPane")
        self.total_label.setMinimumWidth(220)
        bar.addPermanentWidget(self.total_label)

    def _status_button(self, icon: str, tip: str, slot: Callable) -> QToolButton:
        button = QToolButton()
        button.setObjectName("StatusButton")
        button.setIcon(icons.icon(icon))
        button.setProperty("iconName", icon)
        button.setIconSize(QSize(16, 16))
        button.setAutoRaise(True)
        button.setToolTip(tip)
        button.clicked.connect(slot)
        return button

    # ------------------------------------------------------------------
    # navigation
    # ------------------------------------------------------------------

    @property
    def in_archive(self) -> bool:
        return self.archive_path is not None

    def navigate_to(self, folder: str) -> None:
        """Show a folder on disk, leaving archive mode if we were in one."""
        folder = os.path.abspath(os.path.expanduser(folder))
        if not os.path.isdir(folder):
            QMessageBox.warning(self, "LinRAR", f"The folder does not exist:\n{folder}")
            return
        if not os.access(folder, os.R_OK | os.X_OK):
            QMessageBox.warning(
                self, "LinRAR", f"You do not have permission to open:\n{folder}"
            )
            return

        self.archive_path = None
        self.archive_info = None
        self.archive_folder = ""
        self.password = None
        self._filter = None
        self.current_folder = folder
        SETTINGS.set("places/last_folder", folder)

        self._populate_filesystem()
        self.setWindowTitle(f"{folder} - LinRAR")
        self.comment_pane.clear()
        self.tree.show_filesystem(folder)
        self._update_path_combo(folder)
        self._update_actions()

    def open_archive(self, path: str, password: Optional[str] = None) -> bool:
        """Enter an archive, prompting for a password if it needs one."""
        path = os.path.abspath(path)
        if not os.path.isfile(path):
            QMessageBox.warning(self, "LinRAR", f"The file does not exist:\n{path}")
            return False

        try:
            backend, fmt = REGISTRY.for_path(path)
        except OperationError as exc:
            QMessageBox.warning(self, "LinRAR", exc.message)
            return False

        attempt_password = password
        while True:
            try:
                info = backend.read_info(path, attempt_password)
                break
            except PasswordRequired as exc:
                result = PasswordDialog.ask(self, os.path.basename(path))
                if result is None:
                    return False
                attempt_password = result[0]
            except OperationError as exc:
                QMessageBox.critical(self, "LinRAR", exc.message)
                return False

        info.format = fmt if info.format is ArchiveFormat.UNKNOWN else info.format
        self.archive_path = path
        self.archive_info = info
        self.archive_folder = ""
        self.password = attempt_password
        self._filter = None

        self._populate_archive()
        self.setWindowTitle(f"{os.path.basename(path)} - LinRAR")
        self.comment_pane.setPlainText(info.comment)
        if info.comment and not self.comment_pane.isVisible():
            # WinRAR pops the comment pane open when an archive carries one.
            self._show_comment_pane(True)
            self.act_show_comment.setChecked(True)

        folders = sorted(
            {e.name for e in info.entries if e.is_dir}
            | {e.parent for e in info.entries if e.parent}
        )
        self.tree.show_archive(os.path.basename(path), [f for f in folders if f])
        self._update_path_combo(path)
        self._update_actions()
        self.key_button.setToolTip(
            "Password set for this archive" if attempt_password else "No password set"
        )
        return True

    def close_archive(self) -> None:
        if self.in_archive:
            folder = os.path.dirname(self.archive_path or "") or self.current_folder
            self.navigate_to(folder)

    def go_up(self) -> None:
        if self.in_archive:
            if self.archive_folder:
                parent = (
                    self.archive_folder.rsplit("/", 1)[0]
                    if "/" in self.archive_folder
                    else ""
                )
                self.enter_archive_folder(parent)
            else:
                self.close_archive()
            return
        parent = os.path.dirname(self.current_folder.rstrip("/"))
        if parent and parent != self.current_folder:
            self.navigate_to(parent)

    def enter_archive_folder(self, folder: str) -> None:
        self.archive_folder = folder
        self._filter = None
        self._populate_archive()
        self.tree.select_archive_folder(folder)
        self._update_path_combo(self.archive_path or "")

    def refresh(self) -> None:
        if self.in_archive:
            path, password = self.archive_path, self.password
            folder = self.archive_folder
            if path and self.open_archive(path, password):
                self.enter_archive_folder(folder)
        else:
            self._populate_filesystem()

    # ------------------------------------------------------------------
    # listing
    # ------------------------------------------------------------------

    def _populate_filesystem(self) -> None:
        items: list[ListingItem] = []
        parent = os.path.dirname(self.current_folder.rstrip("/"))
        if parent and parent != self.current_folder:
            items.append(ListingItem(name="..", path=parent, is_dir=True, is_parent=True))

        show_hidden = SETTINGS.get("view/show_hidden")
        try:
            with os.scandir(self.current_folder) as entries:
                for entry in entries:
                    if not show_hidden and entry.name.startswith("."):
                        continue
                    try:
                        stat = entry.stat(follow_symlinks=False)
                        is_dir = entry.is_dir(follow_symlinks=True)
                        size = 0 if is_dir else stat.st_size
                        mtime = datetime.fromtimestamp(stat.st_mtime)
                    except OSError:
                        is_dir, size, mtime = False, 0, None
                    items.append(
                        ListingItem(
                            name=entry.name,
                            path=entry.path,
                            is_dir=is_dir,
                            size=size,
                            mtime=mtime,
                            is_link=entry.is_symlink(),
                        )
                    )
        except OSError as exc:
            QMessageBox.warning(self, "LinRAR", f"Cannot read the folder.\n\n{exc}")

        if self._filter:
            items = [i for i in items if i.is_parent or self._filter(i)]

        self.model.set_items(items, archive_mode=False)
        self.list_view.configure_columns(archive_mode=False)
        self._update_status()

    def _populate_archive(self) -> None:
        info = self.archive_info
        if info is None:
            return

        items: list[ListingItem] = []
        items.append(
            ListingItem(name="..", path="", is_dir=True, is_parent=True)
        )

        folder = self.archive_folder
        seen_dirs: set[str] = set()

        for entry in info.entries:
            name = entry.name
            if folder:
                if not name.startswith(folder + "/"):
                    continue
                remainder = name[len(folder) + 1 :]
            else:
                remainder = name
            if not remainder:
                continue

            if "/" in remainder:
                # A deeper path implies a folder at this level.
                child = remainder.split("/", 1)[0]
                full = f"{folder}/{child}" if folder else child
                if full in seen_dirs:
                    continue
                seen_dirs.add(full)
                items.append(
                    ListingItem(name=child, path=full, is_dir=True, mtime=entry.mtime)
                )
                continue

            if entry.is_dir:
                if name in seen_dirs:
                    continue
                seen_dirs.add(name)
                items.append(
                    ListingItem(
                        name=remainder,
                        path=name,
                        is_dir=True,
                        mtime=entry.mtime,
                        entry=entry,
                    )
                )
                continue

            items.append(
                ListingItem(
                    name=remainder,
                    path=name,
                    is_dir=False,
                    size=entry.size,
                    packed=entry.packed_size,
                    mtime=entry.mtime,
                    crc=entry.crc,
                    encrypted=entry.encrypted,
                    is_link=entry.is_link,
                    entry=entry,
                )
            )

        if self._filter:
            items = [i for i in items if i.is_parent or self._filter(i)]

        self.model.set_items(items, archive_mode=True)
        self.list_view.configure_columns(archive_mode=True)
        self._update_status()

    def _update_path_combo(self, path: str) -> None:
        self.path_combo.blockSignals(True)
        self.path_combo.clear()
        if self.in_archive:
            display = path
            if self.archive_folder:
                display = f"{path}\\{self.archive_folder.replace('/', chr(92))}"
            self.path_combo.addItem(icons.icon("archive-small"), display)
        else:
            self.path_combo.addItem(icons.icon("folder"), path)
            for entry in SETTINGS.history():
                if entry != path and os.path.isdir(entry):
                    self.path_combo.addItem(icons.icon("folder"), entry)
        self.path_combo.setCurrentIndex(0)
        self.path_combo.blockSignals(False)

    def _update_status(self) -> None:
        selected = self.list_view.selected_items()
        if selected:
            files = [i for i in selected if not i.is_dir]
            total = sum(i.size for i in files)
            self.selection_label.setText(
                f"{len(selected)} selected  "
                f"{format_size(total)} bytes in {len(files)} file(s)"
            )
        else:
            self.selection_label.setText("")

        items = [i for i in self.model.items if not i.is_parent]
        files = [i for i in items if not i.is_dir]
        total = sum(i.size for i in files)
        folders = len(items) - len(files)
        self.total_label.setText(
            f"Total {format_size(total)} bytes in {len(files)} file(s)"
            + (f", {folders} folder(s)" if folders else "")
        )

    def _update_actions(self) -> None:
        in_archive = self.in_archive
        writable = True
        if in_archive and self.archive_info is not None:
            writable = not self.archive_info.locked

        self.act_close.setEnabled(in_archive)
        self.act_test.setEnabled(in_archive)
        self.act_info.setEnabled(in_archive)
        self.act_comment.setEnabled(in_archive and writable)
        self.act_protect.setEnabled(in_archive and writable)
        self.act_sfx.setEnabled(in_archive and writable)
        self.act_lock.setEnabled(in_archive and writable)
        self.act_convert.setEnabled(in_archive)
        self.act_rename.setEnabled(in_archive and writable)
        self.act_extract_here.setEnabled(in_archive)
        self.list_view.setDragEnabled(True)

    # ------------------------------------------------------------------
    # events
    # ------------------------------------------------------------------

    def _on_item_activated(self, item: ListingItem) -> None:
        if item.is_parent:
            self.go_up()
            return
        if self.in_archive:
            if item.is_dir:
                self.enter_archive_folder(item.path)
            else:
                self.cmd_view()
            return
        if item.is_dir:
            self.navigate_to(item.path)
        elif looks_like_archive(item.name) or detect_format(item.path) is not (
            ArchiveFormat.UNKNOWN
        ):
            self.open_archive(item.path)
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(item.path))

    def _on_tree_folder(self, path: str) -> None:
        if self.in_archive:
            self.enter_archive_folder(path)
        elif path and path != self.current_folder:
            self.navigate_to(path)

    def _on_path_entered(self) -> None:
        text = self.path_combo.currentText().strip()
        if not text:
            return
        expanded = os.path.expanduser(text)
        if os.path.isdir(expanded):
            self.navigate_to(expanded)
        elif os.path.isfile(expanded):
            self.open_archive(expanded)
        else:
            QMessageBox.warning(self, "LinRAR", f"Path not found:\n{text}")

    def _on_path_activated(self, index: int) -> None:
        if self.in_archive:
            return
        text = self.path_combo.itemText(index)
        if os.path.isdir(text) and text != self.current_folder:
            self.navigate_to(text)

    def _show_context_menu(self, pos) -> None:
        menu = QMenu(self)
        selected = self.list_view.selected_items()

        if self.in_archive:
            menu.addAction(self.act_extract_to)
            menu.addAction(self.act_extract_here)
            menu.addAction(self.act_view)
            menu.addAction(self.act_save_as)
            menu.addSeparator()
            menu.addAction(self.act_copy)
            menu.addAction(self.act_test)
            menu.addAction(self.act_delete)
            menu.addAction(self.act_rename)
            menu.addSeparator()
            menu.addAction(self.act_properties)
        else:
            if len(selected) == 1 and selected[0].is_dir:
                open_action = menu.addAction(icons.icon("folder"), "Open")
                open_action.triggered.connect(
                    lambda: self.navigate_to(selected[0].path)
                )
            elif len(selected) == 1 and looks_like_archive(selected[0].name):
                open_action = menu.addAction(icons.icon("archive-small"), "Open archive")
                open_action.triggered.connect(
                    lambda: self.open_archive(selected[0].path)
                )
                menu.addAction(self.act_extract_to)
            menu.addSeparator()
            menu.addAction(self.act_add)
            menu.addAction(self.act_new_folder)
            menu.addSeparator()
            menu.addAction(self.act_copy)
            menu.addAction(self.act_cut)
            menu.addAction(self.act_paste)
            if selected:
                menu.addSeparator()
                menu.addAction(self.act_delete)
                menu.addAction(self.act_rename)
                menu.addAction(self.act_properties)
        menu.addSeparator()
        menu.addAction(self.act_copy_path)
        menu.addAction(self.act_select_all)
        menu.addAction(self.act_refresh)
        menu.exec(self.list_view.viewport().mapToGlobal(pos))

    # -- drag and drop -----------------------------------------------------

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        paths = [
            url.toLocalFile()
            for url in event.mimeData().urls()
            if url.isLocalFile()
        ]
        if not paths:
            return
        event.acceptProposedAction()

        if len(paths) == 1 and os.path.isdir(paths[0]):
            self.navigate_to(paths[0])
            return
        if len(paths) == 1 and detect_format(paths[0]) is not ArchiveFormat.UNKNOWN:
            self.open_archive(paths[0])
            return
        self.cmd_add(paths)

    # ------------------------------------------------------------------
    # task helper
    # ------------------------------------------------------------------

    def _run_task(
        self,
        work: Callable[[TaskContext], object],
        title: str,
        total_bytes: int = 0,
        total_items: int = 0,
    ) -> tuple[Optional[bool], object, Optional[OperationError]]:
        """Run *work* with a modal progress window.

        Returns ``(ok, result, error)``.  ``ok`` is ``None`` when the user sent
        the operation to the background — the task then finishes on its own and
        reports through the status bar, so callers should simply return.
        """
        task = Task(work, title, self)
        task.ctx.total_items = total_items
        self._task = task
        dialog = ProgressDialog(self, task, title, total_bytes)
        dialog.exec()
        if dialog.backgrounded and task.isRunning():
            self._adopt_background_task(task, title)
            return None, None, None
        task.wait(5000)
        self._task = None
        if task.error is not None:
            return False, None, task.error
        return True, task.result, None

    def _adopt_background_task(self, task: Task, title: str) -> None:
        """Keep a backgrounded task alive and report its completion later."""
        self._task = None
        self._background_tasks.append(task)
        task.succeeded.connect(
            lambda _r, t=task, s=title: self._background_finished(t, s, None)
        )
        task.failed.connect(
            lambda err, t=task, s=title: self._background_finished(t, s, err)
        )
        task.passwordNeeded.connect(
            lambda err, t=task, s=title: self._background_finished(t, s, err)
        )
        self.statusBar().showMessage(f"{title} — continuing in the background")

    def _background_finished(
        self, task: Task, title: str, error: Optional[OperationError]
    ) -> None:
        if task in self._background_tasks:
            self._background_tasks.remove(task)
        if error is None:
            self.statusBar().showMessage(f"{title} — finished", 8000)
            self.refresh()
        elif "cancelled" in getattr(error, "message", "").lower():
            self.statusBar().showMessage(f"{title} — cancelled", 6000)
        else:
            QMessageBox.critical(
                self, "LinRAR", f"{title} failed.\n\n{error.message}"
            )

    def _run_with_password(
        self,
        make_work: Callable[[Optional[str]], Callable[[TaskContext], object]],
        title: str,
        total_bytes: int = 0,
        total_items: int = 0,
    ) -> tuple[bool, object]:
        """Run an archive operation, prompting for a password as needed.

        ``make_work`` receives the password to use and returns the worker.  A
        wrong or missing password loops back to the prompt instead of failing,
        and the accepted password is remembered for the rest of the session.
        """
        while True:
            ok, result, error = self._run_task(
                make_work(self.password), title, total_bytes, total_items
            )
            if ok:
                return True, result
            if ok is None or error is None:
                return False, None
            if isinstance(error, PasswordRequired):
                answer = PasswordDialog.ask(
                    self, os.path.basename(self.archive_path or "")
                )
                if answer is None:
                    return False, None
                self.password = answer[0] or None
                continue
            self._report(error)
            return False, None

    def _report(self, error: OperationError, title: str = "LinRAR") -> None:
        if "cancelled" in error.message.lower():
            self.statusBar().showMessage("Operation cancelled", 4000)
            return
        QMessageBox.critical(self, title, error.message)

    def _backend_for_open_archive(self):
        if self.archive_path is None:
            return None
        try:
            backend, _fmt = REGISTRY.for_path(self.archive_path)
        except OperationError as exc:
            QMessageBox.warning(self, "LinRAR", exc.message)
            return None
        return backend

    # ------------------------------------------------------------------
    # commands
    # ------------------------------------------------------------------

    def cmd_add(self, paths: Optional[list[str]] = None) -> None:
        """Add files to a new or existing archive."""
        if isinstance(paths, bool) or paths is None:
            if self.in_archive:
                QMessageBox.information(
                    self,
                    "LinRAR",
                    "Close the archive first, then select the files you want "
                    "to add.",
                )
                return
            selected = self.list_view.selected_items()
            paths = [i.path for i in selected]
            if not paths:
                paths, _f = QFileDialog.getOpenFileNames(
                    self, "Select files to add", self.current_folder
                )
            if not paths:
                return

        # Store paths relative to the folder that actually contains the
        # selection; the browser folder is wrong for files picked elsewhere
        # (wizard, drag and drop).
        base = os.path.commonpath(
            [os.path.dirname(os.path.abspath(p)) or "/" for p in paths]
        ) if paths else self.current_folder

        if len(paths) == 1:
            name = os.path.basename(paths[0].rstrip("/"))
            # Keep dotted folder names intact; only strip a file's extension.
            stem = os.path.splitext(name)[0] if os.path.isfile(paths[0]) else name
        else:
            stem = os.path.basename(base.rstrip("/")) or "archive"
        default_name = os.path.join(self.current_folder, f"{stem}.rar")

        dialog = ArchiveDialog(
            self, files=paths, base_folder=base, default_name=default_name
        )
        # A profile chosen from Options > Compression profiles pre-fills the
        # dialog; otherwise the one marked as default does.
        profile = self._pending_profile or PROFILES.default()
        if profile is not None:
            dialog.apply_profile(profile)
        self._pending_profile = None
        if dialog.exec() != ArchiveDialog.DialogCode.Accepted:
            return

        options = dialog.options()
        files = dialog.selected_files()
        try:
            backend = REGISTRY.for_format(options.format)
        except OperationError as exc:
            QMessageBox.warning(self, "LinRAR", exc.message)
            return

        total, count = _total_bytes(files)

        def work(ctx: TaskContext):
            backend.create(files, options, ctx)
            return options.archive_path

        ok, _result, error = self._run_task(
            work,
            f"Creating {os.path.basename(options.archive_path)}",
            total,
            count,
        )
        if not ok:
            if error is not None:
                self._report(error)
            return
        if not self.in_archive:
            self._populate_filesystem()
        # The backend may have adjusted the name (SFX archives become .sfx).
        self.statusBar().showMessage(
            f"Created {os.path.basename(options.archive_path)}", 5000
        )

    def cmd_extract_to(self) -> None:
        if not self.in_archive:
            selected = [
                i for i in self.list_view.selected_items()
                if not i.is_dir and detect_format(i.path) is not ArchiveFormat.UNKNOWN
            ]
            if len(selected) == 1:
                if self.open_archive(selected[0].path):
                    self.cmd_extract_to()
                return
            QMessageBox.information(
                self, "LinRAR", "Select an archive, or open one first."
            )
            return
        self._extract(ask_options=True)

    def cmd_extract_here(self) -> None:
        if not self.in_archive:
            return
        self._extract(ask_options=False)

    # -- entry points for the file manager's right-click menu --------------

    def extract_paths(self, paths: list[str], ask_options: bool) -> None:
        """Unpack each archive in *paths*, one after the other."""
        for path in paths:
            if not os.path.isfile(path):
                continue
            if not self.open_archive(path):
                continue
            self.list_view.selectionModel().clearSelection()
            self._extract(ask_options=ask_options)

    def test_paths(self, paths: list[str]) -> None:
        for path in paths:
            if os.path.isfile(path) and self.open_archive(path):
                self.cmd_test()

    def _extract(self, ask_options: bool) -> None:
        info = self.archive_info
        backend = self._backend_for_open_archive()
        if info is None or backend is None or self.archive_path is None:
            return

        selected = self.list_view.selected_items()
        members = self._expand_selection(selected)
        default_dir = os.path.dirname(self.archive_path)

        if ask_options:
            dialog = ExtractDialog(
                self,
                archive_name=self.archive_path,
                destination=SETTINGS.get("places/extract_folder") or default_dir,
                members=members,
                password=self.password,
            )
            if dialog.exec() != ExtractDialog.DialogCode.Accepted:
                return
            options = dialog.options()
            if dialog.extract_to_subfolders:
                stem = _archive_stem(self.archive_path)
                options.destination = os.path.join(options.destination, stem)
        else:
            options = ExtractOptions(
                destination=default_dir,
                members=members,
                password=self.password,
                overwrite_mode=OverwriteMode.ASK,
            )

        if options.password is not None:
            self.password = options.password

        resolved = self._resolve_overwrites(info, options)
        if resolved is None:
            return
        options = resolved

        # A destination the user cannot write is not a dead end: offer to
        # finish the job with administrator rights instead.
        deploy = self._prepare_destination(options)
        if deploy is False:
            return

        total = _entries_bytes(info, options.members)
        item_count = len(options.members) or info.file_count
        archive_path = self.archive_path

        def make_work(password: Optional[str]):
            options.password = password

            def work(ctx: TaskContext):
                backend.extract(archive_path, options, ctx)
                return options.destination

            return work

        ok, _destination = self._run_with_password(
            make_work,
            f"Extracting from {os.path.basename(archive_path)}",
            total,
            item_count,
        )
        if not ok:
            return

        final = options.destination
        if deploy is not None:
            if not self._deploy_elevated(deploy, options.overwrite_mode):
                return
            final = deploy[1]

        self.statusBar().showMessage(f"Extracted to {final}", 6000)
        if options.open_when_done:
            QDesktopServices.openUrl(QUrl.fromLocalFile(final))

    # -- writing where the user cannot ------------------------------------

    def _prepare_destination(self, options: ExtractOptions):
        """Check the destination is writable; offer elevation when it is not.

        Returns ``None`` when nothing special is needed, ``False`` when the
        user backed out, or a ``(staging, destination)`` pair when the files
        are to be extracted aside and then moved into place as root.
        """
        destination = os.path.abspath(options.destination)
        probe = destination
        while probe and not os.path.exists(probe):
            parent = os.path.dirname(probe)
            if parent == probe:
                break
            probe = parent
        if os.access(probe, os.W_OK):
            return None

        if elevation.is_root():
            return None
        if not elevation.available():
            QMessageBox.warning(
                self,
                "LinRAR",
                f"You do not have permission to write to:\n{destination}\n\n"
                "No way to obtain administrator rights was found either "
                "(pkexec, sudo and doas are all missing).",
            )
            return False

        reply = QMessageBox.question(
            self,
            "Administrator rights required",
            f"{destination}\n\ncannot be written as {getpass.getuser()}.\n\n"
            "Extract with administrator rights instead?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return False
        if not self._request_elevation("Extracting to a protected folder"):
            return False

        staging = tempfile.mkdtemp(prefix="linrar-elevated-")
        self._temp_dirs.append(staging)
        options.destination = staging
        return staging, destination

    def _request_elevation(self, reason: str) -> bool:
        """Get administrator rights, asking for a password only if needed."""
        preference = str(SETTINGS.get("admin/method") or "auto")
        session = elevation.SESSION
        if elevation.is_root() or session.active:
            return True
        password = None
        if session.needs_password(preference):
            method = session.preferred(preference)
            password, ok = QInputDialog.getText(
                self,
                "Administrator access",
                f"{reason}.\n\nEnter your password for "
                f"{method.binary if method else 'sudo'}:",
                QLineEdit.EchoMode.Password,
            )
            if not ok:
                return False
        granted, message = session.authenticate(password, preference)
        if not granted:
            QMessageBox.warning(self, "Administrator access", message)
        return granted

    def _deploy_elevated(self, deploy: tuple[str, str], mode: OverwriteMode) -> bool:
        """Copy the staged extraction into its real home, as root."""
        staging, destination = deploy
        flags = "-a"
        if mode is OverwriteMode.SKIP:
            flags += "n"  # --no-clobber: honour "skip existing files"
        script = (
            f"mkdir -p {shlex.quote(destination)} && "
            f"cp {flags} {shlex.quote(staging)}/. {shlex.quote(destination)}/"
        )
        code, output = elevation.SESSION.run(
            ["sh", "-c", script],
            str(SETTINGS.get("admin/method") or "auto"),
            timeout=1800,
        )
        shutil.rmtree(staging, ignore_errors=True)
        if code != 0:
            QMessageBox.critical(
                self,
                "LinRAR",
                "The files were extracted but could not be moved into "
                f"{destination}.\n\n{output.strip()[-400:]}",
            )
            return False
        return True

    def _resolve_overwrites(
        self, info: ArchiveInfo, options: ExtractOptions
    ) -> Optional[ExtractOptions]:
        """Apply "Ask before overwrite" by prompting before the work starts."""
        if options.overwrite_mode is not OverwriteMode.ASK:
            return options

        wanted = set(options.members) if options.members else None
        conflicts: list[tuple[str, str, int, Optional[datetime]]] = []
        for entry in info.entries:
            if entry.is_dir:
                continue
            if wanted is not None and entry.name not in wanted:
                continue
            relative = (
                os.path.basename(entry.name) if options.no_paths else entry.name
            )
            target = os.path.join(options.destination, relative)
            if os.path.exists(target):
                conflicts.append((entry.name, target, entry.size, entry.mtime))

        if not conflicts:
            options.overwrite_mode = OverwriteMode.OVERWRITE
            return options

        outcome = resolve_conflicts(self, conflicts)
        if outcome is None:
            return None
        skip, rename = outcome

        if rename:
            options.overwrite_mode = OverwriteMode.RENAME
            return options

        options.overwrite_mode = OverwriteMode.OVERWRITE
        if skip:
            if wanted is None:
                wanted = {e.name for e in info.entries if not e.is_dir}
            options.members = sorted(wanted - set(skip))
            if not options.members:
                self.statusBar().showMessage("Nothing to extract", 4000)
                return None
        return options

    def _expand_selection(self, selected: list[ListingItem]) -> list[str]:
        """Turn selected rows into concrete archive member names.

        Selecting a folder must pull in everything beneath it, and selecting
        nothing means "the whole archive".
        """
        if not selected or self.archive_info is None:
            return []
        members: set[str] = set()
        for item in selected:
            if item.is_dir:
                prefix = item.path.rstrip("/") + "/"
                members.add(item.path)
                for entry in self.archive_info.entries:
                    if entry.name.startswith(prefix):
                        members.add(entry.name)
            else:
                members.add(item.path)
        return sorted(members)

    def cmd_test(self) -> None:
        backend = self._backend_for_open_archive()
        if backend is None or self.archive_path is None:
            return
        archive_path = self.archive_path

        def make_work(password: Optional[str]):
            def work(ctx: TaskContext):
                backend.test(archive_path, password, ctx)
                return True

            return work

        total = self.archive_info.total_size if self.archive_info else 0
        count = self.archive_info.file_count if self.archive_info else 0
        ok, _result = self._run_with_password(
            make_work, f"Testing {os.path.basename(archive_path)}", total, count
        )
        if ok:
            QMessageBox.information(
                self, "LinRAR", "All files tested successfully. No errors found."
            )

    def cmd_view(self) -> None:
        selected = [i for i in self.list_view.selected_items() if not i.is_dir]
        if not selected:
            QMessageBox.information(self, "LinRAR", "Select a file to view.")
            return
        item = selected[0]

        if not self.in_archive:
            QDesktopServices.openUrl(QUrl.fromLocalFile(item.path))
            return

        backend = self._backend_for_open_archive()
        if backend is None or self.archive_path is None:
            return

        workdir = tempfile.mkdtemp(prefix="linrar-view-")
        self._temp_dirs.append(workdir)
        options = ExtractOptions(
            destination=workdir,
            members=[item.path],
            overwrite_mode=OverwriteMode.OVERWRITE,
        )
        archive_path = self.archive_path

        def make_work(password: Optional[str]):
            options.password = password

            def work(ctx: TaskContext):
                backend.extract(archive_path, options, ctx)
                return True

            return work

        ok, _result = self._run_with_password(
            make_work, f"Extracting {item.name}", item.size
        )
        if not ok:
            return

        extracted = os.path.join(workdir, item.path)
        if not os.path.isfile(extracted):
            for root, _dirs, names in os.walk(workdir):
                if item.name in names:
                    extracted = os.path.join(root, item.name)
                    break
        if not os.path.isfile(extracted):
            QMessageBox.warning(self, "LinRAR", "The file could not be extracted.")
            return

        try:
            with open(extracted, "rb") as handle:
                data = handle.read(4 * 1024 * 1024)
        except OSError as exc:
            QMessageBox.warning(self, "LinRAR", f"Cannot read the file.\n\n{exc}")
            return

        ViewerDialog(self, item.name, data).exec()

    def cmd_delete(self) -> None:
        selected = self.list_view.selected_items()
        if not selected:
            return

        if self.in_archive:
            backend = self._backend_for_open_archive()
            if backend is None or self.archive_path is None:
                return
            members = self._expand_selection(selected)
            names = ", ".join(i.name for i in selected[:3])
            more = f" and {len(selected) - 3} more" if len(selected) > 3 else ""
            reply = QMessageBox.question(
                self,
                "Delete",
                f"Delete {names}{more} from the archive?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            archive_path = self.archive_path

            def make_work(password: Optional[str]):
                def work(ctx: TaskContext):
                    backend.delete_members(archive_path, members, password, ctx)
                    return True

                return work

            ok, _r = self._run_with_password(make_work, "Deleting files")
            if ok:
                self.refresh()
            return

        names = ", ".join(i.name for i in selected[:3])
        more = f" and {len(selected) - 3} more" if len(selected) > 3 else ""
        reply = QMessageBox.question(
            self,
            "Delete",
            f"Permanently delete {names}{more}?\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        errors = []
        for item in selected:
            try:
                if item.is_dir and not item.is_link:
                    shutil.rmtree(item.path)
                else:
                    os.unlink(item.path)
            except OSError as exc:
                errors.append(f"{item.name}: {exc}")
        if errors:
            QMessageBox.warning(
                self, "LinRAR", "Some items could not be deleted:\n\n" + "\n".join(errors)
            )
        self._populate_filesystem()

    def cmd_rename(self) -> None:
        selected = self.list_view.selected_items()
        if len(selected) != 1:
            QMessageBox.information(self, "LinRAR", "Select a single item to rename.")
            return
        item = selected[0]
        new_name, ok = QInputDialog.getText(
            self, "Rename", "New name:", text=item.name
        )
        if not ok or not new_name.strip() or new_name == item.name:
            return
        new_name = new_name.strip()

        if self.in_archive:
            backend = self._backend_for_open_archive()
            if backend is None or self.archive_path is None:
                return
            parent = item.path.rsplit("/", 1)[0] if "/" in item.path else ""
            target = f"{parent}/{new_name}" if parent else new_name

            # Renaming a folder must also rename everything beneath it, or the
            # children stay stranded under the old name.
            pairs = [(item.path, target)]
            if item.is_dir and self.archive_info is not None:
                prefix = item.path.rstrip("/") + "/"
                for entry in self.archive_info.entries:
                    if entry.name.startswith(prefix):
                        pairs.append(
                            (entry.name, target + "/" + entry.name[len(prefix):])
                        )
            archive_path = self.archive_path

            def make_work(password: Optional[str]):
                def work(ctx: TaskContext):
                    backend.rename_members(archive_path, pairs, password, ctx)
                    return True

                return work

            ok2, _r = self._run_with_password(make_work, "Renaming")
            if ok2:
                self.refresh()
            return

        target = os.path.join(os.path.dirname(item.path), new_name)
        if os.path.exists(target):
            QMessageBox.warning(self, "LinRAR", "A file with that name already exists.")
            return
        try:
            os.rename(item.path, target)
        except OSError as exc:
            QMessageBox.warning(self, "LinRAR", f"Cannot rename.\n\n{exc}")
            return
        self._populate_filesystem()

    def cmd_find(self) -> None:
        dialog = FindDialog(self, self.in_archive)
        if dialog.exec() != FindDialog.DialogCode.Accepted:
            return
        mask = dialog.mask
        case_sensitive = dialog.case_sensitive

        def matches(item: ListingItem) -> bool:
            name = item.name if case_sensitive else item.name.lower()
            pattern = mask if case_sensitive else mask.lower()
            return fnmatch.fnmatch(name, pattern)

        self._filter = matches
        if self.in_archive:
            self._populate_archive()
        else:
            self._populate_filesystem()
        count = len([i for i in self.model.items if not i.is_parent])
        self.statusBar().showMessage(
            f"{count} item(s) match '{mask}' — press F5 to clear the filter", 8000
        )

    def cmd_info(self) -> None:
        if self.archive_info is None:
            return
        InfoDialog(self, self.archive_info).exec()

    def cmd_comment(self) -> None:
        backend = self._backend_for_open_archive()
        if backend is None or self.archive_path is None or self.archive_info is None:
            return
        dialog = CommentDialog(
            self, self.archive_path, self.archive_info.comment
        )
        if dialog.exec() != CommentDialog.DialogCode.Accepted:
            return
        comment = dialog.comment
        archive_path = self.archive_path

        def make_work(password: Optional[str]):
            def work(ctx: TaskContext):
                backend.set_comment(archive_path, comment, password, ctx)
                return True

            return work

        ok, _r = self._run_with_password(make_work, "Updating comment")
        if ok:
            self.refresh()

    def cmd_protect(self) -> None:
        backend = self._backend_for_open_archive()
        if backend is None or self.archive_path is None:
            return
        percent, ok = QInputDialog.getInt(
            self, "Protect archive", "Recovery record size (% of archive):", 3, 1, 100
        )
        if not ok:
            return

        archive_path = self.archive_path

        def work(ctx: TaskContext):
            backend.add_recovery_record(archive_path, percent, ctx)
            return True

        ok2, _r, error = self._run_task(work, "Adding recovery record")
        if not ok2:
            if error is not None:
                self._report(error)
            return
        self.refresh()
        QMessageBox.information(self, "LinRAR", "Recovery record added.")

    def cmd_lock(self) -> None:
        backend = self._backend_for_open_archive()
        if backend is None or self.archive_path is None:
            return
        reply = QMessageBox.question(
            self,
            "Lock archive",
            "Locking prevents any further changes to this archive.\n\n"
            "This cannot be undone. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        archive_path = self.archive_path

        def work(ctx: TaskContext):
            backend.lock(archive_path, ctx)
            return True

        ok, _r, error = self._run_task(work, "Locking archive")
        if not ok:
            if error is not None:
                self._report(error)
            return
        self.refresh()

    def cmd_repair(self) -> None:
        path = self.archive_path
        if path is None:
            selected = [i for i in self.list_view.selected_items() if not i.is_dir]
            if len(selected) != 1:
                QMessageBox.information(
                    self, "LinRAR", "Select the damaged archive, or open it first."
                )
                return
            path = selected[0].path

        output_dir = os.path.dirname(path)
        backend = REGISTRY.rar

        def work(ctx: TaskContext):
            return backend.repair(path, output_dir, ctx)

        ok, result, error = self._run_task(
            work, f"Repairing {os.path.basename(path)}"
        )
        if not ok:
            if error is not None:
                self._report(error)
            return
        if result:
            QMessageBox.information(
                self, "LinRAR", f"Repaired archive written to:\n{result}"
            )
        else:
            QMessageBox.warning(
                self,
                "LinRAR",
                "The archive could not be repaired. It may be damaged beyond "
                "recovery, or it may have no recovery record.",
            )
        if not self.in_archive:
            self._populate_filesystem()

    def cmd_sfx(self) -> None:
        """Build a self-extracting, self-running AppImage from the archive."""
        source = self.archive_path
        if source is None:
            selected = [
                i for i in self.list_view.selected_items()
                if not i.is_dir and looks_like_archive(i.name)
            ]
            if len(selected) != 1:
                QMessageBox.information(
                    self, "LinRAR", "Select an archive, or open one first."
                )
                return
            source = selected[0].path

        if detect_format(source) not in (ArchiveFormat.RAR5, ArchiveFormat.RAR4):
            QMessageBox.information(
                self,
                "LinRAR",
                "Self-extracting AppImages are built from RAR archives.\n\n"
                "Convert the archive to RAR first (Tools > Convert archives).",
            )
            return

        dialog = SfxDialog(self, archive_path=source)
        if dialog.exec() != SfxDialog.DialogCode.Accepted:
            return
        options = dialog.options()

        default = os.path.splitext(source)[0] + ".AppImage"
        target, _f = QFileDialog.getSaveFileName(
            self, "Save self-extracting archive", default, "AppImage (*.AppImage)"
        )
        if not target:
            return

        # The download prompt has to be answered on the GUI thread, so ask now
        # rather than from inside the worker.
        allow_download = True
        if not os.path.isfile(sfx.cached_runtime_path()) and not sfx.find_donor_appimage():
            url = sfx.RUNTIME_URL.format(arch=sfx.runtime_arch())
            reply = QMessageBox.question(
                self,
                "AppImage runtime",
                "LinRAR needs the AppImage runtime (about 1 MB) to build a "
                "self-extracting archive, and no copy was found on this "
                f"machine.\n\nDownload it once from:\n{url}\n\n"
                "It will be cached for future use.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            allow_download = reply == QMessageBox.StandardButton.Yes
            if not allow_download:
                QMessageBox.information(
                    self,
                    "LinRAR",
                    "Without the runtime an AppImage cannot be built.\n\n"
                    "You can instead use Commands > Convert to RAR .sfx stub, "
                    "which needs no extra files.",
                )
                return

        def work(ctx: TaskContext):
            return sfx.build_sfx_appimage(
                source, target, options, ctx, allow_download=allow_download
            )

        ok, result, error = self._run_task(
            work, "Building self-extracting AppImage", os.path.getsize(source), 1
        )
        if not ok:
            if error is not None:
                self._report(error)
            return

        QMessageBox.information(
            self,
            "LinRAR",
            f"Self-extracting AppImage created:\n{result}\n\n"
            "Run it to unpack, or from a terminal:\n"
            f"    {os.path.basename(str(result))} --help",
        )
        if not self.in_archive:
            self._populate_filesystem()

    def cmd_convert(self) -> None:
        # One entry point for conversion: the batch dialog, pre-filled with the
        # open archive.
        self.cmd_convert_archives()

    def cmd_password(self) -> None:
        result = PasswordDialog.ask(
            self, os.path.basename(self.archive_path or "")
        )
        if result is None:
            return
        self.password = result[0] or None
        self.key_button.setToolTip(
            "Default password set" if self.password else "No default password set"
        )
        self.statusBar().showMessage(
            "Password set" if self.password else "Password cleared", 4000
        )
        if self.in_archive:
            self.refresh()

    def cmd_open_archive(self) -> None:
        path, _f = QFileDialog.getOpenFileName(
            self,
            "Open archive",
            self.current_folder,
            "All archives (*.rar *.zip *.7z *.tar *.gz *.bz2 *.xz *.iso *.cab);;"
            "RAR archives (*.rar);;ZIP archives (*.zip);;All files (*)",
        )
        if path:
            self.open_archive(path)

    def cmd_change_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Change folder", self.current_folder
        )
        if path:
            self.navigate_to(path)

    def cmd_select_all(self) -> None:
        self.list_view.selectAll()

    def cmd_wizard(self) -> None:
        dialog = WizardDialog(
            self,
            current_folder=self.current_folder,
            archive=self.archive_path or "",
        )
        if dialog.exec() != WizardDialog.DialogCode.Accepted:
            return

        from .dialogs.wizard import TASK_ADD, TASK_CREATE, TASK_UNPACK

        if dialog.task == TASK_UNPACK:
            if not self.open_archive(dialog.archive_path):
                return
            SETTINGS.set("places/extract_folder", dialog.destination)
            self.cmd_extract_to()
        elif dialog.task == TASK_CREATE:
            self.cmd_add(dialog.files)
        elif dialog.task == TASK_ADD:
            self._add_to_existing(dialog.archive_path, dialog.files)

    def _add_to_existing(self, archive: str, files: list[str]) -> None:
        """Add files to an archive that already exists."""
        if not files:
            return
        try:
            backend, fmt = REGISTRY.for_path(archive)
        except OperationError as exc:
            QMessageBox.warning(self, "LinRAR", exc.message)
            return
        if fmt not in (
            ArchiveFormat.RAR5,
            ArchiveFormat.RAR4,
            ArchiveFormat.ZIP,
            ArchiveFormat.SEVENZIP,
        ):
            QMessageBox.information(
                self,
                "LinRAR",
                f"Files cannot be added to a {fmt.label} archive.\n\n"
                "Only RAR, ZIP and 7z archives can be updated. Use Tools > "
                "Convert archives to change the format first.",
            )
            return

        base = os.path.commonpath(
            [os.path.dirname(os.path.abspath(f)) or "/" for f in files]
        )
        options = CompressOptions(
            archive_path=archive, format=fmt, base_folder=base
        )
        total, count = _total_bytes(files)

        def work(ctx: TaskContext):
            backend.create(files, options, ctx)
            return archive

        ok, _r, error = self._run_task(
            work, f"Adding to {os.path.basename(archive)}", total, count
        )
        if not ok:
            if error is not None:
                self._report(error)
            return
        self.statusBar().showMessage(f"Added {count} file(s) to {archive}", 5000)

    # -- selection ---------------------------------------------------------

    def _selection_mask(self, title: str) -> Optional[str]:
        mask, ok = QInputDialog.getText(
            self, title, "File mask:", text="*.*"
        )
        return mask.strip() if ok and mask.strip() else None

    def _apply_mask(self, mask: str, select: bool) -> None:
        selection = self.list_view.selectionModel()
        model = self.model
        flag = (
            selection.SelectionFlag.Select
            if select
            else selection.SelectionFlag.Deselect
        )
        count = 0
        for row, item in enumerate(model.items):
            if item.is_parent:
                continue
            if fnmatch.fnmatch(item.name.lower(), mask.lower()):
                index = model.index(row, 0)
                selection.select(
                    index, flag | selection.SelectionFlag.Rows
                )
                count += 1
        self.statusBar().showMessage(
            f"{'Selected' if select else 'Deselected'} {count} item(s) "
            f"matching '{mask}'",
            5000,
        )

    def cmd_select_group(self) -> None:
        mask = self._selection_mask("Select group")
        if mask:
            self._apply_mask(mask, True)

    def cmd_deselect_group(self) -> None:
        mask = self._selection_mask("Deselect group")
        if mask:
            self._apply_mask(mask, False)

    def cmd_invert_selection(self) -> None:
        selection = self.list_view.selectionModel()
        selected = {i.row() for i in selection.selectedRows()}
        selection.clearSelection()
        for row, item in enumerate(self.model.items):
            if item.is_parent or row in selected:
                continue
            selection.select(
                self.model.index(row, 0),
                selection.SelectionFlag.Select | selection.SelectionFlag.Rows,
            )

    # -- file manager operations -------------------------------------------

    def cmd_new_folder(self) -> None:
        if self.in_archive:
            QMessageBox.information(
                self,
                "LinRAR",
                "Folders inside an archive are created by adding files with "
                "that path.",
            )
            return
        name, ok = QInputDialog.getText(self, "New folder", "Folder name:")
        if not ok or not name.strip():
            return
        target = os.path.join(self.current_folder, name.strip())
        try:
            os.makedirs(target, exist_ok=False)
        except FileExistsError:
            QMessageBox.warning(self, "LinRAR", "That folder already exists.")
            return
        except OSError as exc:
            QMessageBox.warning(self, "LinRAR", f"Cannot create the folder.\n\n{exc}")
            return
        self._populate_filesystem()

    def _clipboard_set(self, paths: list[str], cut: bool) -> None:
        from PyQt6.QtCore import QMimeData
        from PyQt6.QtWidgets import QApplication

        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(p) for p in paths])
        # Both GNOME and KDE read the intended action from this hint.
        mime.setData(
            "x-special/gnome-copied-files",
            ("cut\n" if cut else "copy\n")
            + "\n".join(QUrl.fromLocalFile(p).toString() for p in paths),
        )
        QApplication.clipboard().setMimeData(mime)
        self._pending_cut = paths if cut else []

    def cmd_copy(self) -> None:
        items = self.list_view.selected_items()
        if not items:
            return
        if self.in_archive:
            self._copy_from_archive(items)
            return
        self._clipboard_set([i.path for i in items], cut=False)
        self.statusBar().showMessage(f"Copied {len(items)} item(s)", 4000)

    def cmd_cut(self) -> None:
        if self.in_archive:
            QMessageBox.information(
                self, "LinRAR", "Cut is not available inside an archive."
            )
            return
        items = self.list_view.selected_items()
        if not items:
            return
        self._clipboard_set([i.path for i in items], cut=True)
        self.statusBar().showMessage(f"Cut {len(items)} item(s)", 4000)

    def _copy_from_archive(self, items: list[ListingItem]) -> None:
        """Extract to a temp folder, then put the real files on the clipboard."""
        backend = self._backend_for_open_archive()
        if backend is None or self.archive_path is None:
            return
        workdir = tempfile.mkdtemp(prefix="linrar-copy-")
        self._temp_dirs.append(workdir)
        members = self._expand_selection(items)
        options = ExtractOptions(
            destination=workdir,
            members=members,
            overwrite_mode=OverwriteMode.OVERWRITE,
        )
        archive_path = self.archive_path

        def make_work(password: Optional[str]):
            options.password = password

            def work(ctx: TaskContext):
                backend.extract(archive_path, options, ctx)
                return True

            return work

        ok, _r = self._run_with_password(
            make_work, "Copying from archive", 0, len(members)
        )
        if not ok:
            return
        roots = [
            os.path.join(workdir, name.split("/", 1)[0])
            for name in {m.split("/", 1)[0] for m in members}
        ]
        self._clipboard_set(sorted(set(roots)), cut=False)
        self.statusBar().showMessage(
            f"Copied {len(items)} item(s) to the clipboard", 5000
        )

    def cmd_paste(self) -> None:
        from PyQt6.QtWidgets import QApplication

        if self.in_archive:
            QMessageBox.information(
                self,
                "LinRAR",
                "To put files into this archive, close it and use Add.",
            )
            return
        mime = QApplication.clipboard().mimeData()
        if not mime.hasUrls():
            return
        sources = [u.toLocalFile() for u in mime.urls() if u.isLocalFile()]
        if not sources:
            return

        cut = bool(getattr(self, "_pending_cut", None))
        errors = []
        for source in sources:
            target = os.path.join(self.current_folder, os.path.basename(source))
            if os.path.abspath(source) == os.path.abspath(target):
                continue
            if os.path.exists(target):
                target = _unique_path(target)
            try:
                if cut and source in self._pending_cut:
                    shutil.move(source, target)
                elif os.path.isdir(source):
                    shutil.copytree(source, target, symlinks=True)
                else:
                    shutil.copy2(source, target)
            except OSError as exc:
                errors.append(f"{os.path.basename(source)}: {exc}")
        self._pending_cut = []
        if errors:
            QMessageBox.warning(
                self, "LinRAR", "Some items could not be pasted:\n\n" + "\n".join(errors)
            )
        self._populate_filesystem()

    def cmd_copy_path(self) -> None:
        from PyQt6.QtWidgets import QApplication

        items = self.list_view.selected_items()
        if items:
            if self.in_archive:
                text = "\n".join(i.path for i in items)
            else:
                text = "\n".join(i.path for i in items)
        else:
            text = self.archive_path or self.current_folder
        QApplication.clipboard().setText(text)
        self.statusBar().showMessage("Path copied to the clipboard", 4000)

    def cmd_properties(self) -> None:
        items = self.list_view.selected_items()
        if not items:
            if self.in_archive and self.archive_info is not None:
                self.cmd_info()
            return
        item = items[0]
        PropertiesDialog(
            self,
            name=item.name,
            path=item.path,
            entry=item.entry,
            archive=self.archive_path or "",
        ).exec()

    def cmd_save_as(self) -> None:
        """Extract one archived file to a location the user picks."""
        if not self.in_archive:
            return
        items = [i for i in self.list_view.selected_items() if not i.is_dir]
        if len(items) != 1:
            QMessageBox.information(self, "LinRAR", "Select a single file to save.")
            return
        item = items[0]
        target, _f = QFileDialog.getSaveFileName(
            self, "Save file as", os.path.join(self.current_folder, item.name)
        )
        if not target:
            return

        backend = self._backend_for_open_archive()
        if backend is None or self.archive_path is None:
            return
        workdir = tempfile.mkdtemp(prefix="linrar-save-")
        self._temp_dirs.append(workdir)
        options = ExtractOptions(
            destination=workdir,
            members=[item.path],
            overwrite_mode=OverwriteMode.OVERWRITE,
        )
        archive_path = self.archive_path

        def make_work(password: Optional[str]):
            options.password = password

            def work(ctx: TaskContext):
                backend.extract(archive_path, options, ctx)
                return True

            return work

        ok, _r = self._run_with_password(
            make_work, f"Extracting {item.name}", item.size, 1
        )
        if not ok:
            return
        source = os.path.join(workdir, item.path)
        if not os.path.isfile(source):
            for root, _dirs, names in os.walk(workdir):
                if item.name in names:
                    source = os.path.join(root, item.name)
                    break
        try:
            shutil.copy2(source, target)
        except OSError as exc:
            QMessageBox.warning(self, "LinRAR", f"Cannot save the file.\n\n{exc}")
            return
        self.statusBar().showMessage(f"Saved to {target}", 5000)

    # -- new tool commands -------------------------------------------------

    def cmd_convert_archives(self) -> None:
        sources = []
        if not self.in_archive:
            sources = [
                i.path for i in self.list_view.selected_items()
                if not i.is_dir and looks_like_archive(i.name)
            ]
        elif self.archive_path:
            sources = [self.archive_path]
        ConvertDialog(self, sources).exec()
        if not self.in_archive:
            self._populate_filesystem()

    def cmd_report(self) -> None:
        if self.archive_info is None:
            QMessageBox.information(
                self, "LinRAR", "Open an archive to generate a report."
            )
            return
        ReportDialog(self, self.archive_info).exec()

    def cmd_profiles(self) -> None:
        dialog = ProfileDialog(self)
        if dialog.exec() == ProfileDialog.DialogCode.Accepted and dialog.chosen:
            self._pending_profile = dialog.chosen
            self.statusBar().showMessage(
                f"Profile '{dialog.chosen.name}' will be used for the next "
                "archive you create",
                6000,
            )

    def cmd_passwords(self) -> None:
        PasswordManagerDialog(self).exec()

    def cmd_organize_favorites(self) -> None:
        if FavoritesDialog(self).exec() == FavoritesDialog.DialogCode.Accepted:
            self._rebuild_favorites()

    def cmd_recovery_volumes(self) -> None:
        if self.archive_path is None or self.archive_info is None:
            return
        if not self.archive_info.volume:
            QMessageBox.information(
                self,
                "Recovery volumes",
                "Recovery volumes can only be added to a multi-volume "
                "archive.\n\nCreate the archive with 'Split to volumes' first, "
                "then add recovery volumes here.",
            )
            return
        percent, ok = QInputDialog.getInt(
            self,
            "Add recovery volumes",
            "Recovery volumes as a percentage of the volume count:",
            3, 1, 100,
        )
        if not ok:
            return
        path = self.archive_path
        backend = REGISTRY.rar

        def work(ctx: TaskContext):
            backend.add_recovery_volumes(path, f"{percent}%", ctx)
            return True

        ok2, _r, error = self._run_task(work, "Creating recovery volumes")
        if not ok2:
            if error is not None:
                self._report(error)
            return
        QMessageBox.information(
            self, "LinRAR", "Recovery volumes (.rev) created."
        )
        self.refresh()

    def cmd_reconstruct(self) -> None:
        path = self.archive_path
        if path is None:
            selected = [i for i in self.list_view.selected_items() if not i.is_dir]
            if len(selected) != 1:
                QMessageBox.information(
                    self,
                    "LinRAR",
                    "Select the first volume of the set, or open it first.",
                )
                return
            path = selected[0].path
        backend = REGISTRY.rar

        def work(ctx: TaskContext):
            backend.reconstruct_volumes(path, ctx)
            return True

        ok, _r, error = self._run_task(work, "Reconstructing volumes")
        if not ok:
            if error is not None:
                self._report(error)
            return
        QMessageBox.information(
            self, "LinRAR", "Volume reconstruction finished."
        )
        if not self.in_archive:
            self._populate_filesystem()

    def cmd_sfx_stub(self) -> None:
        """rar's own Linux .sfx stub, as an alternative to the AppImage."""
        if self.archive_path is None or self.archive_info is None:
            return
        if self.archive_info.format not in (ArchiveFormat.RAR5, ArchiveFormat.RAR4):
            QMessageBox.information(
                self, "LinRAR", "Only RAR archives can use the rar SFX stub."
            )
            return
        source = self.archive_path
        backend = REGISTRY.rar

        def work(ctx: TaskContext):
            return backend.convert_to_sfx(source, ctx)

        ok, result, error = self._run_task(work, "Creating SFX archive")
        if not ok:
            if error is not None:
                self._report(error)
            return
        QMessageBox.information(
            self, "LinRAR", f"Self-extracting archive created:\n{result}"
        )
        if not self.in_archive:
            self._populate_filesystem()

    def cmd_help_topics(self) -> None:
        HelpDialog(self).exec()

    def cmd_shortcuts(self) -> None:
        HelpDialog(self, page=HelpDialog.SHORTCUTS).exec()

    # ------------------------------------------------------------------
    # customization
    # ------------------------------------------------------------------

    def _apply_policy(self) -> None:
        """Grey out every menu entry whose setting is not the user's to change.

        Without this the menu would still toggle, the view would still change,
        and nothing would be remembered — which reads as a bug rather than as
        a decision somebody made on purpose.
        """
        self.locked_settings = policy.guard_actions({
            "view/show_tree": self.act_show_tree,
            "view/show_comment": self.act_show_comment,
            "toolbar/style": self.act_toolbar_text,
            "view/show_hidden": self.act_show_hidden,
            "view/show_toolbar": self.act_show_toolbar,
            "view/show_address": self.act_show_address,
            "view/show_status": self.act_show_status,
            "view/grid_lines": self.act_grid_lines,
            "view/alternate_rows": self.act_alternate_rows,
            # The corner switch and its toolbar button are the same action.
            "view/theme": self.act_toggle_theme,
        })
        # A group of mutually exclusive entries stands for one setting, so it
        # is all of them or none.
        for key, group in (
            ("view/theme", self.theme_actions),
            ("view/mode", self.view_mode_actions),
            ("view/tree_side", self.tree_side_actions),
            ("view/comment_side", self.comment_side_actions),
        ):
            if not SETTINGS.is_locked(key):
                continue
            policy.guard_actions([(key, action) for action in group.values()])
            if key not in self.locked_settings:
                self.locked_settings.append(key)
        # A submenu whose every entry is greyed out should not invite a click.
        if SETTINGS.is_locked("view/theme"):
            policy.guard_actions([("view/theme", self.theme_menu.menuAction())])

    def set_view_mode(self, mode: str) -> None:
        """Switch the file pane between Details, List, icons and tiles."""
        mode = mode if mode in filelist.VIEW_MODES else filelist.DETAILS
        SETTINGS.set("view/mode", mode)
        self.apply_view_options()

    def apply_view_options(self) -> None:
        """Push every saved file-list preference onto the pane."""
        mode = SETTINGS.get("view/mode")
        if mode not in filelist.VIEW_MODES:
            mode = filelist.DETAILS
        self.list_view.set_mode(mode)
        self.list_view.set_row_spacing(
            filelist.ROW_SPACING.get(SETTINGS.get("view/row_height"), 4)
        )
        self.list_view.set_grid_lines(bool(SETTINGS.get("view/grid_lines")))
        self.list_view.set_alternating(
            bool(SETTINGS.get("view/alternate_rows"))
        )
        for name, action in self.view_mode_actions.items():
            action.setChecked(name == mode)
        self.act_grid_lines.setChecked(bool(SETTINGS.get("view/grid_lines")))
        self.act_alternate_rows.setChecked(
            bool(SETTINGS.get("view/alternate_rows"))
        )
        self._build_columns_menu()

    def apply_layout(self) -> None:
        """Put the tree, comment pane and bars where the settings say."""
        # -- folder tree side --
        tree_width = max(self.tree.width(), 160)
        want = 1 if SETTINGS.get("view/tree_side") == "right" else 0
        if self.splitter.indexOf(self.tree) != want:
            self.splitter.insertWidget(want, self.tree)
            total = sum(self.splitter.sizes()) or self.width()
            self.splitter.setSizes(
                [total - tree_width, tree_width] if want
                else [tree_width, total - tree_width]
            )
        self.splitter.setStretchFactor(0, 0 if want == 0 else 1)
        self.splitter.setStretchFactor(1, 1 if want == 0 else 0)
        self.tree.setVisible(bool(SETTINGS.get("view/show_tree")))

        # -- comment pane side --
        want_comment = 0 if SETTINGS.get("view/comment_side") == "top" else 1
        if self.right_splitter.indexOf(self.comment_pane) != want_comment:
            self.right_splitter.insertWidget(want_comment, self.comment_pane)
        self.right_splitter.setStretchFactor(want_comment, 0)
        self.right_splitter.setStretchFactor(1 - want_comment, 1)
        self._show_comment_pane(bool(SETTINGS.get("view/show_comment")))

        # -- bars --
        area = (
            Qt.ToolBarArea.BottomToolBarArea
            if SETTINGS.get("view/toolbar_area") == "bottom"
            else Qt.ToolBarArea.TopToolBarArea
        )
        if self.toolBarArea(self.toolbar) != area:
            self.addToolBar(area, self.toolbar)
        self.toolbar.setVisible(bool(SETTINGS.get("view/show_toolbar")))
        self.address_bar.setVisible(bool(SETTINGS.get("view/show_address")))
        self.statusBar().setVisible(bool(SETTINGS.get("view/show_status")))

        for name, action in (
            ("show_toolbar", self.act_show_toolbar),
            ("show_address", self.act_show_address),
            ("show_status", self.act_show_status),
            ("show_tree", self.act_show_tree),
            ("show_comment", self.act_show_comment),
        ):
            action.setChecked(bool(SETTINGS.get(f"view/{name}")))
        for side, action in self.tree_side_actions.items():
            action.setChecked(SETTINGS.get("view/tree_side") == side)
        for side, action in self.comment_side_actions.items():
            action.setChecked(SETTINGS.get("view/comment_side") == side)

    def set_tree_side(self, side: str) -> None:
        SETTINGS.set("view/tree_side", side if side == "right" else "left")
        self.apply_layout()

    def set_comment_side(self, side: str) -> None:
        SETTINGS.set("view/comment_side", side if side == "top" else "bottom")
        self.apply_layout()

    def toggle_toolbar(self, checked: bool) -> None:
        SETTINGS.set("view/show_toolbar", checked)
        self.toolbar.setVisible(checked)

    def toggle_address_bar(self, checked: bool) -> None:
        SETTINGS.set("view/show_address", checked)
        self.address_bar.setVisible(checked)

    def toggle_status_bar(self, checked: bool) -> None:
        SETTINGS.set("view/show_status", checked)
        self.statusBar().setVisible(checked)

    def toggle_grid_lines(self, checked: bool) -> None:
        SETTINGS.set("view/grid_lines", checked)
        self.list_view.set_grid_lines(checked)

    def toggle_alternate_rows(self, checked: bool) -> None:
        SETTINGS.set("view/alternate_rows", checked)
        self.list_view.set_alternating(checked)

    def cmd_customize(self) -> None:
        """Options > Customize: toolbar, file list and layout in one place."""
        dialog = CustomizeDialog(self)
        dialog.applied.connect(self._apply_customization)
        if dialog.exec() == CustomizeDialog.DialogCode.Accepted:
            self._apply_customization()

    def _apply_customization(self) -> None:
        self.rebuild_toolbar()
        self.apply_view_options()
        self.apply_layout()

    def cmd_reset_layout(self) -> None:
        reply = QMessageBox.question(
            self,
            "Reset the interface",
            "Put the toolbar, file list and window layout back to the way "
            "LinRAR ships?\n\nYour archives and other settings are untouched.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        SETTINGS.reset(
            "toolbar/items", "toolbar/icon_size", "toolbar/style",
            "view/mode", "view/tree_side", "view/comment_side",
            "view/show_toolbar", "view/show_address", "view/show_status",
            "view/toolbar_area", "view/row_height", "view/grid_lines",
            "view/alternate_rows", "view/show_tree", "view/show_comment",
            "geometry/columns", "geometry/splitter",
        )
        SETTINGS.sync()
        self.list_view.details.header().reset()
        self.list_view.configure_columns(self.in_archive)
        self._apply_customization()
        self.statusBar().showMessage("Interface reset", 3000)

    def cmd_settings(self) -> None:
        if SettingsDialog(self).exec() != SettingsDialog.DialogCode.Accepted:
            return
        chosen = theme.normalize(SETTINGS.get("view/theme"))
        if chosen != theme.mode():
            self.set_theme(chosen)
        self.act_show_hidden.setChecked(SETTINGS.get("view/show_hidden"))
        self._apply_customization()
        self.refresh()

    def cmd_benchmark(self) -> None:
        BenchmarkDialog(self).exec()

    def cmd_dependencies(self) -> None:
        DependenciesDialog(self).exec()
        # Tool availability may have changed, so re-evaluate what is possible.
        REGISTRY.refresh()
        self._update_actions()
        self.update_dependency_state()

    def cmd_about(self) -> None:
        AboutDialog(self).exec()

    def cmd_add_favorite(self) -> None:
        target = self.archive_path or self.current_folder
        favorites = SETTINGS.favorites()
        if target not in favorites:
            favorites.append(target)
            SETTINGS.set_favorites(favorites)
            self._rebuild_favorites()
        self.statusBar().showMessage(f"Added to favorites: {target}", 4000)

    def _rebuild_favorites(self) -> None:
        self.favorites_menu.clear()
        self.favorites_menu.addAction(self.act_add_favorite)
        self.favorites_menu.addAction(self.act_organize_favorites)
        favorites = SETTINGS.favorites()
        if favorites:
            self.favorites_menu.addSeparator()
        for entry in favorites:
            is_dir = os.path.isdir(entry)
            action = self.favorites_menu.addAction(
                icons.icon("folder" if is_dir else "archive-small"), entry
            )
            action.triggered.connect(
                lambda _checked=False, path=entry: (
                    self.navigate_to(path) if os.path.isdir(path)
                    else self.open_archive(path)
                )
            )
        if favorites:
            self.favorites_menu.addSeparator()
            clear = self.favorites_menu.addAction("Clear favorites")
            clear.triggered.connect(self._clear_favorites)

    def _clear_favorites(self) -> None:
        SETTINGS.set_favorites([])
        self._rebuild_favorites()

    # -- appearance --------------------------------------------------------

    def set_theme(self, mode: str) -> None:
        """Repaint the whole application in the light or the dark theme."""
        mode = theme.normalize(mode)
        SETTINGS.set("view/theme", mode)
        SETTINGS.sync()

        app = QApplication.instance()
        if app is not None:
            theme.apply(app, mode)

        self._refresh_icons()
        self._sync_theme_widgets()
        # Icons already handed out to items belong to the old build, so the
        # listing and the tree are filled in again from the new one.
        if self.in_archive:
            self.refresh()
        else:
            self.tree.show_filesystem(self.current_folder)
            self._populate_filesystem()
        self._update_path_combo(self.archive_path or self.current_folder)
        self._rebuild_favorites()
        self.statusBar().showMessage(
            f"{theme.MODE_LABELS[mode]} theme applied", 2500
        )

    def toggle_theme(self) -> None:
        self.set_theme(
            theme.DARK if theme.mode() == theme.LIGHT else theme.LIGHT
        )

    def _sync_theme_widgets(self) -> None:
        """Keep the theme menu and the toolbar switch showing the right state."""
        mode = theme.mode()
        for name, action in self.theme_actions.items():
            action.setChecked(name == mode)

        other = theme.DARK if mode == theme.LIGHT else theme.LIGHT
        label = theme.MODE_LABELS[other].lower()
        self.act_toggle_theme.setIcon(icons.icon(f"theme-{other}"))
        self.act_toggle_theme.setProperty("iconName", f"theme-{other}")
        self.act_toggle_theme.setText(f"Switch to the {label} theme")
        self.act_toggle_theme.setIconText("Theme")
        self.act_toggle_theme.setToolTip(f"Switch to the {label} theme")
        self.act_toggle_theme.setStatusTip(f"Switch to the {label} theme")
        menu = getattr(self, "theme_menu", None)
        if menu is not None:
            menu.setIcon(icons.icon(f"theme-{mode}"))

    def _refresh_icons(self) -> None:
        """Re-issue every icon from the build that matches the new theme."""
        for action in self.findChildren(QAction):
            name = action.property("iconName")
            if name:
                action.setIcon(icons.icon(name))
        self.setWindowIcon(icons.icon("app"))
        for button in (self.disk_button, self.key_button):
            name = button.property("iconName")
            button.setIcon(icons.icon(name))

    # -- view toggles ------------------------------------------------------

    def toggle_tree(self, checked: bool) -> None:
        self.tree.setVisible(checked)
        SETTINGS.set("view/show_tree", checked)

    def toggle_comment(self, checked: bool) -> None:
        self._show_comment_pane(checked)
        SETTINGS.set("view/show_comment", checked)

    def _show_comment_pane(self, visible: bool) -> None:
        """Show/hide the comment pane, giving it real height when revealed.

        A splitter child that was hidden when the splitter last laid out keeps a
        zero size, so it must be re-proportioned explicitly.
        """
        self.comment_pane.setVisible(visible)
        if visible:
            total = sum(self.right_splitter.sizes()) or self.height()
            comment = min(110, max(70, total // 5))
            self.right_splitter.setSizes([total - comment, comment])

    def toggle_toolbar_text(self, checked: bool) -> None:
        """The quick on/off for captions; Customize offers all four styles."""
        current = SETTINGS.get("toolbar/style")
        SETTINGS.set(
            "toolbar/style",
            ("under" if current == "icon" else current) if checked else "icon",
        )
        self.rebuild_toolbar()

    def toggle_hidden(self, checked: bool) -> None:
        SETTINGS.set("view/show_hidden", checked)
        self.refresh()

    # -- shutdown ----------------------------------------------------------

    def closeEvent(self, event) -> None:
        running = [
            t for t in [self._task, *self._background_tasks]
            if t is not None and t.isRunning()
        ]
        if running:
            reply = QMessageBox.question(
                self,
                "LinRAR",
                "An operation is still running. Cancel it and quit?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            for task in running:
                task.cancel()
            for task in running:
                task.wait(3000)

        SETTINGS.save_geometry("main", self.saveGeometry())
        SETTINGS.save_geometry("splitter", self.splitter.saveState())
        SETTINGS.save_geometry("columns", self.list_view.header_state())
        SETTINGS.sync()
        for path in self._temp_dirs:
            shutil.rmtree(path, ignore_errors=True)
        super().closeEvent(event)


def _total_bytes(paths: list[str]) -> tuple[int, int]:
    """Return ``(total_bytes, file_count)`` for a selection, walking folders."""
    total = 0
    count = 0
    for item in paths:
        if os.path.isdir(item):
            for root, _dirs, names in os.walk(item):
                for name in names:
                    count += 1
                    try:
                        total += os.path.getsize(os.path.join(root, name))
                    except OSError:
                        pass
        else:
            count += 1
            try:
                total += os.path.getsize(item)
            except OSError:
                pass
    return total, count


def _entries_bytes(info: ArchiveInfo, members: list[str]) -> int:
    if not members:
        return info.total_size
    wanted = set(members)
    return sum(e.size for e in info.entries if not e.is_dir and e.name in wanted)


def _unique_path(target: str) -> str:
    """``name(1).ext`` style path used when pasting over an existing name."""
    if not os.path.exists(target):
        return target
    stem, ext = os.path.splitext(target)
    index = 1
    while os.path.exists(f"{stem}({index}){ext}"):
        index += 1
    return f"{stem}({index}){ext}"


def _archive_stem(path: str) -> str:
    """"foo.part01.rar" -> "foo", "foo.tar.gz" -> "foo"."""
    name = os.path.basename(path)
    for _ in range(2):
        stem, ext = os.path.splitext(name)
        if ext.lower() in (".rar", ".zip", ".7z", ".gz", ".bz2", ".xz", ".tar", ".zst"):
            name = stem
        else:
            break
    if name.lower().endswith(".part01") or name.lower().endswith(".part1"):
        name = name.rsplit(".", 1)[0]
    return name or "extracted"
