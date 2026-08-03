"""Checksums, the way WinRAR's "Calculate checksums" offers them.

An archive already carries a CRC32 for every member, which is what makes
"is this the file I was sent?" answerable without unpacking anything.  What it
cannot answer is "is this the file the *website* listed?", because a download
page publishes SHA-256.  So both live here, computed in one pass over the
bytes: the file is read once and fed to every algorithm asked for, which
matters when the file is a disc image.

Nothing here imports Qt.
"""

from __future__ import annotations

import hashlib
import os
import zlib
from dataclasses import dataclass, field
from typing import Optional

from .backends.base import TaskContext

#: Read size.  Large enough that the syscall is not the cost, small enough
#: that cancelling is felt immediately.
CHUNK = 1024 * 1024

#: The algorithms offered, in the order they are shown.  CRC32 first because
#: it is the one an archive stores and so the one that can be compared
#: against the listing without doing anything at all.
ALGORITHMS: tuple[str, ...] = ("CRC32", "MD5", "SHA-1", "SHA-256", "SHA-512")

_HASHLIB_NAMES = {
    "MD5": "md5",
    "SHA-1": "sha1",
    "SHA-256": "sha256",
    "SHA-512": "sha512",
}


@dataclass
class FileDigest:
    """Every checksum asked for, for one file."""

    name: str
    path: str = ""
    size: int = 0
    digests: dict[str, str] = field(default_factory=dict)
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error

    def get(self, algorithm: str) -> str:
        return self.digests.get(algorithm, "")


class _Crc32:
    """A hashlib-shaped wrapper around zlib.crc32.

    zlib's CRC is a rolling integer rather than an object, and giving it the
    same three methods as everything else is what lets one loop drive all of
    them.
    """

    def __init__(self) -> None:
        self._value = 0

    def update(self, data: bytes) -> None:
        self._value = zlib.crc32(data, self._value)

    def hexdigest(self) -> str:
        return f"{self._value & 0xFFFFFFFF:08X}"


def _make(algorithm: str):
    if algorithm == "CRC32":
        return _Crc32()
    name = _HASHLIB_NAMES.get(algorithm)
    if name is None:
        raise ValueError(f"unknown algorithm: {algorithm}")
    return hashlib.new(name)


def digest_file(
    path: str,
    algorithms: tuple[str, ...] = ALGORITHMS,
    ctx: Optional[TaskContext] = None,
    name: str = "",
) -> FileDigest:
    """Every checksum in *algorithms* for one file, in a single read."""
    ctx = ctx or TaskContext()
    result = FileDigest(name=name or os.path.basename(path), path=path)
    try:
        result.size = os.path.getsize(path)
    except OSError as exc:
        result.error = str(exc)
        return result

    workers = {name: _make(name) for name in algorithms}
    read = 0
    try:
        with open(path, "rb") as handle:
            while True:
                if ctx.cancelled:
                    result.error = "cancelled"
                    return result
                chunk = handle.read(CHUNK)
                if not chunk:
                    break
                for worker in workers.values():
                    worker.update(chunk)
                read += len(chunk)
                if result.size:
                    ctx.advance(int(read * 100 / result.size))
    except OSError as exc:
        result.error = str(exc)
        return result

    ctx.advance(100)
    result.digests = {name: worker.hexdigest() for name, worker in workers.items()}
    return result


def digest_files(
    files: list[tuple[str, str]],
    algorithms: tuple[str, ...] = ALGORITHMS,
    ctx: Optional[TaskContext] = None,
) -> list[FileDigest]:
    """Checksums for several files, given as ``(display name, path)`` pairs."""
    ctx = ctx or TaskContext()
    plan: dict[str, int] = {}
    for name, path in files:
        try:
            plan[name] = os.path.getsize(path)
        except OSError:
            plan[name] = 0
    ctx.plan(plan)

    results: list[FileDigest] = []
    for name, path in files:
        if ctx.cancelled:
            break
        ctx.start_file(name)
        results.append(digest_file(path, algorithms, ctx, name=name))
    ctx.finish()
    return results


def as_text(results: list[FileDigest], algorithm: str) -> str:
    """The ``sha256sum`` layout: one ``<digest>  <name>`` line per file.

    Deliberately byte-for-byte what the coreutils tools emit, so the output
    can be pasted straight into ``sha256sum -c`` or compared with a checksum
    file somebody published.
    """
    lines = []
    for entry in results:
        if entry.ok and entry.get(algorithm):
            lines.append(f"{entry.get(algorithm).lower()}  {entry.name}")
    return "\n".join(lines) + ("\n" if lines else "")


def as_table(results: list[FileDigest], algorithms: tuple[str, ...]) -> str:
    """Every algorithm for every file, for the clipboard."""
    lines = []
    for entry in results:
        lines.append(entry.name)
        if not entry.ok:
            lines.append(f"    could not be read: {entry.error}")
            continue
        for algorithm in algorithms:
            value = entry.get(algorithm)
            if value:
                lines.append(f"    {algorithm:<8} {value}")
    return "\n".join(lines) + ("\n" if lines else "")


def compare(results: list[FileDigest], expected: str) -> dict[str, str]:
    """Match a pasted checksum against what was computed.

    Answers per file: ``"match"``, or "" when nothing in that file's digests
    equals the expected value.  The comparison is case- and whitespace-blind,
    and accepts a whole ``sha256sum`` line as well as a bare digest, because
    that is what people actually have on the clipboard.
    """
    wanted = expected.strip().split()
    needle = wanted[0].lower() if wanted else ""
    verdicts: dict[str, str] = {}
    if not needle:
        return verdicts
    for entry in results:
        for algorithm, value in entry.digests.items():
            if value.lower() == needle:
                verdicts[entry.name] = algorithm
                break
    return verdicts
