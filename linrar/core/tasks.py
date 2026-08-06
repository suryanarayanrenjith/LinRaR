"""Background execution of backend operations.

Every archive operation can take minutes, so it runs on a :class:`QThread` and
reports progress through signals.  Backends receive a :class:`TaskContext` whose
callbacks emit those signals, which Qt delivers to the GUI thread as queued
connections, so no widget is ever touched from the worker.
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
    #: ``(files_done, files_total, bytes_done, bytes_total)`` for the counters
    #: beside the bars.  Throttled like the percentages.
    statsChanged = pyqtSignal(int, int, int, int)
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

        self._last_stats = 0.0
        self._stats: tuple[int, int, int, int] = (0, 0, 0, 0)

        self.ctx = TaskContext(
            on_file=self._on_file,
            on_percent=self._on_percent,
            on_total=self._on_total,
            on_message=self.messageLogged.emit,
            on_stats=self._on_stats,
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

    def _on_stats(
        self, files_done: int, files_total: int, bytes_done: int, bytes_total: int
    ) -> None:
        stats = (files_done, files_total, bytes_done, bytes_total)
        if stats == self._stats:
            return
        self._stats = stats
        # A byte counter moves on every chunk; the window only needs it a few
        # times a second, and the queued connection is not free.
        now = time.monotonic()
        if files_done and now - self._last_stats < 0.12:
            return
        self._last_stats = now
        self.statsChanged.emit(*stats)

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


class UpdateTask(QThread):
    """Runs an update, or just the check, off the GUI thread.

    The same shape as :class:`Task`, for the same reason: the work is slow,
    involves the network and a subprocess, and must never touch a widget.  What
    it reports is different, because an update has stages rather than files.
    """

    #: ``(stage key, human title)`` as each stage begins.
    stageChanged = pyqtSignal(str, str)
    #: ``(percent within the stage, bytes done, bytes total)``.
    progressChanged = pyqtSignal(int, int, int)
    messageLogged = pyqtSignal(str)
    #: The :class:`~linrar.core.updater.Update` found, or ``None`` when the
    #: installed version is already the newest one.
    checked = pyqtSignal(object)
    #: An update finished; carries the path the previous version was kept at.
    installed = pyqtSignal(str)
    failed = pyqtSignal(object)
    #: The user pressed Cancel and the worker unwound cleanly.
    cancelled = pyqtSignal()

    def __init__(
        self,
        work: Callable[[Any], Any],
        install: bool = False,
        parent: Optional[Any] = None,
    ) -> None:
        super().__init__(parent)
        self.work = work
        #: False for a check, True for a download-and-install run: it decides
        #: which terminal signal is emitted, and the window shows different
        #: things for the two.
        self.installs = install
        self.result: Any = None
        self.error: Optional[Exception] = None
        self._cancel = False

        # Imported here rather than at module scope: core.updater pulls in the
        # network stack, and an archive operation has no use for it.
        from .updater import UpdateContext

        self.ctx = UpdateContext(
            on_stage=self.stageChanged.emit,
            on_progress=self.progressChanged.emit,
            on_message=self.messageLogged.emit,
            should_cancel=lambda: self._cancel,
        )

    def cancel(self) -> None:
        """Ask the worker to stop at its next checkpoint."""
        self._cancel = True

    def run(self) -> None:
        from .updater import Cancelled, UpdateError

        try:
            self.result = self.work(self.ctx)
        except Cancelled:
            self.cancelled.emit()
            return
        except UpdateError as exc:
            self.error = exc
            self.failed.emit(exc)
            return
        except Exception as exc:  # noqa: BLE001 - surface anything unexpected
            self.error = UpdateError(
                str(exc) or exc.__class__.__name__,
                f"{exc.__class__.__name__}: {exc}",
            )
            self.failed.emit(self.error)
            return

        if self.installs:
            self.installed.emit(str(self.result or ""))
        else:
            self.checked.emit(self.result)
