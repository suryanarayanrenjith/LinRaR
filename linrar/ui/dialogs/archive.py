"""The "Archive name and parameters" dialog."""

from __future__ import annotations

import os
import re
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QInputDialog,
    QLineEdit,
    QListWidget,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...core.backends.rar import default_dictionary, dictionary_sizes
from ...core.models import (
    ArchiveFormat,
    CompressOptions,
    CompressionMethod,
    UpdateMode,
)
from ...core.registry import REGISTRY
from ...core.settings import SETTINGS
from ...core.sfx import SfxOptions
from .. import icons
from . import sfx as sfx_dialog
from .password import PasswordDialog

_UNITS = [("B", 1), ("KB", 1024), ("MB", 1024**2), ("GB", 1024**3)]

# WinRAR's preset volume sizes, plus the classic removable-media sizes.  Each
# preset carries its own unit so it can never be misread through the unit
# combo (a bare "1457664" would otherwise be multiplied by megabytes).
_VOLUME_PRESETS = [
    "", "1457664 B", "5 MB", "10 MB", "100 MB", "700 MB",
    "1000 MB", "4480 MB", "8128 MB",
]

_VOLUME_RE = re.compile(
    r"^\s*([\d]+(?:[.,]\d+)?)\s*(B|KB?|MB?|GB?)?\s*$", re.IGNORECASE
)

# Extensions the name box swaps automatically when the format changes.
_KNOWN_TARGET_EXTS = {".rar", ".zip", ".7z", ".sfx", ".appimage"}


class ArchiveDialog(QDialog):
    """Collects every option needed to create or update an archive."""

    def __init__(
        self,
        parent=None,
        files: Optional[list[str]] = None,
        base_folder: str = "",
        default_name: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Archive name and parameters")
        self.setWindowIcon(icons.icon("add"))
        self.setModal(True)
        self.resize(520, 470)

        self.files = files or []
        self.base_folder = base_folder
        self._password: Optional[str] = None
        self._encrypt_headers = False
        #: Set once the user opens the SFX options; ``None`` means "defaults".
        self._sfx_options: Optional[SfxOptions] = None
        # Radio buttons emit toggled() while the page is still being built, so
        # the sync handlers must stay inert until every widget exists.
        self._ready = False

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_general(), "General")
        self.tabs.addTab(self._build_advanced(), "Advanced")
        self.tabs.addTab(self._build_options(), "Options")
        self.tabs.addTab(self._build_files(), "Files")
        self.tabs.addTab(self._build_comment(), "Comment")
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

        if default_name:
            self.name_edit.setText(default_name)
        self._ready = True
        self._restore()
        self._sync_format()

    # -- remembered choices ------------------------------------------------

    def _restore(self) -> None:
        """Start from whatever was used the last time an archive was made."""
        wanted = str(SETTINGS.get("compression/format") or "RAR")
        for fmt, button in self._format_buttons.items():
            if fmt.value == wanted and button.isEnabled():
                button.setChecked(True)
                break
        method = int(SETTINGS.get("compression/method"))
        if 0 <= method < self.method_combo.count():
            self.method_combo.setCurrentIndex(method)
        mode = str(SETTINGS.get("compression/update_mode") or "")
        for index in range(self.update_combo.count()):
            data = self.update_combo.itemData(index)
            if data is not None and data.value == mode:
                self.update_combo.setCurrentIndex(index)
                break
        self.solid_check.setChecked(bool(SETTINGS.get("compression/solid")))
        self.recovery_check.setChecked(bool(SETTINGS.get("compression/recovery")))
        self.recovery_spin.setValue(
            int(SETTINGS.get("compression/recovery_percent"))
        )
        self.test_check.setChecked(bool(SETTINGS.get("compression/test_after")))
        self.delete_check.setChecked(
            bool(SETTINGS.get("compression/delete_after"))
        )
        self.paths_check.setChecked(bool(SETTINGS.get("compression/store_paths")))
        self.recurse_check.setChecked(bool(SETTINGS.get("compression/recurse")))
        self.unit_combo.setCurrentText(
            str(SETTINGS.get("compression/volume_unit") or "MB")
        )
        kind = self.sfx_combo.findData(
            str(SETTINGS.get("compression/sfx_format") or sfx_dialog.APPIMAGE)
        )
        if kind >= 0:
            self.sfx_combo.setCurrentIndex(kind)
        excludes = str(SETTINGS.get("compression/exclude") or "")
        if excludes:
            self.exclude_edit.setPlainText(excludes)
        # Last, because setting the format above rebuilt this combo from the
        # format's own list: _refresh_dictionary keeps a size that is still on
        # offer, so putting the remembered one in now survives the final sync.
        remembered = str(SETTINGS.get("compression/dictionary") or "")
        if remembered:
            index = self.dictionary_combo.findText(remembered)
            if index >= 0:
                self.dictionary_combo.setCurrentIndex(index)

    def _remember(self) -> None:
        """Store the choices so the next archive starts from the same place."""
        SETTINGS.set("compression/format", self.selected_format.value)
        SETTINGS.set("compression/method", self.method_combo.currentIndex())
        mode = self.update_combo.currentData()
        if mode is not None:
            SETTINGS.set("compression/update_mode", mode.value)
        if self.dictionary_combo.isEnabled():
            SETTINGS.set(
                "compression/dictionary", self.dictionary_combo.currentText()
            )
        SETTINGS.set("compression/solid", self.solid_check.isChecked())
        SETTINGS.set("compression/recovery", self.recovery_check.isChecked())
        SETTINGS.set("compression/recovery_percent", self.recovery_spin.value())
        SETTINGS.set("compression/test_after", self.test_check.isChecked())
        SETTINGS.set("compression/delete_after", self.delete_check.isChecked())
        SETTINGS.set("compression/store_paths", self.paths_check.isChecked())
        SETTINGS.set("compression/recurse", self.recurse_check.isChecked())
        SETTINGS.set("compression/volume_unit", self.unit_combo.currentText())
        SETTINGS.set("compression/sfx_format", self.sfx_combo.currentData())
        SETTINGS.set(
            "compression/exclude", self.exclude_edit.toPlainText().strip()
        )
        SETTINGS.sync()

    # -- General tab -------------------------------------------------------

    def _build_general(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(7)

        layout.addWidget(QLabel("Archive name"))
        name_row = QHBoxLayout()
        name_row.setSpacing(6)
        self.name_edit = QLineEdit()
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._browse)
        name_row.addWidget(self.name_edit, 1)
        name_row.addWidget(browse)
        layout.addLayout(name_row)

        profile_row = QHBoxLayout()
        profiles = QPushButton("Profiles...")
        profiles.clicked.connect(self._show_profiles)
        profile_row.addWidget(profiles)
        profile_row.addStretch(1)
        layout.addLayout(profile_row)

        columns = QHBoxLayout()
        columns.setSpacing(12)

        # --- left column ---
        left = QVBoxLayout()
        left.setSpacing(7)

        format_group = QGroupBox("Archive format")
        format_layout = QVBoxLayout(format_group)
        format_layout.setSpacing(3)
        self.format_group = QButtonGroup(self)
        self._format_buttons: dict[ArchiveFormat, QRadioButton] = {}
        available = REGISTRY.creatable_formats()
        for fmt, label in (
            (ArchiveFormat.RAR5, "RAR"),
            (ArchiveFormat.RAR4, "RAR4"),
            (ArchiveFormat.ZIP, "ZIP"),
            (ArchiveFormat.SEVENZIP, "7Z"),
        ):
            button = QRadioButton(label)
            button.setEnabled(fmt in available)
            if fmt not in available:
                button.setToolTip(
                    "The required command line tool is not installed."
                )
            self.format_group.addButton(button)
            format_layout.addWidget(button)
            self._format_buttons[fmt] = button
            button.toggled.connect(self._on_format_changed)
        first = next((f for f in available), ArchiveFormat.ZIP)
        self._format_buttons[first].setChecked(True)
        left.addWidget(format_group)

        left.addWidget(QLabel("Compression method"))
        self.method_combo = QComboBox()
        for method in CompressionMethod:
            self.method_combo.addItem(method.label, method)
        self.method_combo.setCurrentIndex(int(CompressionMethod.NORMAL))
        self.method_combo.currentIndexChanged.connect(self._on_method_changed)
        left.addWidget(self.method_combo)

        left.addWidget(QLabel("Dictionary size"))
        self.dictionary_combo = QComboBox()
        left.addWidget(self.dictionary_combo)

        left.addWidget(QLabel("Split to volumes, size"))
        volume_row = QHBoxLayout()
        volume_row.setSpacing(4)
        self.volume_combo = QComboBox()
        self.volume_combo.setEditable(True)
        self.volume_combo.addItems(_VOLUME_PRESETS)
        self.volume_combo.setCurrentText("")
        self.unit_combo = QComboBox()
        for label, _factor in _UNITS:
            self.unit_combo.addItem(label)
        self.unit_combo.setCurrentText("MB")
        volume_row.addWidget(self.volume_combo, 1)
        volume_row.addWidget(self.unit_combo)
        left.addLayout(volume_row)
        left.addStretch(1)

        # --- right column ---
        right = QVBoxLayout()
        right.setSpacing(7)

        right.addWidget(QLabel("Update mode"))
        self.update_combo = QComboBox()
        for mode in UpdateMode:
            self.update_combo.addItem(mode.label, mode)
        right.addWidget(self.update_combo)

        options_group = QGroupBox("Archiving options")
        options_layout = QVBoxLayout(options_group)
        options_layout.setSpacing(3)
        self.delete_check = QCheckBox("Delete files after archiving")
        self.sfx_check = QCheckBox("Create SFX archive")
        self.sfx_check.toggled.connect(self._on_sfx_toggled)
        self.solid_check = QCheckBox("Create solid archive")
        self.recovery_check = QCheckBox("Add recovery record")
        self.test_check = QCheckBox("Test archived files")
        self.lock_check = QCheckBox("Lock archive")

        options_layout.addWidget(self.delete_check)
        options_layout.addWidget(self.sfx_check)
        # Both kinds of self-extracting archive are offered right here, beside
        # the box that turns them on: an AppImage used to be reachable only by
        # creating a .rar first, opening it, and finding the SFX command.
        sfx_row = QHBoxLayout()
        sfx_row.setContentsMargins(18, 0, 0, 0)
        sfx_row.setSpacing(5)
        self.sfx_combo = QComboBox()
        self.sfx_combo.addItem("AppImage", sfx_dialog.APPIMAGE)
        self.sfx_combo.addItem("RAR .sfx stub", sfx_dialog.RAR_STUB)
        self.sfx_combo.setToolTip(
            "AppImage: one executable that unpacks itself anywhere.\n"
            "RAR .sfx stub: rar's own smaller self-extracting shell script."
        )
        self.sfx_combo.currentIndexChanged.connect(self._on_sfx_kind_changed)
        self.sfx_options_button = QPushButton("Options...")
        self.sfx_options_button.setToolTip(
            "Destination, commands to run, licence, icon and desktop entry"
        )
        self.sfx_options_button.clicked.connect(self._configure_sfx)
        sfx_row.addWidget(self.sfx_combo, 1)
        sfx_row.addWidget(self.sfx_options_button)
        options_layout.addLayout(sfx_row)

        for check in (
            self.solid_check,
            self.recovery_check,
            self.test_check,
            self.lock_check,
        ):
            options_layout.addWidget(check)
        options_layout.addStretch(1)
        right.addWidget(options_group, 1)

        columns.addLayout(left, 1)
        columns.addLayout(right, 1)
        layout.addLayout(columns, 1)

        password_row = QHBoxLayout()
        self.password_button = QPushButton("Set password...")
        self.password_button.clicked.connect(self._set_password)
        self.password_state = QLabel("")
        self.password_state.setObjectName("Success")
        password_row.addWidget(self.password_button)
        password_row.addWidget(self.password_state)
        password_row.addStretch(1)
        layout.addLayout(password_row)

        return page

    # -- Advanced tab ------------------------------------------------------

    def _build_advanced(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        recovery_group = QGroupBox("Recovery record")
        recovery_form = QFormLayout(recovery_group)
        self.recovery_spin = QSpinBox()
        self.recovery_spin.setRange(1, 100)
        self.recovery_spin.setValue(3)
        self.recovery_spin.setSuffix(" %")
        self.recovery_spin.setMaximumWidth(110)
        recovery_form.addRow("Redundancy level", self.recovery_spin)
        note = QLabel(
            "A recovery record lets a damaged archive be repaired, at the cost "
            "of extra size. Enable it on the General tab."
        )
        note.setWordWrap(True)
        note.setObjectName("Hint")
        recovery_form.addRow(note)
        layout.addWidget(recovery_group)

        password_group = QGroupBox("Encryption")
        password_layout = QVBoxLayout(password_group)
        button = QPushButton("Set password...")
        button.clicked.connect(self._set_password)
        password_layout.addWidget(button, 0, Qt.AlignmentFlag.AlignLeft)
        self.advanced_password_state = QLabel("No password set")
        self.advanced_password_state.setObjectName("Hint")
        password_layout.addWidget(self.advanced_password_state)
        layout.addWidget(password_group)

        layout.addStretch(1)
        return page

    # -- Options tab -------------------------------------------------------

    def _build_options(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        group = QGroupBox("File paths")
        group_layout = QVBoxLayout(group)
        self.recurse_check = QCheckBox("Include subfolders")
        self.recurse_check.setChecked(True)
        self.paths_check = QCheckBox("Store full folder structure")
        self.paths_check.setChecked(True)
        group_layout.addWidget(self.recurse_check)
        group_layout.addWidget(self.paths_check)
        layout.addWidget(group)

        exclude_group = QGroupBox("Exclude the following file masks")
        exclude_layout = QVBoxLayout(exclude_group)
        self.exclude_edit = QPlainTextEdit()
        self.exclude_edit.setPlaceholderText("*.tmp\n*.bak\nnode_modules")
        self.exclude_edit.setMaximumHeight(110)
        exclude_layout.addWidget(self.exclude_edit)
        layout.addWidget(exclude_group)

        layout.addStretch(1)
        return page

    # -- Files tab ---------------------------------------------------------

    def _build_files(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        layout.addWidget(QLabel("Files to add"))
        self.files_list = QListWidget()
        for item in self.files:
            self.files_list.addItem(item)
        layout.addWidget(self.files_list, 1)

        row = QHBoxLayout()
        add_files = QPushButton("Add files...")
        add_files.clicked.connect(self._add_files)
        add_folder = QPushButton("Add folder...")
        add_folder.clicked.connect(self._add_folder)
        remove = QPushButton("Remove")
        remove.clicked.connect(self._remove_files)
        row.addWidget(add_files)
        row.addWidget(add_folder)
        row.addWidget(remove)
        row.addStretch(1)
        layout.addLayout(row)
        return page

    # -- Comment tab -------------------------------------------------------

    def _build_comment(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.addWidget(QLabel("Archive comment"))
        self.comment_edit = QPlainTextEdit()
        layout.addWidget(self.comment_edit, 1)
        return page

    # -- behaviour ---------------------------------------------------------

    @property
    def selected_format(self) -> ArchiveFormat:
        for fmt, button in self._format_buttons.items():
            if button.isChecked():
                return fmt
        return ArchiveFormat.ZIP

    def _current_method(self) -> CompressionMethod:
        """Read the method combo.

        ``CompressionMethod.STORE`` is 0 and therefore falsy, so an ``or``
        fallback here would silently turn "Store" into "Normal".
        """
        data = self.method_combo.currentData()
        return CompressionMethod.NORMAL if data is None else data

    def _on_format_changed(self, checked: bool) -> None:
        if checked and self._ready:
            self._sync_format()

    def _on_sfx_toggled(self, _checked: bool) -> None:
        if self._ready:
            self._sync_sfx()
            self._retarget_extension(self.selected_format)

    def _on_sfx_kind_changed(self, _index: int) -> None:
        if self._ready:
            self._sync_sfx()
            self._retarget_extension(self.selected_format)

    @property
    def sfx_kind(self) -> str:
        """"", ``"appimage"`` or ``"rar"``: what the OK button will produce."""
        if not (self.sfx_check.isChecked() and self.sfx_check.isEnabled()):
            return ""
        return self.sfx_combo.currentData() or sfx_dialog.APPIMAGE

    def sfx_options(self) -> SfxOptions:
        """The AppImage settings, defaulted from this dialog when untouched."""
        if self._sfx_options is not None:
            return self._sfx_options
        title = os.path.splitext(
            os.path.basename(self.name_edit.text().strip())
        )[0]
        return SfxOptions(title=title or "Self-extracting archive")

    def _sync_sfx(self) -> None:
        """Keep the SFX row, and the options it rules out, consistent."""
        active = self.sfx_kind
        self.sfx_combo.setEnabled(bool(active))
        self.sfx_options_button.setEnabled(active == sfx_dialog.APPIMAGE)
        # An AppImage is one executable file, so it cannot also be split into
        # volumes; say so by disabling the box rather than failing at the end.
        appimage = active == sfx_dialog.APPIMAGE
        allows_volumes = self.selected_format is not ArchiveFormat.ZIP
        self.volume_combo.setEnabled(allows_volumes and not appimage)
        self.unit_combo.setEnabled(allows_volumes and not appimage)
        if appimage:
            self.volume_combo.setCurrentText("")
            self.volume_combo.setToolTip(
                "An AppImage is a single file, so it cannot be split into "
                "volumes."
            )
        else:
            self.volume_combo.setToolTip("")

    def _configure_sfx(self) -> None:
        """Open the AppImage options.

        The kind is chosen by the combo box beside this button, so the options
        window is not asked to offer it a second time -- and the stub has no
        options, so the button does not apply to it at all.
        """
        if self.sfx_kind == sfx_dialog.RAR_STUB:
            QMessageBox.information(
                self,
                "LinRAR",
                "The RAR .sfx stub takes no options: it is a small shell "
                "script that unpacks the archive beside itself.\n\n"
                "Choose AppImage beside this button if you want a "
                "configurable self-extracting file.",
            )
            return
        dialog = sfx_dialog.SfxDialog(
            self, archive_path=self.name_edit.text().strip()
        )
        if dialog.exec() != sfx_dialog.SfxDialog.DialogCode.Accepted:
            return
        self._sfx_options = dialog.options()

    def _on_method_changed(self, _index: int) -> None:
        if self._ready:
            self._refresh_dictionary()

    def _sync_format(self) -> None:
        if not self._ready:
            return
        fmt = self.selected_format
        is_rar = fmt in (ArchiveFormat.RAR5, ArchiveFormat.RAR4)
        is_zip = fmt is ArchiveFormat.ZIP

        self._refresh_dictionary()
        self._retarget_extension(fmt)

        # Only RAR supports these; grey them out elsewhere like WinRAR does.
        self.recovery_check.setEnabled(is_rar)
        self.solid_check.setEnabled(fmt is not ArchiveFormat.ZIP)
        self.lock_check.setEnabled(is_rar)
        self.sfx_check.setEnabled(is_rar)
        self.recovery_spin.setEnabled(is_rar)
        self.dictionary_combo.setEnabled(not is_zip)
        for widget in (
            self.recovery_check,
            self.lock_check,
            self.sfx_check,
        ):
            if not widget.isEnabled():
                widget.setChecked(False)
        # Owns the volume boxes too: an AppImage rules them out.
        self._sync_sfx()

        # RAR and ZIP honour every update mode; 7z always adds-and-replaces.
        self.update_combo.setEnabled(is_rar or is_zip)
        if self._encrypt_headers and fmt is ArchiveFormat.ZIP:
            self._encrypt_headers = False

    def _refresh_dictionary(self) -> None:
        fmt = self.selected_format
        method = self._current_method()
        sizes = dictionary_sizes(fmt)
        current = self.dictionary_combo.currentText()
        self.dictionary_combo.blockSignals(True)
        self.dictionary_combo.clear()
        self.dictionary_combo.addItems(sizes)
        target = current if current in sizes else default_dictionary(fmt, method)
        index = self.dictionary_combo.findText(target)
        self.dictionary_combo.setCurrentIndex(max(index, 0))
        self.dictionary_combo.blockSignals(False)

    def _expected_extension(self, fmt: ArchiveFormat) -> str:
        """The extension the current format (and SFX option) calls for."""
        if fmt in (ArchiveFormat.RAR5, ArchiveFormat.RAR4):
            kind = self.sfx_kind
            if kind == sfx_dialog.APPIMAGE:
                return ".AppImage"
            return ".sfx" if kind == sfx_dialog.RAR_STUB else ".rar"
        return {
            ArchiveFormat.ZIP: ".zip",
            ArchiveFormat.SEVENZIP: ".7z",
        }.get(fmt, ".rar")

    def _retarget_extension(self, fmt: ArchiveFormat) -> None:
        """Keep the archive name's extension in step with the chosen format."""
        name = self.name_edit.text().strip()
        if not name:
            return
        wanted = self._expected_extension(fmt)
        stem, ext = os.path.splitext(name)
        if ext.lower() == wanted.lower():
            return
        if ext.lower() in _KNOWN_TARGET_EXTS:
            self.name_edit.setText(stem + wanted)
        else:
            # Unknown or missing extension: append rather than destroy part of
            # a name such as "backup.2024".
            self.name_edit.setText(name + wanted)

    def _browse(self) -> None:
        current = self.name_edit.text() or SETTINGS.get("places/last_folder")
        path, _filter = QFileDialog.getSaveFileName(
            self, "Find archive", current,
            "RAR archives (*.rar);;ZIP archives (*.zip);;7z archives (*.7z);;"
            "All files (*)",
        )
        if not path:
            return
        self.name_edit.setText(path)
        # Follow the chosen file's extension if it names a creatable format;
        # otherwise bring the extension in line with the current format.
        by_ext = {
            ".rar": ArchiveFormat.RAR5,
            ".zip": ArchiveFormat.ZIP,
            ".7z": ArchiveFormat.SEVENZIP,
        }
        fmt = by_ext.get(os.path.splitext(path)[1].lower())
        button = self._format_buttons.get(fmt) if fmt else None
        if button is not None and button.isEnabled() and not button.isChecked():
            button.setChecked(True)  # triggers the normal format sync
        else:
            self._retarget_extension(self.selected_format)

    def _add_files(self) -> None:
        paths, _filter = QFileDialog.getOpenFileNames(
            self, "Select files to add", SETTINGS.get("places/last_folder")
        )
        for path in paths:
            self.files_list.addItem(path)

    def _add_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Select a folder to add", SETTINGS.get("places/last_folder")
        )
        if path:
            self.files_list.addItem(path)

    def _remove_files(self) -> None:
        for item in self.files_list.selectedItems():
            self.files_list.takeItem(self.files_list.row(item))

    def _set_password(self) -> None:
        supports_headers = self.selected_format in (
            ArchiveFormat.RAR5,
            ArchiveFormat.RAR4,
            ArchiveFormat.SEVENZIP,
        )
        result = PasswordDialog.ask(
            self,
            os.path.basename(self.name_edit.text()),
            confirm=True,
            allow_header_encryption=supports_headers,
        )
        if result is None:
            return
        password, encrypt_headers = result
        self._password = password or None
        self._encrypt_headers = bool(
            self._password and encrypt_headers and supports_headers
        )
        if not self._password:
            state = ""
        elif self._encrypt_headers:
            state = "Password set (file names encrypted)"
        else:
            state = "Password set"
        self.password_state.setText(state)
        self.advanced_password_state.setText(state or "No password set")

    def _show_profiles(self) -> None:
        from ...core.profiles import PROFILES, Profile
        from .tools import ProfileDialog

        menu = QMenu(self)
        for profile in PROFILES.load():
            action = menu.addAction(f"{profile.name}   ({profile.summary()})")
            action.triggered.connect(
                lambda _c=False, p=profile: self.apply_profile(p)
            )
        menu.addSeparator()
        save_action = menu.addAction("Save current settings as a profile...")
        save_action.triggered.connect(self._save_profile)
        organize = menu.addAction("Organize profiles...")
        organize.triggered.connect(lambda: ProfileDialog(self).exec())
        menu.exec(self.sender().mapToGlobal(self.sender().rect().bottomLeft()))

    def _save_profile(self) -> None:
        from ...core.profiles import PROFILES, Profile

        name, ok = QInputDialog.getText(
            self, "Save profile", "Profile name:", text="My profile"
        )
        if not ok or not name.strip():
            return
        PROFILES.upsert(Profile.from_options(name.strip(), self.options()))
        QMessageBox.information(
            self, "LinRAR", f"Profile '{name.strip()}' saved."
        )

    def apply_profile(self, profile) -> None:
        """Load a saved profile's settings into the dialog."""
        for fmt, button in self._format_buttons.items():
            if fmt.value == profile.format and button.isEnabled():
                button.setChecked(True)
                break
        self.method_combo.setCurrentIndex(int(profile.method))
        self._sync_format()
        if profile.dictionary_size:
            index = self.dictionary_combo.findText(profile.dictionary_size)
            if index >= 0:
                self.dictionary_combo.setCurrentIndex(index)
        for index in range(self.update_combo.count()):
            if self.update_combo.itemData(index).value == profile.update_mode:
                self.update_combo.setCurrentIndex(index)
                break
        self.solid_check.setChecked(profile.solid and self.solid_check.isEnabled())
        self.recovery_check.setChecked(
            profile.recovery_record and self.recovery_check.isEnabled()
        )
        self.recovery_spin.setValue(profile.recovery_percent)
        kind = profile.sfx_format or ("rar" if profile.create_sfx else "")
        index = self.sfx_combo.findData(kind)
        if index >= 0:
            self.sfx_combo.setCurrentIndex(index)
        self.sfx_check.setChecked(bool(kind) and self.sfx_check.isEnabled())
        self.delete_check.setChecked(profile.delete_after)
        self.test_check.setChecked(profile.test_after)
        self.lock_check.setChecked(profile.lock and self.lock_check.isEnabled())
        self.recurse_check.setChecked(profile.recurse_subfolders)
        self.paths_check.setChecked(profile.store_paths)
        self._encrypt_headers = profile.encrypt_headers
        if profile.volume_size:
            self.volume_combo.setCurrentText(f"{profile.volume_size} B")
            self.unit_combo.setCurrentText("B")
        if profile.exclude_patterns:
            self.exclude_edit.setPlainText("\n".join(profile.exclude_patterns))
        if profile.comment:
            self.comment_edit.setPlainText(profile.comment)

    def _show_help(self) -> None:
        QMessageBox.information(
            self,
            "Help",
            "Archive name and parameters\n\n"
            "Choose the archive name, format and compression level, then press "
            "OK to start archiving.\n\n"
            "• RAR gives the best compression and supports recovery "
            "records, solid archives and encrypted file names.\n"
            "• ZIP is the most portable format.\n"
            "• Split to volumes to spread a large archive over several "
            "files.",
        )

    # -- result ------------------------------------------------------------

    def _volume_bytes(self) -> Optional[int]:
        """Parse the volume-size box; ``None`` means the text is invalid.

        A unit written in the text itself ("700 MB", "1457664 B") always wins;
        a bare number falls back to the unit combo.
        """
        text = self.volume_combo.currentText().strip()
        if not text:
            return 0
        match = _VOLUME_RE.match(text)
        if not match:
            return None
        value = float(match.group(1).replace(",", "."))
        suffix = (match.group(2) or "").upper()
        if suffix:
            factor = {"B": 1, "K": 1024, "KB": 1024,
                      "M": 1024**2, "MB": 1024**2,
                      "G": 1024**3, "GB": 1024**3}[suffix]
        else:
            factor = dict(_UNITS)[self.unit_combo.currentText()]
        result = int(value * factor)
        return result if result > 0 else None

    def _accept(self) -> None:
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "LinRAR", "Please enter an archive name.")
            self.tabs.setCurrentIndex(0)
            self.name_edit.setFocus()
            return
        if self.files_list.count() == 0:
            QMessageBox.warning(
                self, "LinRAR", "Please add at least one file to the archive."
            )
            self.tabs.setCurrentIndex(3)
            return
        if self.sfx_kind == sfx_dialog.APPIMAGE:
            ready, why = sfx_dialog.appimage_ready()
            if not ready:
                QMessageBox.warning(
                    self,
                    "LinRAR",
                    f"An AppImage cannot be built on this system.\n\n{why}\n\n"
                    "Choose the RAR .sfx stub instead, or install the missing "
                    "package from the Dependencies manager.",
                )
                self.tabs.setCurrentIndex(0)
                return
        if self._volume_bytes() is None:
            QMessageBox.warning(
                self,
                "LinRAR",
                "The volume size is not a valid number.\n\n"
                "Use a plain number with the unit selector, or write the unit "
                "in the box, e.g.  700 MB",
            )
            self.tabs.setCurrentIndex(0)
            self.volume_combo.setFocus()
            return

        full = name if os.path.isabs(name) else os.path.join(
            self.base_folder or SETTINGS.get("places/last_folder"), name
        )
        folder = os.path.dirname(os.path.abspath(full))
        if not os.path.isdir(folder):
            QMessageBox.warning(
                self, "LinRAR", f"The folder does not exist:\n{folder}"
            )
            return
        if not os.access(folder, os.W_OK):
            QMessageBox.warning(
                self, "LinRAR", f"The folder is not writable:\n{folder}"
            )
            return
        self._remember()
        self.accept()

    def _storage_base(self) -> str:
        """The folder member paths are stored relative to.

        Recomputed from the list as it stands rather than from the selection
        the dialog opened with: files added on the Files tab may live anywhere,
        and measuring them against the original folder produced ``../..``
        paths that the archive tools then stored in surprising places.
        """
        files = [os.path.abspath(f) for f in self.selected_files() if f.strip()]
        if not files:
            return self.base_folder
        folders = [os.path.dirname(f) or "/" for f in files]
        try:
            base = os.path.commonpath(folders)
        except ValueError:
            return self.base_folder
        # One file selected inside the folder the dialog opened on: keep that
        # folder, so "add this one file" still stores it beside its siblings.
        if self.base_folder and base.startswith(self.base_folder):
            return self.base_folder
        return base

    def options(self) -> CompressOptions:
        name = self.name_edit.text().strip()
        # Guarantee a sensible extension even if the user typed a bare name.
        wanted = self._expected_extension(self.selected_format)
        if not os.path.splitext(name)[1]:
            name += wanted
        if not os.path.isabs(name):
            name = os.path.join(
                self.base_folder or SETTINGS.get("places/last_folder"), name
            )
        excludes = [
            line.strip()
            for line in self.exclude_edit.toPlainText().splitlines()
            if line.strip()
        ]
        return CompressOptions(
            archive_path=name,
            format=self.selected_format,
            method=self._current_method(),
            dictionary_size=(
                self.dictionary_combo.currentText()
                if self.dictionary_combo.isEnabled()
                else ""
            ),
            volume_size=self._volume_bytes() or 0,
            update_mode=self.update_combo.currentData() or UpdateMode.ADD_REPLACE,
            delete_after=self.delete_check.isChecked(),
            # An AppImage wraps a finished RAR archive, so rar itself is asked
            # for a plain one; only the stub is its own -sfx switch.
            create_sfx=self.sfx_kind == sfx_dialog.RAR_STUB,
            sfx_format=self.sfx_kind,
            solid=self.solid_check.isChecked(),
            recovery_record=self.recovery_check.isChecked(),
            recovery_percent=self.recovery_spin.value(),
            test_after=self.test_check.isChecked(),
            lock=self.lock_check.isChecked(),
            password=self._password,
            encrypt_headers=self._encrypt_headers,
            recurse_subfolders=self.recurse_check.isChecked(),
            store_paths=self.paths_check.isChecked(),
            base_folder=self._storage_base(),
            comment=self.comment_edit.toPlainText(),
            exclude_patterns=excludes,
        )

    def selected_files(self) -> list[str]:
        return [
            self.files_list.item(i).text() for i in range(self.files_list.count())
        ]
