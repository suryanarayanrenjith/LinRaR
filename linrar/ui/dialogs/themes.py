"""Options > Themes: pick a theme, drop one in, or find out why one will not load.

WinRAR's theme dialog is a list and a picture of what you would get.  This one
is the same, except the picture is real: the preview is a working miniature of
the main window -- toolbar, list pane, headers, buttons, boxes -- with the
candidate theme's style sheet set on it and nothing else.  A Qt style sheet on
an ancestor beats the application's for that subtree, so the preview is not an
approximation of the theme; it *is* the theme, rendered by the same code that
would render the window, and next to a window still wearing the old one.

That matters more than it sounds.  A theme is a file from a stranger, and the
only honest way to answer "what will this do to my window" is to do it, in a
corner, where cancelling costs nothing.

Three things this window is built around:

**Dropping a theme on it installs it.**  Anywhere on the window, any number at
once, a folder or a file.  There is a card saying so, because a drop target
nobody knows about is not a feature, and it names the folder the themes go into
so dragging one there in a file manager works just as well.

**A theme that will not load is *shown*.**  It appears in the list under "needs
fixing", with what is wrong, what belongs there instead and a line of JSON to
copy.  A theme somebody just dropped in and cannot find anywhere is the one
failure they have no way to look into, so silence is the worst possible answer.

**Nothing is destructive by accident.**  *Apply* repaints the application and
leaves the window open, *Cancel* puts back the theme that was in force when it
opened, and *Remove* only ever offers to delete out of a folder this user owns.

And because LinRAR ships with only the two themes drawn into it, this window
says where the others are: ten to download and a builder that makes one from a
dozen colours, both on the website.  A theme chooser that lists two themes and
never mentions that is a dead end.
"""

from __future__ import annotations

import os

from PyQt6.QtCore import QSize, Qt, QUrl
from PyQt6.QtGui import QAction, QColor, QDesktopServices, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QStackedWidget,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...core import themes as packs
from ...version import THEMES_URL, THEME_BUILDER_URL
from .. import icons, policy, theme

#: A row's theme id, for the rows that are themes.
_ID_ROLE = Qt.ItemDataRole.UserRole + 1
#: A row's path, for the rows that are files needing attention.
_PATH_ROLE = Qt.ItemDataRole.UserRole + 2


def _locked() -> bool:
    """Has an administrator fixed the theme for every user of this machine?

    Imported where it is used rather than at the top of the module: the
    settings singleton reads files on construction, and a dialog nobody opens
    should not be a reason to have done that.
    """
    from ...core.settings import SETTINGS

    return SETTINGS.is_locked("view/theme")


def _swatch(colors, size: int = 34) -> QIcon:
    """A little card in a theme's own colours, for its row in the list.

    Four bands rather than one: a theme is a window colour, a list colour, a
    selection colour and an accent, and which of those a person recognises is
    not something to guess at.
    """
    ratio = 2
    pixmap = QPixmap(size * ratio, size * ratio)
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(QColor(colors.window))
    painter = QPainter(pixmap)
    painter.scale(ratio, ratio)
    painter.fillRect(0, 0, size, size // 3, QColor(colors.bar_mid))
    painter.fillRect(3, size // 3, size - 6, size // 3, QColor(colors.base))
    painter.fillRect(3, size // 3, size - 6, 5, QColor(colors.sel_bottom))
    painter.fillRect(0, size - size // 4, size, size // 4,
                     QColor(colors.status_bottom))
    painter.setPen(QColor(colors.bar_edge))
    painter.drawRect(0, 0, size - 1, size - 1)
    painter.end()
    return QIcon(pixmap)


def _dropped_paths(mime) -> list[str]:
    """The local files in a drag, or [] if it is not carrying any."""
    if not mime.hasUrls():
        return []
    found = []
    for url in mime.urls():
        path = url.toLocalFile()
        if path and os.path.exists(path):
            found.append(path)
    return found


class ThemePreview(QFrame):
    """A working miniature of the window, wearing one theme.

    Built out of the same widget classes and the same object names the real
    window uses, because that is what makes the style sheet apply: a preview
    drawn by hand with a painter would only ever show what its author
    remembered to draw.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("ThemePreview")
        self.setFrameShape(QFrame.Shape.NoFrame)
        # A widget with a style sheet in effect paints its background from that
        # sheet rather than from autoFillBackground, and the sheet's window rule
        # names QMainWindow and QDialog -- neither of which this is.  So the
        # frame is given the flag and a rule of its own in show_theme(); without
        # both, everything transparent in the preview (the group box, the column
        # the controls sit in) shows the *dialog's* background instead, and the
        # theme's own text ends up on it.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._build_name = theme.active()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # -- the toolbar, with real actions so the buttons are real buttons --
        self.toolbar = QToolBar()
        self.toolbar.setObjectName("MainToolBar")
        self.toolbar.setMovable(False)
        self.toolbar.setIconSize(QSize(24, 24))
        self.toolbar.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextUnderIcon
        )
        self._buttons: list[QAction] = []
        for name, caption in (
            ("add", "Add"), ("extract-to", "Extract"), ("test", "Test"),
            ("view", "View"), ("delete", "Delete"), ("find", "Find"),
        ):
            action = QAction(caption, self)
            action.setProperty("iconName", name)
            self.toolbar.addAction(action)
            self._buttons.append(action)
        outer.addWidget(self.toolbar)

        # -- the address bar --
        address = QWidget()
        address.setObjectName("AddressBar")
        address_row = QHBoxLayout(address)
        address_row.setContentsMargins(6, 3, 6, 3)
        address_row.setSpacing(6)
        self.address_icon = QLabel()
        address_row.addWidget(self.address_icon)
        self.path = QComboBox()
        self.path.addItem("/home/you/Downloads")
        address_row.addWidget(self.path, 1)
        outer.addWidget(address)

        # -- the file list --
        body = QWidget()
        body_row = QHBoxLayout(body)
        body_row.setContentsMargins(6, 6, 6, 4)
        body_row.setSpacing(6)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["Name", "Size", "Type"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.tree.setColumnWidth(0, 150)
        self.tree.setColumnWidth(1, 66)
        # One of every icon family the file list draws, so a theme's own artwork
        # is what is on show rather than five copies of one glyph.
        self._rows = [
            ("archive", "backup.rar", "1.2 MB", "RAR archive"),
            ("folder", "photos", "", "Folder"),
            ("file-image", "sunset.jpg", "842 KB", "JPEG image"),
            ("file-word", "letter.docx", "24 KB", "Word document"),
            ("file-code", "build.py", "11 KB", "Python source"),
            ("file-text", "notes.txt", "3 KB", "Text file"),
        ]
        body_row.addWidget(self.tree, 1)

        # -- a column of controls, so every widget family is on show --
        side = QVBoxLayout()
        side.setSpacing(6)
        box = QGroupBox("Options")
        box_layout = QVBoxLayout(box)
        box_layout.setSpacing(5)
        self.solid = QCheckBox("Solid archive")
        self.solid.setChecked(True)
        self.recovery = QCheckBox("Recovery record")
        self.best = QRadioButton("Best")
        self.best.setChecked(True)
        self.fastest = QRadioButton("Fastest")
        self.name_edit = QLineEdit("backup.rar")
        for widget in (self.solid, self.recovery, self.best, self.fastest,
                       self.name_edit):
            box_layout.addWidget(widget)
        side.addWidget(box)
        self.bar = QProgressBar()
        self.bar.setValue(62)
        side.addWidget(self.bar)
        buttons = QHBoxLayout()
        self.ok = QPushButton("OK")
        self.ok.setDefault(True)
        self.cancel = QPushButton("Cancel")
        buttons.addWidget(self.ok)
        buttons.addWidget(self.cancel)
        side.addLayout(buttons)
        side.addStretch(1)
        body_row.addLayout(side)
        outer.addWidget(body, 1)

        # -- the status bar --
        status = QWidget()
        status.setObjectName("Banner")
        status_row = QHBoxLayout(status)
        status_row.setContentsMargins(6, 3, 6, 3)
        self.status = QLabel("6 items, 2.0 MB")
        self.status.setObjectName("StatusPane")
        status_row.addWidget(self.status)
        status_row.addStretch(1)
        self.heading = QLabel("Sample")
        self.heading.setObjectName("Hint")
        status_row.addWidget(self.heading)
        outer.addWidget(status)

    def show_theme(self, name: str) -> None:
        """Wear the theme called *name*."""
        colors = theme.colors_for(name)
        build = name if theme.is_pack(name) else theme.variant_of(colors)
        self._build_name = build

        for action in self._buttons:
            action.setIcon(icons.icon_for(build, action.property("iconName")))
        self.address_icon.setPixmap(icons.pixmap_for(build, "folder", 16))
        self.path.setItemIcon(0, icons.icon_for(build, "disk"))

        self.tree.clear()
        for icon_name, name_text, size, kind in self._rows:
            item = QTreeWidgetItem([name_text, size, kind])
            item.setIcon(0, icons.icon_for(build, icon_name))
            self.tree.addTopLevelItem(item)
        # One row selected, because the selection colour is the single thing
        # people pick a theme on and it is invisible until something is chosen.
        first = self.tree.topLevelItem(0)
        if first is not None:
            first.setSelected(True)

        # The palette carries what a style sheet cannot: alternating row
        # colours, and whatever a widget draws with QPalette directly.
        self.setPalette(theme.qt_palette(colors))
        self.setStyleSheet(
            theme.stylesheet(colors)
            # The 3D face the whole preview sits on, standing in for the rule
            # the real window gets as a QMainWindow.
            + f"\n#ThemePreview {{ background: {colors.window}; }}\n"
        )
        # The sheet changed under widgets that are already realised, and Qt
        # only re-reads it for a widget it is told to.
        for widget in [self, *self.findChildren(QWidget)]:
            widget.style().unpolish(widget)
            widget.style().polish(widget)
        self.update()


class DropCard(QLabel):
    """The card that says a theme can be dropped here, and lights up when one is.

    A label rather than anything cleverer, but it carries its own style sheet:
    it has to look like a drop target in every theme, including the ones whose
    chrome it is sitting in, so it cannot borrow the dialog's colours.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("DropCard")
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumHeight(74)
        self.setSizePolicy(QSizePolicy.Policy.Preferred,
                           QSizePolicy.Policy.Minimum)
        self._folder = ""
        self.set_active(False)

    def set_folder(self, folder: str) -> None:
        self._folder = folder
        self.set_active(False)

    def set_active(self, active: bool) -> None:
        colors = theme.current()
        edge = colors.focus_border if active else colors.border
        wash = colors.row_hover if active else colors.alt_base
        self.setStyleSheet(
            f"#DropCard {{ border: 2px dashed {edge}; border-radius: "
            f"{max(colors.card_radius, 4)}px; background: {wash}; "
            f"color: {colors.text_dim}; padding: 8px 10px; }}"
        )
        if active:
            self.setText("<b>Let go to install</b>")
            return
        where = self._folder or packs.writable_dir()
        home = os.path.expanduser("~")
        if where.startswith(home):
            where = "~" + where[len(home):]
        self.setText(
            "<b>Drag a theme here to install it</b><br>"
            "a theme folder, or a <code>.linrar-theme</code> file, or drop it "
            f"straight into<br><code>{where}</code>"
        )


class ThemeManagerDialog(QDialog):
    """The theme chooser: list on the left, live preview on the right."""

    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.setWindowTitle("Themes")
        self.setWindowIcon(icons.icon("themes"))
        self.resize(980, 660)
        # Dropped anywhere on the window, not only on the card: the card is
        # there to say the window takes drops, not to be a small target.
        self.setAcceptDrops(True)

        #: What to go back to if the dialog is cancelled after an Apply.
        self._original = theme.active()
        self._applied = self._original

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.lock_banner = policy.banner(
            ["view/theme"] if _locked() else [], self
        )
        if self.lock_banner is not None:
            layout.addWidget(self.lock_banner)

        split = QHBoxLayout()
        split.setSpacing(10)
        split.addLayout(self._left_column(), 0)
        split.addLayout(self._right_column(), 1)
        layout.addLayout(split, 1)

        # -- the buttons.  Hand-built rather than a QDialogButtonBox: Apply has
        # to sit next to OK and Cancel, and the theme-management buttons belong
        # on the same row, at the other end, where they read as tools rather
        # than as answers to the dialog.
        row = QHBoxLayout()
        row.setSpacing(6)
        self.install_button = QPushButton("Install theme file...")
        self.install_button.setIcon(icons.icon("download"))
        self.install_button.setToolTip(
            "Install a theme folder, a .linrar-theme file, or a zip of one"
        )
        self.install_button.clicked.connect(self._install)
        self.folder_button = QPushButton("Open themes folder")
        self.folder_button.setIcon(icons.icon("folder-open"))
        self.folder_button.clicked.connect(self._open_folder)
        self.remove_button = QPushButton("Remove")
        self.remove_button.setIcon(icons.icon("trash"))
        self.remove_button.clicked.connect(self._remove)
        self.rescan_button = QPushButton("Rescan")
        self.rescan_button.setIcon(icons.icon("refresh"))
        self.rescan_button.setToolTip(
            "Look at the theme folders again, after editing a theme by hand"
        )
        self.rescan_button.clicked.connect(lambda: self.reload(rescan=True))
        for widget in (self.install_button, self.folder_button,
                       self.remove_button, self.rescan_button):
            row.addWidget(widget)
        row.addStretch(1)
        self.apply_button = QPushButton("Apply")
        self.apply_button.clicked.connect(self._apply_selected)
        ok = QPushButton("OK")
        ok.setDefault(True)
        ok.clicked.connect(self._accept)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        for widget in (self.apply_button, ok, cancel):
            row.addWidget(widget)
        layout.addLayout(row)

        # Rescanned on the way in, not just read from the cache: dropping a
        # folder into the themes directory and opening this window is the
        # obvious way to install one by hand, and it should simply work.
        self.reload(select=self._original, rescan=True)

    # -- construction ------------------------------------------------------

    def _left_column(self) -> QVBoxLayout:
        column = QVBoxLayout()
        column.setSpacing(6)
        column.addWidget(QLabel("Installed themes"))
        self.list = QListWidget()
        self.list.setIconSize(QSize(34, 34))
        self.list.setMinimumWidth(248)
        self.list.setMaximumWidth(310)
        self.list.currentItemChanged.connect(self._selection_changed)
        self.list.itemDoubleClicked.connect(self._double_clicked)
        column.addWidget(self.list, 1)
        self.count_label = QLabel()
        self.count_label.setObjectName("Hint")
        self.count_label.setWordWrap(True)
        column.addWidget(self.count_label)
        self.drop_card = DropCard()
        column.addWidget(self.drop_card)
        column.addWidget(self._more_themes())
        return column

    def _more_themes(self) -> QWidget:
        """Where the other themes are.

        LinRAR has two themes of its own and no more; without this the window
        lists them, offers to install a file the reader has not got, and stops.
        Two links, phrased as the two things somebody actually wants: one more
        theme, or one of their own.
        """
        card = QWidget()
        card.setObjectName("Card")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 11)
        layout.setSpacing(2)

        heading = QLabel("Want more?")
        heading.setStyleSheet("font-weight: bold;")
        layout.addWidget(heading)
        blurb = QLabel(
            "LinRAR comes with the light and dark themes only. The rest are "
            "on the website."
        )
        blurb.setObjectName("Hint")
        blurb.setWordWrap(True)
        layout.addWidget(blurb)

        for caption, tip, url in (
            ("Download themes", "Ten to choose from, previewed in full: "
             f"{THEMES_URL}", THEMES_URL),
            ("Create your own", "Pick a dozen colours and the site "
             f"derives the rest: {THEME_BUILDER_URL}", THEME_BUILDER_URL),
        ):
            link = QPushButton(caption)
            link.setObjectName("LinkButton")
            link.setCursor(Qt.CursorShape.PointingHandCursor)
            link.setToolTip(tip)
            link.clicked.connect(
                lambda _checked=False, target=url: self._open_website(target)
            )
            layout.addWidget(link, 0, Qt.AlignmentFlag.AlignLeft)
        return card

    def _open_website(self, url: str) -> None:
        """Open a page in the desktop's browser, and say so if nothing does."""
        if QDesktopServices.openUrl(QUrl(url)):
            return
        QMessageBox.information(
            self, "LinRAR",
            "No browser answered. The themes are at:\n" + url,
        )

    def _right_column(self) -> QVBoxLayout:
        column = QVBoxLayout()
        column.setSpacing(6)

        self.title = QLabel()
        self.title.setObjectName("Heading")
        column.addWidget(self.title)
        # Two labels, not one with a newline in it: a wrapped QLabel in a
        # vertical layout reports the height of a *single* line as its size
        # hint, so a two-line one ends up underneath whatever comes next.
        self.byline = QLabel()
        self.byline.setObjectName("Hint")
        column.addWidget(self.byline)
        self.description = QLabel()
        self.description.setObjectName("Hint")
        self.description.setWordWrap(True)
        self.description.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.MinimumExpanding
        )
        column.addWidget(self.description)

        # Two pages: what a theme looks like, and why one will not load.  They
        # are never both useful, and a broken theme has nothing to preview.
        self.pages = QStackedWidget()
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        inner = QVBoxLayout(frame)
        inner.setContentsMargins(1, 1, 1, 1)
        self.preview = ThemePreview(frame)
        inner.addWidget(self.preview)
        self.pages.addWidget(frame)

        broken_page = QWidget()
        broken_layout = QVBoxLayout(broken_page)
        broken_layout.setContentsMargins(0, 0, 0, 0)
        broken_layout.setSpacing(6)
        self.broken_view = QPlainTextEdit()
        self.broken_view.setReadOnly(True)
        self.broken_view.setLineWrapMode(
            QPlainTextEdit.LineWrapMode.WidgetWidth
        )
        broken_layout.addWidget(self.broken_view, 1)
        broken_buttons = QHBoxLayout()
        self.copy_broken = QPushButton("Copy report")
        self.copy_broken.clicked.connect(
            lambda: QApplication.clipboard().setText(
                self.broken_view.toPlainText()
            )
        )
        self.delete_broken = QPushButton("Delete this file")
        self.delete_broken.setIcon(icons.icon("trash"))
        self.delete_broken.clicked.connect(self._delete_broken)
        broken_buttons.addWidget(self.copy_broken)
        broken_buttons.addWidget(self.delete_broken)
        broken_buttons.addStretch(1)
        broken_layout.addLayout(broken_buttons)
        self.pages.addWidget(broken_page)
        column.addWidget(self.pages, 1)

        # Problems on a theme that *did* load: shown under its preview, since
        # the theme is usable and this is a list of what to improve.
        self.problems = QPlainTextEdit()
        self.problems.setReadOnly(True)
        self.problems.setMaximumHeight(112)
        self.problems.setVisible(False)
        column.addWidget(self.problems)
        problem_row = QHBoxLayout()
        self.problem_label = QLabel()
        self.problem_label.setObjectName("Warning")
        self.problem_label.setWordWrap(True)
        self.problem_label.setVisible(False)
        problem_row.addWidget(self.problem_label, 1)
        self.copy_problems = QPushButton("Copy report")
        self.copy_problems.setVisible(False)
        self.copy_problems.clicked.connect(self._copy_problems)
        problem_row.addWidget(self.copy_problems, 0)
        column.addLayout(problem_row)

        self.origin = QLabel()
        self.origin.setObjectName("Hint")
        self.origin.setWordWrap(True)
        self.origin.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        column.addWidget(self.origin)
        return column

    # -- the list ----------------------------------------------------------

    def reload(self, select: str = "", rescan: bool = False) -> None:
        """Fill the list from what is installed, keeping the selection."""
        wanted = select or self.current_id()
        if rescan:
            theme.reload_packs()
        else:
            theme.packs()

        self.list.blockSignals(True)
        self.list.clear()
        for name in theme.available():
            colors = theme.colors_for(name)
            item = QListWidgetItem(theme.label(name))
            item.setIcon(_swatch(colors))
            item.setData(_ID_ROLE, name)
            info = theme.pack(name)
            if info is None:
                item.setToolTip(
                    f"{theme.label(name)}: built in, always available"
                )
            else:
                tip = [f"{theme.label(name)}: {info.base} theme"]
                if info.summary():
                    tip.append(info.summary())
                if info.description:
                    tip.append(info.description)
                if info.problems:
                    count = len(info.problems)
                    tip.append(f"{count} problem{'' if count == 1 else 's'}; "
                               "the rest of it was used")
                tip.append(info.path)
                item.setToolTip("\n".join(tip))
                if info.problems:
                    item.setText(f"{theme.label(name)}  (!)")
            self.list.addItem(item)

        broken = packs.broken()
        if broken:
            divider = QListWidgetItem("needs fixing")
            divider.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addItem(divider)
            for entry in broken:
                item = QListWidgetItem(entry.label)
                item.setIcon(icons.icon("package-alert"))
                item.setData(_PATH_ROLE, entry.path)
                item.setToolTip(
                    f"{entry.path}\n\n{entry.problem.expected}\n\n"
                    "Select it to see how to fix it."
                )
                self.list.addItem(item)
        self.list.blockSignals(False)

        self._select(wanted)
        self.drop_card.set_folder(packs.writable_dir())
        installed = len(theme.packs())
        text = f"2 built in, {installed} installed"
        if broken:
            text += (f", {len(broken)} need"
                     f"{'s' if len(broken) == 1 else ''} fixing")
        if not installed and not broken:
            # The empty state is the one that has to point somewhere: a chooser
            # offering two themes and an Install button is a dead end unless it
            # says where a third one comes from.
            text += "\nNone installed yet. Download some below, or drop one in."
        self.count_label.setText(text)

    def _select(self, name: str) -> None:
        for row in range(self.list.count()):
            item = self.list.item(row)
            if name and item.data(_ID_ROLE) == name:
                self.list.setCurrentRow(row)
                return
            if name and item.data(_PATH_ROLE) == name:
                self.list.setCurrentRow(row)
                return
        for row in range(self.list.count()):
            if self.list.item(row).data(_ID_ROLE):
                self.list.setCurrentRow(row)
                return

    def current_id(self) -> str:
        item = self.list.currentItem()
        return (item.data(_ID_ROLE) or "") if item is not None else ""

    def current_broken(self):
        """The :class:`~linrar.core.themes.BrokenTheme` selected, or None."""
        item = self.list.currentItem()
        path = (item.data(_PATH_ROLE) or "") if item is not None else ""
        if not path:
            return None
        return next((b for b in packs.broken() if b.path == path), None)

    def _double_clicked(self, item) -> None:
        if item is not None and item.data(_ID_ROLE):
            self._accept()

    def _selection_changed(self, *_args) -> None:
        entry = self.current_broken()
        if entry is not None:
            self._show_broken(entry)
            return
        name = self.current_id()
        if not name:
            return
        self.pages.setCurrentIndex(0)
        self.delete_broken.setEnabled(True)
        info = theme.pack(name)
        self.preview.show_theme(name)

        self.title.setText(theme.label(name))
        if info is None:
            variant = theme.variant_of(theme.colors_for(name))
            self.byline.setText(f"Built in, the {variant} theme LinRAR ships with")
            self.description.setText(
                "Drawn by LinRAR itself rather than inherited from the desktop, "
                "so a foreign GTK theme cannot bleed through it."
            )
            self.origin.setText("")
            self._show_problems(None)
        else:
            bits = [f"{info.base} theme"]
            if info.summary():
                bits.append(info.summary())
            bits.append(f"{icons.style_of(name)} icons")
            self.byline.setText(", ".join(bits))
            self.description.setText(info.description)
            extras = []
            if info.icon_svg:
                extras.append(f"{len(info.icon_svg)} icon(s) of its own")
            if info.stylesheet:
                extras.append("its own style sheet")
            if info.zipped:
                extras.append("read straight out of the archive")
            self.origin.setText(
                info.path + (f"\nAlso ships {', '.join(extras)}." if extras
                             else "")
            )
            self._show_problems(info)

        removable = bool(info is not None and info.removable)
        self.remove_button.setEnabled(removable)
        self.remove_button.setToolTip(
            "Delete this theme from your themes folder" if removable
            else "Built-in and system-wide themes cannot be removed"
        )
        self.apply_button.setEnabled(
            not _locked() and name != theme.active()
        )

    def _show_problems(self, info) -> None:
        """The panel under a preview: what to fix in a theme that does work."""
        if info is None or not info.problems:
            for widget in (self.problems, self.problem_label,
                           self.copy_problems):
                widget.setVisible(False)
            return
        count = len(info.problems)
        self.problem_label.setText(
            f"{count} problem{'' if count == 1 else 's'} in this theme. It is "
            "still usable: everything below was skipped, and the rest was used."
        )
        self.problems.setPlainText(
            "\n".join(problem.detail() for problem in info.problems)
        )
        for widget in (self.problems, self.problem_label, self.copy_problems):
            widget.setVisible(True)

    def _show_broken(self, entry) -> None:
        """The whole right-hand side, for a file that is not a usable theme."""
        self.pages.setCurrentIndex(1)
        self.title.setText(entry.label)
        self.byline.setText("This is in a themes folder and cannot be used")
        self.description.setText(f"It needs to be {entry.problem.expected}.")
        self.broken_view.setPlainText(
            f"{entry.path}\n\n{entry.problem.detail()}\n\n"
            "Fix it and press Rescan, or delete it."
        )
        self.origin.setText(entry.path)
        self._show_problems(None)
        self.remove_button.setEnabled(False)
        self.remove_button.setToolTip(
            "This is not a loaded theme: use Delete this file"
        )
        self.apply_button.setEnabled(False)
        self.delete_broken.setEnabled(packs._can_delete(entry.path))

    def _copy_problems(self) -> None:
        info = theme.pack(self.current_id())
        if info is not None:
            QApplication.clipboard().setText(info.report())

    # -- applying ----------------------------------------------------------

    def _apply(self, name: str) -> bool:
        """Repaint the whole application in *name*."""
        if _locked():
            return False
        window = self.parent()
        if window is not None and hasattr(window, "set_theme"):
            window.set_theme(name)
        else:                                   # pragma: no cover - defensive
            app = QApplication.instance()
            if app is not None:
                theme.apply(app, name)
        self._applied = theme.active()
        # The dialog is now wearing the new theme, and the preview's own sheet
        # still wins inside it, so only the row states need catching up.
        self.apply_button.setEnabled(self.current_id() != theme.active())
        self.drop_card.set_active(False)
        return True

    def _apply_selected(self) -> None:
        name = self.current_id()
        if name:
            self._apply(name)

    def _accept(self) -> None:
        name = self.current_id()
        if name and name != theme.active():
            self._apply(name)
        self.accept()

    def reject(self) -> None:
        """Cancel: put back whatever was in force when the dialog opened."""
        if self._applied != self._original:
            self._apply(self._original)
        super().reject()

    # -- installing, by button or by drop ----------------------------------

    def _install(self) -> None:
        paths, _filter = QFileDialog.getOpenFileNames(
            self,
            "Install themes",
            os.path.expanduser("~"),
            "LinRAR themes (*.linrar-theme *.theme *.zip *.json);;"
            "All files (*)",
        )
        if paths:
            self.install_paths(paths)

    def install_paths(self, paths: list[str]) -> None:
        """Install everything in *paths*, and say what happened to each."""
        if _locked():
            QMessageBox.information(
                self, "LinRAR",
                "The theme is set for every user of this machine by your "
                "system administrator, so installing another one would have "
                "no effect.",
            )
            return
        done, failed = packs.install_all(paths)
        self.reload(select=done[-1].id if done else "", rescan=True)

        if done and not failed:
            names = ", ".join(pack.label for pack in done)
            trouble = sum(len(pack.problems) for pack in done)
            message = (
                f"Installed {names}."
                if len(done) == 1 else f"Installed {len(done)} themes: {names}."
            )
            if trouble:
                message += (
                    f"\n\n{trouble} problem(s) were found in them; the details "
                    "are under the preview. They are still usable."
                )
            QMessageBox.information(self, "LinRAR", message)
            return
        if not done and failed:
            QMessageBox.warning(self, "LinRAR", self._failure_text(failed))
            return
        QMessageBox.warning(
            self, "LinRAR",
            f"Installed {len(done)} of {len(done) + len(failed)}.\n\n"
            + self._failure_text(failed),
        )

    @staticmethod
    def _failure_text(failed) -> str:
        lines = []
        for source, error in failed:
            lines.append(f"{os.path.basename(source)}\n{error.problem.detail()}")
        return "\n\n".join(lines)

    # -- drag and drop -----------------------------------------------------

    def dragEnterEvent(self, event) -> None:      # noqa: N802 - Qt's name
        if _dropped_paths(event.mimeData()) and not _locked():
            event.acceptProposedAction()
            self.drop_card.set_active(True)
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:       # noqa: N802 - Qt's name
        if _dropped_paths(event.mimeData()) and not _locked():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:      # noqa: N802 - Qt's name
        self.drop_card.set_active(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:           # noqa: N802 - Qt's name
        paths = _dropped_paths(event.mimeData())
        self.drop_card.set_active(False)
        if not paths:
            event.ignore()
            return
        event.acceptProposedAction()
        self.install_paths(paths)

    # -- removing ----------------------------------------------------------

    def _remove(self) -> None:
        name = self.current_id()
        info = theme.pack(name)
        if info is None:
            return
        reply = QMessageBox.question(
            self,
            "LinRAR",
            f"Delete the theme \"{info.label}\"?\n\n{info.path}\n\n"
            + ("The file is removed." if info.zipped
               else "The folder and everything in it is removed."),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            packs.remove(name)
        except (packs.ThemeError, OSError) as error:
            QMessageBox.warning(
                self, "LinRAR",
                f"{info.label} could not be removed.\n\n"
                + getattr(getattr(error, "problem", None), "fix", str(error)),
            )
            return
        # Deleting the theme in use would leave the window wearing a theme that
        # no longer exists, so it goes back to the built-in it was based on.
        fallback = theme.normalize(info.base)
        was_active = theme.active() == name
        if self._original == name:
            self._original = fallback
        self.reload(select=fallback, rescan=True)
        if was_active:
            self._apply(fallback)

    def _delete_broken(self) -> None:
        entry = self.current_broken()
        if entry is None:
            return
        reply = QMessageBox.question(
            self,
            "LinRAR",
            f"Delete {entry.path}?\n\nIt is not a usable theme, and nothing "
            "else refers to it.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            packs.remove_broken(entry.path)
        except (packs.ThemeError, OSError) as error:
            QMessageBox.warning(
                self, "LinRAR",
                "It could not be deleted.\n\n"
                + getattr(getattr(error, "problem", None), "fix", str(error)),
            )
            return
        self.reload(rescan=True)

    def _open_folder(self) -> None:
        """Reveal the writable themes folder in the desktop's file manager."""
        folder = packs.ensure_writable_dir()
        if not folder:
            QMessageBox.warning(
                self, "LinRAR",
                "The themes folder could not be created:\n"
                + packs.writable_dir(),
            )
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(folder)):
            QMessageBox.information(
                self, "LinRAR",
                "No file manager answered. Themes live in:\n" + folder,
            )
