"""Archive format sniffing and backend selection."""

from __future__ import annotations

import os

from .backends.base import ArchiveBackend
from .backends.rar import RarBackend
from .backends.sevenzip import SevenZipBackend
from .backends.zip import ZipBackend
from .models import ArchiveFormat, OperationError

# Signatures checked at offset 0.
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
)

ARCHIVE_EXTENSIONS = {
    ".rar", ".rev", ".r00", ".cbr",
    ".zip", ".zipx", ".jar", ".cbz", ".apk", ".epub", ".xpi", ".whl",
    ".7z", ".cb7",
    ".tar", ".gz", ".tgz", ".bz2", ".tbz", ".tbz2", ".xz", ".txz",
    ".zst", ".tzst", ".lzma", ".cab", ".iso", ".arj", ".lzh", ".lha",
    ".ace", ".uue", ".z", ".sfx", ".appimage",
}

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
    try:
        with open(path, "rb") as handle:
            head = handle.read(65536)
    except OSError:
        return _format_from_extension(path)

    if not head:
        return ArchiveFormat.UNKNOWN

    for magic, fmt in _MAGIC:
        if head.startswith(magic):
            return fmt

    # POSIX tar keeps its magic at offset 257.
    if len(head) > 262 and head[257:262] in (b"ustar",):
        return ArchiveFormat.TAR

    # ISO 9660 stores "CD001" in the primary volume descriptor.
    try:
        with open(path, "rb") as handle:
            handle.seek(32769)
            if handle.read(5) == b"CD001":
                return ArchiveFormat.ISO
    except OSError:
        pass

    # Self-extracting archives bury the real header behind an executable stub.
    ext = os.path.splitext(path.lower())[1]
    looks_executable = head.startswith((b"\x7fELF", b"MZ", b"#!"))
    if ext in _SFX_EXTENSIONS or looks_executable:
        embedded = _scan_for_sfx(path)
        if embedded is not ArchiveFormat.UNKNOWN:
            return embedded

    return _format_from_extension(path)


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
        ".cab": ArchiveFormat.CAB,
        ".iso": ArchiveFormat.ISO,
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
                "found.\n\nInstall it, for example:\n"
                "    sudo apt install p7zip-full"
            )
        return self.sevenzip

    def for_path(self, path: str) -> tuple[ArchiveBackend, ArchiveFormat]:
        fmt = detect_format(path)
        return self.for_format(fmt), fmt

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
