"""Organisational dialogs: profiles, passwords, favorites, properties, report."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from ...core import report as report_module
from ...core.models import (
    ArchiveEntry,
    ArchiveInfo,
    CompressionMethod,
    format_size,
    format_size_short,
)
from ...core.passwords import PASSWORDS, PasswordEntry
from ...core.profiles import PROFILES, Profile
from ...core.settings import SETTINGS
from .. import icons, theme

_ROLE = Qt.ItemDataRole.UserRole


class ProfileDialog(QDialog):
    """Organise compression profiles (WinRAR's Options > Compression profiles)."""

    def __init__(self, parent=None, select: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle("Compression profiles")
        self.setWindowIcon(icons.icon("add"))
        self.resize(600, 440)
        self.chosen: Optional[Profile] = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        left = QVBoxLayout()
        left.addWidget(QLabel("Profiles"))
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._on_select)
        left.addWidget(self.list, 1)
        layout.addLayout(left, 1)

        right = QVBoxLayout()
        self.detail = QGroupBox("Settings")
        form = QFormLayout(self.detail)
        self.format_label = QLabel("-")
        self.method_label = QLabel("-")
        self.dict_label = QLabel("-")
        self.flags_label = QLabel("-")
        self.flags_label.setWordWrap(True)
        form.addRow("Format", self.format_label)
        form.addRow("Method", self.method_label)
        form.addRow("Dictionary", self.dict_label)
        form.addRow("Options", self.flags_label)
        right.addWidget(self.detail)

        buttons = QVBoxLayout()
        for text, slot in (
            ("Set as default", self._set_default),
            ("Rename...", self._rename),
            ("Delete", self._delete),
        ):
            button = QPushButton(text)
            button.clicked.connect(slot)
            buttons.addWidget(button)
        buttons.addStretch(1)
        right.addLayout(buttons)
        right.addStretch(1)

        box = QDialogButtonBox()
        self.use_button = box.addButton(
            "Use this profile", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.use_button.clicked.connect(self._use)
        close = box.addButton(QDialogButtonBox.StandardButton.Close)
        close.clicked.connect(self.reject)
        right.addWidget(box)

        layout.addLayout(right, 1)
        self._reload(select)

    def _reload(self, select: str = "") -> None:
        self.list.clear()
        for profile in PROFILES.load():
            label = profile.name + ("  (default)" if profile.is_default else "")
            item = QListWidgetItem(icons.icon("add"), label)
            item.setData(_ROLE, profile.name)
            self.list.addItem(item)
            if profile.name == select:
                self.list.setCurrentItem(item)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)

    def _current(self) -> Optional[Profile]:
        item = self.list.currentItem()
        if item is None:
            return None
        return PROFILES.get(item.data(_ROLE))

    def _on_select(self) -> None:
        profile = self._current()
        if profile is None:
            return
        self.format_label.setText(profile.summary().split(",")[0])
        self.method_label.setText(CompressionMethod(profile.method).label)
        self.dict_label.setText(profile.dictionary_size or "(automatic)")
        flags = []
        for label, value in (
            ("solid", profile.solid),
            ("recovery record", profile.recovery_record),
            ("SFX", profile.create_sfx),
            ("test after", profile.test_after),
            ("lock", profile.lock),
            ("delete originals", profile.delete_after),
            ("encrypt names", profile.encrypt_headers),
        ):
            if value:
                flags.append(label)
        if profile.volume_size:
            flags.append(f"split at {format_size_short(profile.volume_size)}")
        self.flags_label.setText(", ".join(flags) or "(none)")

    def _set_default(self) -> None:
        profile = self._current()
        if profile:
            PROFILES.set_default(profile.name)
            self._reload(profile.name)

    def _rename(self) -> None:
        profile = self._current()
        if profile is None:
            return
        name, ok = QInputDialog.getText(
            self, "Rename profile", "New name:", text=profile.name
        )
        if not ok or not name.strip() or name == profile.name:
            return
        PROFILES.remove(profile.name)
        profile.name = name.strip()
        PROFILES.upsert(profile)
        self._reload(profile.name)

    def _delete(self) -> None:
        profile = self._current()
        if profile is None:
            return
        if len(PROFILES.load()) <= 1:
            QMessageBox.information(
                self, "LinRAR", "At least one profile must remain."
            )
            return
        reply = QMessageBox.question(
            self,
            "Delete profile",
            f"Delete the profile '{profile.name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            PROFILES.remove(profile.name)
            self._reload()

    def _use(self) -> None:
        self.chosen = self._current()
        if self.chosen is not None:
            self.accept()


class PasswordManagerDialog(QDialog):
    """WinRAR's Tools > Organize passwords."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Organize passwords")
        self.setWindowIcon(icons.icon("key"))
        self.resize(600, 430)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        storage = QLabel(
            f"<b>Storage:</b> {PASSWORDS.backend_name}"
        )
        layout.addWidget(storage)

        if PASSWORDS.secure:
            note = QLabel(
                "Passwords are held in your desktop's keyring and are "
                "protected by your login."
            )
            note.setObjectName("Success")
        else:
            note = QLabel(
                "No system keyring was found, so passwords are stored in "
                "LinRAR's own settings file. They are obfuscated but "
                "<b>not encrypted</b> — anyone who can read your home folder "
                "can recover them. Install 'libsecret-tools' (secret-tool) for "
                "proper keyring storage."
            )
            note.setObjectName("Warning")
        note.setWordWrap(True)
        layout.addWidget(note)

        self.table = QTreeWidget()
        self.table.setColumnCount(4)
        self.table.setHeaderLabels(["Label", "Applies to", "Password", "Note"])
        self.table.setRootIsDecorated(False)
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        header = self.table.header()
        header.setStretchLastSection(True)
        self.table.setColumnWidth(0, 150)
        self.table.setColumnWidth(1, 120)
        self.table.setColumnWidth(2, 120)
        layout.addWidget(self.table, 1)

        self.show_check = QCheckBox("Show passwords")
        self.show_check.toggled.connect(self._reload)
        layout.addWidget(self.show_check)

        row = QHBoxLayout()
        for text, slot in (
            ("Add...", self._add),
            ("Edit...", self._edit),
            ("Remove", self._remove),
        ):
            button = QPushButton(text)
            button.clicked.connect(slot)
            row.addWidget(button)
        row.addStretch(1)
        layout.addLayout(row)

        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        box.rejected.connect(self.reject)
        box.accepted.connect(self.accept)
        layout.addWidget(box)

        self._entries: list[PasswordEntry] = PASSWORDS.load()
        self._reload()

    def _reload(self) -> None:
        self.table.clear()
        for entry in self._entries:
            shown = entry.password if self.show_check.isChecked() else "•" * 8
            item = QTreeWidgetItem(
                self.table, [entry.label, entry.mask, shown, entry.note]
            )
            item.setIcon(0, icons.icon("key"))

    def _selected_index(self) -> int:
        item = self.table.currentItem()
        return self.table.indexOfTopLevelItem(item) if item else -1

    def _add(self) -> None:
        entry = self._prompt(PasswordEntry(label="", mask="*"))
        if entry:
            self._entries.append(entry)
            PASSWORDS.save(self._entries)
            self._reload()

    def _edit(self) -> None:
        index = self._selected_index()
        if index < 0:
            return
        entry = self._prompt(self._entries[index])
        if entry:
            self._entries[index] = entry
            PASSWORDS.save(self._entries)
            self._reload()

    def _remove(self) -> None:
        index = self._selected_index()
        if index < 0:
            return
        del self._entries[index]
        PASSWORDS.save(self._entries)
        self._reload()

    def _prompt(self, entry: PasswordEntry) -> Optional[PasswordEntry]:
        dialog = QDialog(self)
        dialog.setWindowTitle("Password entry")
        form = QFormLayout(dialog)
        label_edit = QLineEdit(entry.label)
        mask_edit = QLineEdit(entry.mask or "*")
        mask_edit.setToolTip(
            "File name mask this password should be tried for, e.g. backup*.rar"
        )
        password_edit = QLineEdit(entry.password)
        password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        note_edit = QLineEdit(entry.note)
        form.addRow("Label", label_edit)
        form.addRow("Applies to", mask_edit)
        form.addRow("Password", password_edit)
        form.addRow("Note", note_edit)
        box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        box.accepted.connect(dialog.accept)
        box.rejected.connect(dialog.reject)
        form.addRow(box)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        if not label_edit.text().strip():
            QMessageBox.warning(self, "LinRAR", "Please enter a label.")
            return None
        return PasswordEntry(
            label=label_edit.text().strip(),
            mask=mask_edit.text().strip() or "*",
            password=password_edit.text(),
            note=note_edit.text().strip(),
        )


class FavoritesDialog(QDialog):
    """WinRAR's Favorites > Organize favorites."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Organize favorites")
        self.setWindowIcon(icons.icon("folder"))
        self.resize(560, 380)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.list = QListWidget()
        layout.addWidget(self.list, 1)

        row = QHBoxLayout()
        for text, slot in (
            ("Add folder...", self._add_folder),
            ("Add archive...", self._add_archive),
            ("Remove", self._remove),
            ("Move up", self._up),
            ("Move down", self._down),
        ):
            button = QPushButton(text)
            button.clicked.connect(slot)
            row.addWidget(button)
        row.addStretch(1)
        layout.addLayout(row)

        box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        box.accepted.connect(self._save)
        box.rejected.connect(self.reject)
        layout.addWidget(box)

        for path in SETTINGS.favorites():
            self._append(path)

    def _append(self, path: str) -> None:
        is_dir = os.path.isdir(path)
        item = QListWidgetItem(
            icons.icon("folder" if is_dir else "archive-small"), path
        )
        if not os.path.exists(path):
            item.setForeground(QColor(theme.current().error))
            item.setToolTip("This location no longer exists.")
        self.list.addItem(item)

    def _add_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select a folder")
        if path:
            self._append(path)

    def _add_archive(self) -> None:
        path, _f = QFileDialog.getOpenFileName(
            self, "Select an archive", "", "All archives (*.rar *.zip *.7z);;All files (*)"
        )
        if path:
            self._append(path)

    def _remove(self) -> None:
        for item in self.list.selectedItems():
            self.list.takeItem(self.list.row(item))

    def _move(self, delta: int) -> None:
        row = self.list.currentRow()
        target = row + delta
        if row < 0 or not 0 <= target < self.list.count():
            return
        item = self.list.takeItem(row)
        self.list.insertItem(target, item)
        self.list.setCurrentRow(target)

    def _up(self) -> None:
        self._move(-1)

    def _down(self) -> None:
        self._move(1)

    def _save(self) -> None:
        SETTINGS.set_favorites(
            [self.list.item(i).text() for i in range(self.list.count())]
        )
        self.accept()


class PropertiesDialog(QDialog):
    """Per-item properties, for both disk files and archive members."""

    def __init__(
        self,
        parent,
        name: str,
        path: str,
        entry: Optional[ArchiveEntry] = None,
        archive: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{name} — Properties")
        self.setWindowIcon(icons.icon("info"))
        self.resize(430, 380)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(9)

        header = QHBoxLayout()
        icon_label = QLabel()
        icon_label.setPixmap(icons.pixmap("file" if entry and not entry.is_dir else "folder", 48))
        header.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignTop)
        title = QLabel(f"<b>{name}</b>")
        title.setWordWrap(True)
        header.addWidget(title, 1)
        layout.addLayout(header)

        group = QGroupBox("General")
        form = QFormLayout(group)
        form.setSpacing(4)

        if entry is not None:
            form.addRow("Location in archive", _selectable(entry.parent or "(root)"))
            form.addRow("Archive", _selectable(archive))
            form.addRow("Type", QLabel("Folder" if entry.is_dir else "File"))
            if not entry.is_dir:
                form.addRow("Size", QLabel(f"{format_size(entry.size)} bytes "
                                           f"({format_size_short(entry.size)})"))
                form.addRow(
                    "Packed size",
                    QLabel(f"{format_size(entry.packed_size)} bytes "
                           f"({format_size_short(entry.packed_size)})"),
                )
                form.addRow("Ratio", QLabel(f"{entry.ratio}%"))
                form.addRow("CRC32", _selectable(entry.crc or "-"))
            form.addRow(
                "Modified",
                QLabel(entry.mtime.strftime("%d %B %Y, %H:%M:%S") if entry.mtime else "-"),
            )
            form.addRow("Attributes", QLabel(entry.attributes or "-"))
            form.addRow("Host OS", QLabel(entry.host_os or "-"))
            form.addRow("Compression", QLabel(entry.method or "-"))
            form.addRow("Encrypted", QLabel("Yes" if entry.encrypted else "No"))
            if entry.link_target:
                form.addRow("Link target", _selectable(entry.link_target))
        else:
            form.addRow("Location", _selectable(os.path.dirname(path)))
            try:
                stat = os.stat(path, follow_symlinks=False)
                is_dir = os.path.isdir(path)
                form.addRow("Type", QLabel("Folder" if is_dir else "File"))
                if not is_dir:
                    form.addRow(
                        "Size",
                        QLabel(f"{format_size(stat.st_size)} bytes "
                               f"({format_size_short(stat.st_size)})"),
                    )
                form.addRow(
                    "Modified",
                    QLabel(datetime.fromtimestamp(stat.st_mtime)
                           .strftime("%d %B %Y, %H:%M:%S")),
                )
                form.addRow(
                    "Accessed",
                    QLabel(datetime.fromtimestamp(stat.st_atime)
                           .strftime("%d %B %Y, %H:%M:%S")),
                )
                import stat as stat_module

                form.addRow("Permissions", QLabel(stat_module.filemode(stat.st_mode)))
                form.addRow("Owner", QLabel(_owner(stat.st_uid, stat.st_gid)))
                if os.path.islink(path):
                    form.addRow("Symlink to", _selectable(os.readlink(path)))
                if is_dir:
                    form.addRow("Contains", QLabel(_folder_summary(path)))
            except OSError as exc:
                form.addRow("Error", QLabel(str(exc)))

        layout.addWidget(group)
        layout.addStretch(1)

        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        box.rejected.connect(self.reject)
        box.accepted.connect(self.accept)
        layout.addWidget(box)


class ReportDialog(QDialog):
    """WinRAR's Tools > Generate report."""

    def __init__(self, parent, info: ArchiveInfo) -> None:
        super().__init__(parent)
        self.setWindowTitle("Generate report")
        self.setWindowIcon(icons.icon("view"))
        self.resize(680, 520)
        self.info = info

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        row = QHBoxLayout()
        row.addWidget(QLabel("Format"))
        self.format_combo = QComboBox()
        self.format_combo.addItems(list(report_module.FORMATS.keys()))
        self.format_combo.currentIndexChanged.connect(self._refresh)
        row.addWidget(self.format_combo)
        self.folders_check = QCheckBox("Include folders")
        self.folders_check.setChecked(True)
        self.folders_check.toggled.connect(self._refresh)
        row.addWidget(self.folders_check)
        row.addStretch(1)
        layout.addLayout(row)

        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setFont(QFont("monospace", 8))
        self.preview.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(self.preview, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        copy = QPushButton("Copy to clipboard")
        copy.clicked.connect(self._copy)
        save = QPushButton("Save as...")
        save.setDefault(True)
        save.clicked.connect(self._save)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        for button in (copy, save, close):
            buttons.addWidget(button)
        layout.addLayout(buttons)

        self._refresh()

    def _generate(self) -> str:
        _ext, func = report_module.FORMATS[self.format_combo.currentText()]
        return func(self.info, self.folders_check.isChecked())

    def _refresh(self) -> None:
        self.preview.setPlainText(self._generate())

    def _copy(self) -> None:
        from PyQt6.QtWidgets import QApplication

        QApplication.clipboard().setText(self._generate())
        QMessageBox.information(self, "LinRAR", "Report copied to the clipboard.")

    def _save(self) -> None:
        label = self.format_combo.currentText()
        ext, _func = report_module.FORMATS[label]
        stem = os.path.splitext(os.path.basename(self.info.path))[0]
        default = os.path.join(
            os.path.dirname(self.info.path), f"{stem}-report.{ext}"
        )
        path, _f = QFileDialog.getSaveFileName(self, "Save report", default, label)
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(self._generate())
        except OSError as exc:
            QMessageBox.warning(self, "LinRAR", f"Cannot save the report.\n\n{exc}")
            return
        QMessageBox.information(self, "LinRAR", f"Report saved to:\n{path}")


def _selectable(text: str) -> QLabel:
    label = QLabel(text or "-")
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


def _owner(uid: int, gid: int) -> str:
    try:
        import grp
        import pwd

        user = pwd.getpwuid(uid).pw_name
        group = grp.getgrgid(gid).gr_name
        return f"{user}:{group}"
    except (ImportError, KeyError):
        return f"{uid}:{gid}"


def _folder_summary(path: str) -> str:
    files = folders = 0
    total = 0
    for root, dirs, names in os.walk(path):
        folders += len(dirs)
        files += len(names)
        for name in names:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
        if files > 20000:
            return f"{files}+ files (stopped counting)"
    return f"{files} files, {folders} folders, {format_size_short(total)}"
