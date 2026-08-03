"""What a file is, and what LinRAR can usefully do with it.

LinRAR is an archive manager, but it spends a great deal of its time looking at
files that are not archives: members waiting to be viewed, the contents of the
folder being browsed, the thing somebody double-clicked that turned out to be a
spreadsheet.  Answering "what is this?" in one place means the file list, the
viewer and the error messages all give the same answer.

Three questions get asked, and they are not the same question:

**What is it called?**  The extension, which is cheap, works on a name alone
(so it works for a member of an archive that has not been unpacked yet), and is
what the *Type* column shows.

**What is it really?**  The leading bytes.  A ``.txt`` holding a PNG is a PNG,
and the viewer must not print it as text.

**What should happen when it is opened?**  Not the same as either.  A ``.docx``
*is* a ZIP archive — genuinely, byte for byte — but somebody who double-clicks
one wants their word processor, not a listing of ``word/document.xml``.  That
distinction is :data:`DOCUMENT_CONTAINERS`, and it is why LinRAR can open a
``.docx`` as an archive when asked to and still hand it to LibreOffice when
not.

The document readers below turn OOXML, OpenDocument and EPUB into plain text
with nothing but the standard library, so the viewer can show what a document
*says* rather than a hex dump of the ZIP it happens to be stored in.  They are
deliberately forgiving: a document that cannot be read gives back nothing and
the viewer falls through to its next option, because a viewer that raises is
worse than one that shows a hex dump.
"""

from __future__ import annotations

import enum
import functools
import html
import os
import re
import zipfile
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

#: Never read more than this from a document being previewed.  A viewer is not
#: an unpacker: the point is to show what the thing is, and a hundred pages of
#: text is already more than anybody reads in a preview pane.
MAX_DOCUMENT_BYTES = 32 * 1024 * 1024
MAX_TEXT_CHARS = 2 * 1024 * 1024


class Kind(enum.Enum):
    """What sort of thing a file is, from the viewer's point of view."""

    TEXT = "text"
    IMAGE = "image"
    DOCUMENT = "document"       # readable as text once unwrapped
    PDF = "pdf"
    ARCHIVE = "archive"
    AUDIO = "audio"
    VIDEO = "video"
    FONT = "font"
    EXECUTABLE = "executable"
    DATA = "data"               # known, but nothing useful to show inline
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class FileType:
    """The answer to "what is this file?"."""

    kind: Kind
    #: What a person would call it: "Word document", "PNG image".
    label: str
    #: How the answer was reached: ``content``, ``name`` or ``""``.
    source: str = ""

    @property
    def viewable_as_text(self) -> bool:
        return self.kind in (Kind.TEXT, Kind.DOCUMENT)


# --------------------------------------------------------------- extensions
#
# Grouped by what they are rather than alphabetically, because that is how the
# table gets maintained: a new image format goes next to the other images.

_TEXT = {
    "txt": "Text", "text": "Text", "log": "Log", "md": "Markdown",
    "markdown": "Markdown", "rst": "reStructuredText", "adoc": "AsciiDoc",
    "asciidoc": "AsciiDoc", "org": "Org document", "tex": "LaTeX",
    "bib": "BibTeX", "nfo": "Info", "diz": "Description", "readme": "Readme",
    "csv": "CSV table", "tsv": "TSV table", "json": "JSON", "jsonl": "JSON lines",
    "yaml": "YAML", "yml": "YAML", "toml": "TOML", "ini": "Configuration",
    "cfg": "Configuration", "conf": "Configuration", "properties": "Properties",
    "env": "Environment file", "desktop": "Desktop entry", "service": "systemd unit",
    "xml": "XML", "xsd": "XML schema", "xsl": "XSL stylesheet", "dtd": "DTD",
    "svg": "SVG image", "html": "HTML page", "htm": "HTML page",
    "xhtml": "HTML page", "css": "Stylesheet", "scss": "Sass stylesheet",
    "less": "Less stylesheet",
    "js": "JavaScript", "mjs": "JavaScript", "cjs": "JavaScript",
    "ts": "TypeScript", "tsx": "TypeScript", "jsx": "JavaScript",
    "py": "Python", "pyi": "Python stub", "rb": "Ruby", "pl": "Perl",
    "pm": "Perl module", "php": "PHP", "lua": "Lua", "tcl": "Tcl",
    "sh": "Shell script", "bash": "Shell script", "zsh": "Shell script",
    "fish": "Fish script", "ps1": "PowerShell script", "bat": "Batch file",
    "cmd": "Batch file", "awk": "AWK script", "sed": "sed script",
    "c": "C source", "h": "C header", "cpp": "C++ source", "cc": "C++ source",
    "cxx": "C++ source", "hpp": "C++ header", "hh": "C++ header",
    "cs": "C# source", "java": "Java source", "kt": "Kotlin source",
    "kts": "Kotlin script", "scala": "Scala source", "go": "Go source",
    "rs": "Rust source", "swift": "Swift source", "m": "Objective-C source",
    "mm": "Objective-C++ source", "dart": "Dart source", "hs": "Haskell source",
    "ml": "OCaml source", "ex": "Elixir source", "exs": "Elixir script",
    "erl": "Erlang source", "clj": "Clojure source", "lisp": "Lisp source",
    "el": "Emacs Lisp", "vim": "Vim script", "r": "R script",
    "jl": "Julia source", "nim": "Nim source", "zig": "Zig source",
    "v": "V source", "f90": "Fortran source", "pas": "Pascal source",
    "asm": "Assembly", "s": "Assembly", "sql": "SQL", "graphql": "GraphQL",
    "proto": "Protocol buffer", "patch": "Patch", "diff": "Diff",
    "gitignore": "Git ignore list", "dockerfile": "Dockerfile",
    "makefile": "Makefile", "mk": "Makefile", "cmake": "CMake script",
    "gradle": "Gradle script", "srt": "Subtitles", "vtt": "Subtitles",
    "ass": "Subtitles", "sub": "Subtitles", "m3u": "Playlist",
    "m3u8": "Playlist", "pls": "Playlist", "vcf": "Contact card",
    "ics": "Calendar", "reg": "Registry export", "pem": "PEM certificate",
    "crt": "Certificate", "csr": "Certificate request", "pub": "Public key",
}

_IMAGES = {
    "png": "PNG image", "jpg": "JPEG image", "jpeg": "JPEG image",
    "jpe": "JPEG image", "jfif": "JPEG image", "gif": "GIF image",
    "bmp": "Bitmap image", "webp": "WebP image", "tif": "TIFF image",
    "tiff": "TIFF image", "ico": "Icon", "cur": "Cursor",
    "ppm": "Netpbm image", "pgm": "Netpbm image", "pbm": "Netpbm image",
    "pnm": "Netpbm image", "xpm": "XPM image", "xbm": "XBM image",
    "tga": "Targa image", "avif": "AVIF image", "heic": "HEIF image",
    "heif": "HEIF image", "jxl": "JPEG XL image", "psd": "Photoshop image",
    "xcf": "GIMP image", "kra": "Krita image", "raw": "Camera raw image",
    "cr2": "Canon raw image", "nef": "Nikon raw image", "arw": "Sony raw image",
    "dng": "Digital negative",
}

#: ZIP containers that are documents first and archives second.  LinRAR will
#: open any of them as an archive when asked, and never does so by accident:
#: double-clicking one hands it to whatever the desktop opens it with.
DOCUMENT_CONTAINERS: Dict[str, str] = {
    "docx": "Word document", "docm": "Word document (macros)",
    "dotx": "Word template", "dotm": "Word template (macros)",
    "xlsx": "Excel workbook", "xlsm": "Excel workbook (macros)",
    "xltx": "Excel template", "xltm": "Excel template (macros)",
    "pptx": "PowerPoint presentation", "pptm": "PowerPoint presentation (macros)",
    "potx": "PowerPoint template", "ppsx": "PowerPoint slide show",
    "ppsm": "PowerPoint slide show (macros)",
    "vsdx": "Visio drawing", "vssx": "Visio stencil",
    "odt": "OpenDocument text", "ott": "OpenDocument text template",
    "ods": "OpenDocument spreadsheet", "ots": "OpenDocument spreadsheet template",
    "odp": "OpenDocument presentation", "otp": "OpenDocument presentation template",
    "odg": "OpenDocument drawing", "odf": "OpenDocument formula",
    "odb": "OpenDocument database",
    "epub": "EPUB book", "fb2z": "FictionBook archive",
    "sxw": "OpenOffice document", "sxc": "OpenOffice spreadsheet",
    "sxi": "OpenOffice presentation",
    "kra": "Krita image", "ora": "OpenRaster image",
    "xmind": "XMind map", "mmap": "MindManager map",
    "scrivx": "Scrivener project",
}

_DOCUMENTS = {
    "pdf": "PDF document",
    "doc": "Word document (legacy)", "dot": "Word template (legacy)",
    "xls": "Excel workbook (legacy)", "xlt": "Excel template (legacy)",
    "ppt": "PowerPoint presentation (legacy)", "pps": "PowerPoint show (legacy)",
    "rtf": "Rich text document", "wpd": "WordPerfect document",
    "pages": "Pages document", "numbers": "Numbers spreadsheet",
    "key": "Keynote presentation", "mobi": "Mobipocket book",
    "azw": "Kindle book", "azw3": "Kindle book", "djvu": "DjVu document",
    "fb2": "FictionBook", "chm": "Compiled help",
}

_AUDIO = {
    "mp3": "MP3 audio", "flac": "FLAC audio", "wav": "WAV audio",
    "ogg": "Ogg audio", "oga": "Ogg audio", "opus": "Opus audio",
    "aac": "AAC audio", "m4a": "MPEG-4 audio", "wma": "Windows Media audio",
    "aiff": "AIFF audio", "aif": "AIFF audio", "ape": "Monkey's audio",
    "wv": "WavPack audio", "mid": "MIDI", "midi": "MIDI", "mod": "Tracker module",
    "xm": "Tracker module", "it": "Tracker module", "s3m": "Tracker module",
}

_VIDEO = {
    "mp4": "MPEG-4 video", "m4v": "MPEG-4 video", "mkv": "Matroska video",
    "webm": "WebM video", "avi": "AVI video", "mov": "QuickTime video",
    "wmv": "Windows Media video", "flv": "Flash video", "mpg": "MPEG video",
    "mpeg": "MPEG video", "mts": "AVCHD video", "m2ts": "AVCHD video",
    "ts": "MPEG transport stream", "ogv": "Ogg video", "3gp": "3GPP video",
    "vob": "DVD video", "rm": "RealMedia", "rmvb": "RealMedia",
}

_FONTS = {
    "ttf": "TrueType font", "otf": "OpenType font", "woff": "Web font",
    "woff2": "Web font", "eot": "Embedded font", "pfb": "Type 1 font",
    "pfm": "Type 1 font metrics", "bdf": "Bitmap font", "pcf": "Bitmap font",
}

_EXECUTABLES = {
    "exe": "Windows program", "dll": "Windows library", "msi": "Windows installer",
    "so": "Shared library", "o": "Object file", "ko": "Kernel module",
    "dylib": "macOS library", "class": "Java class", "pyc": "Compiled Python",
    "pyo": "Compiled Python", "elf": "Linux program", "bin": "Binary",
    "run": "Installer", "appimage": "AppImage", "flatpak": "Flatpak bundle",
    "wasm": "WebAssembly module",
}

_DATA = {
    "db": "Database", "sqlite": "SQLite database", "sqlite3": "SQLite database",
    "mdb": "Access database", "accdb": "Access database",
    "dat": "Data file", "bak": "Backup", "tmp": "Temporary file",
    "swp": "Editor swap file", "lock": "Lock file", "pid": "Process id",
    "iso": "Disc image", "img": "Disk image", "vmdk": "Virtual disk",
    "qcow2": "Virtual disk", "vdi": "Virtual disk", "torrent": "Torrent",
    "ics2": "Data file", "pak": "Game data", "sav": "Saved game",
    "npy": "NumPy array", "npz": "NumPy archive", "parquet": "Parquet table",
    "h5": "HDF5 data", "hdf5": "HDF5 data", "pickle": "Python pickle",
    "pkl": "Python pickle", "shp": "Shapefile", "gpx": "GPS track",
}

#: Archive extensions live in :mod:`linrar.core.registry`, which is where the
#: rest of the application asks about them.  This maps the ones worth naming in
#: the Type column; anything registry knows about but this does not still comes
#: back as an archive, just labelled generically.
_ARCHIVES = {
    "rar": "RAR archive", "cbr": "Comic book archive", "rev": "RAR recovery volume",
    "zip": "ZIP archive", "zipx": "ZIP archive", "cbz": "Comic book archive",
    "7z": "7-Zip archive", "cb7": "Comic book archive",
    "tar": "TAR archive", "gz": "GZip archive", "tgz": "Compressed TAR",
    "bz2": "BZip2 archive", "tbz": "Compressed TAR", "tbz2": "Compressed TAR",
    "xz": "XZ archive", "txz": "Compressed TAR", "zst": "Zstandard archive",
    "tzst": "Compressed TAR", "lzma": "LZMA archive", "lz": "Lzip archive",
    "lz4": "LZ4 archive", "z": "compress archive", "cab": "Cabinet archive",
    "arj": "ARJ archive", "lzh": "LZH archive", "lha": "LZH archive",
    "ace": "ACE archive", "deb": "Debian package", "rpm": "RPM package",
    "apk": "Android package", "jar": "Java archive", "war": "Java web archive",
    "whl": "Python wheel", "xpi": "Firefox add-on", "crx": "Chrome extension",
    "nupkg": "NuGet package", "vsix": "Visual Studio extension",
    "snap": "Snap package", "squashfs": "SquashFS image", "sfs": "SquashFS image",
    "cpio": "cpio archive", "ar": "ar archive", "a": "Static library",
    "wim": "Windows image", "swm": "Windows image", "esd": "Windows image",
    "dmg": "Apple disk image", "xar": "xar archive", "pkg": "Package",
    "sfx": "Self-extracting archive", "vhd": "Virtual hard disk",
    "vhdx": "Virtual hard disk", "udeb": "Debian package",
}

#: Names with no extension that are still perfectly recognisable.
_BY_NAME = {
    "makefile": (Kind.TEXT, "Makefile"),
    "gnumakefile": (Kind.TEXT, "Makefile"),
    "dockerfile": (Kind.TEXT, "Dockerfile"),
    "containerfile": (Kind.TEXT, "Dockerfile"),
    "readme": (Kind.TEXT, "Readme"),
    "license": (Kind.TEXT, "Licence"),
    "licence": (Kind.TEXT, "Licence"),
    "copying": (Kind.TEXT, "Licence"),
    "changelog": (Kind.TEXT, "Changelog"),
    "authors": (Kind.TEXT, "Authors"),
    "notice": (Kind.TEXT, "Notice"),
    "vagrantfile": (Kind.TEXT, "Vagrantfile"),
    "cmakelists.txt": (Kind.TEXT, "CMake script"),
    "pkgbuild": (Kind.TEXT, "Arch build script"),
    "core": (Kind.DATA, "Core dump"),
}


def _table() -> Dict[str, Tuple[Kind, str]]:
    """Every extension LinRAR knows, flattened once."""
    merged: Dict[str, Tuple[Kind, str]] = {}
    for group, kind in (
        (_TEXT, Kind.TEXT),
        (_IMAGES, Kind.IMAGE),
        (DOCUMENT_CONTAINERS, Kind.DOCUMENT),
        (_DOCUMENTS, Kind.DOCUMENT),
        (_AUDIO, Kind.AUDIO),
        (_VIDEO, Kind.VIDEO),
        (_FONTS, Kind.FONT),
        (_EXECUTABLES, Kind.EXECUTABLE),
        (_DATA, Kind.DATA),
        (_ARCHIVES, Kind.ARCHIVE),
    ):
        for extension, label in group.items():
            # Earlier groups win: ".svg" is text LinRAR can show, not an image
            # it would have to rasterise, and ".kra" is a document container
            # before it is an image.
            merged.setdefault(extension, (kind, label))
    return merged


EXTENSIONS: Dict[str, Tuple[Kind, str]] = _table()

#: PDF gets its own kind: it is a document, but not one that can be turned into
#: text without a dependency LinRAR does not have.
_PDF_KIND = Kind.PDF


# ---------------------------------------------------------------- signatures

_SIGNATURES: Tuple[Tuple[bytes, Kind, str], ...] = (
    (b"%PDF-", Kind.PDF, "PDF document"),
    (b"\x89PNG\r\n\x1a\n", Kind.IMAGE, "PNG image"),
    (b"\xff\xd8\xff", Kind.IMAGE, "JPEG image"),
    (b"GIF87a", Kind.IMAGE, "GIF image"),
    (b"GIF89a", Kind.IMAGE, "GIF image"),
    (b"BM", Kind.IMAGE, "Bitmap image"),
    (b"II*\x00", Kind.IMAGE, "TIFF image"),
    (b"MM\x00*", Kind.IMAGE, "TIFF image"),
    (b"\x00\x00\x01\x00", Kind.IMAGE, "Icon"),
    (b"8BPS", Kind.IMAGE, "Photoshop image"),
    (b"gimp xcf", Kind.IMAGE, "GIMP image"),
    (b"\x7fELF", Kind.EXECUTABLE, "Linux program or library"),
    (b"MZ", Kind.EXECUTABLE, "Windows program"),
    (b"\xca\xfe\xba\xbe", Kind.EXECUTABLE, "Java class"),
    (b"\x00asm", Kind.EXECUTABLE, "WebAssembly module"),
    (b"SQLite format 3\x00", Kind.DATA, "SQLite database"),
    (b"OggS", Kind.AUDIO, "Ogg media"),
    (b"fLaC", Kind.AUDIO, "FLAC audio"),
    (b"ID3", Kind.AUDIO, "MP3 audio"),
    (b"MThd", Kind.AUDIO, "MIDI"),
    (b"\x1aE\xdf\xa3", Kind.VIDEO, "Matroska or WebM video"),
    (b"wOFF", Kind.FONT, "Web font"),
    (b"wOF2", Kind.FONT, "Web font"),
    (b"OTTO", Kind.FONT, "OpenType font"),
    (b"\x00\x01\x00\x00\x00", Kind.FONT, "TrueType font"),
    (b"{\\rtf", Kind.TEXT, "Rich text document"),
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", Kind.DOCUMENT,
     "Legacy Office document"),
    (b"%!PS", Kind.TEXT, "PostScript document"),
    (b"-----BEGIN ", Kind.TEXT, "PEM key or certificate"),
    (b"#!", Kind.TEXT, "Script"),
)

#: Signatures a container shares with something else, resolved by looking
#: inside.  Every OOXML, OpenDocument and EPUB file is a ZIP.
_ZIP_MAGIC = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")


# --------------------------------------------------------------------- icons
#
# Which drawing stands for which file.  It lives here, next to the table that
# decides what a file *is*, so the icon in the list and the name in the Type
# column are always two views of the same answer.  The names are the ones
# linrar.ui.icons draws.

#: Extensions that have earned a drawing of their own.
_ICON_BY_EXTENSION: Dict[str, str] = {
    "docx": "file-word", "docm": "file-word", "dotx": "file-word",
    "dotm": "file-word", "doc": "file-word", "dot": "file-word",
    "rtf": "file-word", "wpd": "file-word", "pages": "file-word",
    "xlsx": "file-excel", "xlsm": "file-excel", "xltx": "file-excel",
    "xltm": "file-excel", "xls": "file-excel", "xlt": "file-excel",
    "csv": "file-excel", "tsv": "file-excel", "ods": "file-excel",
    "ots": "file-excel", "sxc": "file-excel", "numbers": "file-excel",
    "pptx": "file-powerpoint", "pptm": "file-powerpoint",
    "potx": "file-powerpoint", "ppsx": "file-powerpoint",
    "ppsm": "file-powerpoint", "ppt": "file-powerpoint",
    "pps": "file-powerpoint", "odp": "file-powerpoint",
    "otp": "file-powerpoint", "sxi": "file-powerpoint",
    "key": "file-powerpoint",
    "pdf": "file-pdf",
    "iso": "file-disc", "img": "file-disc", "udf": "file-disc",
    "dmg": "file-disc", "vhd": "file-disc", "vhdx": "file-disc",
    "vmdk": "file-disc", "qcow2": "file-disc", "vdi": "file-disc",
    "pem": "file-key", "crt": "file-key", "csr": "file-key",
    "pub": "file-key", "gpg": "file-key", "asc": "file-key",
    "kbx": "file-key", "keystore": "file-key", "jks": "file-key",
    # Text LinRAR can show, but a picture is what it is.
    "svg": "file-image", "xpm": "file-image", "xbm": "file-image",
}

#: What everything else gets, by what sort of thing it is.
_ICON_BY_KIND: Dict[Kind, str] = {
    Kind.TEXT: "file-text",
    Kind.IMAGE: "file-image",
    Kind.DOCUMENT: "file-document",
    Kind.PDF: "file-pdf",
    Kind.ARCHIVE: "archive-small",
    Kind.AUDIO: "file-audio",
    Kind.VIDEO: "file-video",
    Kind.FONT: "file-font",
    Kind.EXECUTABLE: "file-exec",
    Kind.DATA: "file-data",
    Kind.UNKNOWN: "file",
}

#: Source code and markup get the code drawing rather than the plain page:
#: they are text, but a folder of them reads far faster when they are not all
#: the same shape as the README beside them.
_CODE_EXTENSIONS = frozenset({
    "py", "pyi", "rb", "pl", "pm", "php", "lua", "tcl", "sh", "bash", "zsh",
    "fish", "ps1", "bat", "cmd", "awk", "sed", "c", "h", "cpp", "cc", "cxx",
    "hpp", "hh", "cs", "java", "kt", "kts", "scala", "go", "rs", "swift",
    "m", "mm", "dart", "hs", "ml", "ex", "exs", "erl", "clj", "lisp", "el",
    "vim", "r", "jl", "nim", "zig", "v", "f90", "pas", "asm", "s", "sql",
    "graphql", "proto", "js", "mjs", "cjs", "ts", "tsx", "jsx", "html",
    "htm", "xhtml", "css", "scss", "less", "xml", "xsd", "xsl", "dtd",
    "json", "jsonl", "yaml", "yml", "toml", "ini", "cfg", "conf", "diff",
    "patch", "makefile", "mk", "cmake", "gradle", "dockerfile", "desktop",
    "service", "properties", "env",
})


def icon_for(name: str, kind: Optional[Kind] = None) -> str:
    """The icon that stands for *name*.  Never touches the disk."""
    base = os.path.basename(name.rstrip("/")).lower()
    extension = extension_of(base)
    if extension in _ICON_BY_EXTENSION:
        return _ICON_BY_EXTENSION[extension]
    if extension in _CODE_EXTENSIONS or base in ("makefile", "dockerfile",
                                                 "gnumakefile", "cmakelists.txt",
                                                 "vagrantfile", "pkgbuild"):
        return "file-code"
    if kind is None:
        kind = by_name(name).kind
    return _ICON_BY_KIND.get(kind, "file")


def extension_of(name: str) -> str:
    """The extension of *name*, lowercased, without the dot."""
    return os.path.splitext(name.strip())[1].lstrip(".").lower()


def by_name(name: str) -> FileType:
    """What the name says this is.  Never touches the disk."""
    base = os.path.basename(name.rstrip("/")).lower()
    if base in _BY_NAME:
        kind, label = _BY_NAME[base]
        return FileType(kind, label, "name")
    extension = extension_of(base)
    if extension == "pdf":
        return FileType(_PDF_KIND, "PDF document", "name")
    if extension in EXTENSIONS:
        kind, label = EXTENSIONS[extension]
        return FileType(kind, label, "name")
    if extension:
        return FileType(Kind.UNKNOWN, f"{extension.upper()} file", "name")
    return FileType(Kind.UNKNOWN, "File", "")


def by_content(data: bytes, name: str = "") -> Optional[FileType]:
    """What the leading bytes say this is, or ``None`` when they say nothing.

    The name is consulted only to tell apart things that genuinely share a
    signature — every ZIP-based document looks exactly like a ZIP archive.
    """
    if not data:
        return None
    for signature, kind, label in _SIGNATURES:
        if data.startswith(signature):
            # "MZ" and "BM" are two bytes and turn up inside plain text often
            # enough to be worth a second opinion.
            if signature in (b"MZ", b"BM") and _looks_textual(data):
                break
            return FileType(kind, label, "content")
    if data.startswith(_ZIP_MAGIC):
        extension = extension_of(name)
        if extension in DOCUMENT_CONTAINERS:
            return FileType(Kind.DOCUMENT, DOCUMENT_CONTAINERS[extension],
                            "content")
        label = _ARCHIVES.get(extension, "ZIP archive")
        return FileType(Kind.ARCHIVE, label, "content")
    if _looks_textual(data):
        named = by_name(name)
        if named.kind is Kind.TEXT:
            return FileType(Kind.TEXT, named.label, "content")
        return FileType(Kind.TEXT, "Text", "content")
    return None


def identify(name: str = "", data: bytes = b"", path: str = "") -> FileType:
    """The best answer available, contents first and the name as backup."""
    if path and not data:
        try:
            with open(path, "rb") as handle:
                data = handle.read(8192)
        except OSError:
            data = b""
        name = name or path
    found = by_content(data, name)
    if found is not None:
        # A name that is more specific than the bytes wins on the label alone:
        # the bytes say "ZIP archive", the name says "Word document", and both
        # are true.
        named = by_name(name)
        if found.kind is named.kind and named.source == "name":
            return FileType(found.kind, named.label, "content")
        return found
    return by_name(name)


@functools.lru_cache(maxsize=8192)
def _sniffed(path: str, _size: int, _mtime: int) -> FileType:
    """Identify a file by reading its first bytes, remembering the answer.

    The size and modification time are arguments purely so that the cache
    invalidates itself when the file changes: a listing repaints far more often
    than its files are edited, and reading 512 bytes per row per repaint would
    be felt on a network share.
    """
    try:
        with open(path, "rb") as handle:
            head = handle.read(512)
    except OSError:
        return FileType(Kind.UNKNOWN, "File", "")
    found = by_content(head, path)
    return found if found is not None else FileType(Kind.UNKNOWN, "File", "")


def identify_file(path: str, name: str = "") -> FileType:
    """What *path* is, using its name first and its contents only if needed.

    This is what the file list asks about the handful of entries that have no
    extension to go on — a ``README`` with no suffix, a compiled program, a
    core dump.  Everything with an extension is answered from the name alone
    and never touches the disk.
    """
    name = name or os.path.basename(path)
    named = by_name(name)
    if named.kind is not Kind.UNKNOWN or extension_of(name):
        return named
    try:
        stat = os.stat(path)
    except OSError:
        return named
    if not stat.st_size:
        return named
    return _sniffed(path, stat.st_size, int(stat.st_mtime))


def _looks_textual(data: bytes, sample: int = 8192) -> bool:
    """Is this plausibly text? — the same test ``file`` and ``git`` use.

    A NUL byte means binary, and so does a high proportion of bytes that are
    not printable in any encoding a text file would use.
    """
    head = data[:sample]
    if not head:
        return True
    if b"\x00" in head:
        # Every other byte a NUL is not binary, it is UTF-16 without a byte
        # order mark — which is what a great many text files written on
        # Windows look like, and they arrive inside downloaded archives all
        # the time.  Calling those binary showed the user a hex dump of an
        # ordinary README.
        return looks_utf16(head) is not None
    printable = sum(
        1 for byte in head
        if 32 <= byte < 127 or byte in (9, 10, 13, 12, 27) or byte >= 128
    )
    return printable / len(head) > 0.90


def looks_utf16(data: bytes, sample: int = 8192) -> Optional[str]:
    """``"utf-16-le"``, ``"utf-16-be"`` or ``None`` for BOM-less UTF-16.

    ASCII text encoded as UTF-16 is one NUL byte for every character, always
    on the same side of it.  That pattern is unmistakable, and it has to be
    looked for explicitly: ``bytes.decode("utf-8")`` accepts NUL happily, so a
    UTF-16 file decodes "successfully" into ``h\\x00e\\x00l\\x00l\\x00o`` and
    every search for a word in it comes back empty.
    """
    head = data[:sample]
    # Two bytes per character, and enough of them to be sure.
    if len(head) < 8 or len(head) % 2:
        head = head[: len(head) - len(head) % 2]
    if len(head) < 8:
        return None
    even = head[0::2]
    odd = head[1::2]
    for nulls, others, encoding in (
        (odd, even, "utf-16-le"),
        (even, odd, "utf-16-be"),
    ):
        if nulls.count(0) >= len(nulls) * 0.9 and others.count(0) <= len(others) * 0.1:
            return encoding
    return None


def decode(data: bytes) -> str:
    """Turn bytes into text the way a viewer should: never raising.

    Byte-order marks are honoured, BOM-less UTF-16 is recognised by its shape,
    UTF-8 is tried, and latin-1 is the floor — it maps every byte to
    something, so there is always an answer.
    """
    # The endian-agnostic codecs, not the -le/-be ones: those decode the mark
    # itself into a zero-width space at the front of the text, which then turns
    # up as a stray character in the viewer.  "utf-16" and "utf-32" read the
    # mark, pick the byte order from it, and drop it.  The four-byte marks are
    # tested first because a UTF-32-LE mark begins with a UTF-16-LE one.
    for bom, encoding in (
        (b"\xef\xbb\xbf", "utf-8-sig"),
        (b"\xff\xfe\x00\x00", "utf-32"),
        (b"\x00\x00\xfe\xff", "utf-32"),
        (b"\xff\xfe", "utf-16"),
        (b"\xfe\xff", "utf-16"),
    ):
        if data.startswith(bom):
            try:
                return data.decode(encoding, "replace")
            except (UnicodeDecodeError, LookupError):
                break
    # Before UTF-8, because UTF-8 accepts the NUL bytes and answers with
    # nonsense rather than failing over to something better.
    wide = looks_utf16(data)
    if wide:
        return data.decode(wide, "replace")
    for encoding in ("utf-8", "utf-16", "latin-1"):
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return data.decode("latin-1", "replace")


# ----------------------------------------------------------------- documents
#
# OOXML, OpenDocument and EPUB are all ZIP containers holding XML.  Getting the
# text out needs no library: the markup is stripped with a regular expression
# rather than parsed, which is both faster and immune to the entity-expansion
# tricks an XML parser has to be defended against — and this is reading files
# that arrived inside somebody's archive.

_TAG = re.compile(r"<[^>]+>")
_BREAKS = (
    # Anything that ends a line in the source, turned into one in the output.
    re.compile(r"</w:p>|<w:br\b[^>]*/?>|</a:p>|</text:p>|</text:h>|"
               r"</table:table-row>|</p>|<br\s*/?>|</div>|</li>|</tr>", re.I),
    "\n",
)
_TABS = (re.compile(r"<w:tab\b[^>]*/?>|</table:table-cell>", re.I), "\t")
_PARAGRAPH_GAP = re.compile(r"\n{3,}")


def _strip_markup(xml: str) -> str:
    """Everything a person would read, and none of the angle brackets."""
    text = _BREAKS[0].sub(_BREAKS[1], xml)
    text = _TABS[0].sub(_TABS[1], text)
    text = _TAG.sub("", text)
    text = html.unescape(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    return _PARAGRAPH_GAP.sub("\n\n", text).strip()


def _members(archive: zipfile.ZipFile, wanted, limit: int) -> List[str]:
    """Read the named members, refusing to be talked into reading too much."""
    budget = limit
    parts: List[str] = []
    for name in wanted:
        try:
            info = archive.getinfo(name)
        except KeyError:
            continue
        if info.file_size > budget:
            break
        budget -= info.file_size
        try:
            parts.append(archive.read(name).decode("utf-8", "replace"))
        except (OSError, zipfile.BadZipFile, RuntimeError):
            continue
    return parts


def _sorted_slides(names: List[str], prefix: str, suffix: str) -> List[str]:
    """Slide 2 before slide 10, which sorting the names alphabetically is not."""
    def order(name: str) -> Tuple[int, str]:
        digits = re.findall(r"(\d+)", name)
        return (int(digits[-1]) if digits else 0, name)

    return sorted(
        (n for n in names if n.startswith(prefix) and n.endswith(suffix)),
        key=order,
    )


def document_text(data: bytes = b"", path: str = "") -> Optional[str]:
    """The readable text of an OOXML, OpenDocument or EPUB file.

    ``None`` when this is not a document LinRAR can read, or when reading it
    failed — the caller falls through to its next option rather than showing an
    error, because failing to preview something is not an error worth a dialog.
    """
    import io

    try:
        source = io.BytesIO(data) if data else path
        if not data and not path:
            return None
        with zipfile.ZipFile(source) as archive:
            names = archive.namelist()
            text = _read_document(archive, names)
    except (zipfile.BadZipFile, OSError, RuntimeError, ValueError, KeyError):
        return None
    if not text:
        return None
    return text[:MAX_TEXT_CHARS]


def _read_document(archive: zipfile.ZipFile, names: List[str]) -> str:
    limit = MAX_DOCUMENT_BYTES

    # -- OOXML: Word, PowerPoint, Excel ---------------------------------
    if "word/document.xml" in names:
        parts = _members(archive, ["word/document.xml"], limit)
        return _strip_markup("".join(parts))

    slides = _sorted_slides(names, "ppt/slides/slide", ".xml")
    if slides:
        pages = []
        for index, name in enumerate(slides, 1):
            body = _strip_markup("".join(_members(archive, [name], limit)))
            pages.append(f"--- Slide {index} ---\n{body}" if body
                         else f"--- Slide {index} ---")
        return "\n\n".join(pages)

    sheets = _sorted_slides(names, "xl/worksheets/sheet", ".xml")
    if sheets or "xl/workbook.xml" in names:
        return _read_workbook(archive, names, sheets, limit)

    # -- OpenDocument: Writer, Calc, Impress, Draw ----------------------
    if "content.xml" in names:
        return _strip_markup("".join(_members(archive, ["content.xml"], limit)))

    # -- EPUB ------------------------------------------------------------
    chapters = [
        name for name in names
        if name.lower().endswith((".xhtml", ".html", ".htm"))
        and not name.startswith("__MACOSX")
    ]
    if chapters:
        pages = []
        for name in sorted(chapters):
            body = _strip_markup("".join(_members(archive, [name], limit)))
            if body:
                pages.append(body)
        return "\n\n".join(pages)
    return ""


_SHARED_STRING = re.compile(r"<si>(.*?)</si>", re.S)
_CELL = re.compile(r"<c\b([^>]*)>(.*?)</c>|<c\b([^>]*)/>", re.S)
_VALUE = re.compile(r"<v>(.*?)</v>", re.S)
_INLINE = re.compile(r"<is>(.*?)</is>", re.S)
_ROW = re.compile(r"<row\b[^>]*>(.*?)</row>", re.S)


def _read_workbook(archive, names, sheets, limit: int) -> str:
    """A spreadsheet as tab-separated rows, which is what a preview wants.

    Excel keeps most cell text in one shared table and refers to it by index,
    so that has to be read first or every string cell reads as a number.
    """
    shared: List[str] = []
    if "xl/sharedStrings.xml" in names:
        blob = "".join(_members(archive, ["xl/sharedStrings.xml"], limit))
        shared = [_strip_markup(match) for match in _SHARED_STRING.findall(blob)]

    pages = []
    for index, name in enumerate(sheets, 1):
        blob = "".join(_members(archive, [name], limit))
        rows = []
        for row in _ROW.findall(blob):
            cells = []
            for attributes, body, empty_attributes in _CELL.findall(row):
                attributes = attributes or empty_attributes
                value = _VALUE.search(body or "")
                inline = _INLINE.search(body or "")
                if inline:
                    cells.append(_strip_markup(inline.group(1)))
                elif value is None:
                    cells.append("")
                elif 't="s"' in attributes:
                    try:
                        cells.append(shared[int(value.group(1))])
                    except (ValueError, IndexError):
                        cells.append("")
                else:
                    cells.append(html.unescape(_TAG.sub("", value.group(1))))
            if any(cell.strip() for cell in cells):
                rows.append("\t".join(cells))
        heading = f"--- Sheet {index} ---" if len(sheets) > 1 else ""
        if rows:
            pages.append("\n".join([heading, *rows]) if heading else "\n".join(rows))
    return "\n\n".join(pages)


def is_document_container(name: str) -> bool:
    """Is *name* a document that merely happens to be stored as a ZIP?

    True for ``.docx`` and its relations.  These are opened as archives only
    when somebody asks for that explicitly; double-clicking one is a request
    for the application that owns it.
    """
    return extension_of(name) in DOCUMENT_CONTAINERS


def hex_dump(data: bytes, width: int = 16, limit: int = 64 * 1024) -> str:
    """A classic offset / hex / ASCII dump, for what nothing else can show."""
    lines = []
    body = data[:limit]
    for offset in range(0, len(body), width):
        chunk = body[offset:offset + width]
        hexed = " ".join(f"{byte:02x}" for byte in chunk)
        text = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{offset:08x}  {hexed:<{width * 3 - 1}}  |{text}|")
    if len(data) > limit:
        lines.append(f"... {len(data) - limit} more bytes")
    return "\n".join(lines)
