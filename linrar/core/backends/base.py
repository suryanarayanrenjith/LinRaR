"""Common backend interface and the task context used to report progress."""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from typing import Callable, Optional

from ..models import (
    ArchiveFormat,
    ArchiveInfo,
    CompressOptions,
    ExtractOptions,
    OperationError,
)
from ..process import ProcessRunner


#: The most members a listing may have before LinRAR refuses to build one.
#:
#: A directory of a few hundred thousand entries is already beyond what the
#: file list can show usefully, and an archive claiming tens of millions is
#: not a large archive: it is a small file that expands into one, and reading
#: it would fill memory with :class:`ArchiveEntry` objects long before the
#: window ever appeared.  Refusing with a sentence beats being killed by the
#: kernel with none.
MAX_ENTRIES = 500_000


def _noop(*_args, **_kwargs) -> None:
    return None


@dataclass
class TaskContext:
    """Carries progress callbacks and cancellation into a backend operation.

    It also keeps the arithmetic behind WinRAR's two progress bars, so every
    backend gets the same answer from the same code.  The top bar is the file
    being worked on; the bottom bar is the whole operation, weighted by
    **bytes** rather than by file count: thirty small files followed by one
    large one is not "97% done" after the small ones, and a bar that says so
    is worse than no bar.

    Feed it a plan with :meth:`plan`, then call :meth:`start_file` as each
    member begins and :meth:`advance` with that member's percentage.  A backend
    whose tool reports overall progress instead (7-Zip) calls
    :meth:`set_overall` and gets the per-file figure derived for it.
    """

    on_file: Callable[[str], None] = _noop
    on_percent: Callable[[int], None] = _noop
    on_total: Callable[[int], None] = _noop
    on_message: Callable[[str], None] = _noop
    #: Receives ``(files_done, files_total, bytes_done, bytes_total)`` whenever
    #: the numbers move, for the counters beside the bars.
    on_stats: Callable[[int, int, int, int], None] = _noop

    #: How many members the operation is expected to touch.  Used to weight
    #: the overall bar when no byte sizes are known.  Zero means "unknown".
    total_items: int = 0
    #: Uncompressed bytes the operation is expected to move, 0 when unknown.
    total_bytes: int = 0

    _runner: Optional[ProcessRunner] = field(default=None, repr=False)
    _cancel: threading.Event = field(default_factory=threading.Event, repr=False)

    # -- progress bookkeeping ----------------------------------------------
    _sizes: dict[str, int] = field(default_factory=dict, repr=False)
    _by_basename: dict[str, list[str]] = field(default_factory=dict, repr=False)
    _current: str = field(default="", repr=False)
    _current_size: int = field(default=0, repr=False)
    _bytes_done: int = field(default=0, repr=False)
    _files_done: int = field(default=0, repr=False)
    _last_percent: int = field(default=-1, repr=False)
    _overall: int = field(default=0, repr=False)

    def attach(self, runner: ProcessRunner) -> None:
        """Register the live child process so :meth:`cancel` can reach it."""
        self._runner = runner
        if self._cancel.is_set():
            runner.cancel()

    def detach(self) -> None:
        self._runner = None

    def cancel(self) -> None:
        self._cancel.set()
        if self._runner is not None:
            self._runner.cancel()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    # -- the plan ----------------------------------------------------------

    def plan(self, sizes: dict[str, int], total_bytes: int = 0) -> None:
        """Declare the members and their sizes before the work starts."""
        self._sizes = {}
        self._by_basename = {}
        for name, size in sizes.items():
            key = _normalise(name)
            if not key:
                continue
            self._sizes[key] = int(size or 0)
            self._by_basename.setdefault(key.rsplit("/", 1)[-1], []).append(key)
        self.total_bytes = int(total_bytes or sum(self._sizes.values()))
        if not self.total_items:
            self.total_items = len(self._sizes)

    def size_of(self, name: str) -> int:
        """The planned size of *name*, however the tool chose to spell it.

        ``unrar x archive.rar dest/`` announces each member by its *output*
        path, so an exact match on the archive member name misses every time;
        the tail of the path is what the two spellings have in common.
        """
        key = _normalise(name)
        if not key:
            return 0
        direct = self._sizes.get(key)
        if direct is not None:
            return direct
        candidates = self._by_basename.get(key.rsplit("/", 1)[-1], [])
        for candidate in candidates:
            if key.endswith("/" + candidate) or candidate.endswith("/" + key):
                return self._sizes[candidate]
        # A unique basename is answer enough: paths get rewritten by -ep and
        # by the destination prefix, but names stay.
        if len(candidates) == 1:
            return self._sizes[candidates[0]]
        return 0

    # -- reporting ---------------------------------------------------------

    def start_file(self, name: str) -> None:
        """A member has begun; bank the previous one and reset the top bar."""
        if not name or name == self._current:
            return
        if self._current:
            self._bytes_done += self._current_size
        self._current = name
        self._current_size = self.size_of(name)
        self._files_done += 1
        self._last_percent = -1
        self.on_file(name)
        self._publish(0)

    def advance(self, percent: int) -> None:
        """Report the current member's own percentage."""
        percent = max(0, min(100, int(percent)))
        if percent != self._last_percent:
            self._last_percent = percent
            self.on_percent(percent)
        self._publish(percent)

    def set_overall(self, percent: int) -> None:
        """Report the *whole operation's* percentage, for tools that give it.

        The per-file figure is worked back out of it when the plan makes that
        possible, so the top bar still means what it says.
        """
        percent = max(0, min(100, int(percent)))
        self._emit_overall(percent)
        if self.total_bytes > 0 and self._current_size > 0:
            done = self.total_bytes * percent / 100.0 - self._bytes_done
            file_percent = max(0, min(100, int(done * 100 / self._current_size)))
            if file_percent != self._last_percent:
                self._last_percent = file_percent
                self.on_percent(file_percent)
        self._emit_stats(self._last_percent if self._last_percent > 0 else 0)

    def reset_progress(self, label: str = "") -> None:
        """Start a second phase of the same job from zero.

        Building a self-extracting AppImage compresses first and wraps second;
        without this the wrapping phase would report against the compression's
        finished total and the bar would sit at 100% while work carried on.
        """
        self._sizes = {}
        self._by_basename = {}
        self._current = ""
        self._current_size = 0
        self._bytes_done = 0
        self._files_done = 0
        self._last_percent = -1
        self._overall = 0
        self.total_bytes = 0
        self.total_items = 0
        self.on_percent(0)
        self.on_total(0)
        if label:
            self.on_file(label)

    def finish(self) -> None:
        """Everything is done: fill both bars rather than leaving them short."""
        if self._current:
            self._bytes_done += self._current_size
            self._current = ""
            self._current_size = 0
        self.on_percent(100)
        self._emit_overall(100)
        self._emit_stats(100)

    # -- internals ---------------------------------------------------------

    def _publish(self, percent: int) -> None:
        self._emit_overall(self._weighted(percent))
        self._emit_stats(percent)

    def _weighted(self, percent: int) -> int:
        """Where the operation as a whole stands, given this member's share."""
        if self.total_bytes > 0:
            done = self._bytes_done + self._current_size * percent / 100.0
            return int(min(100.0, done * 100.0 / self.total_bytes))
        if self.total_items > 0:
            done = max(self._files_done - 1, 0) + percent / 100.0
            return int(min(100.0, done * 100.0 / self.total_items))
        # Nothing better to say than the file's own progress.
        return percent

    def _emit_overall(self, value: int) -> None:
        # rar makes more than one pass over some files and its percentage
        # jumps backwards; an overall bar that retreats reads as a fault.
        if value > self._overall:
            self._overall = value
            self.on_total(value)

    def _emit_stats(self, percent: int) -> None:
        done = self._bytes_done + self._current_size * max(0, percent) / 100.0
        self.on_stats(
            self._files_done,
            self.total_items,
            int(min(done, self.total_bytes or done)),
            self.total_bytes,
        )


def _normalise(name: str) -> str:
    return name.replace("\\", "/").strip().strip("/")


class ArchiveBackend:
    """Interface implemented by every archive handler.

    Only :meth:`read_info`, :meth:`extract` and :meth:`test` are mandatory;
    the write operations raise :class:`OperationError` by default so read-only
    formats can simply not implement them.
    """

    name: str = "generic"
    formats: tuple[ArchiveFormat, ...] = ()
    can_write: bool = False

    # -- reading -----------------------------------------------------------

    def read_info(self, path: str, password: Optional[str] = None) -> ArchiveInfo:
        raise NotImplementedError

    def extract(
        self,
        path: str,
        options: ExtractOptions,
        ctx: Optional[TaskContext] = None,
    ) -> None:
        raise NotImplementedError

    def test(
        self,
        path: str,
        password: Optional[str] = None,
        ctx: Optional[TaskContext] = None,
    ) -> None:
        raise NotImplementedError

    # -- writing -----------------------------------------------------------

    def create(
        self,
        files: list[str],
        options: CompressOptions,
        ctx: Optional[TaskContext] = None,
    ) -> None:
        self._unsupported("Creating archives")

    def delete_members(
        self,
        path: str,
        members: list[str],
        password: Optional[str] = None,
        ctx: Optional[TaskContext] = None,
    ) -> None:
        self._unsupported("Deleting files from archives")

    def rename_member(
        self,
        path: str,
        old_name: str,
        new_name: str,
        password: Optional[str] = None,
        ctx: Optional[TaskContext] = None,
    ) -> None:
        self._unsupported("Renaming files inside archives")

    def rename_members(
        self,
        path: str,
        pairs: list[tuple[str, str]],
        password: Optional[str] = None,
        ctx: Optional[TaskContext] = None,
    ) -> None:
        """Apply several renames; needed when a whole folder is renamed."""
        for old_name, new_name in pairs:
            self.rename_member(path, old_name, new_name, password, ctx)

    def set_comment(
        self,
        path: str,
        comment: str,
        password: Optional[str] = None,
        ctx: Optional[TaskContext] = None,
    ) -> None:
        self._unsupported("Archive comments")

    def lock(self, path: str, ctx: Optional[TaskContext] = None) -> None:
        self._unsupported("Locking archives")

    def add_recovery_record(
        self, path: str, percent: int = 3, ctx: Optional[TaskContext] = None
    ) -> None:
        self._unsupported("Recovery records")

    def repair(
        self, path: str, output_dir: str, ctx: Optional[TaskContext] = None
    ) -> Optional[str]:
        self._unsupported("Repairing archives")
        return None

    # -- helpers -----------------------------------------------------------

    def _unsupported(self, what: str) -> None:
        raise OperationError(
            f"{what} is not supported for {self.name} archives."
        )

    @staticmethod
    def check_entry_count(count: int, path: str) -> None:
        """Refuse a listing too large to hold, before it is held.

        See :data:`MAX_ENTRIES`.  Called with the count the archive declares,
        so nothing is allocated for a listing that will be turned away.
        """
        if count > MAX_ENTRIES:
            raise OperationError(
                f"{os.path.basename(path)} says it holds {count:,} files, "
                f"which is more than LinRAR will list ({MAX_ENTRIES:,}).\n\n"
                "Unpack it from a terminal if it really is that large:\n"
                f"    unrar x {os.path.basename(path)}"
            )
