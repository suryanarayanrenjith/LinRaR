"""Smaller dialogs: archive info, comment editor, find, settings, help, about."""

from __future__ import annotations

import os

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QFont
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTabWidget,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...core.models import ArchiveInfo, format_size, format_size_short
from ...core import elevation, tools
from ...core.registry import REGISTRY
from ...core.settings import SETTINGS
from .. import icons, theme

APP_VERSION = "2.0.0"
AUTHOR = "Surya"
PORTFOLIO = "https://surya.is-a.dev/"


class InfoDialog(QDialog):
    """"Archive information" — WinRAR's Ctrl+I property sheet."""

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
    """The built-in viewer for a single extracted file."""

    def __init__(self, parent, name: str, data: bytes) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"View - {name}")
        self.setWindowIcon(icons.icon("view"))
        self.resize(700, 520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        self.editor = QTextEdit()
        self.editor.setReadOnly(True)
        self.editor.setFont(QFont("monospace", 9))
        self.editor.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.editor.setPlainText(_as_text(data))
        layout.addWidget(self.editor, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class FindDialog(QDialog):
    """"Find files" — filters the current listing by a name mask."""

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
        form.addRow("File names to find", self.mask_edit)
        self.text_edit = QLineEdit()
        self.text_edit.setPlaceholderText("(optional)")
        form.addRow("Text to find", self.text_edit)
        layout.addLayout(form)

        self.case_check = QCheckBox("Case sensitive")
        self.case_check.setChecked(bool(SETTINGS.get("find/case_sensitive")))
        layout.addWidget(self.case_check)

        scope = QLabel(
            "Searching inside the open archive."
            if in_archive
            else "Searching the current folder."
        )
        scope.setObjectName("Hint")
        layout.addWidget(scope)

        layout.addStretch(1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Find")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _accept(self) -> None:
        SETTINGS.set("find/mask", self.mask_edit.text().strip() or "*")
        SETTINGS.set("find/case_sensitive", self.case_check.isChecked())
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


class SettingsDialog(QDialog):
    """A trimmed version of WinRAR's Options > Settings."""

    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setWindowIcon(icons.icon("app"))
        self.resize(480, 470)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._general_tab(), "General")
        self.tabs.addTab(self._paths_tab(), "Tools and system")
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

        layout.addStretch(1)
        return page

    def _paths_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)

        detected = QGroupBox("Command line tools")
        detected_form = QFormLayout(detected)
        detected_form.setSpacing(5)
        self.path_edits: dict[str, QLineEdit] = {}
        for key, label, kind in (
            ("rar", "rar", "rar"),
            ("unrar", "unrar", "unrar"),
            ("sevenzip", "7z", "sevenzip"),
            ("zip", "zip", "zip"),
        ):
            row = QHBoxLayout()
            row.setSpacing(5)
            edit = QLineEdit(str(SETTINGS.get(f"paths/{key}") or ""))
            edit.setPlaceholderText(tools.find(kind) or "not found")
            edit.setToolTip(
                "Leave empty to search the PATH and the usual install "
                "locations, or point at a specific binary."
            )
            browse = QPushButton("Browse...")
            browse.setMaximumWidth(90)
            browse.clicked.connect(
                lambda _c=False, e=edit, n=label: self._browse_tool(e, n)
            )
            row.addWidget(edit, 1)
            row.addWidget(browse, 0)
            detected_form.addRow(label, row)
            self.path_edits[key] = edit
        layout.addWidget(detected)

        note = QLabel(
            "Leave a box empty and LinRAR finds the tool itself: the PATH "
            "first, then the places distributions and manual installs use "
            "(/usr/local/bin, /opt/rar, ~/.local/bin, /snap/bin, Flatpak and "
            "Nix profiles). Fill one in to pin a specific build."
        )
        note.setWordWrap(True)
        note.setObjectName("Hint")
        layout.addWidget(note)

        manage = QPushButton("Manage dependencies...")
        manage.setIcon(icons.icon("package"))
        manage.clicked.connect(self._open_dependencies)
        layout.addWidget(manage, 0, Qt.AlignmentFlag.AlignLeft)

        admin = QGroupBox("Administrator rights")
        admin_form = QFormLayout(admin)
        self.elevation_combo = QComboBox()
        self.elevation_combo.addItem("Automatic (recommended)", "auto")
        for method in elevation.METHODS:
            label = method.label + ("" if method.path else "  — not installed")
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
        reset = QPushButton("Reset all settings...")
        reset.setIcon(icons.icon("refresh"))
        reset.clicked.connect(self._reset_all)
        stored_layout.addWidget(reset, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(stored)

        layout.addStretch(1)
        return page

    def _browse_tool(self, edit: QLineEdit, name: str) -> None:
        start = edit.text().strip() or "/usr/bin"
        path, _filter = QFileDialog.getOpenFileName(
            self, f"Select the {name} program", start
        )
        if path:
            edit.setText(path)

    def _reset_all(self) -> None:
        reply = QMessageBox.question(
            self,
            "Reset all settings",
            "Forget every saved preference — theme, toolbar, layout, "
            "compression and extraction defaults, favourites and history?\n\n"
            "Saved passwords and compression profiles go too. Your archives "
            "are untouched.",
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
        self.setFixedWidth(460)

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
            f"Version {APP_VERSION} &nbsp;·&nbsp; PyQt6</div>"
            "<div style='margin-top:9px'>A native Linux archive manager with "
            "the classic WinRAR interface, built on top of the <b>rar</b>, "
            "<b>unrar</b> and <b>7z</b> command line tools.</div>"
        )
        text.setWordWrap(True)
        header.addWidget(text, 1)
        layout.addLayout(header)

        layout.addWidget(_rule())

        credits_box = QGroupBox("Credits")
        credits_layout = QHBoxLayout(credits_box)
        credits_layout.setSpacing(11)
        badge = QLabel()
        badge.setPixmap(icons.pixmap("globe", 32))
        credits_layout.addWidget(badge, 0, Qt.AlignmentFlag.AlignVCenter)
        credit = QLabel(
            f"<div style='font-size:10pt'>UI built by <b>{AUTHOR}</b></div>"
            f"<div style='margin-top:3px'><a href='{PORTFOLIO}' "
            f"style='color:{colors.link}; text-decoration:none'>"
            f"{PORTFOLIO}</a></div>"
        )
        credit.setOpenExternalLinks(True)
        credit.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextBrowserInteraction
        )
        credits_layout.addWidget(credit, 1)
        layout.addWidget(credits_box)

        note = QLabel(
            "RAR and UnRAR are Copyright (c) Alexander Roshal. This is an "
            "independent front end and is not affiliated with win.rar GmbH."
        )
        note.setObjectName("Hint")
        note.setWordWrap(True)
        layout.addWidget(note)

        row = QHBoxLayout()
        visit = QPushButton("Visit portfolio")
        visit.setIcon(icons.icon("globe"))
        visit.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(PORTFOLIO)))
        row.addWidget(visit)
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
        + _section("Creating an archive")
        + "<p>Select the files, press <b>Add</b> (Alt+A) and the <i>Archive "
        "name and parameters</i> dialog opens. Pick the format and compression "
        "method, optionally split the result into volumes, set a password, or "
        "save the whole set of choices as a profile for next time.</p>"
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
                ("Alt+S", "Convert to a self-extracting AppImage"),
                ("Alt+Q", "Convert archives to another format"),
                ("Alt+G", "Generate a report of the contents"),
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
                ("Backspace", "Up one level"),
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


def _wrapped(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


def _as_text(data: bytes) -> str:
    """Render a member for the viewer, falling back to a hex dump if binary."""
    for encoding in ("utf-8", "latin-1"):
        try:
            text = data.decode(encoding)
        except UnicodeDecodeError:
            continue
        if "\x00" not in text[:4096]:
            return text
    lines = []
    for offset in range(0, min(len(data), 64 * 1024), 16):
        chunk = data[offset : offset + 16]
        hex_part = " ".join(f"{b:02X}" for b in chunk).ljust(47)
        ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{offset:08X}  {hex_part}  {ascii_part}")
    if len(data) > 64 * 1024:
        lines.append("... (truncated)")
    return "\n".join(lines)
