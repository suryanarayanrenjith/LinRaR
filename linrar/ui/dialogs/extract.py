"""The "Extraction path and options" dialog."""

from __future__ import annotations

import os
from typing import Optional

from PyQt6.QtCore import QDir, Qt
from PyQt6.QtGui import QFileSystemModel  # moved out of QtWidgets in Qt 6
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QTabWidget,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from ...core.models import ExtractOptions, ExtractUpdateMode, OverwriteMode
from ...core import elevation
from ...core.settings import SETTINGS
from .. import icons
from .password import PasswordDialog


class ExtractDialog(QDialog):
    """Destination picker plus WinRAR's update/overwrite/miscellaneous options."""

    def __init__(
        self,
        parent=None,
        archive_name: str = "",
        destination: str = "",
        members: Optional[list[str]] = None,
        password: Optional[str] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Extraction path and options")
        self.setWindowIcon(icons.icon("extract-to"))
        self.setModal(True)
        self.resize(600, 480)

        self.members = members or []
        self._password = password

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        if archive_name:
            title = QLabel(f"Extract from  <b>{os.path.basename(archive_name)}</b>")
            root.addWidget(title)

        root.addWidget(QLabel("Destination path (will be created if it does not exist)"))
        self.path_combo = QComboBox()
        self.path_combo.setEditable(True)
        history = [p for p in SETTINGS.history() if p]
        start = destination or SETTINGS.get("places/extract_folder")
        self.path_combo.addItem(start)
        for entry in history:
            if entry != start:
                self.path_combo.addItem(entry)
        self.path_combo.setCurrentText(start)
        self.path_combo.currentTextChanged.connect(self._on_path_typed)
        root.addWidget(self.path_combo)

        body = QHBoxLayout()
        body.setSpacing(10)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_general(), "General")
        self.tabs.addTab(self._build_advanced(), "Advanced")
        body.addWidget(self.tabs, 0)

        tree_box = QVBoxLayout()
        tree_box.setSpacing(4)
        self.tree = QTreeView()
        self.fs_model = QFileSystemModel(self)
        self.fs_model.setRootPath("")
        self.fs_model.setFilter(
            QDir.Filter.AllDirs | QDir.Filter.NoDotAndDotDot | QDir.Filter.Drives
        )
        self.tree.setModel(self.fs_model)
        for column in range(1, self.fs_model.columnCount()):
            self.tree.hideColumn(column)
        self.tree.setHeaderHidden(True)
        self.tree.clicked.connect(self._on_tree_clicked)
        tree_box.addWidget(self.tree, 1)

        tree_buttons = QHBoxLayout()
        new_folder = QPushButton("New folder")
        new_folder.clicked.connect(self._new_folder)
        display = QPushButton("Display")
        display.clicked.connect(self._reveal_current)
        tree_buttons.addWidget(display)
        tree_buttons.addWidget(new_folder)
        tree_buttons.addStretch(1)
        tree_box.addLayout(tree_buttons)
        body.addLayout(tree_box, 1)

        root.addLayout(body, 1)

        buttons = QHBoxLayout()
        self.save_button = QPushButton("Save settings")
        self.save_button.clicked.connect(self._save_settings)
        buttons.addWidget(self.save_button)
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

        self._reveal_current()

    # -- tabs --------------------------------------------------------------

    def _build_general(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(9, 9, 9, 9)
        layout.setSpacing(8)

        update_group = QGroupBox("Update mode")
        update_layout = QVBoxLayout(update_group)
        update_layout.setSpacing(3)
        self.update_group = QButtonGroup(self)
        self.update_replace = QRadioButton("Extract and replace files")
        self.update_update = QRadioButton("Extract and update files")
        self.update_freshen = QRadioButton("Freshen existing files only")
        # "Save settings" persists these, so start from the saved values.
        saved_update = SETTINGS.get("extract/update")
        {
            ExtractUpdateMode.EXTRACT_UPDATE.value: self.update_update,
            ExtractUpdateMode.FRESHEN.value: self.update_freshen,
        }.get(saved_update, self.update_replace).setChecked(True)
        for button in (self.update_replace, self.update_update, self.update_freshen):
            self.update_group.addButton(button)
            update_layout.addWidget(button)
        layout.addWidget(update_group)

        overwrite_group = QGroupBox("Overwrite mode")
        overwrite_layout = QVBoxLayout(overwrite_group)
        overwrite_layout.setSpacing(3)
        self.overwrite_group = QButtonGroup(self)
        self.overwrite_ask = QRadioButton("Ask before overwrite")
        self.overwrite_yes = QRadioButton("Overwrite without prompt")
        self.overwrite_skip = QRadioButton("Skip existing files")
        self.overwrite_rename = QRadioButton("Rename automatically")
        saved_overwrite = SETTINGS.get("extract/overwrite")
        {
            OverwriteMode.OVERWRITE.value: self.overwrite_yes,
            OverwriteMode.SKIP.value: self.overwrite_skip,
            OverwriteMode.RENAME.value: self.overwrite_rename,
        }.get(saved_overwrite, self.overwrite_ask).setChecked(True)
        for button in (
            self.overwrite_ask,
            self.overwrite_yes,
            self.overwrite_skip,
            self.overwrite_rename,
        ):
            self.overwrite_group.addButton(button)
            overwrite_layout.addWidget(button)
        layout.addWidget(overwrite_group)

        misc_group = QGroupBox("Miscellaneous")
        misc_layout = QVBoxLayout(misc_group)
        misc_layout.setSpacing(3)
        self.subfolders_check = QCheckBox("Extract archives to subfolders")
        self.subfolders_check.setChecked(bool(SETTINGS.get("extract/subfolders")))
        self.keep_broken_check = QCheckBox("Keep broken files")
        self.keep_broken_check.setChecked(bool(SETTINGS.get("extract/keep_broken")))
        self.open_check = QCheckBox("Display files in the file manager")
        self.open_check.setChecked(bool(SETTINGS.get("extract/open_when_done")))
        for widget in (
            self.subfolders_check,
            self.keep_broken_check,
            self.open_check,
        ):
            misc_layout.addWidget(widget)
        layout.addWidget(misc_group)

        layout.addStretch(1)
        return page

    def _build_advanced(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(9, 9, 9, 9)
        layout.setSpacing(8)

        paths_group = QGroupBox("File paths")
        paths_layout = QVBoxLayout(paths_group)
        self.full_paths = QRadioButton("Extract with full paths")
        self.no_paths = QRadioButton("Extract without paths")
        self.no_paths.setChecked(bool(SETTINGS.get("extract/no_paths")))
        self.full_paths.setChecked(not self.no_paths.isChecked())
        paths_layout.addWidget(self.full_paths)
        paths_layout.addWidget(self.no_paths)
        layout.addWidget(paths_group)

        password_group = QGroupBox("Password")
        password_layout = QVBoxLayout(password_group)
        button = QPushButton("Set password...")
        button.clicked.connect(self._set_password)
        password_layout.addWidget(button, 0, Qt.AlignmentFlag.AlignLeft)
        self.password_state = QLabel(
            "Password set" if self._password else "No password set"
        )
        self.password_state.setObjectName("Hint")
        password_layout.addWidget(self.password_state)
        layout.addWidget(password_group)

        layout.addStretch(1)
        return page

    # -- behaviour ---------------------------------------------------------

    def _on_tree_clicked(self, index) -> None:
        path = self.fs_model.filePath(index)
        if path:
            self.path_combo.blockSignals(True)
            self.path_combo.setCurrentText(path)
            self.path_combo.blockSignals(False)

    def _on_path_typed(self, text: str) -> None:
        if os.path.isdir(text):
            index = self.fs_model.index(text)
            if index.isValid():
                self.tree.setCurrentIndex(index)
                self.tree.scrollTo(index)

    def _reveal_current(self) -> None:
        path = self.path_combo.currentText()
        if os.path.isdir(path):
            index = self.fs_model.index(path)
            if index.isValid():
                self.tree.expand(index)
                self.tree.setCurrentIndex(index)
                self.tree.scrollTo(index)

    def _new_folder(self) -> None:
        parent = self.path_combo.currentText()
        if not os.path.isdir(parent):
            QMessageBox.warning(
                self, "LinRAR", "Select an existing folder first."
            )
            return
        name, ok = QInputDialog.getText(self, "New folder", "Folder name:")
        if not ok or not name.strip():
            return
        target = os.path.join(parent, name.strip())
        try:
            os.makedirs(target, exist_ok=False)
        except OSError as exc:
            QMessageBox.warning(self, "LinRAR", f"Cannot create the folder.\n\n{exc}")
            return
        self.path_combo.setCurrentText(target)
        self._reveal_current()

    def _set_password(self) -> None:
        result = PasswordDialog.ask(self)
        if result is None:
            return
        self._password = result[0] or None
        self.password_state.setText(
            "Password set" if self._password else "No password set"
        )

    def _save_settings(self) -> None:
        self._remember()
        SETTINGS.set("places/extract_folder", self.path_combo.currentText())
        SETTINGS.sync()
        QMessageBox.information(
            self, "LinRAR", "These options are now the defaults for extraction."
        )

    def _show_help(self) -> None:
        QMessageBox.information(
            self,
            "Help",
            "Extraction path and options\n\n"
            "Type a destination folder or pick one from the tree, then press "
            "OK.\n\n"
            "- Update mode decides which files are written.\n"
            "- Overwrite mode decides what happens when a file already "
            "exists.\n"
            "- 'Extract archives to subfolders' puts the contents into a "
            "folder named after the archive.",
        )

    def _accept(self) -> None:
        path = self.path_combo.currentText().strip()
        if not path:
            QMessageBox.warning(self, "LinRAR", "Please choose a destination folder.")
            return
        path = os.path.abspath(os.path.expanduser(path))
        if os.path.exists(path) and not os.path.isdir(path):
            QMessageBox.warning(
                self, "LinRAR", f"The destination is not a folder:\n{path}"
            )
            return
        if not os.path.isdir(path):
            reply = QMessageBox.question(
                self,
                "LinRAR",
                f"The folder does not exist:\n{path}\n\nCreate it?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            try:
                os.makedirs(path, exist_ok=True)
            except OSError as exc:
                # A protected parent is not a refusal: the main window offers
                # to finish the job with administrator rights.
                if not elevation.available() and not elevation.is_root():
                    QMessageBox.warning(
                        self, "LinRAR", f"Cannot create the folder.\n\n{exc}"
                    )
                    return
        if (
            os.path.isdir(path)
            and not os.access(path, os.W_OK)
            and not elevation.available()
            and not elevation.is_root()
        ):
            QMessageBox.warning(
                self,
                "LinRAR",
                f"The destination folder is not writable:\n{path}\n\n"
                "No way to obtain administrator rights was found either.",
            )
            return

        SETTINGS.set("places/extract_folder", path)
        SETTINGS.push_history(path)
        self._remember()
        self.accept()

    def _remember(self) -> None:
        """Keep this run's choices as the starting point for the next one."""
        SETTINGS.set("extract/overwrite", self.overwrite_mode.value)
        SETTINGS.set("extract/update", self.update_mode.value)
        SETTINGS.set("extract/no_paths", self.no_paths.isChecked())
        SETTINGS.set("extract/keep_broken", self.keep_broken_check.isChecked())
        SETTINGS.set("extract/subfolders", self.subfolders_check.isChecked())
        SETTINGS.set("extract/open_when_done", self.open_check.isChecked())
        SETTINGS.sync()

    # -- result ------------------------------------------------------------

    @property
    def update_mode(self) -> ExtractUpdateMode:
        if self.update_update.isChecked():
            return ExtractUpdateMode.EXTRACT_UPDATE
        if self.update_freshen.isChecked():
            return ExtractUpdateMode.FRESHEN
        return ExtractUpdateMode.EXTRACT_REPLACE

    @property
    def overwrite_mode(self) -> OverwriteMode:
        if self.overwrite_yes.isChecked():
            return OverwriteMode.OVERWRITE
        if self.overwrite_skip.isChecked():
            return OverwriteMode.SKIP
        if self.overwrite_rename.isChecked():
            return OverwriteMode.RENAME
        return OverwriteMode.ASK

    @property
    def extract_to_subfolders(self) -> bool:
        return self.subfolders_check.isChecked()

    def options(self) -> ExtractOptions:
        return ExtractOptions(
            destination=os.path.abspath(
                os.path.expanduser(self.path_combo.currentText().strip())
            ),
            update_mode=self.update_mode,
            overwrite_mode=self.overwrite_mode,
            keep_broken=self.keep_broken_check.isChecked(),
            extract_to_subfolders=self.subfolders_check.isChecked(),
            no_paths=self.no_paths.isChecked(),
            open_when_done=self.open_check.isChecked(),
            password=self._password,
            members=list(self.members),
        )
