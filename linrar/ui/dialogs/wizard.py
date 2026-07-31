"""The step-by-step Wizard, matching WinRAR's Tools > Wizard."""

from __future__ import annotations

import os
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ...core.registry import detect_format
from ...core.models import ArchiveFormat
from .. import icons

TASK_UNPACK = "unpack"
TASK_CREATE = "create"
TASK_ADD = "add"


class WizardDialog(QDialog):
    """Guides the user through unpacking, creating or updating an archive.

    On completion, :attr:`task` says what was chosen and the accompanying
    attributes carry the collected paths; the main window then opens the normal
    dialog for that operation.
    """

    def __init__(self, parent=None, current_folder: str = "", archive: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle("Wizard")
        self.setWindowIcon(icons.icon("wizard"))
        self.setModal(True)
        self.resize(520, 400)

        self.current_folder = current_folder or os.path.expanduser("~")
        self.task: Optional[str] = None
        self.archive_path: str = archive
        self.files: list[str] = []
        self.destination: str = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        banner = QWidget()
        banner.setObjectName("Banner")
        banner_layout = QHBoxLayout(banner)
        banner_layout.setContentsMargins(14, 10, 14, 10)
        icon_label = QLabel()
        icon_label.setPixmap(icons.pixmap("wizard", 40))
        banner_layout.addWidget(icon_label)
        self.heading = QLabel()
        heading_font = QFont()
        heading_font.setBold(True)
        heading_font.setPointSize(11)
        self.heading.setFont(heading_font)
        banner_layout.addWidget(self.heading, 1)
        root.addWidget(banner)

        self.pages = QStackedWidget()
        self.pages.addWidget(self._page_task())
        self.pages.addWidget(self._page_archive())
        self.pages.addWidget(self._page_files())
        self.pages.addWidget(self._page_destination())
        self.pages.addWidget(self._page_summary())
        root.addWidget(self.pages, 1)

        nav = QHBoxLayout()
        nav.setContentsMargins(12, 10, 12, 12)
        nav.addStretch(1)
        self.back_button = QPushButton("< Back")
        self.back_button.clicked.connect(self._back)
        self.next_button = QPushButton("Next >")
        self.next_button.setDefault(True)
        self.next_button.clicked.connect(self._next)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        for button in (self.back_button, self.next_button, cancel):
            nav.addWidget(button)
        root.addLayout(nav)

        self._history: list[int] = []
        self._show_page(0)

    # -- pages -------------------------------------------------------------

    def _page_task(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)
        layout.addWidget(QLabel("What would you like to do?"))

        self.task_group = QButtonGroup(self)
        self.task_unpack = QRadioButton("Unpack an archive")
        self.task_create = QRadioButton("Create a new archive")
        self.task_add = QRadioButton("Add files to an existing archive")
        self.task_unpack.setChecked(True)
        for button in (self.task_unpack, self.task_create, self.task_add):
            self.task_group.addButton(button)
            layout.addWidget(button)

        hint = QLabel(
            "The Wizard walks through the common tasks one step at a time. "
            "Everything here is also available directly from the toolbar."
        )
        hint.setWordWrap(True)
        hint.setObjectName("Hint")
        layout.addSpacing(8)
        layout.addWidget(hint)
        layout.addStretch(1)
        return page

    def _page_archive(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)
        self.archive_prompt = QLabel("Choose the archive.")
        self.archive_prompt.setWordWrap(True)
        layout.addWidget(self.archive_prompt)

        row = QHBoxLayout()
        self.archive_edit = QLineEdit(self.archive_path)
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._browse_archive)
        row.addWidget(self.archive_edit, 1)
        row.addWidget(browse)
        layout.addLayout(row)
        layout.addStretch(1)
        return page

    def _page_files(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)
        layout.addWidget(QLabel("Choose the files and folders to include."))

        self.files_list = QListWidget()
        layout.addWidget(self.files_list, 1)

        row = QHBoxLayout()
        add_files = QPushButton("Add files...")
        add_files.clicked.connect(self._add_files)
        add_folder = QPushButton("Add folder...")
        add_folder.clicked.connect(self._add_folder)
        remove = QPushButton("Remove")
        remove.clicked.connect(self._remove_files)
        for button in (add_files, add_folder, remove):
            row.addWidget(button)
        row.addStretch(1)
        layout.addLayout(row)
        return page

    def _page_destination(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)
        self.destination_prompt = QLabel("Where should the files go?")
        layout.addWidget(self.destination_prompt)

        row = QHBoxLayout()
        self.destination_edit = QLineEdit(self.current_folder)
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._browse_destination)
        row.addWidget(self.destination_edit, 1)
        row.addWidget(browse)
        layout.addLayout(row)

        self.subfolder_check = QCheckBox(
            "Put the contents in a folder named after the archive"
        )
        layout.addWidget(self.subfolder_check)
        layout.addStretch(1)
        return page

    def _page_summary(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)
        layout.addWidget(QLabel("Ready to go. Review the details below."))
        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        self.summary_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.summary_label.setObjectName("Card")
        layout.addWidget(self.summary_label, 1)
        return page

    # -- navigation --------------------------------------------------------

    @property
    def selected_task(self) -> str:
        if self.task_create.isChecked():
            return TASK_CREATE
        if self.task_add.isChecked():
            return TASK_ADD
        return TASK_UNPACK

    def _flow(self) -> list[int]:
        """The page sequence for the chosen task."""
        task = self.selected_task
        if task == TASK_UNPACK:
            return [0, 1, 3, 4]
        if task == TASK_CREATE:
            return [0, 2, 4]
        return [0, 1, 2, 4]

    def _show_page(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        headings = {
            0: "Choose a task",
            1: "Select the archive",
            2: "Select the files",
            3: "Choose the destination",
            4: "Summary",
        }
        self.heading.setText(headings.get(index, ""))
        self.back_button.setEnabled(bool(self._history))

        flow = self._flow()
        is_last = index == flow[-1]
        self.next_button.setText("Finish" if is_last else "Next >")

        if index == 1:
            self.archive_prompt.setText(
                "Choose the archive to unpack."
                if self.selected_task == TASK_UNPACK
                else "Choose the archive to add files to."
            )
        if index == 3:
            self.destination_prompt.setText("Where should the files be extracted?")
        if index == 4:
            self.summary_label.setText(self._summary_text())

    def _summary_text(self) -> str:
        task = self.selected_task
        if task == TASK_UNPACK:
            target = self.destination_edit.text()
            if self.subfolder_check.isChecked():
                stem = os.path.splitext(
                    os.path.basename(self.archive_edit.text())
                )[0]
                target = os.path.join(target, stem)
            return (
                f"<b>Unpack an archive</b><br><br>"
                f"Archive: {self.archive_edit.text()}<br>"
                f"Extract to: {target}<br><br>"
                "The extraction dialog will open so you can adjust the "
                "overwrite options."
            )
        files = "<br>".join(
            f"&nbsp;&nbsp;{self.files_list.item(i).text()}"
            for i in range(min(self.files_list.count(), 8))
        )
        more = (
            f"<br>&nbsp;&nbsp;... and {self.files_list.count() - 8} more"
            if self.files_list.count() > 8
            else ""
        )
        if task == TASK_CREATE:
            return (
                f"<b>Create a new archive</b><br><br>"
                f"Files ({self.files_list.count()}):<br>{files}{more}<br><br>"
                "The archive dialog will open so you can choose the name, "
                "format and compression."
            )
        return (
            f"<b>Add files to an archive</b><br><br>"
            f"Archive: {self.archive_edit.text()}<br>"
            f"Files ({self.files_list.count()}):<br>{files}{more}"
        )

    def _next(self) -> None:
        index = self.pages.currentIndex()
        if not self._validate(index):
            return
        flow = self._flow()
        if index == flow[-1]:
            self._finish()
            return
        position = flow.index(index) if index in flow else 0
        self._history.append(index)
        self._show_page(flow[position + 1])

    def _back(self) -> None:
        if self._history:
            self._show_page(self._history.pop())

    def _validate(self, index: int) -> bool:
        if index == 1:
            path = self.archive_edit.text().strip()
            if not path or not os.path.isfile(path):
                QMessageBox.warning(self, "Wizard", "Choose an existing archive.")
                return False
            if detect_format(path) is ArchiveFormat.UNKNOWN:
                QMessageBox.warning(
                    self, "Wizard", "That file is not a recognised archive."
                )
                return False
        if index == 2 and self.files_list.count() == 0:
            QMessageBox.warning(self, "Wizard", "Add at least one file or folder.")
            return False
        if index == 3:
            path = self.destination_edit.text().strip()
            if not path:
                QMessageBox.warning(self, "Wizard", "Choose a destination folder.")
                return False
        return True

    def _finish(self) -> None:
        self.task = self.selected_task
        self.archive_path = self.archive_edit.text().strip()
        self.files = [
            self.files_list.item(i).text() for i in range(self.files_list.count())
        ]
        destination = self.destination_edit.text().strip()
        if self.subfolder_check.isChecked() and self.task == TASK_UNPACK:
            stem = os.path.splitext(os.path.basename(self.archive_path))[0]
            destination = os.path.join(destination, stem)
        self.destination = destination
        self.accept()

    # -- browsing ----------------------------------------------------------

    def _browse_archive(self) -> None:
        path, _f = QFileDialog.getOpenFileName(
            self,
            "Select an archive",
            self.current_folder,
            "All archives (*.rar *.zip *.7z *.tar *.gz *.bz2 *.xz);;All files (*)",
        )
        if path:
            self.archive_edit.setText(path)

    def _browse_destination(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Select a destination folder", self.destination_edit.text()
        )
        if path:
            self.destination_edit.setText(path)

    def _add_files(self) -> None:
        paths, _f = QFileDialog.getOpenFileNames(
            self, "Select files", self.current_folder
        )
        for path in paths:
            self.files_list.addItem(path)

    def _add_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Select a folder", self.current_folder
        )
        if path:
            self.files_list.addItem(path)

    def _remove_files(self) -> None:
        for item in self.files_list.selectedItems():
            self.files_list.takeItem(self.files_list.row(item))
