"""The results of a text search: what was found, and where.

Find has two answers, and they want different windows.  A name mask filters
the listing in place; the file list is already the right shape for that.  A
text search produces something the listing cannot show at all: several hits
inside one file, each with its line.  So it gets a window of its own, grouped
by file, with the file names it found ready to act on.
"""

from __future__ import annotations


from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from ...core.search import SearchQuery, SearchResult
from .. import icons

_NAME_ROLE = Qt.ItemDataRole.UserRole


class SearchResultsDialog(QDialog):
    """Groups every hit under the file it was found in."""

    #: Emitted with the name the user chose (a path on disk, or a member name
    #: inside the archive) when they ask to be taken to it.
    goTo = pyqtSignal(str)

    def __init__(
        self,
        parent,
        query: SearchQuery,
        result: SearchResult,
        where: str,
        in_archive: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Search results")
        self.setWindowIcon(icons.icon("find"))
        self.resize(760, 520)

        self.query = query
        self.result = result
        self._in_archive = in_archive

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        layout.addWidget(self._header(where))

        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["File", "Line", "Text"])
        self.tree.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.tree.setColumnWidth(0, 300)
        self.tree.setColumnWidth(1, 60)
        self.tree.header().setStretchLastSection(True)
        self.tree.itemDoubleClicked.connect(self._on_double_click)
        layout.addWidget(self.tree, 1)

        buttons = QHBoxLayout()
        self.goto_button = QPushButton("Go to file")
        self.goto_button.setIcon(icons.icon("find"))
        self.goto_button.setToolTip(
            "Show the selected file in the main window"
        )
        self.goto_button.clicked.connect(self._go_to_selected)
        copy = QPushButton("Copy list")
        copy.clicked.connect(self._copy)
        buttons.addWidget(self.goto_button)
        buttons.addWidget(copy)
        buttons.addStretch(1)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        box.rejected.connect(self.reject)
        buttons.addWidget(box)
        layout.addLayout(buttons)

        self._fill()

    # -- construction ------------------------------------------------------

    def _header(self, where: str) -> QLabel:
        files = len(self.result.found_names)
        hits = sum(1 for m in self.result.matches if not m.skipped)
        skipped = sum(1 for m in self.result.matches if m.skipped)

        if not hits:
            text = (
                f"No file in {where} contains '{self.query.text}'.\n"
                f"{self.result.searched} file(s) were read."
            )
        else:
            text = (
                f"'{self.query.text}' found {hits} time(s) in {files} file(s), "
                f"out of {self.result.searched} read in {where}."
            )
        if skipped:
            text += f"  {skipped} file(s) could not be searched."
        if self.result.cancelled:
            text += "  The search was stopped early, so this list is partial."

        label = QLabel(text)
        label.setWordWrap(True)
        return label

    def _fill(self) -> None:
        """One top-level row per file, its hits beneath it."""
        mono = QFont("monospace")
        mono.setPointSize(9)
        grouped: dict[str, list] = {}
        for match in self.result.matches:
            grouped.setdefault(match.name, []).append(match)

        for name, matches in grouped.items():
            hits = [m for m in matches if not m.skipped]
            caption = f"{name}   ({len(hits)})" if hits else name
            parent = QTreeWidgetItem(self.tree, [caption, "", ""])
            parent.setIcon(0, icons.icon(
                "archive-small" if self._in_archive else "file"
            ))
            parent.setData(0, _NAME_ROLE, name)
            for match in matches:
                if match.skipped:
                    child = QTreeWidgetItem(parent, ["", "", match.skipped])
                    child.setDisabled(True)
                    continue
                child = QTreeWidgetItem(
                    parent,
                    ["", str(match.line_number or ""), match.line],
                )
                child.setFont(2, mono)
                child.setData(0, _NAME_ROLE, name)
            parent.setExpanded(len(grouped) <= 12)

        self.goto_button.setEnabled(bool(grouped))
        if self.tree.topLevelItemCount():
            self.tree.setCurrentItem(self.tree.topLevelItem(0))

    # -- actions -----------------------------------------------------------

    def _selected_name(self) -> str:
        item = self.tree.currentItem()
        while item is not None:
            name = item.data(0, _NAME_ROLE)
            if name:
                return str(name)
            item = item.parent()
        return ""

    def _on_double_click(self, item: QTreeWidgetItem, _column: int) -> None:
        self._go_to_selected()

    def _go_to_selected(self) -> None:
        name = self._selected_name()
        if name:
            self.goTo.emit(name)

    def _copy(self) -> None:
        from PyQt6.QtWidgets import QApplication

        lines = []
        for match in self.result.matches:
            if match.skipped:
                lines.append(f"{match.name}: {match.skipped}")
            elif match.line_number:
                lines.append(f"{match.name}:{match.line_number}: {match.line}")
            else:
                lines.append(match.name)
        QApplication.clipboard().setText("\n".join(lines))
        QMessageBox.information(
            self, "LinRAR", f"{len(lines)} result(s) copied to the clipboard."
        )


def result_summary(result: SearchResult, query: SearchQuery) -> str:
    """One line for the status bar, so a search always says something."""
    if not query.wants_text:
        return f"{len(result.names)} name(s) match '{query.mask}'"
    files = len(result.found_names)
    if not files:
        return f"'{query.text}' was not found in any of the files searched"
    return (
        f"'{query.text}' found in {files} file(s)"
        + (": search stopped early" if result.cancelled else "")
    )

