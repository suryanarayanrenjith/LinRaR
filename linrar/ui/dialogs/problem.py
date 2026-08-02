"""The window that explains a failure instead of announcing one.

A ``QMessageBox`` with one sentence in it is the wrong shape for "this file
cannot be opened": the interesting part is *why*, and the useful part is what
to do next.  :class:`ProblemDialog` shows a :class:`~linrar.core.diagnose.
Problem` as a headline, a paragraph, a table of what LinRAR actually found, a
list of suggestions, and a collapsed block of technical detail that copies to
the clipboard in one click, with the actions that make sense for this
particular failure as real buttons.
"""

from __future__ import annotations

from typing import Callable, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...core.diagnose import Problem
from .. import icons

#: Problem kind -> the icon that fits it.  Everything unknown gets the
#: information icon rather than an alarm: most of these are not emergencies.
_ICONS = {
    "missing": "find",
    "broken-link": "find",
    "directory": "folder",
    "not-a-file": "info",
    "not-a-folder": "info",
    "permission": "lock",
    "empty": "file",
    "volume": "archive-small",
    "no-tool": "package-alert",
    "not-archive": "file",
    "damaged": "repair",
    "password": "key",
    "no-handler": "globe",
}


class ProblemDialog(QDialog):
    """Shows one :class:`Problem`, with buttons for what can be done about it."""

    def __init__(self, parent, problem: Problem) -> None:
        super().__init__(parent)
        self.problem = problem
        self.chosen: str = ""

        self.setWindowTitle(problem.title or "LinRAR")
        self.setWindowIcon(icons.icon("app"))
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 12)
        layout.setSpacing(10)

        layout.addLayout(self._headline_row(problem))

        if problem.explanation:
            body = QLabel(problem.explanation.replace("\n", "<br>"))
            body.setWordWrap(True)
            body.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            layout.addWidget(body)

        if problem.facts:
            layout.addWidget(self._facts_card(problem))

        if problem.suggestions:
            layout.addWidget(_rule())
            layout.addWidget(QLabel("<b>What you can do</b>"))
            for line in problem.suggestions:
                bullet = QLabel(f"•   {line}")
                # Plain text: a suggestion may legitimately contain a "<" or a
                # "&" (a shell command, a file name) and must not be read as
                # markup, nor show its escapes.
                bullet.setTextFormat(Qt.TextFormat.PlainText)
                bullet.setWordWrap(True)
                bullet.setTextInteractionFlags(
                    Qt.TextInteractionFlag.TextSelectableByMouse
                )
                bullet.setContentsMargins(8, 0, 0, 0)
                layout.addWidget(bullet)

        self.details = QPlainTextEdit(problem.details)
        self.details.setReadOnly(True)
        self.details.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.details.setMaximumHeight(190)
        self.details.setVisible(False)
        layout.addWidget(self.details)

        layout.addStretch(1)
        layout.addLayout(self._buttons(problem))

    # -- construction ------------------------------------------------------

    def _headline_row(self, problem: Problem) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(11)
        badge = QLabel()
        badge.setPixmap(icons.pixmap(_ICONS.get(problem.kind, "info"), 32))
        badge.setFixedWidth(36)
        row.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
        headline = QLabel(problem.headline)
        headline.setObjectName("Heading")
        headline.setWordWrap(True)
        headline.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        row.addWidget(headline, 1)
        return row

    def _facts_card(self, problem: Problem) -> QWidget:
        card = QWidget()
        card.setObjectName("Card")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        form = QFormLayout(card)
        form.setContentsMargins(10, 8, 10, 8)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(3)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        for name, value in problem.facts:
            caption = QLabel(name)
            caption.setObjectName("Hint")
            shown = QLabel(str(value))
            shown.setWordWrap(True)
            shown.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            form.addRow(caption, shown)
        return card

    def _buttons(self, problem: Problem) -> QVBoxLayout:
        """Offered actions on their own row, above the standard one.

        Sharing one row crowds three long captions into whatever is left
        beside Close, and clipped button labels are exactly the sort of thing
        this window exists to avoid.
        """
        box = QVBoxLayout()
        box.setSpacing(7)

        self._action_row = QHBoxLayout()
        self._action_row.setSpacing(7)
        self._action_row.addStretch(1)
        self._actions_holder = QWidget()
        self._actions_holder.setLayout(self._action_row)
        self._actions_holder.setVisible(False)
        box.addWidget(self._actions_holder)

        row = QHBoxLayout()
        row.setSpacing(7)
        self.details_button = QPushButton("Show details")
        self.details_button.setCheckable(True)
        self.details_button.toggled.connect(self._toggle_details)
        self.details_button.setEnabled(bool(problem.details))
        row.addWidget(self.details_button)

        copy_button = QPushButton("Copy report")
        copy_button.setToolTip(
            "Copy everything in this window to the clipboard, ready to paste "
            "into a bug report"
        )
        copy_button.clicked.connect(self._copy)
        row.addWidget(copy_button)
        row.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.reject)
        row.addWidget(buttons)
        self._close_box = buttons
        box.addLayout(row)
        return box

    # -- public API --------------------------------------------------------

    def add_action(self, key: str, label: str, tip: str = "") -> QPushButton:
        """Offer *label* as a button; pressing it closes with ``chosen = key``."""
        button = QPushButton(label)
        if tip:
            button.setToolTip(tip)
        button.clicked.connect(lambda: self._choose(key))
        # Appended after the stretch so the actions sit to the right, in the
        # order they were added.
        self._action_row.addWidget(button)
        self._actions_holder.setVisible(True)
        return button

    def _choose(self, key: str) -> None:
        self.chosen = key
        self.accept()

    def _toggle_details(self, shown: bool) -> None:
        self.details.setVisible(shown)
        self.details_button.setText("Hide details" if shown else "Show details")
        if not shown:
            self.adjustSize()

    def _copy(self) -> None:
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self.problem.as_text())
        self.details_button.setFocus()

    # -- convenience -------------------------------------------------------

    @staticmethod
    def report(
        parent,
        problem: Problem,
        actions: Optional[dict[str, tuple[str, Callable[[], None]]]] = None,
    ) -> str:
        """Show *problem*; run and return whichever offered action was picked.

        *actions* maps an action key from :mod:`linrar.core.diagnose` to a
        ``(label, callback)`` pair.  Only the keys the problem itself suggests
        are offered, so one table of handlers serves every caller without
        putting a meaningless button in front of the user.
        """
        dialog = ProblemDialog(parent, problem)
        handlers = actions or {}
        for key in problem.actions:
            entry = handlers.get(key)
            if entry is not None:
                dialog.add_action(key, entry[0])
        dialog.exec()
        picked = dialog.chosen
        if picked and picked in handlers:
            handlers[picked][1]()
        return picked


def _rule() -> QWidget:
    line = QFrame()
    line.setObjectName("Rule")
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFixedHeight(1)
    return line
