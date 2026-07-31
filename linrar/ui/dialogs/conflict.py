"""WinRAR's "Confirm file replace" prompt.

Extraction with the "Ask before overwrite" option is resolved here, up front:
the caller detects which targets already exist and asks once per conflict.  That
keeps the decision in the GUI instead of trying to drive unrar's interactive
console prompt.
"""

from __future__ import annotations

import enum
import os
from datetime import datetime
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from ...core.models import format_size
from .. import icons


class ConflictChoice(enum.Enum):
    YES = "yes"
    YES_ALL = "yes_all"
    NO = "no"
    NO_ALL = "no_all"
    RENAME = "rename"
    CANCEL = "cancel"


class ConflictDialog(QDialog):
    """Shows both versions of a clashing file and asks what to do."""

    def __init__(
        self,
        parent,
        target_path: str,
        new_size: int,
        new_mtime: Optional[datetime],
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Confirm file replace")
        self.setWindowIcon(icons.icon("app"))
        self.setModal(True)
        self.choice = ConflictChoice.CANCEL

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 12)
        layout.setSpacing(10)

        prompt = QLabel(
            "The destination folder already contains a file with this name."
        )
        prompt.setWordWrap(True)
        layout.addWidget(prompt)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(4)

        existing_size = existing_time = "-"
        try:
            stat = os.stat(target_path)
            existing_size = f"{format_size(stat.st_size)} bytes"
            existing_time = datetime.fromtimestamp(stat.st_mtime).strftime(
                "%d/%m/%Y %H:%M"
            )
        except OSError:
            pass

        icon_label = QLabel()
        icon_label.setPixmap(icons.pixmap("file", 32))
        grid.addWidget(icon_label, 0, 0, 3, 1, Qt.AlignmentFlag.AlignTop)

        name_label = QLabel(f"<b>{os.path.basename(target_path)}</b>")
        grid.addWidget(name_label, 0, 1, 1, 2)

        grid.addWidget(QLabel("Existing file:"), 1, 1)
        grid.addWidget(QLabel(f"{existing_size}, modified {existing_time}"), 1, 2)

        new_time = new_mtime.strftime("%d/%m/%Y %H:%M") if new_mtime else "-"
        grid.addWidget(QLabel("File in archive:"), 2, 1)
        grid.addWidget(
            QLabel(f"{format_size(new_size)} bytes, modified {new_time}"), 2, 2
        )
        grid.setColumnStretch(2, 1)
        layout.addLayout(grid)

        folder = QLabel(f"Folder: {os.path.dirname(target_path)}")
        folder.setObjectName("Hint")
        folder.setWordWrap(True)
        layout.addWidget(folder)

        row1 = QHBoxLayout()
        row1.addStretch(1)
        for text, choice in (
            ("Yes", ConflictChoice.YES),
            ("Yes to All", ConflictChoice.YES_ALL),
            ("No", ConflictChoice.NO),
            ("No to All", ConflictChoice.NO_ALL),
        ):
            button = QPushButton(text)
            button.clicked.connect(lambda _c=False, ch=choice: self._pick(ch))
            row1.addWidget(button)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addStretch(1)
        rename = QPushButton("Rename automatically")
        rename.clicked.connect(lambda: self._pick(ConflictChoice.RENAME))
        row2.addWidget(rename)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(lambda: self._pick(ConflictChoice.CANCEL))
        row2.addWidget(cancel)
        layout.addLayout(row2)

    def _pick(self, choice: ConflictChoice) -> None:
        self.choice = choice
        if choice is ConflictChoice.CANCEL:
            self.reject()
        else:
            self.accept()


def resolve_conflicts(
    parent,
    conflicts: list[tuple[str, str, int, Optional[datetime]]],
) -> Optional[tuple[list[str], bool]]:
    """Ask about each conflicting file.

    *conflicts* holds ``(member_name, target_path, size, mtime)`` tuples.
    Returns ``(members_to_skip, rename_instead_of_overwrite)`` or ``None`` when
    the user cancels the whole operation.
    """
    skip: list[str] = []
    for index, (member, target, size, mtime) in enumerate(conflicts):
        dialog = ConflictDialog(parent, target, size, mtime)
        dialog.exec()
        choice = dialog.choice
        if choice is ConflictChoice.CANCEL:
            return None
        if choice is ConflictChoice.YES:
            continue
        if choice is ConflictChoice.YES_ALL:
            return skip, False
        if choice is ConflictChoice.NO:
            skip.append(member)
            continue
        if choice is ConflictChoice.NO_ALL:
            # Only the remaining files; earlier "Yes" answers still stand.
            skip.extend(m for m, _t, _s, _d in conflicts[index:])
            return skip, False
        if choice is ConflictChoice.RENAME:
            return skip, True
    return skip, False
