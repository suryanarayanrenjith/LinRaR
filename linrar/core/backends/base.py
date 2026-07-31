"""Common backend interface and the task context used to report progress."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable, Optional

from ..models import (
    ArchiveEntry,
    ArchiveFormat,
    ArchiveInfo,
    CompressOptions,
    ExtractOptions,
    OperationError,
)
from ..process import ProcessRunner


def _noop(*_args, **_kwargs) -> None:
    return None


@dataclass
class TaskContext:
    """Carries progress callbacks and cancellation into a backend operation."""

    on_file: Callable[[str], None] = _noop
    on_percent: Callable[[int], None] = _noop
    on_total: Callable[[int], None] = _noop
    on_message: Callable[[str], None] = _noop

    #: How many members the operation is expected to touch.  The rar backend
    #: only reports a per-file percentage, so this is what lets it derive an
    #: overall figure for the second progress bar.  Zero means "unknown".
    total_items: int = 0

    _runner: Optional[ProcessRunner] = field(default=None, repr=False)
    _cancel: threading.Event = field(default_factory=threading.Event, repr=False)

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
    def build_tree(entries: list[ArchiveEntry]) -> dict[str, list[ArchiveEntry]]:
        """Group entries by parent folder, synthesising missing directories.

        Some archives only store file records, so a folder that exists solely as
        a path component of a file would otherwise be invisible to the browser.
        """
        tree: dict[str, list[ArchiveEntry]] = {"": []}
        known_dirs: set[str] = set()

        for entry in entries:
            if entry.is_dir:
                known_dirs.add(entry.name.rstrip("/"))

        # Materialise every intermediate folder referenced by a path.
        implied: set[str] = set()
        for entry in entries:
            parts = entry.name.rstrip("/").split("/")
            stop = len(parts) if entry.is_dir else len(parts) - 1
            for i in range(1, stop + 1):
                implied.add("/".join(parts[:i]))

        for folder in implied:
            tree.setdefault(folder, [])

        placed: set[str] = set()
        for entry in entries:
            key = entry.name.rstrip("/")
            if entry.is_dir:
                placed.add(key)
            tree.setdefault(entry.parent, [])
            tree[entry.parent].append(entry)

        # Add synthetic entries for folders the archive never recorded.
        for folder in sorted(implied):
            if folder in placed:
                continue
            parent = folder.rsplit("/", 1)[0] if "/" in folder else ""
            tree.setdefault(parent, [])
            tree[parent].append(ArchiveEntry(name=folder, is_dir=True))
            placed.add(folder)

        return tree
