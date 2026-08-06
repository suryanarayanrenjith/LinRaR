"""Working out *why* something could not be opened, in words a person can use.

An archiver spends a good part of its life being handed files that are not
archives: a download that was really an HTML error page, a ``.rar`` that is the
second volume of a set, a file on a disk that is no longer mounted, a format
that needs a tool nobody installed.  The command line tools answer all of those
with roughly the same shrug: "cannot open", exit code 6. Passing that
along makes the application look broken when the file is the problem.

So before anything is reported, the file is inspected: what it is, what it
claims to be, how big it is, whether it can be read at all, which tool would
open it and whether that tool exists.  :func:`describe` turns the result into a
headline, an explanation, a table of facts, concrete suggestions, and a block
of technical detail that can be pasted into a bug report.  The dialog in
:mod:`linrar.ui.dialogs.problem` renders it; nothing here imports Qt, so it is
equally usable from the command line and from the tests.
"""

from __future__ import annotations

import os
import stat as stat_module
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .models import ArchiveFormat, PasswordRequired, format_size_short
from .registry import (
    REGISTRY,
    detect_format_source,
    first_volume,
    looks_like_archive,
    volume_number,
)

#: Things the dialog may offer to do about a problem.  The UI decides which of
#: them it can actually carry out; this module only says which make sense.
ACTION_DEPENDENCIES = "dependencies"
ACTION_FIRST_VOLUME = "first-volume"
ACTION_OPEN_EXTERNAL = "open-external"
ACTION_VIEW = "view"
ACTION_REPAIR = "repair"
ACTION_PARENT = "parent"
ACTION_RETRY = "retry"

#: What the leading bytes say a file really is, when it is not an archive.
#: Only used for the explanation, never to decide what to do, so a wrong guess
#: costs nothing.
_CONTENT_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"\x7fELF", "a Linux program or shared library (ELF)"),
    (b"MZ", "a Windows program (.exe/.dll)"),
    (b"%PDF-", "a PDF document"),
    (b"\x89PNG\r\n\x1a\n", "a PNG image"),
    (b"\xff\xd8\xff", "a JPEG image"),
    (b"GIF87a", "a GIF image"),
    (b"GIF89a", "a GIF image"),
    (b"BM", "a bitmap image"),
    (b"\x00\x00\x01\x00", "a Windows icon"),
    (b"SQLite format 3\x00", "an SQLite database"),
    (b"OggS", "an Ogg media file"),
    (b"fLaC", "a FLAC audio file"),
    (b"ID3", "an MP3 audio file"),
    (b"\x1a\x45\xdf\xa3", "a Matroska/WebM video"),
    (b"%!PS", "a PostScript document"),
    (b"\xca\xfe\xba\xbe", "a Java class file"),
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "a legacy Office document (Word/Excel)"),
    (b"-----BEGIN ", "a PEM key or certificate"),
    (b"\x00asm", "a WebAssembly module"),
    (b"wOFF", "a web font"),
    (b"\x00\x01\x00\x00\x00", "a TrueType font"),
    (b"OTTO", "an OpenType font"),
    (b"<?xml", "an XML document"),
    (b"<!DOCTYPE", "an HTML document"),
    (b"<html", "an HTML document"),
    (b"#!", "a script"),
)

#: How much of the file the details block shows.
_DUMP_BYTES = 64


@dataclass
class FileFacts:
    """Everything cheap that can be learned about a path without opening it."""

    path: str
    exists: bool = False
    kind: str = "missing"          # file, directory, symlink, socket, ...
    size: int = 0
    readable: bool = False
    mtime: Optional[datetime] = None
    link_target: str = ""
    broken_link: bool = False
    extension: str = ""
    magic: bytes = b""
    format: ArchiveFormat = ArchiveFormat.UNKNOWN
    format_source: str = ""        # content, sfx, name or ""
    content: str = ""              # what the bytes look like, if not an archive
    volume: int = 0
    first_volume: str = ""
    tool: str = ""
    package: str = ""
    tool_installed: bool = True
    error: str = ""                # why the inspection itself failed

    @property
    def is_archive(self) -> bool:
        return self.format is not ArchiveFormat.UNKNOWN

    @property
    def confirmed(self) -> bool:
        """Is the format proven by the file's contents rather than its name?

        The difference matters: LinRAR still *tries* a file that only looks
        like an archive by its extension (some old tar variants carry no
        signature at all), but it must never tell the user a text file is a
        RAR archive just because somebody renamed it.
        """
        return self.format_source in ("content", "sfx")

    @property
    def mislabelled(self) -> bool:
        """Named like an archive, but the bytes say it is something else."""
        return bool(self.content) and not self.confirmed

    @property
    def named_like_archive(self) -> bool:
        return looks_like_archive(self.path)

    @property
    def missing_tool(self) -> bool:
        return bool(self.tool) and not self.tool_installed

    def rows(self) -> list[tuple[str, str]]:
        """The fact table shown in the dialog, in a fixed, readable order."""
        rows: list[tuple[str, str]] = [("File", os.path.basename(self.path))]
        rows.append(("Folder", os.path.dirname(self.path) or "/"))
        if not self.exists:
            rows.append(("Status", "does not exist"))
            return rows
        rows.append(("Type", _KIND_LABELS.get(self.kind, self.kind)))
        if self.link_target:
            rows.append(
                ("Points to",
                 self.link_target + (" (broken)" if self.broken_link else ""))
            )
        if self.kind == "file":
            size = format_size_short(self.size)
            if self.size >= 1024:
                size += f"  ({self.size:,} bytes)".replace(",", " ")
            rows.append(("Size", size))
        if self.mtime:
            rows.append(("Modified", self.mtime.strftime("%Y-%m-%d %H:%M:%S")))
        rows.append(("Readable", "yes" if self.readable else "no"))
        if self.is_archive:
            rows.append(("Detected as", f"{self.format.label} "
                                        f"({_SOURCE_LABELS[self.format_source]})"))
        if self.content:
            rows.append(("Content", self.content))
        elif not self.is_archive and self.size:
            rows.append(("Content", "no recognised file signature"))
        if self.extension:
            rows.append(("Extension", self.extension))
        if self.volume > 1:
            rows.append(("Volume", f"part {self.volume} of a multi-volume set"))
        if self.tool:
            rows.append(
                ("Needs", f"{self.tool}: "
                          + ("installed" if self.tool_installed else "NOT installed"))
            )
        return rows


@dataclass
class Problem:
    """A failure, described well enough to act on."""

    kind: str = "failed"
    title: str = "LinRAR"
    headline: str = "The file could not be opened."
    explanation: str = ""
    facts: list[tuple[str, str]] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    details: str = ""
    actions: list[str] = field(default_factory=list)

    def as_text(self) -> str:
        """The whole report as plain text, for the clipboard and the terminal."""
        out = [self.headline, ""]
        if self.explanation:
            out += [self.explanation, ""]
        if self.facts:
            width = max(len(name) for name, _ in self.facts)
            out += [f"  {name:<{width}}  {value}" for name, value in self.facts]
            out.append("")
        if self.suggestions:
            out.append("What you can do:")
            out += [f"  - {line}" for line in self.suggestions]
            out.append("")
        if self.details:
            out += ["Technical details:", self.details]
        return "\n".join(out).strip() + "\n"


_KIND_LABELS = {
    "file": "regular file",
    "directory": "folder",
    "socket": "socket (not a file)",
    "fifo": "named pipe (not a file)",
    "block": "block device",
    "char": "character device",
    "missing": "missing",
    "unknown": "unknown",
}

_SOURCE_LABELS = {
    "content": "by its contents",
    "sfx": "self-extracting archive",
    "name": "by its name only",
    "": "not recognised",
}


# ----------------------------------------------------------------------
# inspection
# ----------------------------------------------------------------------


def inspect_path(path: str) -> FileFacts:
    """Learn everything cheap about *path*.  Never raises."""
    path = os.path.abspath(os.path.expanduser(path))
    facts = FileFacts(path=path, extension=os.path.splitext(path)[1].lower())

    try:
        link_stat = os.lstat(path)
    except OSError as exc:
        facts.error = str(exc)
        # ENOENT is the ordinary case; anything else (a dead mount, a
        # permission wall on the parent) still leaves us with a name to show.
        return facts

    facts.exists = True
    if stat_module.S_ISLNK(link_stat.st_mode):
        try:
            facts.link_target = os.readlink(path)
        except OSError:
            facts.link_target = "?"
        facts.broken_link = not os.path.exists(path)

    try:
        info = os.stat(path)
    except OSError as exc:
        facts.error = str(exc)
        facts.kind = "symlink" if facts.link_target else "unknown"
        return facts

    mode = info.st_mode
    facts.kind = (
        "directory" if stat_module.S_ISDIR(mode)
        else "file" if stat_module.S_ISREG(mode)
        else "socket" if stat_module.S_ISSOCK(mode)
        else "fifo" if stat_module.S_ISFIFO(mode)
        else "block" if stat_module.S_ISBLK(mode)
        else "char" if stat_module.S_ISCHR(mode)
        else "unknown"
    )
    facts.size = info.st_size
    facts.readable = os.access(path, os.R_OK)
    try:
        facts.mtime = datetime.fromtimestamp(info.st_mtime)
    except (OverflowError, OSError, ValueError):
        facts.mtime = None

    if facts.kind != "file":
        return facts

    try:
        with open(path, "rb") as handle:
            facts.magic = handle.read(_DUMP_BYTES)
    except OSError as exc:
        facts.error = str(exc)
        return facts

    if facts.readable:
        facts.format, facts.format_source = detect_format_source(path)
    # Worked out even when a format was found, unless the format was proven by
    # the contents: that is what tells a real archive from a renamed one.
    if not facts.confirmed:
        facts.content = _identify_content(facts.magic)

    facts.volume = volume_number(path)
    if facts.volume > 1:
        facts.first_volume = first_volume(path)

    facts.tool, facts.package, facts.tool_installed = REGISTRY.requirement(
        facts.format
    )
    return facts


def _identify_content(magic: bytes) -> str:
    """A readable name for what the leading bytes look like."""
    if not magic:
        return "empty"
    for signature, label in _CONTENT_SIGNATURES:
        if magic.startswith(signature):
            return label
    if _looks_like_text(magic):
        return "plain text"
    return ""


def _looks_like_text(data: bytes) -> bool:
    if b"\x00" in data:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        # A cut multi-byte character at the end of the window is not binary.
        try:
            data[:-3].decode("utf-8")
        except UnicodeDecodeError:
            return False
    printable = sum(1 for byte in data if byte in (9, 10, 13) or 32 <= byte < 127)
    return bool(data) and printable / len(data) > 0.85


def hexdump(data: bytes, limit: int = _DUMP_BYTES) -> str:
    """A classic offset / hex / ASCII dump of the first bytes of a file."""
    lines = []
    for offset in range(0, min(len(data), limit), 16):
        chunk = data[offset : offset + 16]
        hex_part = " ".join(f"{byte:02X}" for byte in chunk).ljust(47)
        text = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{offset:08X}  {hex_part}  {text}")
    return "\n".join(lines) or "(the file is empty)"


# ----------------------------------------------------------------------
# turning facts into a report
# ----------------------------------------------------------------------


def describe(path: str, error: Optional[BaseException] = None) -> Problem:
    """Explain why *path* could not be opened as an archive.

    *error* is whatever the backend raised, if it got that far; the facts about
    the file are gathered either way, because the tool's own message is usually
    the least informative part of the answer.
    """
    facts = inspect_path(path)
    problem = _structural_problem(facts)
    if problem is None:
        problem = _archive_problem(facts, error)
    problem.facts = facts.rows()
    problem.details = _details(facts, error)
    return problem


def _structural_problem(facts: FileFacts) -> Optional[Problem]:
    """Everything that is wrong before the format even matters."""
    name = os.path.basename(facts.path)

    if not facts.exists:
        return Problem(
            kind="missing",
            title="File not found",
            headline=f"There is no file called '{name}' here.",
            explanation=(
                "It may have been moved, renamed or deleted since the folder "
                "was last listed, or the drive it lives on may no longer be "
                "mounted."
            ),
            suggestions=[
                "List the folder again (F5) to see what is really there.",
                "Check the folder in the address bar is the one you expect.",
                "If the file is on a removable or network drive, make sure it "
                "is still mounted.",
            ],
            actions=[ACTION_PARENT, ACTION_RETRY],
        )

    if facts.broken_link:
        return Problem(
            kind="broken-link",
            title="Broken link",
            headline=f"'{name}' is a link that points nowhere.",
            explanation=(
                f"The link leads to '{facts.link_target}', and there is "
                "nothing there. Whatever it pointed at has been moved or "
                "deleted."
            ),
            suggestions=[
                "Open the file the link was meant to point at directly.",
                "Delete the link if it is no longer useful.",
            ],
            actions=[ACTION_PARENT],
        )

    if facts.kind == "directory":
        return Problem(
            kind="directory",
            title="That is a folder",
            headline=f"'{name}' is a folder, not an archive.",
            explanation=(
                "LinRAR browses folders rather than opening them: press Enter "
                "or double-click to step inside."
            ),
            suggestions=[
                "Select the folder and press Add (Alt+A) to compress it.",
            ],
            actions=[],
        )

    if facts.kind not in ("file", "symlink"):
        return Problem(
            kind="not-a-file",
            title="Not a file",
            headline=f"'{name}' is {_KIND_LABELS.get(facts.kind, facts.kind)}.",
            explanation=(
                "It is not a regular file, so there is nothing in it to read "
                "as an archive. Devices, sockets and pipes only look like "
                "files in the listing."
            ),
            suggestions=["Choose a regular file."],
            actions=[ACTION_PARENT],
        )

    if not facts.readable:
        owner = ""
        try:
            import pwd

            owner = pwd.getpwuid(os.stat(facts.path).st_uid).pw_name
        except Exception:  # pragma: no cover - a numeric uid is fine too
            owner = ""
        return Problem(
            kind="permission",
            title="Permission denied",
            headline=f"You do not have permission to read '{name}'.",
            explanation=(
                "The file exists, but its permissions do not let this user "
                "open it"
                + (f"; it belongs to {owner}." if owner else ".")
            ),
            suggestions=[
                "Ask the owner of the file, or an administrator, for access.",
                f"From a terminal:  sudo chmod +r {facts.path}",
            ],
            actions=[ACTION_PARENT],
        )

    if facts.size == 0:
        return Problem(
            kind="empty",
            title="Empty file",
            headline=f"'{name}' is empty.",
            explanation=(
                "The file is zero bytes long, so there is nothing in it at "
                "all. That usually means a download or a copy was interrupted "
                "before any data arrived."
            ),
            suggestions=[
                "Download or copy the file again.",
                "Check there is free space on the drive it was written to.",
            ],
            actions=[ACTION_PARENT],
        )
    return None


def _archive_problem(
    facts: FileFacts, error: Optional[BaseException]
) -> Problem:
    """The file is readable and has content, so what is wrong with it?"""
    name = os.path.basename(facts.path)

    # A part of a volume set, opened on its own.
    if facts.volume > 1 and (error is not None or not facts.is_archive):
        target = os.path.basename(facts.first_volume) if facts.first_volume else ""
        return Problem(
            kind="volume",
            title="Part of a multi-volume archive",
            headline=f"'{name}' is part {facts.volume} of a split archive.",
            explanation=(
                "A split archive is opened through its first volume, which "
                "carries the index of everything in the set. The other parts "
                "hold data only and cannot be opened on their own."
                + (f"\n\nThe first volume is '{target}', in the same folder."
                   if target else
                   "\n\nThe first volume is not in this folder, so the set is "
                   "incomplete.")
            ),
            suggestions=(
                [f"Open '{target}' instead."] if target else
                ["Find the first volume of the set and open that one.",
                 "Every part of the set must be in the same folder."]
            ),
            actions=([ACTION_FIRST_VOLUME] if facts.first_volume else [])
            + [ACTION_PARENT],
        )

    # A format we know, but the program that reads it is not installed.
    if facts.missing_tool:
        return Problem(
            kind="no-tool",
            title="A tool is missing",
            headline=(
                f"'{name}' is {_article(facts.format.label)} archive, and the "
                f"'{facts.tool}' command that opens it is not installed."
            ),
            explanation=(
                "LinRAR drives the standard Linux archive tools rather than "
                f"reimplementing them, so {facts.format.label} archives need "
                f"'{facts.tool}' to be present. Everything else about the "
                "file is fine."
            ),
            suggestions=[
                "Open the Dependencies manager and install it: LinRAR knows "
                "the package name for your distribution.",
                f"Or install it by hand:  sudo apt install {facts.package}",
            ],
            actions=[ACTION_DEPENDENCIES],
        )

    # Not an archive at all: either nothing matched, or the name promised one
    # format while the bytes plainly say something else.
    if not facts.is_archive or facts.mislabelled:
        what = facts.content or "not in any format LinRAR recognises"
        misleading = (
            facts.named_like_archive
            and facts.extension
            and facts.content
        )
        explanation = (
            f"LinRAR read the start of the file and it is {what}. "
            if facts.content
            else "LinRAR read the start of the file and found no archive "
                 "signature in it: no RAR, ZIP, 7z, tar, gzip or any of the "
                 "other formats it knows. "
        )
        if misleading:
            explanation += (
                f"The name ends in '{facts.extension}', but the contents do "
                "not match, so the file has been renamed, is a different kind "
                "of file altogether, or was damaged in transit."
            )
        else:
            explanation += (
                "Archives are identified by their contents, not their names, "
                "so renaming the file will not help."
            )
        suggestions = ["Open it with the application that normally handles it."]
        if facts.content == "plain text" or (
            facts.content or "").startswith(("an HTML", "an XML")):
            suggestions.insert(
                0,
                "View it inside LinRAR to see what it really is: a failed "
                "download is often an error page saved under the right name.",
            )
        suggestions.append(
            "If it should be an archive, download or copy it again: a "
            "truncated transfer looks exactly like this."
        )
        return Problem(
            kind="not-archive",
            title="Not an archive",
            headline=f"'{name}' is not an archive LinRAR can open.",
            explanation=explanation,
            suggestions=suggestions,
            actions=[ACTION_VIEW, ACTION_OPEN_EXTERNAL],
        )

    # It is an archive, of a format we can read, and it still failed.
    return _backend_failure(facts, error)


def _backend_failure(facts: FileFacts, error: Optional[BaseException]) -> Problem:
    name = os.path.basename(facts.path)
    message = getattr(error, "message", None) or (str(error) if error else "")

    if isinstance(error, PasswordRequired):
        return Problem(
            kind="password",
            title="Password required",
            headline=f"'{name}' is encrypted.",
            explanation=(
                "The archive's file names are encrypted too, so nothing in it "
                "can be listed until the right password is given."
            ),
            suggestions=[
                "Enter the password when LinRAR asks for it.",
                "Passwords are case sensitive, and a wrong one is "
                "indistinguishable from a damaged archive to the tool.",
            ],
            actions=[],
        )

    truncated = facts.format_source == "content" and facts.size < 128
    explanation = (
        f"The file starts like {_article(facts.format.label)} archive, so it "
        "is the right kind of file, but reading it failed."
    )
    if truncated:
        explanation += (
            " At only "
            f"{facts.size} bytes it is far too short to be a complete one: "
            "the transfer that produced it almost certainly stopped early."
        )
    if message:
        explanation += f"\n\nThe tool reported:\n{message.strip()}"

    suggestions = [
        "Test the archive (Alt+T) to find out how much of it is readable.",
        "If it has a recovery record, Repair (Alt+R) can rebuild it.",
        "Download or copy the archive again: this is what a truncated or "
        "corrupted transfer looks like.",
    ]
    if facts.volume:
        suggestions.insert(
            0, "Check that every volume of the set is present in this folder."
        )
    return Problem(
        kind="damaged",
        title="The archive could not be read",
        headline=f"'{name}' could not be read.",
        explanation=explanation,
        suggestions=suggestions,
        actions=[ACTION_REPAIR] if facts.format in (
            ArchiveFormat.RAR5, ArchiveFormat.RAR4
        ) else [],
    )


def _details(facts: FileFacts, error: Optional[BaseException]) -> str:
    """The technical block: exactly what LinRAR saw, for a bug report."""
    lines = [f"path        {facts.path}"]
    lines.append(f"kind        {facts.kind}")
    lines.append(f"size        {facts.size} bytes")
    lines.append(f"readable    {facts.readable}")
    if facts.link_target:
        lines.append(f"symlink     -> {facts.link_target}")
    lines.append(
        f"detected    {facts.format.name} "
        f"({_SOURCE_LABELS[facts.format_source]})"
    )
    if facts.content:
        lines.append(f"content     {facts.content}")
    if facts.volume:
        lines.append(f"volume      part {facts.volume}")
    if facts.tool:
        lines.append(
            f"tool        {facts.tool} "
            f"({'found' if facts.tool_installed else 'not found'})"
        )
    if facts.error:
        lines.append(f"os error    {facts.error}")
    if error is not None:
        lines.append(f"exception   {type(error).__name__}")
        code = getattr(error, "code", None)
        if code is not None and code != -1:
            lines.append(f"exit code   {code}")
        message = getattr(error, "message", None) or str(error)
        if message:
            lines.append("message     " + message.strip().replace("\n", "\n            "))
        output = getattr(error, "output", "")
        if output:
            tail = output.strip().splitlines()[-20:]
            lines.append("output      " + "\n            ".join(tail))
    if facts.magic:
        lines.append("")
        lines.append("first bytes:")
        lines.append(hexdump(facts.magic))
    lines.append("")
    lines.append("tools:")
    lines.append("  " + REGISTRY.describe_tools().replace("\n", "\n  "))
    return "\n".join(lines)


def _article(label: str) -> str:
    return ("an " if label[:1].upper() in "AEIOU78" else "a ") + label


# ----------------------------------------------------------------------
# the other two things that fail to open
# ----------------------------------------------------------------------


def describe_folder(path: str) -> Problem:
    """Why a folder could not be listed."""
    facts = inspect_path(path)
    name = os.path.basename(path.rstrip("/")) or path
    nearest = nearest_existing(path)

    if not facts.exists:
        return Problem(
            kind="missing",
            title="Folder not found",
            headline=f"The folder '{name}' no longer exists.",
            explanation=(
                f"Nothing is at {path} any more. It may have been renamed or "
                "deleted, or it may be on a drive that is no longer mounted."
                + (f"\n\nThe nearest folder that does exist is {nearest}."
                   if nearest else "")
            ),
            facts=facts.rows(),
            suggestions=(
                [f"Go to {nearest} instead."] if nearest else []
            ) + ["Check whether the drive is still mounted."],
            actions=[ACTION_PARENT] if nearest else [],
            details=_details(facts, None),
        )

    if facts.kind != "directory":
        return Problem(
            kind="not-a-folder",
            title="Not a folder",
            headline=f"'{name}' is not a folder.",
            explanation=(
                f"It is {_KIND_LABELS.get(facts.kind, facts.kind)}, so there "
                "is nothing in it to list."
            ),
            facts=facts.rows(),
            suggestions=["Open its parent folder instead."],
            actions=[ACTION_PARENT],
            details=_details(facts, None),
        )

    return Problem(
        kind="permission",
        title="Permission denied",
        headline=f"You do not have permission to open '{name}'.",
        explanation=(
            "The folder exists, but this user may not list it. Opening a "
            "folder needs both read and execute permission on it."
        ),
        facts=facts.rows(),
        suggestions=[
            "Ask an administrator for access to the folder.",
            f"From a terminal:  ls -ld {path}   shows who owns it.",
        ] + ([f"Go to {nearest} instead."] if nearest else []),
        actions=[ACTION_PARENT] if nearest else [],
        details=_details(facts, None),
    )


def describe_no_handler(path: str) -> Problem:
    """No desktop application claimed a file LinRAR was asked to open."""
    facts = inspect_path(path)
    name = os.path.basename(path)
    what = facts.content or "of an unrecognised kind"
    return Problem(
        kind="no-handler",
        title="Nothing opened it",
        headline=f"Nothing on this system opens '{name}'.",
        explanation=(
            f"LinRAR handed the file to the desktop, which has no application "
            f"registered for it. The file itself is fine: it is {what}"
            + (f", {format_size_short(facts.size)} in size." if facts.size
               else ".")
            + "\n\nThis is also what happens when no desktop session is "
            "running, for instance over a plain SSH connection."
        ),
        facts=facts.rows(),
        suggestions=[
            "View it inside LinRAR, which shows text and a hex dump of "
            "anything else.",
            "Install an application that handles this kind of file, then try "
            "again.",
            "Set a default application for it in your desktop's file manager.",
        ],
        actions=[ACTION_VIEW],
        details=_details(facts, None),
    )


def nearest_existing(path: str) -> str:
    """The closest ancestor of *path* that exists and can be listed."""
    probe = os.path.abspath(os.path.expanduser(path))
    seen = set()
    while probe and probe not in seen:
        seen.add(probe)
        if os.path.isdir(probe) and os.access(probe, os.R_OK | os.X_OK):
            return probe
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent
    home = os.path.expanduser("~")
    return home if os.path.isdir(home) else "/"


def summarise(path: str, error: Optional[BaseException] = None) -> str:
    """The whole report as text: what the command line prints."""
    return describe(path, error).as_text()


__all__ = [
    "ACTION_DEPENDENCIES",
    "ACTION_FIRST_VOLUME",
    "ACTION_OPEN_EXTERNAL",
    "ACTION_PARENT",
    "ACTION_REPAIR",
    "ACTION_RETRY",
    "ACTION_VIEW",
    "FileFacts",
    "Problem",
    "describe",
    "describe_folder",
    "describe_no_handler",
    "hexdump",
    "inspect_path",
    "nearest_existing",
    "summarise",
]
