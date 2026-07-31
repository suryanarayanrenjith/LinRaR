"""Background execution of backend operations.

Every archive operation can take minutes, so it runs on a :class:`QThread` and
reports progress through signals.  Backends receive a :class:`TaskContext` whose
callbacks emit those signals, which Qt delivers to the GUI thread as queued
connections — no widget is ever touched from the worker.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Optional

from PyQt6.QtCore import QThread, pyqtSignal

from .backends.base import TaskContext
from .models import OperationError, PasswordRequired


class Task(QThread):
    """Runs ``work(ctx)`` off the GUI thread."""

    fileChanged = pyqtSignal(str)
    percentChanged = pyqtSignal(int)
    totalChanged = pyqtSignal(int)
    messageLogged = pyqtSignal(str)
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(object)
    passwordNeeded = pyqtSignal(object)

    def __init__(
        self,
        work: Callable[[TaskContext], Any],
        title: str = "Processing",
        parent: Optional[Any] = None,
    ) -> None:
        super().__init__(parent)
        self.work = work
        self.title = title
        self.result: Any = None
        self.error: Optional[OperationError] = None
        self.started_at = 0.0

        # Throttle progress signals; rar can emit hundreds per second.
        self._last_emit = 0.0
        self._last_percent = -1
        self._last_total = -1

        self.ctx = TaskContext(
            on_file=self._on_file,
            on_percent=self._on_percent,
            on_total=self._on_total,
            on_message=self.messageLogged.emit,
        )

    # -- context callbacks (worker thread) ---------------------------------

    def _on_file(self, name: str) -> None:
        self.fileChanged.emit(name)

    def _throttled(self) -> bool:
        now = time.monotonic()
        if now - self._last_emit < 0.03:
            return True
        self._last_emit = now
        return False

    def _on_percent(self, value: int) -> None:
        if value == self._last_percent:
            return
        if value not in (0, 100) and self._throttled():
            return
        self._last_percent = value
        self.percentChanged.emit(value)

    def _on_total(self, value: int) -> None:
        if value == self._last_total:
            return
        self._last_total = value
        self.totalChanged.emit(value)

    # -- thread body -------------------------------------------------------

    def run(self) -> None:
        self.started_at = time.monotonic()
        try:
            self.result = self.work(self.ctx)
        except PasswordRequired as exc:
            self.error = exc
            self.passwordNeeded.emit(exc)
            return
        except OperationError as exc:
            self.error = exc
            self.failed.emit(exc)
            return
        except Exception as exc:  # noqa: BLE001 - surface anything unexpected
            self.error = OperationError(str(exc) or exc.__class__.__name__)
            self.failed.emit(self.error)
            return
        self.succeeded.emit(self.result)

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started_at if self.started_at else 0.0

    def cancel(self) -> None:
        self.ctx.cancel()
