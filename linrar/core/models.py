"""Data models shared by the backends and the UI."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


class ArchiveFormat(enum.Enum):
    """Archive container formats the application knows about.

    Everything past :data:`ISO` is read-only and handled by 7-Zip.  They are
    listed by name rather than lumped into one "other" case so that a file
    LinRAR *can* open is never turned away with "not recognised", and so the
    Info dialog and the error messages can say what the file actually is.
    """

    RAR5 = "RAR"
    RAR4 = "RAR4"
    ZIP = "ZIP"
    SEVENZIP = "7Z"
    TAR = "TAR"
    GZIP = "GZ"
    BZIP2 = "BZ2"
    XZ = "XZ"
    ZSTD = "ZST"
    CAB = "CAB"
    ISO = "ISO"
    # -- read-only, via 7-Zip --
    LZMA = "LZMA"
    LZIP = "LZ"
    COMPRESS = "Z"
    LZ4 = "LZ4"
    ARJ = "ARJ"
    LZH = "LZH"
    AR = "AR"
    DEB = "DEB"
    RPM = "RPM"
    CPIO = "CPIO"
    WIM = "WIM"
    DMG = "DMG"
    MSI = "MSI"
    SQUASHFS = "SQFS"
    VHD = "VHD"
    UNKNOWN = "?"

    @property
    def label(self) -> str:
        return _FORMAT_LABELS[self]

    @property
    def read_only(self) -> bool:
        """Formats LinRAR can list and unpack but never write."""
        return self not in (
            ArchiveFormat.RAR5,
            ArchiveFormat.RAR4,
            ArchiveFormat.ZIP,
            ArchiveFormat.SEVENZIP,
        )


_FORMAT_LABELS = {
    ArchiveFormat.RAR5: "RAR5",
    ArchiveFormat.RAR4: "RAR4",
    ArchiveFormat.ZIP: "ZIP",
    ArchiveFormat.SEVENZIP: "7-Zip",
    ArchiveFormat.TAR: "TAR",
    ArchiveFormat.GZIP: "GZip",
    ArchiveFormat.BZIP2: "BZip2",
    ArchiveFormat.XZ: "XZ",
    ArchiveFormat.ZSTD: "Zstandard",
    ArchiveFormat.CAB: "CAB",
    ArchiveFormat.ISO: "ISO",
    ArchiveFormat.LZMA: "LZMA",
    ArchiveFormat.LZIP: "Lzip",
    ArchiveFormat.COMPRESS: "compress (.Z)",
    ArchiveFormat.LZ4: "LZ4",
    ArchiveFormat.ARJ: "ARJ",
    ArchiveFormat.LZH: "LZH",
    ArchiveFormat.AR: "ar archive",
    ArchiveFormat.DEB: "Debian package",
    ArchiveFormat.RPM: "RPM package",
    ArchiveFormat.CPIO: "cpio",
    ArchiveFormat.WIM: "Windows image (WIM)",
    ArchiveFormat.DMG: "Apple disk image",
    ArchiveFormat.MSI: "Windows installer (MSI)",
    ArchiveFormat.SQUASHFS: "SquashFS",
    ArchiveFormat.VHD: "Virtual hard disk",
    ArchiveFormat.UNKNOWN: "Unknown",
}


class CompressionMethod(enum.IntEnum):
    """WinRAR's six compression presets, mapped to rar's -m0..-m5."""

    STORE = 0
    FASTEST = 1
    FAST = 2
    NORMAL = 3
    GOOD = 4
    BEST = 5

    @property
    def label(self) -> str:
        return {
            CompressionMethod.STORE: "Store",
            CompressionMethod.FASTEST: "Fastest",
            CompressionMethod.FAST: "Fast",
            CompressionMethod.NORMAL: "Normal",
            CompressionMethod.GOOD: "Good",
            CompressionMethod.BEST: "Best",
        }[self]


class UpdateMode(enum.Enum):
    """"Update mode" combo on the archive dialog."""

    ADD_REPLACE = "add_replace"
    ADD_UPDATE = "add_update"
    FRESHEN = "freshen"
    ASK = "ask"
    SKIP_EXISTING = "skip_existing"
    SYNCHRONIZE = "synchronize"

    @property
    def label(self) -> str:
        return {
            UpdateMode.ADD_REPLACE: "Add and replace files",
            UpdateMode.ADD_UPDATE: "Add and update files",
            UpdateMode.FRESHEN: "Freshen existing files only",
            UpdateMode.ASK: "Ask before overwrite",
            UpdateMode.SKIP_EXISTING: "Skip existing files",
            UpdateMode.SYNCHRONIZE: "Synchronize archive contents",
        }[self]


class ExtractUpdateMode(enum.Enum):
    """"Update mode" radio group on the extraction dialog."""

    EXTRACT_REPLACE = "replace"
    EXTRACT_UPDATE = "update"
    FRESHEN = "freshen"


class OverwriteMode(enum.Enum):
    """"Overwrite mode" radio group on the extraction dialog."""

    ASK = "ask"
    OVERWRITE = "overwrite"
    SKIP = "skip"
    RENAME = "rename"


@dataclass
class ArchiveEntry:
    """A single member of an archive."""

    name: str
    is_dir: bool = False
    size: int = 0
    packed_size: int = 0
    mtime: Optional[datetime] = None
    crc: str = ""
    attributes: str = ""
    host_os: str = ""
    method: str = ""
    encrypted: bool = False
    link_target: Optional[str] = None

    @property
    def basename(self) -> str:
        return self.name.rsplit("/", 1)[-1]

    @property
    def parent(self) -> str:
        return self.name.rsplit("/", 1)[0] if "/" in self.name else ""

    @property
    def is_link(self) -> bool:
        return self.link_target is not None

    @property
    def ratio(self) -> int:
        """Packed size as a percentage of the original, WinRAR-style."""
        if self.is_dir or self.size <= 0:
            return 0
        return int(round(self.packed_size * 100.0 / self.size))


@dataclass
class ArchiveInfo:
    """Everything known about an archive as a whole."""

    path: str
    format: ArchiveFormat = ArchiveFormat.UNKNOWN
    entries: list[ArchiveEntry] = field(default_factory=list)
    comment: str = ""
    solid: bool = False
    locked: bool = False
    encrypted_headers: bool = False
    recovery_record: bool = False
    volume: bool = False
    volume_number: int = 0
    sfx: bool = False
    detail_line: str = ""

    @property
    def total_size(self) -> int:
        return sum(e.size for e in self.entries if not e.is_dir)

    @property
    def total_packed(self) -> int:
        return sum(e.packed_size for e in self.entries if not e.is_dir)

    @property
    def file_count(self) -> int:
        return sum(1 for e in self.entries if not e.is_dir)

    @property
    def folder_count(self) -> int:
        return sum(1 for e in self.entries if e.is_dir)

    @property
    def ratio(self) -> int:
        total = self.total_size
        if total <= 0:
            return 0
        return int(round(self.total_packed * 100.0 / total))

    @property
    def has_encrypted_entries(self) -> bool:
        return self.encrypted_headers or any(e.encrypted for e in self.entries)


@dataclass
class CompressOptions:
    """Mirrors the "Archive name and parameters" dialog."""

    archive_path: str = ""
    format: ArchiveFormat = ArchiveFormat.RAR5
    method: CompressionMethod = CompressionMethod.NORMAL
    dictionary_size: str = ""
    volume_size: int = 0  # bytes; 0 disables splitting
    update_mode: UpdateMode = UpdateMode.ADD_REPLACE

    delete_after: bool = False
    #: rar's own ``-sfx`` stub.  The backends act on this one.
    create_sfx: bool = False
    #: What kind of self-extracting archive was asked for: "", "rar" or
    #: "appimage".  An AppImage is built by wrapping a finished RAR archive, so
    #: the backends never see it: it is carried here so the choice survives
    #: into a saved profile and back out again.
    sfx_format: str = ""
    solid: bool = False
    recovery_record: bool = False
    recovery_percent: int = 3
    test_after: bool = False
    lock: bool = False

    password: Optional[str] = None
    encrypt_headers: bool = False

    recurse_subfolders: bool = True
    store_paths: bool = True
    base_folder: str = ""
    comment: str = ""
    exclude_patterns: list[str] = field(default_factory=list)


@dataclass
class ExtractOptions:
    """Mirrors the "Extraction path and options" dialog."""

    destination: str = ""
    update_mode: ExtractUpdateMode = ExtractUpdateMode.EXTRACT_REPLACE
    overwrite_mode: OverwriteMode = OverwriteMode.ASK
    keep_broken: bool = False
    extract_to_subfolders: bool = False
    no_paths: bool = False
    open_when_done: bool = False
    password: Optional[str] = None
    members: list[str] = field(default_factory=list)


class OperationError(Exception):
    """Raised when a backend command fails.

    ``code`` carries the raw exit status so callers can distinguish a wrong
    password (which is recoverable by prompting) from a hard failure.
    """

    def __init__(self, message: str, code: int = -1, output: str = ""):
        super().__init__(message)
        self.message = message
        self.code = code
        self.output = output


class PasswordRequired(OperationError):
    """Raised when an archive needs a password we do not have (or it was wrong)."""


def format_size(value: int) -> str:
    """Group digits with spaces the way WinRAR does (e.g. ``1 234 567``)."""
    if value < 0:
        return ""
    return f"{value:,}".replace(",", " ")


def format_size_short(value: float) -> str:
    """Human readable size used in the status bar and property sheets."""
    units = ["bytes", "KB", "MB", "GB", "TB", "PB"]
    idx = 0
    val = float(value)
    while val >= 1024.0 and idx < len(units) - 1:
        val /= 1024.0
        idx += 1
    if idx == 0:
        return f"{int(val)} {units[idx]}"
    return f"{val:,.1f} {units[idx]}".replace(",", " ")
