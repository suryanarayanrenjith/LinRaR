"""The "Advanced SFX options" dialog, targeting AppImage output."""

from __future__ import annotations

import os
from typing import Optional

from PyQt6.QtCore import QBuffer, QIODevice, Qt
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...core.sfx import SfxOptions, appimage_ready, runtime_arch
from .. import icons


class SfxDialog(QDialog):
    """Collects every option for a self-extracting AppImage.

    Mirrors WinRAR's SFX module configuration, with the Windows-only pages
    (registry keys, shortcuts) replaced by their Linux equivalents.
    """

    def __init__(self, parent=None, archive_path: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle("Advanced SFX options")
        self.setWindowIcon(icons.icon("sfx"))
        self.setModal(True)
        self.resize(560, 500)

        self.archive_path = archive_path
        self._icon_png: Optional[bytes] = None

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        root.addWidget(self._build_header())

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_general(), "General")
        self.tabs.addTab(self._build_setup(), "Setup")
        self.tabs.addTab(self._build_modes(), "Modes")
        self.tabs.addTab(self._build_text(), "Text and icon")
        self.tabs.addTab(self._build_license(), "License")
        self.tabs.addTab(self._build_advanced(), "Advanced")
        root.addWidget(self.tabs, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        ok = QPushButton("OK")
        ok.setDefault(True)
        ok.clicked.connect(self._accept)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        help_button = QPushButton("Help")
        help_button.clicked.connect(self._show_help)
        for button in (ok, cancel, help_button):
            buttons.addWidget(button)
        root.addLayout(buttons)

    # -- header ------------------------------------------------------------

    def _build_header(self) -> QGroupBox:
        group = QGroupBox("Output format")
        box = QVBoxLayout(group)
        box.setSpacing(3)
        box.addWidget(
            QLabel(
                "<b>AppImage</b> — a single executable file that unpacks itself "
                "when run, the Linux equivalent of a Windows SFX .exe."
            )
        )
        ready, note = appimage_ready()
        # Qt only treats a label as rich text when it contains a tag, so plain
        # entities like &nbsp; would show up literally.
        label = QLabel(
            f"<span>Architecture: {runtime_arch()} &nbsp;•&nbsp; </span>"
            + (
                note
                if ready
                else f"<span style='color:#B00020'>{note}</span>"
            )
        )
        label.setWordWrap(True)
        label.setObjectName("Hint")
        box.addWidget(label)
        return group

    # -- tabs --------------------------------------------------------------

    def _build_general(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        group = QGroupBox("Path to extract")
        form = QFormLayout(group)
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("~/MyApplication  (blank = current folder)")
        form.addRow("Default destination", self.path_edit)
        note = QLabel(
            "A leading ~ is expanded on the target machine. Leave blank to "
            "extract into whatever folder the archive is run from."
        )
        note.setWordWrap(True)
        note.setObjectName("Hint")
        form.addRow(note)
        layout.addWidget(group)

        self.ask_check = QCheckBox("Ask the user for the destination folder")
        self.ask_check.setChecked(True)
        layout.addWidget(self.ask_check)

        layout.addStretch(1)
        return page

    def _build_setup(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        group = QGroupBox("Run after extraction")
        form = QFormLayout(group)
        self.run_after_edit = QLineEdit()
        self.run_after_edit.setPlaceholderText("./install.sh")
        form.addRow("Command", self.run_after_edit)
        layout.addWidget(group)

        before_group = QGroupBox("Run before extraction")
        before_form = QFormLayout(before_group)
        self.run_before_edit = QLineEdit()
        before_form.addRow("Command", self.run_before_edit)
        layout.addWidget(before_group)

        note = QLabel(
            "Commands run with the destination folder as the working "
            "directory, using /bin/sh."
        )
        note.setWordWrap(True)
        note.setObjectName("Hint")
        layout.addWidget(note)

        layout.addStretch(1)
        return page

    def _build_modes(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        silent_group = QGroupBox("Silent mode")
        silent_layout = QVBoxLayout(silent_group)
        self.silent_group = QButtonGroup(self)
        self.mode_all = QRadioButton("Display all dialogs")
        self.mode_silent = QRadioButton("Hide all dialogs (fully unattended)")
        self.mode_all.setChecked(True)
        for button in (self.mode_all, self.mode_silent):
            self.silent_group.addButton(button)
            silent_layout.addWidget(button)
        layout.addWidget(silent_group)

        overwrite_group = QGroupBox("Overwrite mode")
        overwrite_layout = QVBoxLayout(overwrite_group)
        self.overwrite_group = QButtonGroup(self)
        self.ow_overwrite = QRadioButton("Overwrite all files")
        self.ow_skip = QRadioButton("Skip existing files")
        self.ow_rename = QRadioButton("Rename extracted files")
        self.ow_overwrite.setChecked(True)
        for button in (self.ow_overwrite, self.ow_skip, self.ow_rename):
            self.overwrite_group.addButton(button)
            overwrite_layout.addWidget(button)
        layout.addWidget(overwrite_group)

        layout.addStretch(1)
        return page

    def _build_text(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        form = QFormLayout()
        self.title_edit = QLineEdit(
            os.path.splitext(os.path.basename(self.archive_path))[0] or
            "Self-extracting archive"
        )
        form.addRow("Title of SFX window", self.title_edit)
        layout.addLayout(form)

        layout.addWidget(QLabel("Text to display"))
        self.description_edit = QPlainTextEdit()
        self.description_edit.setPlaceholderText(
            "Shown to the user before extraction begins."
        )
        self.description_edit.setMaximumHeight(110)
        layout.addWidget(self.description_edit)

        icon_group = QGroupBox("Icon")
        icon_row = QHBoxLayout(icon_group)
        self.icon_preview = QLabel()
        self.icon_preview.setPixmap(icons.pixmap("archive", 48))
        self.icon_preview.setFixedSize(56, 56)
        self.icon_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_row.addWidget(self.icon_preview)
        choose = QPushButton("Load icon...")
        choose.clicked.connect(self._choose_icon)
        reset = QPushButton("Use default")
        reset.clicked.connect(self._reset_icon)
        icon_row.addWidget(choose)
        icon_row.addWidget(reset)
        icon_row.addStretch(1)
        layout.addWidget(icon_group)

        layout.addStretch(1)
        return page

    def _build_license(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        form = QFormLayout()
        self.license_title_edit = QLineEdit()
        self.license_title_edit.setPlaceholderText("License Agreement")
        form.addRow("License window title", self.license_title_edit)
        layout.addLayout(form)

        layout.addWidget(QLabel("License text"))
        self.license_edit = QPlainTextEdit()
        self.license_edit.setPlaceholderText(
            "If this is filled in, the user must accept it before extraction."
        )
        layout.addWidget(self.license_edit, 1)
        return page

    def _build_advanced(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        group = QGroupBox("Desktop entry")
        form = QFormLayout(group)
        self.desktop_check = QCheckBox(
            "Create a desktop menu entry after extraction"
        )
        form.addRow(self.desktop_check)
        self.desktop_name_edit = QLineEdit()
        self.desktop_name_edit.setPlaceholderText("My Application")
        form.addRow("Entry name", self.desktop_name_edit)
        self.desktop_exec_edit = QLineEdit()
        self.desktop_exec_edit.setPlaceholderText("bin/myapp")
        form.addRow("Command (relative to destination)", self.desktop_exec_edit)
        layout.addWidget(group)

        note = QLabel(
            "This is the Linux counterpart of WinRAR's shortcut and registry "
            "options: it writes a .desktop file into "
            "~/.local/share/applications on the target machine."
        )
        note.setWordWrap(True)
        note.setObjectName("Hint")
        layout.addWidget(note)

        layout.addStretch(1)
        return page

    # -- behaviour ---------------------------------------------------------

    def _choose_icon(self) -> None:
        path, _f = QFileDialog.getOpenFileName(
            self, "Select an icon", "", "Images (*.png *.jpg *.jpeg *.svg *.xpm)"
        )
        if not path:
            return
        from PyQt6.QtGui import QPixmap

        pixmap = QPixmap(path)
        if pixmap.isNull():
            QMessageBox.warning(self, "LinRAR", "That image could not be loaded.")
            return
        scaled = pixmap.scaled(
            256, 256,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._icon_png = _pixmap_to_png(scaled)
        self.icon_preview.setPixmap(
            scaled.scaled(48, 48, Qt.AspectRatioMode.KeepAspectRatio,
                          Qt.TransformationMode.SmoothTransformation)
        )

    def _reset_icon(self) -> None:
        self._icon_png = None
        self.icon_preview.setPixmap(icons.pixmap("archive", 48))

    def _show_help(self) -> None:
        QMessageBox.information(
            self,
            "Help",
            "Advanced SFX options\n\n"
            "LinRAR turns the archive into an AppImage: one executable file "
            "that unpacks itself when run, with no installation needed.\n\n"
            "The recipient can also drive it from a terminal:\n"
            "    ./Archive.AppImage --help\n"
            "    ./Archive.AppImage -d ~/somewhere --silent\n"
            "    ./Archive.AppImage --list\n\n"
            "The unrar extractor is bundled inside, so the archive unpacks "
            "even on a machine with no RAR tools installed.",
        )

    def _accept(self) -> None:
        if self.desktop_check.isChecked() and not self.desktop_exec_edit.text().strip():
            QMessageBox.warning(
                self,
                "LinRAR",
                "Enter the command to launch, or turn off the desktop entry "
                "option.",
            )
            self.tabs.setCurrentIndex(5)
            return
        self.accept()

    # -- result ------------------------------------------------------------

    def options(self) -> SfxOptions:
        if self._icon_png is not None:
            icon_png = self._icon_png
        else:
            icon_png = _pixmap_to_png(icons.pixmap("archive", 256))

        overwrite = "overwrite"
        if self.ow_skip.isChecked():
            overwrite = "skip"
        elif self.ow_rename.isChecked():
            overwrite = "rename"

        return SfxOptions(
            default_path=self.path_edit.text().strip(),
            ask_destination=self.ask_check.isChecked(),
            run_after=self.run_after_edit.text().strip(),
            run_before=self.run_before_edit.text().strip(),
            silent=self.mode_silent.isChecked(),
            overwrite=overwrite,
            title=self.title_edit.text().strip() or "Self-extracting archive",
            description=self.description_edit.toPlainText().strip(),
            icon_png=icon_png,
            license_title=self.license_title_edit.text().strip(),
            license_text=self.license_edit.toPlainText(),
            create_desktop_entry=self.desktop_check.isChecked(),
            desktop_entry_name=(
                self.desktop_name_edit.text().strip()
                or self.title_edit.text().strip()
            ),
            desktop_entry_exec=self.desktop_exec_edit.text().strip(),
        )


def _pixmap_to_png(pixmap) -> bytes:
    """Serialise a QPixmap to PNG bytes for embedding in the AppDir."""
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    pixmap.save(buffer, "PNG")
    data = bytes(buffer.data())
    buffer.close()
    return data
