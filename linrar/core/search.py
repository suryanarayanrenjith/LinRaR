"""Searching for text inside files, on disk and inside archives.

The Find dialog has always offered a "Text to find" box; this is what stands
behind it.  Nothing here imports Qt, so the same search can be driven from the
window, from a test, or from a script.

Two decisions worth knowing about:

**A file is rejected on its bytes before it is ever decoded.**  The needle is
encoded once, in a handful of likely encodings, and looked for in the raw
bytes.  Only a file that could plausibly contain it is decoded and split into
lines, which is what keeps a folder of photographs from costing anything.

**An archive is searched by unpacking it once.**  There is no "read member *n*"
in any of the tools LinRAR drives, so the members whose names pass the mask are
extracted together into a scratch folder, searched there, and the folder is
removed.  That is one pass over the archive rather than one per member, which
matters enormously for a solid archive.
"""

from __future__ import annotations

import fnmatch
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from typing import Callable, Optional

from . import filetypes
from .backends.base import TaskContext
from .models import ExtractOptions, OverwriteMode

#: Files past this size are searched in chunks rather than read whole; the
#: value is a compromise between one read syscall and one enormous allocation.
CHUNK = 1024 * 1024

#: A file bigger than this is skipped: at that size the answer is a job for
#: grep, and scanning it would make Find look like a hang.
MAX_FILE = 256 * 1024 * 1024

#: How much of a matching line is worth showing beside the file name.
LINE_LIMIT = 300


@dataclass
class Match:
    """One hit: where it is, and enough of the line to recognise it."""

    #: The member name inside the archive, or the path on disk.
    name: str
    #: Where the file really is, for opening it; "" for an archive member
    #: whose scratch copy has already been cleaned up.
    path: str = ""
    line_number: int = 0
    line: str = ""
    #: Set when the file matched the name mask but was not searched for text
    #: (too large, unreadable): shown so a silent gap is never mistaken for a
    #: confident "not here".
    skipped: str = ""


@dataclass
class SearchQuery:
    """What to look for."""

    mask: str = "*"
    text: str = ""
    case_sensitive: bool = False
    recurse: bool = True

    @property
    def wants_text(self) -> bool:
        return bool(self.text)

    def matches_name(self, name: str) -> bool:
        pattern = self.mask or "*"
        if self.case_sensitive:
            return fnmatch.fnmatchcase(name, pattern)
        return fnmatch.fnmatch(name.lower(), pattern.lower())


@dataclass
class SearchResult:
    """Everything one run of the search found."""

    matches: list[Match] = field(default_factory=list)
    #: Files opened and read, for "searched 412 files" in the results window.
    searched: int = 0
    #: True when the user cancelled: the list is partial and says so.
    cancelled: bool = False

    @property
    def names(self) -> list[str]:
        """Every file mentioned, hits and skips alike, in the order found."""
        seen: list[str] = []
        for match in self.matches:
            if match.name not in seen:
                seen.append(match.name)
        return seen

    @property
    def found_names(self) -> list[str]:
        """Only the files the text was actually found in.

        Kept apart from :attr:`names` because a file that could not be read is
        listed — silently dropping it would turn "I could not look" into "it
        is not there" — but it must never be counted as a result.
        """
        return [
            name for name in self.names
            if any(m.name == name and not m.skipped for m in self.matches)
        ]


# -- the text test ---------------------------------------------------------

#: Encodings a needle is looked for in.  UTF-8 covers almost everything, but a
#: Windows-authored text file inside a downloaded archive is very often UTF-16,
#: and a needle encoded only as UTF-8 would never be found in one.
_ENCODINGS = ("utf-8", "utf-16-le", "utf-16-be", "latin-1")


def _needles(text: str, case_sensitive: bool) -> list[bytes]:
    """The byte forms of *text* worth scanning a file for."""
    variants = [text] if case_sensitive else [text.lower(), text.upper(), text]
    out: list[bytes] = []
    for variant in dict.fromkeys(variants):
        for encoding in _ENCODINGS:
            try:
                encoded = variant.encode(encoding)
            except (UnicodeEncodeError, LookupError):
                continue
            if encoded and encoded not in out:
                out.append(encoded)
    return out


def _contains(path: str, needles: list[bytes], case_sensitive: bool) -> bool:
    """Cheap byte-level test: could this file possibly hold the text?

    Read in overlapping chunks so a needle straddling a boundary is still
    found, and lower-cased per chunk for a case-insensitive search so an
    ASCII needle matches whatever case the file used.
    """
    overlap = max((len(n) for n in needles), default=1)
    tail = b""
    try:
        with open(path, "rb") as handle:
            while True:
                chunk = handle.read(CHUNK)
                if not chunk:
                    return False
                window = tail + chunk
                haystack = window if case_sensitive else window.lower()
                for needle in needles:
                    probe = needle if case_sensitive else needle.lower()
                    if probe in haystack:
                        return True
                tail = window[-overlap:]
    except OSError:
        return False


def _lines_in(path: str, text: str, case_sensitive: bool) -> list[tuple[int, str]]:
    """The numbered lines of *path* that contain *text*."""
    try:
        with open(path, "rb") as handle:
            data = handle.read(MAX_FILE)
    except OSError:
        return []
    decoded = filetypes.decode(data)
    needle = text if case_sensitive else text.lower()
    hits: list[tuple[int, str]] = []
    for number, line in enumerate(decoded.splitlines(), start=1):
        subject = line if case_sensitive else line.lower()
        if needle in subject:
            trimmed = line.strip()
            if len(trimmed) > LINE_LIMIT:
                trimmed = trimmed[:LINE_LIMIT] + "…"
            hits.append((number, trimmed))
    return hits


def search_file(
    path: str, name: str, query: SearchQuery
) -> tuple[list[Match], bool]:
    """Search one file.  Returns ``(matches, was_read)``."""
    try:
        size = os.path.getsize(path)
    except OSError as exc:
        return [Match(name=name, path=path, skipped=str(exc))], False
    if size > MAX_FILE:
        return (
            [Match(name=name, path=path,
                   skipped=f"not searched: {size:,} bytes is too large")],
            False,
        )
    if not _contains(path, _needles(query.text, query.case_sensitive),
                     query.case_sensitive):
        return [], True
    hits = _lines_in(path, query.text, query.case_sensitive)
    if not hits:
        # The bytes were there but the decoded text is not: a compressed or
        # otherwise binary file that happened to contain the same bytes.
        return [Match(name=name, path=path, line_number=0, line="(binary match)")], True
    return [
        Match(name=name, path=path, line_number=number, line=line)
        for number, line in hits
    ], True


# -- searching a folder ----------------------------------------------------


def search_folder(
    folder: str,
    query: SearchQuery,
    ctx: Optional[TaskContext] = None,
) -> SearchResult:
    """Find files under *folder* whose name — and optionally text — match."""
    ctx = ctx or TaskContext()
    result = SearchResult()
    show_hidden_prefix = query.mask.startswith(".")

    for path, name in _walk(folder, query.recurse, show_hidden_prefix):
        if ctx.cancelled:
            result.cancelled = True
            return result
        relative = os.path.relpath(path, folder)
        if not query.matches_name(name):
            continue
        ctx.on_file(relative)
        if not query.wants_text:
            result.matches.append(Match(name=relative, path=path))
            continue
        matches, read = search_file(path, relative, query)
        result.searched += 1 if read else 0
        result.matches.extend(matches)
    return result


def _walk(folder: str, recurse: bool, include_hidden: bool):
    """Every file under *folder*, as ``(path, basename)`` pairs."""
    if not recurse:
        try:
            with os.scandir(folder) as entries:
                for entry in sorted(entries, key=lambda e: e.name.lower()):
                    if entry.is_file(follow_symlinks=False):
                        yield entry.path, entry.name
        except OSError:
            return
        return
    for root, dirs, names in os.walk(folder):
        # Descending into a dot directory turns "find in my project" into a
        # walk of .git; the mask can still ask for one by name.
        if not include_hidden:
            dirs[:] = [d for d in dirs if not d.startswith(".")]
        dirs.sort(key=str.lower)
        for name in sorted(names, key=str.lower):
            yield os.path.join(root, name), name


# -- searching an archive --------------------------------------------------


def search_archive(
    archive_path: str,
    backend,
    info,
    query: SearchQuery,
    password: Optional[str] = None,
    ctx: Optional[TaskContext] = None,
    extract: Optional[Callable] = None,
) -> SearchResult:
    """Find members of an archive whose name — and optionally text — match.

    *extract* is only for the tests: it stands in for ``backend.extract`` so
    the search can be exercised without a real archive tool.
    """
    ctx = ctx or TaskContext()
    result = SearchResult()

    candidates = [
        entry for entry in info.entries
        if not entry.is_dir and query.matches_name(entry.name.rsplit("/", 1)[-1])
    ]
    if not query.wants_text:
        result.matches = [Match(name=entry.name) for entry in candidates]
        return result
    if not candidates:
        return result

    workdir = tempfile.mkdtemp(prefix="linrar-search-")
    try:
        ctx.on_message(
            f"Unpacking {len(candidates)} file(s) to search them..."
        )
        options = ExtractOptions(
            destination=workdir,
            members=[entry.name for entry in candidates],
            password=password,
            overwrite_mode=OverwriteMode.OVERWRITE,
        )
        (extract or backend.extract)(archive_path, options, ctx)

        for entry in candidates:
            if ctx.cancelled:
                result.cancelled = True
                return result
            ctx.on_file(entry.name)
            path = _locate(workdir, entry.name)
            if path is None:
                result.matches.append(
                    Match(name=entry.name, skipped="could not be unpacked")
                )
                continue
            matches, read = search_file(path, entry.name, query)
            result.searched += 1 if read else 0
            for match in matches:
                # The scratch copy is about to be deleted, so nothing may be
                # told it can open the file from there.
                match.path = ""
                result.matches.append(match)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    return result


def _locate(workdir: str, member: str) -> Optional[str]:
    """Where a member landed, whether or not its path survived extraction."""
    direct = os.path.join(workdir, member)
    if os.path.isfile(direct):
        return direct
    base = member.rsplit("/", 1)[-1]
    for root, _dirs, names in os.walk(workdir):
        if base in names:
            return os.path.join(root, base)
    return None
