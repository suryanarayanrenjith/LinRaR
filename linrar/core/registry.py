"""Archive format sniffing and backend selection.

Detection is by content first and by extension second, because the extension is
the one thing about a file anybody can change.  A file that *is* an archive is
opened whatever it is called, and a ``.rar`` that is really a JPEG is reported
as a JPEG rather than as a broken RAR: see :mod:`linrar.core.diagnose`, which
turns what is learned here into something a person can act on.
"""

from __future__ import annotations

import os
import re

from .backends.base import ArchiveBackend
from .backends.rar import RarBackend
from .backends.sevenzip import SevenZipBackend
from .backends.zip import ZipBackend
from .models import ArchiveFormat, OperationError

# Signatures checked at offset 0, longest first so a prefix never shadows a
# more specific match.
_MAGIC: tuple[tuple[bytes, ArchiveFormat], ...] = (
    (b"Rar!\x1a\x07\x01\x00", ArchiveFormat.RAR5),
    (b"Rar!\x1a\x07\x00", ArchiveFormat.RAR4),
    (b"PK\x03\x04", ArchiveFormat.ZIP),
    (b"PK\x05\x06", ArchiveFormat.ZIP),
    (b"PK\x07\x08", ArchiveFormat.ZIP),
    (b"7z\xbc\xaf\x27\x1c", ArchiveFormat.SEVENZIP),
    (b"\xfd7zXZ\x00", ArchiveFormat.XZ),
    (b"\x1f\x8b", ArchiveFormat.GZIP),
    (b"BZh", ArchiveFormat.BZIP2),
    (b"\x28\xb5\x2f\xfd", ArchiveFormat.ZSTD),
    (b"MSCF", ArchiveFormat.CAB),
    # -- read-only formats, all handled by 7-Zip --
    (b"\x1f\x9d", ArchiveFormat.COMPRESS),
    (b"LZIP", ArchiveFormat.LZIP),
    (b"\x04\x22\x4d\x18", ArchiveFormat.LZ4),
    (b"\x60\xea", ArchiveFormat.ARJ),
    (b"\xed\xab\xee\xdb", ArchiveFormat.RPM),
    (b"MSWIM\x00\x00\x00", ArchiveFormat.WIM),
    (b"hsqs", ArchiveFormat.SQUASHFS),
    (b"sqsh", ArchiveFormat.SQUASHFS),
    (b"070701", ArchiveFormat.CPIO),
    (b"070702", ArchiveFormat.CPIO),
    (b"070707", ArchiveFormat.CPIO),
    (b"\xc7\x71", ArchiveFormat.CPIO),
    (b"!<arch>\ndebian", ArchiveFormat.DEB),
    (b"!<arch>\n", ArchiveFormat.AR),
)

#: Signatures that are shared with things nobody wants opened as an archive.
#: An OLE compound file is an ``.msi`` *and* every legacy Word and Excel
#: document; raw LZMA has no real magic at all.  These only count when the name
#: agrees, so double-clicking a ``.doc`` still opens the word processor.
_AMBIGUOUS_MAGIC: tuple[tuple[bytes, ArchiveFormat, tuple[str, ...]], ...] = (
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", ArchiveFormat.MSI, (".msi", ".msp")),
    (b"\x5d\x00\x00", ArchiveFormat.LZMA, (".lzma", ".tlz")),
)

#: Formats whose signature is at the end of the file, or nowhere: taken on the
#: strength of the extension alone.
_TRAILER_FORMATS = {
    ".dmg": ArchiveFormat.DMG,
    ".vhd": ArchiveFormat.VHD,
    ".vhdx": ArchiveFormat.VHD,
}

ARCHIVE_EXTENSIONS = {
    ".rar", ".rev", ".r00", ".cbr",
    ".zip", ".zipx", ".jar", ".cbz", ".apk", ".epub", ".xpi", ".whl",
    ".7z", ".cb7",
    ".tar", ".gz", ".tgz", ".bz2", ".tbz", ".tbz2", ".xz", ".txz",
    ".zst", ".tzst", ".lzma", ".tlz", ".lz", ".lz4", ".cab", ".iso",
    ".arj", ".lzh", ".lha", ".ace", ".uue", ".z", ".sfx", ".appimage",
    ".deb", ".udeb", ".rpm", ".ar", ".a", ".cpio", ".wim", ".swm", ".esd",
    ".dmg", ".msi", ".msp", ".squashfs", ".sfs", ".snap", ".vhd", ".vhdx",
    ".img", ".udf", ".xar", ".pkg",
}

#: ``archive.part03.rar`` / ``archive.r02`` / ``archive.7z.002``: the volume
#: naming schemes rar and 7z produce.  Only the first volume of a set can be
#: opened, so recognising the others is what lets LinRAR redirect instead of
#: handing the user unrar's "cannot find volume" wording.
_VOLUME_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^(?P<stem>.+)\.part(?P<num>\d+)\.rar$", re.I), "part"),
    (re.compile(r"^(?P<stem>.+)\.r(?P<num>\d{2,})$", re.I), "r"),
    (re.compile(r"^(?P<stem>.+\.[0-9a-z]+)\.(?P<num>\d{3})$", re.I), "numeric"),
)

# How far into a self-extracting stub we look for the embedded archive header.
# AppImage SFX files carry a SquashFS image (with a bundled extractor) before
# the payload, so the scan must reach well past the first couple of megabytes.
_SFX_SCAN_BYTES = 24 * 1024 * 1024
_SFX_CHUNK = 1024 * 1024

# Extensions that plausibly hide an executable self-extracting stub.  The deep
# scan is limited to these (or files that start like an executable) so listing
# folders and double-clicking ordinary files stays fast.
_SFX_EXTENSIONS = {".sfx", ".exe", ".appimage", ".run", ".bin", ""}


def detect_format(path: str) -> ArchiveFormat:
    """Identify an archive by content, falling back to its extension."""
    return _detect(path)[0]


def detect_format_source(path: str) -> tuple[ArchiveFormat, str]:
    """As :func:`detect_format`, but also *how* the answer was reached.

    The source is one of ``"content"``, ``"sfx"``, ``"name"`` or ``""``, and is
    what lets an error message distinguish "this file is not an archive" from
    "this file is only called one".
    """
    return _detect(path)


def _detect(path: str) -> tuple[ArchiveFormat, str]:
    ext = os.path.splitext(path.lower())[1]
    try:
        with open(path, "rb") as handle:
            head = handle.read(65536)
    except OSError:
        return _format_from_extension(path), "name"

    if not head:
        return ArchiveFormat.UNKNOWN, ""

    for magic, fmt in _MAGIC:
        if head.startswith(magic):
            return fmt, "content"

    for magic, fmt, extensions in _AMBIGUOUS_MAGIC:
        if head.startswith(magic) and ext in extensions:
            return fmt, "content"

    # POSIX tar keeps its magic at offset 257.
    if len(head) > 262 and head[257:262] in (b"ustar",):
        return ArchiveFormat.TAR, "content"

    # LZH/LHA writes "-lh0-" .. "-lh7-" at offset 2.
    if len(head) > 7 and head[2:4] == b"-l" and head[6:7] == b"-":
        return ArchiveFormat.LZH, "content"

    # ISO 9660 stores "CD001" in the primary volume descriptor.
    try:
        with open(path, "rb") as handle:
            handle.seek(32769)
            if handle.read(5) == b"CD001":
                return ArchiveFormat.ISO, "content"
    except OSError:
        pass

    # Self-extracting archives bury the real header behind an executable stub.
    looks_executable = head.startswith((b"\x7fELF", b"MZ", b"#!"))
    if ext in _SFX_EXTENSIONS or looks_executable:
        embedded = _scan_for_sfx(path)
        if embedded is not ArchiveFormat.UNKNOWN:
            return embedded, "sfx"

    if ext in _TRAILER_FORMATS:
        return _TRAILER_FORMATS[ext], "name"

    by_name = _format_from_extension(path)
    return by_name, "name" if by_name is not ArchiveFormat.UNKNOWN else ""


def _scan_for_sfx(path: str) -> ArchiveFormat:
    """Search the leading part of a file for an embedded RAR/7z signature.

    Reads in chunks (with a small overlap so a signature split across a chunk
    boundary is still found) instead of loading the whole window at once.
    """
    overlap = 8
    scanned = 0
    tail = b""
    try:
        with open(path, "rb") as handle:
            while scanned < _SFX_SCAN_BYTES:
                chunk = handle.read(_SFX_CHUNK)
                if not chunk:
                    break
                window = tail + chunk
                index = window.find(b"Rar!\x1a\x07")
                if index >= 0:
                    if window[index : index + 8].startswith(b"Rar!\x1a\x07\x01\x00"):
                        return ArchiveFormat.RAR5
                    return ArchiveFormat.RAR4
                if window.find(b"7z\xbc\xaf\x27\x1c") >= 0:
                    return ArchiveFormat.SEVENZIP
                tail = window[-overlap:]
                scanned += len(chunk)
    except OSError:
        pass
    return ArchiveFormat.UNKNOWN


def _format_from_extension(path: str) -> ArchiveFormat:
    lower = path.lower()
    ext = os.path.splitext(lower)[1]
    mapping = {
        ".rar": ArchiveFormat.RAR5,
        ".cbr": ArchiveFormat.RAR5,
        ".rev": ArchiveFormat.RAR5,
        ".sfx": ArchiveFormat.RAR5,
        ".zip": ArchiveFormat.ZIP,
        ".zipx": ArchiveFormat.ZIP,
        ".jar": ArchiveFormat.ZIP,
        ".cbz": ArchiveFormat.ZIP,
        ".apk": ArchiveFormat.ZIP,
        ".epub": ArchiveFormat.ZIP,
        ".xpi": ArchiveFormat.ZIP,
        ".whl": ArchiveFormat.ZIP,
        ".7z": ArchiveFormat.SEVENZIP,
        ".cb7": ArchiveFormat.SEVENZIP,
        ".tar": ArchiveFormat.TAR,
        ".gz": ArchiveFormat.GZIP,
        ".tgz": ArchiveFormat.GZIP,
        ".bz2": ArchiveFormat.BZIP2,
        ".tbz": ArchiveFormat.BZIP2,
        ".tbz2": ArchiveFormat.BZIP2,
        ".xz": ArchiveFormat.XZ,
        ".txz": ArchiveFormat.XZ,
        ".zst": ArchiveFormat.ZSTD,
        ".tzst": ArchiveFormat.ZSTD,
        ".cab": ArchiveFormat.CAB,
        ".iso": ArchiveFormat.ISO,
        ".img": ArchiveFormat.ISO,
        ".udf": ArchiveFormat.ISO,
        ".lzma": ArchiveFormat.LZMA,
        ".tlz": ArchiveFormat.LZMA,
        ".lz": ArchiveFormat.LZIP,
        ".lz4": ArchiveFormat.LZ4,
        ".z": ArchiveFormat.COMPRESS,
        ".arj": ArchiveFormat.ARJ,
        ".lzh": ArchiveFormat.LZH,
        ".lha": ArchiveFormat.LZH,
        ".deb": ArchiveFormat.DEB,
        ".udeb": ArchiveFormat.DEB,
        ".rpm": ArchiveFormat.RPM,
        ".ar": ArchiveFormat.AR,
        ".a": ArchiveFormat.AR,
        ".cpio": ArchiveFormat.CPIO,
        ".wim": ArchiveFormat.WIM,
        ".swm": ArchiveFormat.WIM,
        ".esd": ArchiveFormat.WIM,
        ".dmg": ArchiveFormat.DMG,
        ".msi": ArchiveFormat.MSI,
        ".msp": ArchiveFormat.MSI,
        ".squashfs": ArchiveFormat.SQUASHFS,
        ".sfs": ArchiveFormat.SQUASHFS,
        ".snap": ArchiveFormat.SQUASHFS,
        ".vhd": ArchiveFormat.VHD,
        ".vhdx": ArchiveFormat.VHD,
    }
    if re_match := mapping.get(ext):
        return re_match
    # "archive.part01.rar" and friends.
    if ".rar" in lower or ".r0" in lower:
        return ArchiveFormat.RAR5
    return ArchiveFormat.UNKNOWN


def looks_like_archive(path: str) -> bool:
    """Cheap extension test used for file-list icons (no I/O)."""
    return os.path.splitext(path.lower())[1] in ARCHIVE_EXTENSIONS


def volume_number(path: str) -> int:
    """Which part of a volume set *path* is, or 0 when it is not one.

    The first volume answers 1, so ``number > 1`` means "this cannot be opened
    on its own".
    """
    name = os.path.basename(path)
    for pattern, scheme in _VOLUME_PATTERNS:
        match = pattern.match(name)
        if not match:
            continue
        try:
            number = int(match.group("num"))
        except ValueError:
            continue
        # "foo.r00" is the *second* part: "foo.rar" holds the first.
        return number + 2 if scheme == "r" else number
    return 0


def first_volume(path: str) -> str:
    """The path of the first volume of *path*'s set, or "" if there is none.

    Only returns a file that actually exists, so a caller can offer to open it
    without checking again.
    """
    folder = os.path.dirname(path)
    name = os.path.basename(path)
    for pattern, scheme in _VOLUME_PATTERNS:
        match = pattern.match(name)
        if not match:
            continue
        stem = match.group("stem")
        digits = len(match.group("num"))
        if scheme == "part":
            candidates = [f"{stem}.part{'1'.zfill(width)}.rar"
                          for width in (digits, 1, 2, 3)]
        elif scheme == "r":
            candidates = [f"{stem}.rar"]
        else:
            candidates = [f"{stem}.{'1'.zfill(digits)}", f"{stem}.001"]
        for candidate in candidates:
            full = os.path.join(folder, candidate)
            if os.path.isfile(full) and full != path:
                return full
    return ""


class BackendRegistry:
    """Chooses the right backend for a format and reports what is installed."""

    def __init__(self) -> None:
        self.rar = RarBackend()
        self.zip = ZipBackend()
        self.sevenzip = SevenZipBackend()

    def refresh(self) -> None:
        """Re-probe the tool paths.

        Backends resolve their executables once at construction, so this must
        be called after the user installs or removes a dependency.
        """
        self.rar = RarBackend()
        self.sevenzip = SevenZipBackend()

    def for_format(self, fmt: ArchiveFormat) -> ArchiveBackend:
        if fmt in (ArchiveFormat.RAR5, ArchiveFormat.RAR4):
            if not self.rar.available:
                raise OperationError(
                    "RAR archives need the 'unrar' command, which was not "
                    "found on this system.\n\nInstall it from the "
                    "Dependencies manager, or by hand:\n"
                    "    sudo apt install unrar"
                )
            return self.rar
        if fmt is ArchiveFormat.ZIP:
            # Prefer the in-process reader; fall back to 7z for exotic ZIPs.
            return self.zip
        if fmt is ArchiveFormat.UNKNOWN:
            raise OperationError(
                "The file format is not recognised or the file is not an archive."
            )
        if not self.sevenzip.available:
            raise OperationError(
                f"{fmt.label} archives require the '7z' command, which was not "
                "found.\n\nInstall it from the Dependencies manager, or by "
                "hand:\n    sudo apt install p7zip-full"
            )
        return self.sevenzip

    def for_path(self, path: str) -> tuple[ArchiveBackend, ArchiveFormat]:
        fmt = detect_format(path)
        return self.for_format(fmt), fmt

    def requirement(self, fmt: ArchiveFormat) -> tuple[str, str, bool]:
        """``(tool, package, installed)`` for the tool that opens *fmt*.

        ``tool`` is "" for the formats LinRAR handles in-process, which is the
        answer that stops an error message blaming a missing program for
        something that is really a damaged file.
        """
        if fmt in (ArchiveFormat.RAR5, ArchiveFormat.RAR4):
            return "unrar", "unrar", self.rar.available
        if fmt is ArchiveFormat.ZIP:
            return "", "", True
        if fmt is ArchiveFormat.UNKNOWN:
            return "", "", True
        return "7z", "p7zip-full", self.sevenzip.available

    def creatable_formats(self) -> list[ArchiveFormat]:
        """Formats offered in the archive dialog's format selector."""
        formats = []
        if self.rar.rar:
            formats.extend([ArchiveFormat.RAR5, ArchiveFormat.RAR4])
        formats.append(ArchiveFormat.ZIP)
        if self.sevenzip.available:
            formats.append(ArchiveFormat.SEVENZIP)
        return formats

    def describe_tools(self) -> str:
        """Human readable summary of every tool LinRAR can drive."""
        from . import tools

        return "\n".join(
            f"{name + ':':<7}{path or 'not found'}"
            for name, path in (
                ("rar", self.rar.rar),
                ("unrar", self.rar.unrar),
                ("7z", self.sevenzip.exe),
                ("zip", tools.find("zip")),
            )
        )


REGISTRY = BackendRegistry()
