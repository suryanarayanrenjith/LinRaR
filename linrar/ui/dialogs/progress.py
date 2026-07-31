"""The operation progress window."""

from __future__ import annotations

import time

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from ...core.models import format_size_short
from ...core.tasks import Task
from .. import icons


class ProgressDialog(QDialog):
    """Shows per-file and overall progress while a :class:`Task` runs.

    The dialog owns the task's lifetime: closing it cancels, and the task's
    terminal signals close it.
    """

    cancelled = pyqtSignal()

    def __init__(
        self,
        parent,
        task: Task,
        title: str = "Processing",
        total_bytes: int = 0,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowIcon(icons.icon("app"))
        self.setModal(True)
        self.setMinimumWidth(430)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, True)

        self.task = task
        self.total_bytes = total_bytes
        self._start = time.monotonic()
        self._finished = False
        self._cancelling = False
        self._started = False
        #: Set when the user pressed "Background": the dialog closes but the
        #: task keeps running; the caller takes over completion handling.
        self.backgrounded = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(9)

        header = QHBoxLayout()
        icon_label = QLabel()
        icon_label.setPixmap(icons.pixmap("archive", 32))
        header.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignTop)

        text_box = QVBoxLayout()
        text_box.setSpacing(2)
        self.action_label = QLabel(title)
        font = self.action_label.font()
        font.setBold(True)
        self.action_label.setFont(font)
        self.file_label = QLabel("Preparing...")
        self.file_label.setWordWrap(False)
        self.file_label.setTextFormat(Qt.TextFormat.PlainText)
        text_box.addWidget(self.action_label)
        text_box.addWidget(self.file_label)
        header.addLayout(text_box, 1)
        layout.addLayout(header)

        self.file_bar = QProgressBar()
        self.file_bar.setRange(0, 100)
        layout.addWidget(self.file_bar)

        self.total_bar = QProgressBar()
        self.total_bar.setRange(0, 100)
        layout.addWidget(self.total_bar)

        stats = QGroupBox()
        stats_form = QFormLayout(stats)
        stats_form.setContentsMargins(10, 8, 10, 8)
        stats_form.setSpacing(4)
        self.elapsed_label = QLabel("00:00:00")
        self.remaining_label = QLabel("--:--:--")
        stats_form.addRow("Elapsed time", self.elapsed_label)
        stats_form.addRow("Time left", self.remaining_label)
        if total_bytes:
            self.processed_label = QLabel("0 bytes")
            stats_form.addRow("Processed", self.processed_label)
        else:
            self.processed_label = None
        layout.addWidget(stats)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.background_button = QPushButton("Background")
        self.background_button.clicked.connect(self._on_background)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self._on_cancel)
        buttons.addWidget(self.background_button)
        buttons.addWidget(self.cancel_button)
        layout.addLayout(buttons)

        task.fileChanged.connect(self._on_file)
        task.percentChanged.connect(self.file_bar.setValue)
        task.totalChanged.connect(self._on_total)
        task.succeeded.connect(self._on_finished)
        task.failed.connect(self._on_finished)
        task.passwordNeeded.connect(self._on_finished)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(500)

    # -- updates -----------------------------------------------------------

    def _on_file(self, name: str) -> None:
        metrics = self.file_label.fontMetrics()
        width = max(self.width() - 90, 200)
        self.file_label.setText(
            metrics.elidedText(name, Qt.TextElideMode.ElideMiddle, width)
        )

    def _on_total(self, value: int) -> None:
        self.total_bar.setValue(value)
        if self.processed_label is not None and self.total_bytes:
            done = self.total_bytes * value / 100.0
            self.processed_label.setText(
                f"{format_size_short(done)} of {format_size_short(self.total_bytes)}"
            )

    def _tick(self) -> None:
        elapsed = time.monotonic() - self._start
        self.elapsed_label.setText(_clock(elapsed))
        percent = self.total_bar.value()
        if percent > 2 and elapsed > 1.0:
            remaining = elapsed * (100 - percent) / percent
            self.remaining_label.setText(_clock(remaining))

    # -- lifecycle ---------------------------------------------------------

    def showEvent(self, event) -> None:
        # Start the worker only once the dialog is on screen and the event loop
        # is running, so no completion signal can arrive before we can react.
        super().showEvent(event)
        if not self._started:
            self._started = True
            self._start = time.monotonic()
            self.task.start()

    def _on_background(self) -> None:
        """Close the window but leave the task running.

        Hiding a modal dialog makes ``exec()`` return, so the caller must check
        :attr:`backgrounded` and keep the task alive.
        """
        if self._finished:
            self.accept()
            return
        self.backgrounded = True
        self._timer.stop()
        self.hide()

    def _on_cancel(self) -> None:
        if self._finished:
            self.reject()
            return
        self._cancelling = True
        self.cancel_button.setEnabled(False)
        self.action_label.setText("Cancelling...")
        self.task.cancel()
        self.cancelled.emit()

    def _on_finished(self, _payload=None) -> None:
        self._finished = True
        self._timer.stop()
        self.accept()

    def closeEvent(self, event) -> None:
        if not self._finished:
            self._on_cancel()
            event.ignore()
            return
        self._timer.stop()
        super().closeEvent(event)

    def reject(self) -> None:
        # Esc must cancel the operation rather than silently orphan it.
        if not self._finished:
            self._on_cancel()
            return
        super().reject()


def _clock(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"
