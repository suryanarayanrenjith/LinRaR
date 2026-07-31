"""The "Convert archives" dialog (batch format conversion)."""

from __future__ import annotations

import os
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from ...core.convert import ConvertOptions, ConvertResult, convert_many
from ...core.models import CompressionMethod, CompressOptions
from ...core.passwords import PASSWORDS
from ...core.registry import REGISTRY
from ...core.tasks import Task
from .. import icons, theme
from .progress import ProgressDialog


class ConvertDialog(QDialog):
    """Pick archives, choose a target format, convert them all."""

    def __init__(self, parent=None, sources: Optional[list[str]] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Convert archives")
        self.setWindowIcon(icons.icon("convert"))
        self.resize(640, 520)

        self._results: list[ConvertResult] = []
        self._task: Optional[Task] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        layout.addWidget(QLabel("Archives to convert"))
        self.list = QTreeWidget()
        self.list.setColumnCount(3)
        self.list.setHeaderLabels(["Archive", "Folder", "Result"])
        self.list.setRootIsDecorated(False)
        self.list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        header = self.list.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.list.setColumnWidth(0, 200)
        self.list.setColumnWidth(1, 240)
        layout.addWidget(self.list, 1)

        row = QHBoxLayout()
        add = QPushButton("Add archives...")
        add.clicked.connect(self._add)
        add_folder = QPushButton("Add folder...")
        add_folder.clicked.connect(self._add_folder)
        remove = QPushButton("Remove")
        remove.clicked.connect(self._remove)
        row.addWidget(add)
        row.addWidget(add_folder)
        row.addWidget(remove)
        row.addStretch(1)
        layout.addLayout(row)

        settings = QGroupBox("Conversion settings")
        form = QFormLayout(settings)

        self.format_combo = QComboBox()
        for fmt in REGISTRY.creatable_formats():
            self.format_combo.addItem(fmt.label, fmt)
        form.addRow("Convert to", self.format_combo)

        self.method_combo = QComboBox()
        for method in CompressionMethod:
            self.method_combo.addItem(method.label, method)
        self.method_combo.setCurrentIndex(int(CompressionMethod.NORMAL))
        form.addRow("Compression", self.method_combo)

        output_row = QHBoxLayout()
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("(beside each original archive)")
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._browse_output)
        output_row.addWidget(self.output_edit, 1)
        output_row.addWidget(browse)
        form.addRow("Output folder", output_row)

        self.delete_check = QCheckBox("Delete the original archive afterwards")
        form.addRow(self.delete_check)
        self.keep_going_check = QCheckBox("Continue if an archive fails")
        self.keep_going_check.setChecked(True)
        form.addRow(self.keep_going_check)
        self.passwords_check = QCheckBox(
            "Try saved passwords on encrypted archives"
        )
        self.passwords_check.setChecked(True)
        form.addRow(self.passwords_check)

        layout.addWidget(settings)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.convert_button = QPushButton("Convert")
        self.convert_button.setDefault(True)
        self.convert_button.clicked.connect(self._convert)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        buttons.addWidget(self.convert_button)
        buttons.addWidget(close)
        layout.addLayout(buttons)

        for path in sources or []:
            self._append(path)

    # -- list management ---------------------------------------------------

    def _append(self, path: str) -> None:
        existing = {self._path_of(i) for i in range(self.list.topLevelItemCount())}
        if path in existing:
            return
        item = QTreeWidgetItem(
            self.list,
            [os.path.basename(path), os.path.dirname(path), ""],
        )
        item.setIcon(0, icons.icon("archive-small"))
        item.setData(0, Qt.ItemDataRole.UserRole, path)

    def _path_of(self, index: int) -> str:
        item = self.list.topLevelItem(index)
        return item.data(0, Qt.ItemDataRole.UserRole) if item else ""

    def _paths(self) -> list[str]:
        return [self._path_of(i) for i in range(self.list.topLevelItemCount())]

    def _add(self) -> None:
        paths, _f = QFileDialog.getOpenFileNames(
            self,
            "Select archives",
            "",
            "All archives (*.rar *.zip *.7z *.tar *.gz *.bz2 *.xz);;All files (*)",
        )
        for path in paths:
            self._append(path)

    def _add_folder(self) -> None:
        from ...core.registry import looks_like_archive

        folder = QFileDialog.getExistingDirectory(self, "Select a folder")
        if not folder:
            return
        found = 0
        for root, _dirs, names in os.walk(folder):
            for name in sorted(names):
                if looks_like_archive(name):
                    self._append(os.path.join(root, name))
                    found += 1
        if not found:
            QMessageBox.information(
                self, "LinRAR", "No archives were found in that folder."
            )

    def _remove(self) -> None:
        for item in self.list.selectedItems():
            self.list.takeTopLevelItem(self.list.indexOfTopLevelItem(item))

    def _browse_output(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select an output folder")
        if folder:
            self.output_edit.setText(folder)

    # -- conversion --------------------------------------------------------

    def _convert(self) -> None:
        sources = self._paths()
        if not sources:
            QMessageBox.information(
                self, "LinRAR", "Add at least one archive to convert."
            )
            return

        output = self.output_edit.text().strip()
        if output and not os.path.isdir(output):
            QMessageBox.warning(
                self, "LinRAR", f"The output folder does not exist:\n{output}"
            )
            return

        options = ConvertOptions(
            target_format=self.format_combo.currentData(),
            output_folder=output,
            delete_original=self.delete_check.isChecked(),
            keep_going=self.keep_going_check.isChecked(),
            compress=CompressOptions(
                method=self.method_combo.currentData() or CompressionMethod.NORMAL
            ),
            passwords=(
                [e.password for e in PASSWORDS.load() if e.password]
                if self.passwords_check.isChecked()
                else []
            ),
        )

        task = Task(
            lambda ctx: convert_many(sources, options, ctx), "Converting archives", self
        )
        self._task = task
        dialog = ProgressDialog(self, task, "Converting archives")
        dialog.exec()
        if dialog.backgrounded and task.isRunning():
            # Keep the worker alive and fill the results in when it finishes.
            self.convert_button.setEnabled(False)
            task.succeeded.connect(lambda _r: self._on_task_done(task))
            task.failed.connect(lambda _e: self._on_task_done(task))
            return
        task.wait(5000)
        self._on_task_done(task)

    def _on_task_done(self, task: Task) -> None:
        self._task = None
        self.convert_button.setEnabled(True)
        results = task.result if isinstance(task.result, list) else []
        self._show_results(results)
        if task.error is not None and not results:
            QMessageBox.critical(self, "LinRAR", task.error.message)

    def closeEvent(self, event) -> None:
        if self._task is not None and self._task.isRunning():
            self._task.cancel()
            self._task.wait(3000)
            self._task = None
        super().closeEvent(event)

    def _show_results(self, results: list[ConvertResult]) -> None:
        by_source = {r.source: r for r in results}
        succeeded = failed = 0
        for index in range(self.list.topLevelItemCount()):
            item = self.list.topLevelItem(index)
            path = item.data(0, Qt.ItemDataRole.UserRole)
            result = by_source.get(path)
            if result is None:
                item.setText(2, "Skipped")
                item.setForeground(2, QColor(theme.current().warn))
                continue
            item.setText(2, result.message)
            if result.ok:
                succeeded += 1
                item.setForeground(2, QColor(theme.current().ok))
            else:
                failed += 1
                item.setForeground(2, QColor(theme.current().error))

        if results:
            QMessageBox.information(
                self,
                "Convert archives",
                f"Finished.\n\nConverted: {succeeded}\nFailed: {failed}",
            )
