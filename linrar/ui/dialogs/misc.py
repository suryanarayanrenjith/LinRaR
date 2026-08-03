"""Smaller dialogs: archive info, comment editor, find, settings, help, about."""

from __future__ import annotations

import os

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QFont, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTabWidget,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...core.models import ArchiveInfo, format_size, format_size_short
from ...core import elevation, filetypes, tools
from ...core.registry import REGISTRY
from ...core import settings as settings_module
from ...core.settings import SETTINGS
from ... import version as version_module
from ...version import REPOSITORY_URL, __version__, describe
from .. import icons, policy, theme

#: Kept under its old name because the whole interface says "APP_VERSION", but
#: there is only one version now and it lives in linrar/version.py.
APP_VERSION = __version__
AUTHOR = "Surya"
PORTFOLIO = "https://surya.is-a.dev/"
#: LinRAR's own home on the web, and where its source lives.  Both are shown
#: in About and are the two links the README points at.
WEBSITE = "https://linrar.vercel.app/"
REPOSITORY = REPOSITORY_URL


class InfoDialog(QDialog):
    """"Archive information": WinRAR's Ctrl+I property sheet."""

    def __init__(self, parent, info: ArchiveInfo) -> None:
        super().__init__(parent)
        self.setWindowTitle("Archive information")
        self.setWindowIcon(icons.icon("info"))
        self.resize(460, 430)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(9)

        header = QHBoxLayout()
        icon_label = QLabel()
        icon_label.setPixmap(icons.pixmap("archive", 48))
        header.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignTop)
        name = QLabel(f"<b>{os.path.basename(info.path)}</b>")
        name.setWordWrap(True)
        header.addWidget(name, 1, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(header)

        try:
            physical = os.path.getsize(info.path)
        except OSError:
            physical = 0

        group = QGroupBox("General")
        form = QFormLayout(group)
        form.setSpacing(4)
        form.addRow("Full path", _wrapped(os.path.dirname(info.path) or "/"))
        form.addRow("Archive format", QLabel(info.format.label))
        form.addRow("Details", QLabel(info.detail_line or "-"))
        form.addRow("Archive size", QLabel(f"{format_size(physical)} bytes"))
        form.addRow(
            "Total size", QLabel(f"{format_size(info.total_size)} bytes")
        )
        form.addRow(
            "Packed size", QLabel(f"{format_size(info.total_packed)} bytes")
        )
        form.addRow("Compression ratio", QLabel(f"{info.ratio}%"))
        form.addRow("Files", QLabel(str(info.file_count)))
        form.addRow("Folders", QLabel(str(info.folder_count)))
        layout.addWidget(group)

        flags = QGroupBox("Properties")
        flags_layout = QVBoxLayout(flags)
        flags_layout.setSpacing(2)
        for label, value in (
            ("Solid archive", info.solid),
            ("Locked", info.locked),
            ("Recovery record", info.recovery_record),
            ("Encrypted file names", info.encrypted_headers),
            ("Contains encrypted files", info.has_encrypted_entries),
            ("Volume (part of a set)", info.volume),
            ("Self-extracting (SFX)", info.sfx),
        ):
            check = QCheckBox(label)
            check.setChecked(bool(value))
            check.setEnabled(False)
            flags_layout.addWidget(check)
        layout.addWidget(flags)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)


class CommentDialog(QDialog):
    """Read or replace an archive comment."""

    def __init__(self, parent, archive_name: str, comment: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Comment - {os.path.basename(archive_name)}")
        self.setWindowIcon(icons.icon("comment"))
        self.resize(520, 380)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addWidget(QLabel("Archive comment"))

        self.editor = QPlainTextEdit(comment)
        self.editor.setFont(QFont("monospace", 9))
        layout.addWidget(self.editor, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def comment(self) -> str:
        return self.editor.toPlainText()


class ViewerDialog(QDialog):
    """The built-in viewer, which tries to show the file rather than its bytes.

    A viewer that answers every file with a hex dump is a viewer nobody opens
    twice.  This one asks :mod:`linrar.core.filetypes` what it is holding and
    shows the most useful thing it can:

    * **text and source** as text, in whatever encoding it turns out to be;
    * **images** as images, scaled to fit;
    * **Word, PowerPoint, Excel, OpenDocument and EPUB** as their text — those
      are all ZIP containers full of XML, and the text can be lifted out of
      them with nothing but the standard library;
    * **archives** with an offer to open them in LinRAR proper;
    * and everything genuinely opaque as a hex dump — but with the file named
      and identified above it, and the desktop's own application one button
      away, rather than as an unexplained wall of hex.

    The raw bytes are always reachable through **View as hex**, because
    sometimes the hex is exactly what somebody came for.
    """

    #: Past this, the text view is the wrong tool and says so rather than
    #: locking the interface up laying out a hundred megabytes of one line.
    MAX_TEXT = 8 * 1024 * 1024

    def __init__(self, parent, name: str, data: bytes, path: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle(f"View - {name}")
        self.setWindowIcon(icons.icon("view"))
        self.resize(760, 560)

        self.name = name
        self.data = data
        #: Where the file is on disk, when it is anywhere: an archive member
        #: has been unpacked to a temporary folder by the time it gets here,
        #: which is what makes "open with another application" possible.
        self.path = path
        self.file_type = filetypes.identify(name=name, data=data)
        #: Set when the user asks for the archive to be opened; the main
        #: window reads it after exec() returns.
        self.open_as_archive = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        layout.addLayout(self._header())
        layout.addLayout(self._view_modes())

        self.pages = QStackedWidget()
        self.text_view = self._text_view()
        self.image_view, self.image_label = self._image_view()
        self.pages.addWidget(self.text_view)
        self.pages.addWidget(self.image_view)
        layout.addWidget(self.pages, 1)

        self.note = QLabel()
        self.note.setObjectName("Hint")
        self.note.setWordWrap(True)
        self.note.setVisible(False)
        layout.addWidget(self.note)

        layout.addWidget(self._buttons())
        self._show_best()

    # -- construction ------------------------------------------------------

    def _header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)
        icon = QLabel()
        icon.setPixmap(icons.pixmap(_VIEWER_ICONS.get(self.file_type.kind,
                                                      "file"), 32))
        icon.setFixedSize(36, 36)
        row.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)

        text = QVBoxLayout()
        text.setSpacing(1)
        title = QLabel(self.name)
        font = title.font()
        font.setBold(True)
        title.setFont(font)
        title.setTextFormat(Qt.TextFormat.PlainText)
        subtitle = QLabel(
            f"{self.file_type.label} · {format_size_short(len(self.data))}"
        )
        subtitle.setObjectName("Hint")
        text.addWidget(title)
        text.addWidget(subtitle)
        row.addLayout(text, 1)
        return row

    def _text_view(self) -> QPlainTextEdit:
        view = QPlainTextEdit()
        view.setReadOnly(True)
        view.setFont(QFont("monospace", 9))
        view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        return view

    def _image_view(self):
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label = QLabel()
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        area.setWidget(label)
        return area, label

    def _view_modes(self) -> QHBoxLayout:
        """How to look at it, as distinct from what to do with it.

        These are not dialog buttons and do not belong beside Close: they
        change the view, the way a tab does.
        """
        row = QHBoxLayout()
        row.setSpacing(4)
        self.btn_text = QPushButton("View as &text")
        self.btn_hex = QPushButton("View as he&x")
        for button in (self.btn_text, self.btn_hex):
            button.setFlat(True)
            button.setCheckable(True)
            row.addWidget(button)
        self.btn_text.clicked.connect(self._show_text)
        self.btn_hex.clicked.connect(self._show_hex)
        row.addStretch(1)
        return row

    def _buttons(self) -> QDialogButtonBox:
        box = QDialogButtonBox()
        self.btn_open = box.addButton("&Open with...",
                                      QDialogButtonBox.ButtonRole.ActionRole)
        self.btn_archive = box.addButton("Open in &LinRAR",
                                         QDialogButtonBox.ButtonRole.ActionRole)
        self.btn_save = box.addButton("&Save a copy...",
                                      QDialogButtonBox.ButtonRole.ActionRole)
        close = box.addButton(QDialogButtonBox.StandardButton.Close)

        self.btn_open.clicked.connect(self._open_externally)
        self.btn_archive.clicked.connect(self._open_in_linrar)
        self.btn_save.clicked.connect(self._save_as)
        close.clicked.connect(self.reject)

        self.btn_open.setIcon(icons.icon("view"))
        self.btn_archive.setIcon(icons.icon("archive-small"))
        self.btn_open.setEnabled(bool(self.path))
        self.btn_archive.setVisible(
            self.file_type.kind in (filetypes.Kind.ARCHIVE,
                                    filetypes.Kind.DOCUMENT)
            and bool(self.path)
        )
        return box

    # -- deciding what to show --------------------------------------------

    def _show_best(self) -> None:
        """Show the most useful view this file has, and say so when there is none."""
        kind = self.file_type.kind

        if kind is filetypes.Kind.IMAGE and self._show_image():
            return

        if kind is filetypes.Kind.DOCUMENT:
            text = filetypes.document_text(data=self.data)
            if text:
                self._mode(text=True)
                self._set_text(text)
                self._say(
                    f"The text of this {self.file_type.label}. Formatting, "
                    "images and layout are not shown — \"Open with...\" opens "
                    "it in the application that owns it."
                )
                return

        if kind is filetypes.Kind.PDF:
            self._show_hex()
            self._say(
                "LinRAR does not render PDF pages. \"Open with...\" hands it "
                "to your PDF reader; the bytes are shown here."
            )
            return

        if kind is filetypes.Kind.ARCHIVE:
            self._show_hex()
            self._say(
                f"This is {_article(self.file_type.label)}. "
                "\"Open in LinRAR\" opens it as one."
                if self.path else
                f"This is {_article(self.file_type.label)}."
            )
            return

        if self.file_type.viewable_as_text or filetypes._looks_textual(self.data):
            self._show_text()
            return

        self._show_hex()
        self._say(
            f"There is nothing readable to show for {_article(self.file_type.label)}, "
            "so its bytes are shown instead."
            + (" \"Open with...\" hands it to the application that owns it."
               if self.path else "")
        )

    def _show_image(self) -> bool:
        pixmap = QPixmap()
        if not pixmap.loadFromData(self.data) or pixmap.isNull():
            return False
        self._pixmap = pixmap
        self._fit_image()
        self.pages.setCurrentWidget(self.image_view)
        self.btn_text.setChecked(False)
        self.btn_hex.setChecked(False)
        self._say(f"{pixmap.width()} × {pixmap.height()} pixels, "
                  f"{self.file_type.label}")
        return True

    def _fit_image(self) -> None:
        pixmap = getattr(self, "_pixmap", None)
        if pixmap is None:
            return
        room = self.pages.size()
        if pixmap.width() > room.width() or pixmap.height() > room.height():
            pixmap = pixmap.scaled(
                room, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        self.image_label.setPixmap(pixmap)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.pages.currentWidget() is self.image_view:
            self._fit_image()

    def _set_text(self, text: str) -> None:
        if len(text) > self.MAX_TEXT:
            text = text[:self.MAX_TEXT] + "\n\n... (truncated)"
        self.text_view.setPlainText(text)
        self.pages.setCurrentWidget(self.text_view)

    def _show_text(self) -> None:
        self._mode(text=True)
        if self.file_type.kind is filetypes.Kind.DOCUMENT:
            extracted = filetypes.document_text(data=self.data)
            if extracted:
                self._set_text(extracted)
                return
        self._set_text(filetypes.decode(self.data))
        self.note.setVisible(False)

    def _show_hex(self) -> None:
        self._mode(text=False)
        self._set_text(filetypes.hex_dump(self.data))

    def _mode(self, text: bool) -> None:
        self.btn_text.setChecked(text)
        self.btn_hex.setChecked(not text)

    def _say(self, message: str) -> None:
        self.note.setText(message)
        self.note.setVisible(bool(message))

    # -- the buttons -------------------------------------------------------

    def _open_externally(self) -> None:
        if not self.path:
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(self.path)):
            QMessageBox.information(
                self, "LinRAR",
                f"No application on this system offered to open "
                f"{os.path.basename(self.path)}.",
            )

    def _open_in_linrar(self) -> None:
        self.open_as_archive = True
        self.accept()

    def _save_as(self) -> None:
        target, _filter = QFileDialog.getSaveFileName(
            self, "Save a copy", os.path.join(os.path.expanduser("~"), self.name)
        )
        if not target:
            return
        try:
            with open(target, "wb") as handle:
                handle.write(self.data)
        except OSError as exc:
            QMessageBox.warning(self, "LinRAR", f"Could not save it.\n\n{exc}")


#: Which icon stands for each kind of file at the top of the viewer.
_VIEWER_ICONS = {
    filetypes.Kind.ARCHIVE: "archive",
    filetypes.Kind.DOCUMENT: "info",
    filetypes.Kind.PDF: "info",
    filetypes.Kind.IMAGE: "view",
    filetypes.Kind.TEXT: "comment",
    filetypes.Kind.EXECUTABLE: "settings",
}


def _article(label: str) -> str:
    """"a ZIP archive" / "an Ogg media file" — for a sentence, not a table."""
    lowered = label[:1].lower() + label[1:]
    return f"{'an' if lowered[:1] in 'aeiou' else 'a'} {lowered}"


class FindDialog(QDialog):
    """"Find files": filters the current listing by a name mask."""

    def __init__(self, parent, in_archive: bool) -> None:
        super().__init__(parent)
        self.setWindowTitle("Find files")
        self.setWindowIcon(icons.icon("find"))
        self.resize(420, 200)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        form = QFormLayout()
        self.mask_edit = QLineEdit(str(SETTINGS.get("find/mask") or "*.*"))
        self.mask_edit.setToolTip("A file name mask, e.g.  *.log  or  report*")
        form.addRow("File names to find", self.mask_edit)
        self.text_edit = QLineEdit(str(SETTINGS.get("find/text") or ""))
        self.text_edit.setPlaceholderText("(optional) text inside the files")
        self.text_edit.setToolTip(
            "Leave empty to filter the list by name.\n"
            "Fill it in and LinRAR reads the files themselves and reports "
            "every line that contains this text."
        )
        form.addRow("Text to find", self.text_edit)
        layout.addLayout(form)

        self.case_check = QCheckBox("Case sensitive")
        self.case_check.setChecked(bool(SETTINGS.get("find/case_sensitive")))
        layout.addWidget(self.case_check)

        self.recurse_check = QCheckBox("Look in subfolders")
        self.recurse_check.setChecked(bool(SETTINGS.get("find/recurse")))
        self.recurse_check.setEnabled(not in_archive)
        if in_archive:
            self.recurse_check.setChecked(True)
            self.recurse_check.setToolTip(
                "The whole archive is searched, wherever a file sits in it."
            )
        layout.addWidget(self.recurse_check)

        self.scope_label = QLabel()
        self.scope_label.setObjectName("Hint")
        self.scope_label.setWordWrap(True)
        self._in_archive = in_archive
        self.text_edit.textChanged.connect(self._describe_scope)
        self.recurse_check.toggled.connect(self._describe_scope)
        self._describe_scope()
        layout.addWidget(self.scope_label)

        layout.addStretch(1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Find")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _describe_scope(self) -> None:
        """Say what pressing Find will actually do, before it is pressed."""
        where = (
            "the open archive" if self._in_archive
            else ("this folder and everything under it"
                  if self.recurse_check.isChecked() else "this folder")
        )
        if self.text_edit.text():
            self.scope_label.setText(
                f"Reads the matching files in {where} and lists every line "
                "that contains the text."
            )
        else:
            self.scope_label.setText(
                f"Filters the list to the names that match, in {where}. "
                "F5 clears the filter."
            )

    def _accept(self) -> None:
        SETTINGS.set("find/mask", self.mask_edit.text().strip() or "*")
        SETTINGS.set("find/case_sensitive", self.case_check.isChecked())
        SETTINGS.set("find/text", self.text_edit.text())
        if self.recurse_check.isEnabled():
            SETTINGS.set("find/recurse", self.recurse_check.isChecked())
        SETTINGS.sync()
        self.accept()

    @property
    def mask(self) -> str:
        return self.mask_edit.text().strip() or "*"

    @property
    def text(self) -> str:
        return self.text_edit.text()

    @property
    def case_sensitive(self) -> bool:
        return self.case_check.isChecked()

    @property
    def recurse(self) -> bool:
        return self.recurse_check.isChecked()

    def query(self):
        """This dialog's answer, as the search module wants it."""
        from ...core.search import SearchQuery

        return SearchQuery(
            mask=self.mask,
            text=self.text,
            case_sensitive=self.case_sensitive,
            recurse=self.recurse,
        )


class SettingsDialog(QDialog):
    """A trimmed version of WinRAR's Options > Settings."""

    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setWindowIcon(icons.icon("app"))
        self.resize(560, 560)

        #: Filled in by the tab builders: every key an administrator locked.
        self.locked: list[str] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._general_tab(), "General")
        self.tabs.addTab(self._paths_tab(), "Tools and system")
        # The banner is built after the tabs, which is what discovers the locks.
        self.lock_banner = policy.banner(self.locked, self)
        if self.lock_banner is not None:
            layout.addWidget(self.lock_banner)
        layout.addWidget(self.tabs, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _general_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)

        interface = QGroupBox("Interface")
        interface_layout = QVBoxLayout(interface)
        theme_row = QFormLayout()
        theme_row.setContentsMargins(0, 0, 0, 4)
        self.theme_combo = QComboBox()
        for name in theme.MODES:
            self.theme_combo.addItem(
                icons.icon(f"theme-{name}"), theme.MODE_LABELS[name], name
            )
        # The live theme wins: it is what the user is looking at right now.
        active = self.theme_combo.findData(theme.mode())
        self.theme_combo.setCurrentIndex(max(active, 0))
        theme_row.addRow("Colour theme", self.theme_combo)
        interface_layout.addLayout(theme_row)

        self.tree_check = QCheckBox("Show the folder tree")
        self.tree_check.setChecked(SETTINGS.get("view/show_tree"))
        # These two are the quick version of what Customize > Toolbar offers.
        self.toolbar_text_check = QCheckBox("Show button text on the toolbar")
        self.toolbar_text_check.setChecked(SETTINGS.get("toolbar/style") != "icon")
        self.large_icons_check = QCheckBox("Large toolbar buttons")
        self.large_icons_check.setChecked(
            int(SETTINGS.get("toolbar/icon_size")) >= 32
        )
        self.hidden_check = QCheckBox("Show hidden files and folders")
        self.hidden_check.setChecked(SETTINGS.get("view/show_hidden"))
        for widget in (
            self.tree_check,
            self.toolbar_text_check,
            self.large_icons_check,
            self.hidden_check,
        ):
            interface_layout.addWidget(widget)

        customize = QPushButton("Customize the toolbar, list and layout...")
        customize.setIcon(icons.icon("settings"))
        customize.clicked.connect(self._open_customize)
        interface_layout.addWidget(customize, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(interface)

        compression = QGroupBox("Compression")
        compression_form = QFormLayout(compression)
        self.method_combo = QComboBox()
        self.method_combo.addItems(
            ["Store", "Fastest", "Fast", "Normal", "Good", "Best"]
        )
        self.method_combo.setCurrentIndex(int(SETTINGS.get("compression/method")))
        compression_form.addRow("Default compression method", self.method_combo)
        layout.addWidget(compression)

        layout.addWidget(self._updates_group())

        self.locked += policy.guard_all({
            "view/theme": self.theme_combo,
            "view/show_tree": self.tree_check,
            "view/show_hidden": self.hidden_check,
            "compression/method": self.method_combo,
            "update/check_on_start": self.update_check,
            "update/automatic": self.update_auto,
            "update/prereleases": self.update_pre,
        })
        # The two toolbar checkboxes are one setting each, but Customize is the
        # full version of both: disable it only when neither can be changed.
        if policy.guard(self.toolbar_text_check, "toolbar/style"):
            self.locked.append("toolbar/style")
        if policy.guard(self.large_icons_check, "toolbar/icon_size"):
            self.locked.append("toolbar/icon_size")

        layout.addStretch(1)
        return page

    def _updates_group(self) -> QGroupBox:
        """How LinRAR keeps itself current — off until it is asked.

        Checking is a network request the user did not make, so nothing here
        starts switched on, and an administrator can lock the whole ``update/``
        group to settle it for a machine.
        """
        # Imported here, not at the top of the module: linrar.core.updater
        # brings in urllib, and every launch of LinRAR would pay for it whether
        # or not anybody ever opens Settings.  It also has to stay out of the
        # import path that runs before the "this is not Linux" check, because
        # urllib.request itself fails to import on a system that is not the one
        # it was built for.
        from ...core import updater

        box = QGroupBox("Updates")
        layout = QVBoxLayout(box)
        layout.setSpacing(5)

        self.update_check = QCheckBox("Check for updates when LinRAR starts")
        self.update_check.setChecked(bool(SETTINGS.get("update/check_on_start")))
        self.update_auto = QCheckBox(
            "Download and install them automatically"
        )
        self.update_auto.setChecked(bool(SETTINGS.get("update/automatic")))
        self.update_pre = QCheckBox("Include pre-release versions")
        self.update_pre.setChecked(bool(SETTINGS.get("update/prereleases")))
        # Installing automatically implies looking automatically; saying so by
        # ticking the box is clearer than quietly meaning it.
        self.update_auto.toggled.connect(
            lambda on: on and self.update_check.setChecked(True)
        )
        for widget in (self.update_check, self.update_auto, self.update_pre):
            layout.addWidget(widget)

        state = QLabel(
            f"This copy is LinRAR {version_module.describe_state()} "
            f"({version_module.channel()})."
        )
        state.setObjectName("Hint")
        state.setWordWrap(True)
        layout.addWidget(state)

        allowed = updater.eligibility()
        if not allowed:
            note = QLabel(f"{allowed.reason} {allowed.suggestion}")
            note.setObjectName("Hint")
            note.setWordWrap(True)
            layout.addWidget(note)

        check_now = QPushButton("Check for updates now...")
        check_now.setIcon(icons.icon("download"))
        check_now.clicked.connect(self._check_updates_now)
        layout.addWidget(check_now, 0, Qt.AlignmentFlag.AlignLeft)
        return box

    def _check_updates_now(self) -> None:
        # Saved first: a check started from here should honour the boxes as
        # they are now, not as they were when the dialog opened.
        self._save_updates()
        SETTINGS.sync()
        from .update import open_updater

        open_updater(self)
        self.update_check.setChecked(bool(SETTINGS.get("update/check_on_start")))

    def _save_updates(self) -> None:
        SETTINGS.set("update/check_on_start", self.update_check.isChecked())
        SETTINGS.set("update/automatic", self.update_auto.isChecked())
        SETTINGS.set("update/prereleases", self.update_pre.isChecked())

    def _paths_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)

        detected = QGroupBox("Command line tools")
        # A grid rather than a form: the name, the path and the button then
        # line up in real columns, the path box gets every spare pixel, and
        # the margins keep the buttons clear of the group box border.
        grid = QGridLayout(detected)
        grid.setContentsMargins(12, 8, 12, 10)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(1, 1)

        heading = QLabel("Where LinRAR found it, or the path you want used")
        heading.setObjectName("Hint")
        grid.addWidget(heading, 0, 0, 1, 3)

        self.path_edits: dict[str, QLineEdit] = {}
        self.path_labels: dict[str, QLabel] = {}
        for row, (key, label, kind) in enumerate(
            (
                ("rar", "rar", "rar"),
                ("unrar", "unrar", "unrar"),
                ("sevenzip", "7z", "sevenzip"),
                ("zip", "zip", "zip"),
            ),
            start=1,
        ):
            found = tools.find(kind)

            name = QLabel(label)
            name.setMinimumWidth(46)
            if not found:
                name.setObjectName("Warning")   # nothing to run for this one

            edit = QLineEdit(str(SETTINGS.get(f"paths/{key}") or ""))
            edit.setPlaceholderText(found or "not found: install it or browse")
            edit.setMinimumWidth(260)
            edit.setClearButtonEnabled(True)
            edit.setToolTip(
                f"Leave empty and LinRAR searches for {label} itself.\n"
                "Fill this in to pin one specific binary."
            )

            browse = QPushButton("Browse...")
            browse.setFixedWidth(96)
            browse.setAutoDefault(False)
            browse.clicked.connect(
                lambda _c=False, e=edit, n=label: self._browse_tool(e, n)
            )

            grid.addWidget(name, row, 0)
            grid.addWidget(edit, row, 1)
            grid.addWidget(browse, row, 2)
            self.path_edits[key] = edit
            self.path_labels[key] = name
            if policy.guard(edit, f"paths/{key}"):
                # Browsing to a program the setting cannot record is a trap.
                policy.guard(browse, f"paths/{key}")
                self.locked.append(f"paths/{key}")

        note = QLabel(
            "Empty means <b>search</b>: the PATH, then /usr/local/bin, "
            "/opt/rar, ~/.local/bin, /snap/bin, Flatpak and Nix profiles."
        )
        note.setWordWrap(True)
        note.setObjectName("Hint")
        note.setToolTip(
            "Every name these tools ship under is accepted: 7z, 7zz, 7za, "
            "7zr, and unrar, unrar-nonfree, unrar-free."
        )
        # A wrapped label in a grid only gets the height it asks for if the
        # row is allowed to grow to it.
        note.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.MinimumExpanding
        )
        grid.addWidget(note, 5, 0, 1, 3)
        grid.setRowMinimumHeight(5, note.fontMetrics().height() * 2 + 6)

        buttons = QHBoxLayout()
        manage = QPushButton("Manage dependencies...")
        manage.setIcon(icons.icon("package"))
        manage.setAutoDefault(False)
        manage.clicked.connect(self._open_dependencies)
        rescan = QPushButton("Re-scan")
        rescan.setIcon(icons.icon("refresh"))
        rescan.setAutoDefault(False)
        rescan.clicked.connect(self._rescan_tools)
        buttons.addWidget(manage)
        buttons.addWidget(rescan)
        buttons.addStretch(1)
        grid.addLayout(buttons, 6, 0, 1, 3)

        layout.addWidget(detected)

        admin = QGroupBox("Administrator rights")
        admin_form = QFormLayout(admin)
        self.elevation_combo = QComboBox()
        self.elevation_combo.addItem("Automatic (recommended)", "auto")
        for method in elevation.METHODS:
            label = method.label + ("" if method.path else "  (not installed)")
            self.elevation_combo.addItem(label, method.key)
            index = self.elevation_combo.count() - 1
            self.elevation_combo.model().item(index).setEnabled(
                bool(method.path)
            )
        index = self.elevation_combo.findData(SETTINGS.get("admin/method"))
        self.elevation_combo.setCurrentIndex(max(index, 0))
        admin_form.addRow("Ask for rights with", self.elevation_combo)

        state = QLabel(elevation.SESSION.describe(
            str(SETTINGS.get("admin/method") or "auto")
        ))
        state.setObjectName("Hint")
        state.setWordWrap(True)
        admin_form.addRow(state)
        self.locked += policy.guard_all({"admin/method": self.elevation_combo})
        layout.addWidget(admin)

        stored = QGroupBox("Saved settings")
        stored_layout = QVBoxLayout(stored)
        where = QLabel(
            f"Everything you change is written to<br><code>{SETTINGS.path}</code>"
        )
        where.setWordWrap(True)
        where.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        stored_layout.addWidget(where)

        # What an administrator has decided for everyone on this machine, said
        # plainly and with the files named, so it can be found and edited.
        system = QLabel(self._system_summary())
        system.setObjectName("Hint")
        system.setWordWrap(True)
        system.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        stored_layout.addWidget(system)

        reset = QPushButton("Reset all settings...")
        reset.setIcon(icons.icon("refresh"))
        reset.clicked.connect(self._reset_all)
        stored_layout.addWidget(reset, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(stored)

        layout.addStretch(1)
        return page

    def _system_summary(self) -> str:
        """The system-wide layer as rich text for the "Saved settings" box."""
        system = SETTINGS.system
        if not system.files and not system.problems:
            return (
                "No system-wide configuration is installed. An administrator "
                f"can create <code>{settings_module.SYSTEM_CONFIG_DIR}/"
                f"{settings_module.CONFIG_NAME}</code> to set defaults for "
                "every user of this machine."
            )
        lines = ["System-wide settings, applied before your own, come from:"]
        for path in system.files:
            count = list(system.origin.values()).count(path)
            lines.append(
                f"<code>{path}</code>: {count} setting{'' if count == 1 else 's'}"
            )
        for problem in system.problems:
            lines.append(f"<b>could not be read:</b> {problem}")
        locked = system.locked_keys()
        if locked:
            lines.append(
                f"{len(locked)} of them {'is' if len(locked) == 1 else 'are'} "
                "locked: shown greyed out here and left alone when you save."
            )
        return "<br>".join(lines)

    def _browse_tool(self, edit: QLineEdit, name: str) -> None:
        start = edit.text().strip() or edit.placeholderText() or "/usr/bin"
        if not os.path.exists(start):
            start = "/usr/bin"
        path, _filter = QFileDialog.getOpenFileName(
            self, f"Select the {name} program", start
        )
        if path:
            edit.setText(path)

    def _rescan_tools(self) -> None:
        """Look for the tools again, after installing one outside LinRAR."""
        for key, edit in self.path_edits.items():
            SETTINGS.set(f"paths/{key}", edit.text().strip())
        SETTINGS.sync()
        REGISTRY.refresh()
        for key, kind in (("rar", "rar"), ("unrar", "unrar"),
                          ("sevenzip", "sevenzip"), ("zip", "zip")):
            found = tools.find(kind, str(SETTINGS.get(f"paths/{key}") or ""))
            edit = self.path_edits[key]
            edit.setPlaceholderText(found or "not found: install it or browse")
            name = self.path_labels[key]
            name.setObjectName("" if found else "Warning")
            name.style().unpolish(name)
            name.style().polish(name)

    def _reset_all(self) -> None:
        extra = (
            "\n\nThe settings your administrator applies to every user of this "
            "machine stay in force; they are not yours to clear."
            if SETTINGS.system.active else ""
        )
        reply = QMessageBox.question(
            self,
            "Reset all settings",
            "Forget every saved preference: theme, toolbar, layout, "
            "compression and extraction defaults, favourites and history?\n\n"
            "Saved passwords and compression profiles go too. Your archives "
            "are untouched." + extra,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        SETTINGS.reset_all()
        QMessageBox.information(
            self,
            "Reset all settings",
            "Settings cleared. Restart LinRAR to start from the defaults.",
        )
        self.reject()

    def _open_dependencies(self) -> None:
        from .dependencies import DependenciesDialog

        DependenciesDialog(self).exec()

    def _open_customize(self) -> None:
        from .customize import CustomizeDialog

        window = self.parent()
        dialog = CustomizeDialog(window)
        if window is not None and hasattr(window, "_apply_customization"):
            dialog.applied.connect(window._apply_customization)
            if dialog.exec() == CustomizeDialog.DialogCode.Accepted:
                window._apply_customization()
        else:
            dialog.exec()
        # The toolbar controls here may now disagree with what Customize did.
        self.toolbar_text_check.setChecked(SETTINGS.get("toolbar/style") != "icon")
        self.large_icons_check.setChecked(
            int(SETTINGS.get("toolbar/icon_size")) >= 32
        )

    def _save(self) -> None:
        SETTINGS.set("view/theme", self.theme_combo.currentData())
        SETTINGS.set("view/show_tree", self.tree_check.isChecked())
        style = SETTINGS.get("toolbar/style")
        if self.toolbar_text_check.isChecked():
            SETTINGS.set("toolbar/style", "under" if style == "icon" else style)
        else:
            SETTINGS.set("toolbar/style", "icon")
        SETTINGS.set(
            "toolbar/icon_size", 32 if self.large_icons_check.isChecked() else 24
        )
        SETTINGS.set("view/show_hidden", self.hidden_check.isChecked())
        SETTINGS.set("compression/method", self.method_combo.currentIndex())
        self._save_updates()
        SETTINGS.set("admin/method", self.elevation_combo.currentData())
        for key, edit in self.path_edits.items():
            SETTINGS.set(f"paths/{key}", edit.text().strip())
        REGISTRY.refresh()
        SETTINGS.sync()
        self.accept()


class AboutDialog(QDialog):
    """Help > About LinRAR."""

    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.setWindowTitle("About LinRAR")
        self.setWindowIcon(icons.icon("app"))
        self.setFixedWidth(500)

        colors = theme.current()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(14)
        icon_label = QLabel()
        icon_label.setPixmap(icons.pixmap("app", 64))
        icon_label.setFixedSize(70, 70)
        header.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignTop)

        text = QLabel(
            "<div style='font-size:15pt; font-weight:bold'>LinRAR "
            "<span style='font-weight:normal'>for Linux</span></div>"
            f"<div style='color:{colors.text_dim}; margin-top:2px'>"
            f"Version {version_module.describe_state()} &nbsp;·&nbsp; PyQt6</div>"
            "<div style='margin-top:9px'>A native Linux archive manager with "
            "the classic WinRAR interface, built on top of the <b>rar</b>, "
            "<b>unrar</b> and <b>7z</b> command line tools.</div>"
        )
        text.setWordWrap(True)
        header.addWidget(text, 1)
        layout.addLayout(header)

        layout.addWidget(_rule())

        links_box = QGroupBox("Project")
        links_layout = QVBoxLayout(links_box)
        links_layout.setSpacing(5)
        for caption, url in (
            ("Website", WEBSITE),
            ("Source code", REPOSITORY),
            (f"Built by {AUTHOR}", PORTFOLIO),
        ):
            links_layout.addWidget(_link_row(caption, url, colors))
        layout.addWidget(links_box)

        note = QLabel(
            "LinRAR is MIT licensed. RAR and UnRAR are Copyright (c) Alexander "
            "Roshal; this is an independent front end and is not affiliated "
            "with win.rar GmbH."
        )
        note.setObjectName("Hint")
        note.setWordWrap(True)
        layout.addWidget(note)

        row = QHBoxLayout()
        visit = QPushButton("Website")
        visit.setIcon(icons.icon("globe"))
        visit.setToolTip(WEBSITE)
        visit.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(WEBSITE)))
        row.addWidget(visit)
        source = QPushButton("GitHub")
        source.setIcon(icons.icon("globe"))
        source.setToolTip(REPOSITORY)
        source.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(REPOSITORY))
        )
        row.addWidget(source)
        row.addStretch(1)
        ok = QPushButton("OK")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        row.addWidget(ok)
        layout.addLayout(row)


class HelpDialog(QDialog):
    """Help > Help topics: the short manual, in place of a message box."""

    OVERVIEW, SHORTCUTS, FORMATS = 0, 1, 2

    def __init__(self, parent, page: int = OVERVIEW) -> None:
        super().__init__(parent)
        self.setWindowTitle("LinRAR help")
        self.setWindowIcon(icons.icon("help"))
        self.resize(600, 500)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(9)

        header = QHBoxLayout()
        header.setSpacing(10)
        badge = QLabel()
        badge.setPixmap(icons.pixmap("help", 32))
        header.addWidget(badge, 0, Qt.AlignmentFlag.AlignVCenter)
        title = QLabel("Using LinRAR")
        title.setObjectName("Heading")
        header.addWidget(title, 1)
        layout.addLayout(header)

        self.tabs = QTabWidget()
        for label, html in (
            ("Getting started", _help_overview()),
            ("Keyboard shortcuts", _help_shortcuts()),
            ("Formats and tools", _help_formats()),
        ):
            self.tabs.addTab(_page(html), label)
        self.tabs.setCurrentIndex(page)
        layout.addWidget(self.tabs, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)


class BenchmarkDialog(QDialog):
    """Tools > Benchmark, a light stand-in for WinRAR's speed test."""

    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.setWindowTitle("Benchmark and hardware test")
        self.setWindowIcon(icons.icon("test"))
        self.resize(400, 220)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(9)

        self.status = QLabel("Press Start to measure compression speed.")
        layout.addWidget(self.status)

        self.bar = QProgressBar()
        layout.addWidget(self.bar)

        form = QFormLayout()
        self.speed_label = QLabel("-")
        form.addRow("Compression speed", self.speed_label)
        layout.addLayout(form)

        layout.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        self.start_button = QPushButton("Start")
        self.start_button.clicked.connect(self._start)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        row.addWidget(self.start_button)
        row.addWidget(close)
        layout.addLayout(row)

        self._task = None

    def closeEvent(self, event) -> None:
        if self._task is not None and self._task.isRunning():
            self._task.cancel()
            self._task.wait(3000)
        super().closeEvent(event)

    def _start(self) -> None:
        """Run the benchmark on a worker thread so the UI stays responsive."""
        import os as _os
        import shutil
        import tempfile
        import time

        from ...core.models import CompressOptions, CompressionMethod
        from ...core.tasks import Task

        if not REGISTRY.rar.rar:
            self.status.setText(
                "The 'rar' command is required for the benchmark but was not "
                "found. Install it via Tools > Dependencies."
            )
            return

        self.start_button.setEnabled(False)
        self.status.setText("Running...")
        self.bar.setRange(0, 0)

        workdir = tempfile.mkdtemp(prefix="linrar-bench-")

        def work(_ctx):
            sample = _os.path.join(workdir, "sample.dat")
            # Semi-compressible data gives a more representative number than
            # either pure random bytes or a long run of zeroes.
            block = (b"LinRAR benchmark sample data block. " * 64) + _os.urandom(1024)
            with open(sample, "wb") as handle:
                for _ in range(400):
                    handle.write(block)
            size = _os.path.getsize(sample)
            options = CompressOptions(
                archive_path=_os.path.join(workdir, "bench.rar"),
                method=CompressionMethod.NORMAL,
                base_folder=workdir,
                recurse_subfolders=False,
            )
            started = time.monotonic()
            REGISTRY.rar.create([sample], options)
            elapsed = max(time.monotonic() - started, 0.001)
            return size / elapsed

        def finish(message: str, speed: float = 0.0) -> None:
            self.bar.setRange(0, 100)
            self.bar.setValue(100)
            self.start_button.setEnabled(True)
            self.status.setText(message)
            if speed:
                self.speed_label.setText(f"{format_size_short(speed)}/s")
            shutil.rmtree(workdir, ignore_errors=True)
            self._task = None

        task = Task(work, "Benchmark", self)
        task.succeeded.connect(lambda speed: finish("Finished.", speed))
        task.failed.connect(lambda exc: finish(f"Benchmark failed: {exc}"))
        self._task = task
        task.start()


def _rule() -> QWidget:
    """A hairline separator that follows the theme."""
    line = QWidget()
    line.setObjectName("Rule")
    line.setFixedHeight(1)
    return line


def _page(body: str) -> QTextBrowser:
    view = QTextBrowser()
    view.setOpenExternalLinks(True)
    colors = theme.current()
    view.setHtml(
        f'<body style="color:{colors.text}; font-size:9pt; '
        f'line-height:140%">{body}</body>'
    )
    return view


def _section(title: str) -> str:
    colors = theme.current()
    return (
        f'<div style="color:{colors.group_title}; font-size:10pt; '
        f'font-weight:bold; margin:12px 0 4px 0">{title}</div>'
    )


def _rows(pairs: list[tuple[str, str]]) -> str:
    colors = theme.current()
    cells = "".join(
        f'<tr><td style="padding:3px 16px 3px 0; white-space:nowrap">'
        f'<b>{key}</b></td>'
        f'<td style="padding:3px 0; color:{colors.text}">{value}</td></tr>'
        for key, value in pairs
    )
    return f'<table cellspacing="0" cellpadding="0">{cells}</table>'


def _help_overview() -> str:
    return (
        _section("Browsing")
        + "<p>LinRAR starts as a file manager. Double-click an archive to step "
        "inside it and the window becomes an archive browser; the <b>..</b> row "
        "at the top steps back out again. The folder tree on the left follows "
        "whichever of the two you are looking at.</p>"
        + "<p><b>Alt+Left</b> and <b>Alt+Right</b> are Back and Forward, "
        "<b>Backspace</b> goes up, <b>Ctrl+L</b> lets you type a path, and "
        "<b>F5</b> lists the folder again and clears any find filter. "
        "<b>File &gt; Open recent</b> keeps the archives you opened lately, and "
        "files can be dragged straight out of the list — including out of an "
        "open archive, which unpacks them on the way.</p>"
        + _section("Finding things")
        + "<p><b>Ctrl+F</b> asks for a name mask and, if you want it, some "
        "text. A mask on its own filters the list in place. Add text and "
        "LinRAR reads the files themselves — inside the open archive, or "
        "through the current folder and everything under it — and lists every "
        "line that contains it.</p>"
        + "<p><b>Ctrl+K</b> works out CRC32, MD5, SHA-1, SHA-256 and SHA-512 "
        "for whatever is selected, on disk or inside an archive, in one pass "
        "over the bytes. Paste a published checksum into the box at the "
        "bottom and it says which file matches it.</p>"
        + _section("When a file will not open")
        + "<p>Archives are recognised by what is inside them rather than by "
        "their names, so a file opens whatever it is called. When one cannot "
        "be opened, LinRAR shows what it actually found: what the file is, "
        "what its name claimed, which tool is needed and whether it is "
        "installed, and the first bytes of the file, together with the things "
        "you can do about it. The same report is available from a terminal "
        "with <b>linrar -i FILE</b>.</p>"
        + _section("Creating an archive")
        + "<p>Select the files, press <b>Add</b> (Alt+A) and the <i>Archive "
        "name and parameters</i> dialog opens. Pick the format and compression "
        "method, optionally split the result into volumes, set a password, or "
        "save the whole set of choices as a profile for next time.</p>"
        + "<p>Tick <b>Create SFX archive</b> there to get a self-extracting "
        "one in the same step, and choose the kind beside it: an "
        "<b>AppImage</b>, which unpacks itself on any Linux machine with "
        "nothing installed, or rar's smaller <b>.sfx stub</b>. "
        "<b>Options…</b> opens the full SFX module. An archive that already "
        "exists is converted the same way from <b>Commands &gt; Convert "
        "archive to SFX</b> (Alt+S).</p>"
        + _section("Extracting")
        + "<p><b>Extract To</b> (Alt+E) asks where the files should go and how "
        "to handle existing ones. <b>Alt+W</b> unpacks straight into the "
        "current folder. <b>Test</b> (Alt+T) checks an archive without writing "
        "anything.</p>"
        + _section("Protecting and repairing")
        + "<p>A recovery record (Alt+P) lets a damaged RAR archive be repaired "
        "later, recovery volumes rebuild a missing part of a volume set, and "
        "<b>Repair</b> (Alt+R) puts both to work. <b>Alt+S</b> turns an archive "
        "into a self-extracting AppImage.</p>"
        + _section("Appearance")
        + "<p>The light and dark themes live under <b>Options &gt; Theme</b>, "
        "on the switch at the right end of the toolbar, or on "
        "<b>Ctrl+Shift+T</b>. The toolbar, the folder tree, the comment pane "
        "and the file-list columns can all be turned on and off from the same "
        "menu.</p>"
    )


def _help_shortcuts() -> str:
    return (
        _section("Commands")
        + _rows(
            [
                ("Alt+A", "Add the selected files to an archive"),
                ("Alt+E", "Extract to a folder you choose"),
                ("Alt+W", "Extract to the current folder"),
                ("Alt+T", "Test the archive"),
                ("Alt+V", "View the selected file"),
                ("Alt+I", "Archive information"),
                ("Alt+R", "Repair the archive"),
                ("Alt+P", "Add a recovery record"),
                ("Alt+S", "Convert the archive to a self-extracting one"),
                ("Alt+Q", "Convert archives to another format"),
                ("Alt+G", "Generate a report of the contents"),
                ("Ctrl+K", "Calculate checksums for the selected files"),
                ("Del", "Delete the selection"),
                ("F2", "Rename"),
                ("F7", "New folder"),
            ]
        )
        + _section("Browsing and selection")
        + _rows(
            [
                ("Ctrl+O", "Open an archive"),
                ("Ctrl+W", "Close the archive"),
                ("Alt+Left / Alt+Right", "Back and forward"),
                ("Backspace", "Up one level"),
                ("Ctrl+L", "Type a path in the address bar"),
                ("Ctrl+G", "Go to a folder"),
                ("F5", "Refresh and clear any filter"),
                ("Ctrl+F", "Find files"),
                ("Ctrl+A", "Select everything"),
                ("+ / - / *", "Select, deselect and invert by file mask"),
                ("Ctrl+C / X / V", "Copy, cut and paste"),
                ("Ctrl+Shift+C", "Copy the path to the clipboard"),
                ("Alt+Enter", "Properties"),
            ]
        )
        + _section("Application")
        + _rows(
            [
                ("Ctrl+T", "Show or hide the folder tree"),
                ("Ctrl+H", "Show or hide hidden files"),
                ("Ctrl+Shift+T", "Switch between the light and dark theme"),
                ("Ctrl+P", "Set the default password"),
                ("Ctrl+S", "Settings"),
                ("Ctrl+D", "Add to favorites"),
                ("F1", "This help"),
                ("Ctrl+Q", "Quit"),
            ]
        )
    )


def _help_formats() -> str:
    colors = theme.current()
    return (
        _section("Formats")
        + _rows(
            [
                (
                    "RAR",
                    "The best compression, plus solid archives, recovery "
                    "records, encrypted file names and volumes. Needs "
                    "<b>rar</b> to create, <b>unrar</b> to read.",
                ),
                ("RAR4", "The older RAR format, for maximum compatibility."),
                ("ZIP", "The most portable format; readable everywhere."),
                ("7Z", "Strong compression, handled by <b>7z</b>."),
                (
                    "Others",
                    "TAR, GZ, BZ2, XZ, ISO and CAB archives can be listed and "
                    "extracted when 7-Zip is installed.",
                ),
            ]
        )
        + _section("Command line tools")
        + _rows(
            [
                ("unrar", "Reads, extracts and tests RAR archives. Needed to "
                          "open .rar files at all."),
                ("rar", "Creates and modifies RAR archives: compression, "
                        "recovery records, locking, SFX. Shareware from "
                        "RARLAB."),
                ("7z", "7z, TAR, GZip, BZip2, XZ, ISO and CAB support."),
                ("zip", "Password-protected ZIP creation. Plain ZIP reading "
                        "and writing need nothing installed."),
                ("squashfs-tools", "Building self-extracting AppImages."),
                ("secret-tool", "Storing saved passwords in the system "
                                "keyring instead of LinRAR's own file."),
            ]
        )
        + _section("Found on this system")
        + f'<pre style="color:{colors.text_dim}">{REGISTRY.describe_tools()}</pre>'
        + "<p>Anything missing can be installed from the <b>Dependencies</b> "
        "button on the toolbar, which drives your distribution's package "
        "manager. <b>Settings &gt; Tools and system</b> can point LinRAR at a "
        "specific binary if you keep several.</p>"
    )


def _link_row(caption: str, url: str, colors) -> QWidget:
    """A captioned, clickable link for the About window.

    The scheme is dropped from what is shown (it is noise in a link nobody
    has to type) while the anchor keeps the real address.
    """
    row = QWidget()
    box = QHBoxLayout(row)
    box.setContentsMargins(0, 0, 0, 0)
    box.setSpacing(9)
    badge = QLabel()
    badge.setPixmap(icons.pixmap("globe", 16))
    badge.setFixedWidth(20)
    box.addWidget(badge, 0, Qt.AlignmentFlag.AlignVCenter)

    shown = url.split("://", 1)[-1].rstrip("/")
    label = QLabel(
        f"<span style='color:{colors.text_dim}'>{caption}</span>"
    )
    label.setMinimumWidth(104)
    box.addWidget(label, 0)
    link = QLabel(
        f"<a href='{url}' style='color:{colors.link}; text-decoration:none'>"
        f"{shown}</a>"
    )
    link.setOpenExternalLinks(True)
    link.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
    link.setToolTip(url)
    box.addWidget(link, 1)
    return row


def _wrapped(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


