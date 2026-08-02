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


def ensure_supported(stream: TextIO | None = None) -> None:
    """Refuse to go any further unless this is Linux.

    Raises :class:`SystemExit` so it can guard a module body — the point is to
    stop before the graphical stack is even imported.
    """
    message = problem()
    if message:
        print(message, file=stream or sys.stderr)
        raise SystemExit(EXIT_UNSUPPORTED)
    note = warning()
    if note:
        print(note, file=stream or sys.stderr)
