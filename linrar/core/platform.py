"""LinRAR runs on Linux, and says so rather than half-working elsewhere.

This is not a stylistic position.  The application shells out to the Linux
builds of ``rar``, ``unrar``, ``7z``, ``zip`` and ``mksquashfs``; it stores its
settings under the XDG base directories; it installs itself through
freedesktop.org desktop entries, MIME associations and file-manager service
menus; and it asks for administrator rights through pkexec, sudo or doas.  On
Windows or macOS every one of those is either missing or means something else,
so the honest answer is to refuse at the door with an explanation, not to open
a window that fails at the first archive.

The check is deliberately made before PyQt6 is imported: a system LinRAR does
not support is also a system where the Qt wheels may not install, and
``ModuleNotFoundError`` is a far worse explanation than this one.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import TextIO

#: What the launcher and ``main()`` return when the system is not supported.
EXIT_UNSUPPORTED = 1

#: Set this to anything non-empty to start anyway, at your own risk.  It exists
#: for people porting LinRAR, not as a supported way to run it.
OVERRIDE_ENV = "LINRAR_ALLOW_ANY_OS"

#: ``sys.platform`` prefix -> the name a person would use.  Read in order, and
#: from the same place :func:`is_linux` reads, so the two can never disagree.
_PLATFORM_NAMES: tuple[tuple[str, str], ...] = (
    ("linux", "Linux"),
    ("darwin", "macOS"),
    ("win32", "Windows"),
    ("cygwin", "Cygwin"),
    ("msys", "MSYS"),
    ("freebsd", "FreeBSD"),
    ("openbsd", "OpenBSD"),
    ("netbsd", "NetBSD"),
    ("dragonfly", "DragonFly BSD"),
    ("sunos", "illumos or Solaris"),
    ("aix", "AIX"),
    ("emscripten", "WebAssembly"),
)

#: What to point people at instead, keyed by the names above.
_ALTERNATIVES = {
    "Windows": "On Windows, use WinRAR or 7-Zip.",
    "Cygwin": "On Windows, use WinRAR or 7-Zip.",
    "MSYS": "On Windows, use WinRAR or 7-Zip.",
    "macOS": "On macOS, use Keka or The Unarchiver.",
    "FreeBSD": "On the BSDs, use the native 7-Zip or unrar port.",
    "OpenBSD": "On the BSDs, use the native 7-Zip or unrar port.",
    "NetBSD": "On the BSDs, use the native 7-Zip or unrar port.",
    "DragonFly BSD": "On the BSDs, use the native 7-Zip or unrar port.",
    "illumos or Solaris": "There, use the native 7-Zip port.",
}


def system_name() -> str:
    """A readable name for the system this process is running on."""
    platform_id = (sys.platform or "").lower()
    for prefix, label in _PLATFORM_NAMES:
        if platform_id.startswith(prefix):
            return label
    try:
        return os.uname().sysname or platform_id or "an unknown system"
    except AttributeError:                 # Windows has no os.uname()
        return platform_id or "an unknown system"


def is_linux() -> bool:
    """The one platform LinRAR supports.  WSL counts: it is a Linux kernel."""
    return sys.platform.startswith("linux")


def override_active() -> bool:
    return bool(os.environ.get(OVERRIDE_ENV, "").strip())


def is_supported() -> bool:
    return is_linux() or override_active()


def problem() -> str:
    """Why this system cannot run LinRAR, or "" when it can."""
    if is_supported():
        return ""
    name = system_name()
    lines = [
        f"LinRAR for Linux does not run on {name}.",
        "",
        "It drives the Linux builds of rar, unrar, 7z and zip, keeps its",
        "settings in the XDG configuration directories, and registers itself",
        f"with a freedesktop.org desktop. None of that exists on {name}.",
        "",
        f"  {_ALTERNATIVES.get(name, 'Use an archiver built for this system.')}",
        "  Under WSL, install LinRAR inside the Linux distribution itself,",
        "  not on the Windows side.",
        "",
        f"To start it anyway and see what breaks, set {OVERRIDE_ENV}=1.",
        "That configuration is unsupported and untested.",
    ]
    return "\n".join(lines)


def warning() -> str:
    """The note printed when someone overrides the check."""
    if not override_active() or is_linux():
        return ""
    return (
        f"{OVERRIDE_ENV} is set: running LinRAR on {system_name()}, which is "
        "unsupported.\nArchive operations, settings and desktop integration "
        "may all misbehave."
    )


# -------------------------------------------------------------- architecture
#
# Linux runs on a great deal more than x86, and LinRAR runs wherever Python and
# Qt do -- which is everywhere its distribution builds them.  What is *not*
# everywhere is the tools it drives:
#
#   * ``unrar``, ``7z``, ``zip`` and ``mksquashfs`` are open source and are
#     built by every distribution for every architecture it supports;
#   * ``rar`` -- the only thing that can *write* a RAR archive -- is shareware,
#     is shipped as a binary by RARLAB, and exists for four architectures;
#   * the AppImage runtime LinRAR wraps self-extracting archives in is
#     published for four as well, and not the same four.
#
# So the honest answer on a POWER or RISC-V machine is "everything works except
# creating RAR archives and AppImages, and here is why" -- not a Missing label
# beside an Install button that cannot succeed.


@dataclass(frozen=True)
class Architecture:
    """The machine LinRAR is running on, and what is available for it."""

    #: The normalised name: ``x86_64``, ``aarch64``, ``riscv64``...
    key: str
    #: What ``uname -m`` actually said, which may be a synonym.
    machine: str
    label: str
    #: Does RARLAB publish ``rar``/``unrar`` binaries for it?
    rarlab: bool = False
    #: Is there a published AppImage type 2 runtime for it?
    appimage: bool = False
    #: 64 or 32, for the odd message that needs to say.
    bits: int = 64

    @property
    def known(self) -> bool:
        return self.key in ARCHITECTURES


#: Every architecture with a Linux port worth naming, what to call it, and
#: which of the two binary-only pieces exist for it.  A machine that is not in
#: here still runs LinRAR: it is simply described as itself.
ARCHITECTURES: dict[str, tuple[str, bool, bool, int]] = {
    #  key           label                       rarlab appimage bits
    "x86_64":     ("64-bit x86 (x86-64)",          True,  True,  64),
    "i686":       ("32-bit x86",                   True,  True,  32),
    "aarch64":    ("64-bit ARM (AArch64)",         True,  True,  64),
    "armv7l":     ("32-bit ARM (hard float)",      True,  True,  32),
    "armv6l":     ("32-bit ARM (ARMv6)",           False, True,  32),
    "riscv64":    ("64-bit RISC-V",                False, False, 64),
    "ppc64le":    ("64-bit POWER (little endian)", False, False, 64),
    "ppc64":      ("64-bit POWER (big endian)",    False, False, 64),
    "s390x":      ("IBM Z (s390x)",                False, False, 64),
    "loongarch64": ("64-bit LoongArch",            False, False, 64),
    "mips64el":   ("64-bit MIPS (little endian)",  False, False, 64),
    "mipsel":     ("32-bit MIPS (little endian)",  False, False, 32),
    "sparc64":    ("64-bit SPARC",                 False, False, 64),
    "alpha":      ("DEC Alpha",                    False, False, 64),
    "m68k":       ("Motorola 68000",               False, False, 32),
    "sh4":        ("SuperH",                       False, False, 32),
    "hppa":       ("PA-RISC",                      False, False, 32),
}

#: What the kernel may call a machine, and what LinRAR calls it.  ``uname -m``
#: is not standardised: the same processor answers ``amd64`` on one system and
#: ``x86_64`` on another, and normalising once here keeps every table below
#: from having to know that.
_MACHINE_ALIASES = {
    "amd64": "x86_64", "x64": "x86_64", "x86-64": "x86_64",
    "i386": "i686", "i486": "i686", "i586": "i686", "x86": "i686",
    "arm64": "aarch64", "armv8l": "aarch64", "armv8b": "aarch64",
    "armv7": "armv7l", "armhf": "armv7l", "armv7hl": "armv7l",
    "armv6": "armv6l", "arm": "armv6l",
    "riscv": "riscv64", "rv64": "riscv64", "riscv64gc": "riscv64",
    "power8": "ppc64le", "power9": "ppc64le", "powerpc64le": "ppc64le",
    "powerpc64": "ppc64", "powerpc": "ppc64",
    "loong64": "loongarch64", "loongarch": "loongarch64",
    "mips64": "mips64el", "mips": "mipsel",
    "sun4v": "sparc64", "sparc": "sparc64",
    "parisc": "hppa", "parisc64": "hppa",
}


def machine() -> str:
    """What ``uname -m`` says, verbatim and lowercased."""
    try:
        return (os.uname().machine or "").lower()
    except AttributeError:                 # pragma: no cover - not Linux
        import platform as _stdlib

        return (_stdlib.machine() or "").lower()


def normalise_machine(name: str) -> str:
    """Turn any spelling of a machine into the one LinRAR's tables use."""
    lowered = (name or "").strip().lower()
    return _MACHINE_ALIASES.get(lowered, lowered)


def architecture(name: str = "") -> Architecture:
    """Describe the machine this is running on, or the one named."""
    raw = name or machine()
    key = normalise_machine(raw)
    if key in ARCHITECTURES:
        label, rarlab, appimage, bits = ARCHITECTURES[key]
        return Architecture(key, raw, label, rarlab, appimage, bits)
    # Unknown, which is not the same as unsupported: LinRAR itself is Python
    # and Qt, and both run anywhere they are built.  Only the binary-only
    # pieces are assumed absent, because assuming otherwise means offering a
    # download that will 404.
    bits = 32 if any(tag in key for tag in ("32", "i3", "i4", "i5", "i6")) else 64
    return Architecture(key or "unknown", raw, key or "an unknown machine",
                        False, False, bits)


def describe_machine() -> str:
    """One line naming the architecture, for reports and ``--config-info``."""
    arch = architecture()
    if arch.known:
        return f"{arch.label} ({arch.machine})"
    return f"{arch.machine or 'unknown machine'} (not one LinRAR has a note about)"


def ensure_supported(stream: TextIO | None = None) -> None:
    """Refuse to go any further unless this is Linux.

    Raises :class:`SystemExit` so it can guard a module body: the point is to
    stop before the graphical stack is even imported.
    """
    message = problem()
    if message:
        print(message, file=stream or sys.stderr)
        raise SystemExit(EXIT_UNSUPPORTED)
    note = warning()
    if note:
        print(note, file=stream or sys.stderr)
