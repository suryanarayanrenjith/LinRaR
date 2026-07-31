"""Finding the command line tools, wherever a given distribution puts them.

``shutil.which`` alone is not enough in practice: ``rar`` from RARLAB's tarball
lands in ``/opt/rar`` or ``~/bin``, p7zip is ``7z``/``7za``/``7zz``/``7zr``
depending on the packaging, Debian's free build is ``unrar-free``, Snap and
Flatpak export their own bin directories, and Nix hides everything under a
profile.  This module tries the user's own setting first, then ``PATH``, then
the places that are not always on it.
"""

from __future__ import annotations

import os
import shutil
from typing import Optional

#: Directories worth searching that are routinely missing from PATH.
EXTRA_DIRS: tuple[str, ...] = (
    "/usr/local/bin",
    "/usr/local/sbin",
    "/usr/bin",
    "/bin",
    "/usr/sbin",
    "/opt/bin",
    "/opt/rar",
    "/opt/local/bin",
    "/snap/bin",
    "/var/lib/flatpak/exports/bin",
    "/usr/lib/p7zip",
    "/usr/libexec/p7zip",
    "~/.local/bin",
    "~/bin",
    "~/.nix-profile/bin",
    "~/.local/share/flatpak/exports/bin",
)

#: Every name a tool is known to ship under, best first.
CANDIDATES: dict[str, tuple[str, ...]] = {
    # 7-Zip 21+ calls itself 7zz; p7zip ships 7z/7za/7zr.
    "sevenzip": ("7z", "7zz", "7za", "7zzs", "7zr", "p7zip"),
    # unrar-free is feature-poor but can still list and extract.
    "unrar": ("unrar", "unrar-nonfree", "unrar-free", "rar"),
    "rar": ("rar",),
    "zip": ("zip",),
    "unzip": ("unzip",),
}


def _expand(directory: str) -> str:
    return os.path.expanduser(directory)


def _executable(path: str) -> bool:
    return bool(path) and os.path.isfile(path) and os.access(path, os.X_OK)


def find(kind: str, override: str = "") -> str:
    """Locate the tool named by *kind*, honouring an explicit *override*.

    Returns an absolute path, or "" when the tool is nowhere to be found.
    """
    override = _expand(override.strip()) if override else ""
    if override:
        if _executable(override):
            return override
        # A bare name in the setting ("7zz") is treated as a PATH lookup.
        resolved = shutil.which(override)
        if resolved:
            return resolved

    for name in CANDIDATES.get(kind, (kind,)):
        resolved = shutil.which(name)
        if resolved:
            return resolved

    for directory in EXTRA_DIRS:
        folder = _expand(directory)
        for name in CANDIDATES.get(kind, (kind,)):
            candidate = os.path.join(folder, name)
            if _executable(candidate):
                return candidate
    return ""


def setting(key: str) -> str:
    """Read a ``paths/*`` preference without importing settings at module load."""
    try:
        from .settings import SETTINGS

        return str(SETTINGS.get(f"paths/{key}") or "")
    except Exception:  # pragma: no cover - settings must never break lookup
        return ""


def locate(kind: str, explicit: Optional[str] = None) -> str:
    """The path a backend should use for *kind*."""
    if explicit:
        return explicit
    return find(kind, setting(kind))
