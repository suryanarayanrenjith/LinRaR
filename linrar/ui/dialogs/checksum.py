"""Tools > Calculate checksums.

Shows every digest for every selected file at once, because the question is
almost never "what is the MD5"; it is "does this match what the download page
said", and the page could have said any of them.  Pasting the published value
into the box at the bottom marks the file that matches it.
"""

from __future__ import annotations

import os

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from ...core import hashes
from ...core.models import format_size_short
from .. import icons, theme


class ChecksumDialog(QDialog):
    """The results of a checksum run, with a comparison box."""

    def __init__(self, parent, results: list[hashes.FileDigest]) -> None:
        super().__init__(parent)
        self.setWindowTitle("Checksums")
        self.setWindowIcon(icons.icon("test"))
        self.resize(760, 460)
        self.results = results

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        readable = [r for r in results if r.ok]
        total = sum(r.size for r in readable)
        heading = QLabel(
            f"{len(readable)} file(s), {format_size_short(total)}"
            + (f", {len(results) - len(readable)} could not be read"
               if len(readable) != len(results) else "")
        )
        layout.addWidget(heading)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels(["File", "Checksum"])
        self.tree.setRootIsDecorated(True)
        self.tree.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.tree.setColumnWidth(0, 250)
        self.tree.header().setStretchLastSection(True)
        layout.addWidget(self.tree, 1)
        self._fill()

        compare_row = QHBoxLayout()
        compare_row.addWidget(QLabel("Compare with"))
        self.expected_edit = QLineEdit()
        self.expected_edit.setPlaceholderText(
            "Paste a published checksum (or a whole sha256sum line)"
        )
        self.expected_edit.setClearButtonEnabled(True)
        self.expected_edit.textChanged.connect(self._compare)
        compare_row.addWidget(self.expected_edit, 1)
        paste = QPushButton("Paste")
        paste.clicked.connect(self._paste)
        compare_row.addWidget(paste)
        layout.addLayout(compare_row)

        self.verdict = QLabel("")
        self.verdict.setWordWrap(True)
        layout.addWidget(self.verdict)

        buttons = QHBoxLayout()
        buttons.addWidget(QLabel("Copy or save as"))
        self.format_combo = QComboBox()
        self.format_combo.addItem("all algorithms", "")
        for algorithm in hashes.ALGORITHMS:
            self.format_combo.addItem(f"{algorithm}sum format", algorithm)
        buttons.addWidget(self.format_combo)
        copy = QPushButton("Copy")
        copy.clicked.connect(self._copy)
        save = QPushButton("Save...")
        save.clicked.connect(self._save)
        buttons.addWidget(copy)
        buttons.addWidget(save)
        buttons.addStretch(1)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        box.rejected.connect(self.reject)
        buttons.addWidget(box)
        layout.addLayout(buttons)

    # -- contents ----------------------------------------------------------

    def _fill(self) -> None:
        mono = QFont("monospace")
        mono.setPointSize(9)
        self._rows: dict[str, QTreeWidgetItem] = {}
        for entry in self.results:
            parent = QTreeWidgetItem(self.tree, [entry.name, ""])
            parent.setIcon(0, icons.icon("file"))
            self._rows[entry.name] = parent
            if not entry.ok:
                parent.setText(1, f"could not be read: {entry.error}")
                parent.setForeground(1, QColor(theme.current().error))
                continue
            parent.setText(1, format_size_short(entry.size))
            for algorithm in hashes.ALGORITHMS:
                value = entry.get(algorithm)
                if not value:
                    continue
                child = QTreeWidgetItem(parent, [algorithm, value])
                child.setFont(1, mono)
                child.setTextAlignment(0, Qt.AlignmentFlag.AlignRight)
            parent.setExpanded(len(self.results) <= 4)

    # -- comparison --------------------------------------------------------

    def _paste(self) -> None:
        self.expected_edit.setText(QApplication.clipboard().text().strip())

    def _compare(self) -> None:
        text = self.expected_edit.text().strip()
        for item in self._rows.values():
            item.setForeground(0, QColor(theme.current().text))
        if not text:
            self.verdict.setText("")
            return
        verdicts = hashes.compare(self.results, text)
        if not verdicts:
            self.verdict.setText(
                "No file here has that checksum."
            )
            self.verdict.setObjectName("Warning")
        else:
            names = ", ".join(f"{n} ({a})" for n, a in verdicts.items())
            self.verdict.setText(f"Matches: {names}")
            self.verdict.setObjectName("Success")
            for name in verdicts:
                item = self._rows.get(name)
                if item is not None:
                    item.setForeground(0, QColor(theme.current().ok))
                    item.setExpanded(True)
        self.verdict.style().unpolish(self.verdict)
        self.verdict.style().polish(self.verdict)

    # -- output ------------------------------------------------------------

    def _text(self) -> str:
        algorithm = self.format_combo.currentData()
        if algorithm:
            return hashes.as_text(self.results, algorithm)
        return hashes.as_table(self.results, hashes.ALGORITHMS)

    def _copy(self) -> None:
        QApplication.clipboard().setText(self._text())
        QMessageBox.information(self, "LinRAR", "Checksums copied to the clipboard.")

    def _save(self) -> None:
        algorithm = self.format_combo.currentData()
        suffix = (algorithm.replace("-", "").lower() + "sum") if algorithm else "txt"
        start = os.path.join(
            os.path.dirname(self.results[0].path) if self.results else
            os.path.expanduser("~"),
            f"checksums.{suffix}",
        )
        path, _filter = QFileDialog.getSaveFileName(self, "Save checksums", start)
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(self._text())
        except OSError as exc:
            QMessageBox.warning(self, "LinRAR", f"Cannot save it.\n\n{exc}")
            return
        QMessageBox.information(self, "LinRAR", f"Saved to:\n{path}")
