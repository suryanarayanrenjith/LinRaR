"""Detection and management of the command line tools the app depends on.

LinRAR for Linux is a front end: it needs ``unrar`` to read RAR archives, ``rar``
to write them, and optionally ``7z``/``zip`` for other formats.  This module
identifies the running distribution, maps each dependency to that distro's
package names, and builds the privileged commands used to install or remove
them.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Optional

from . import elevation


@dataclass(frozen=True)
class PackageManager:
    """A native package manager and the command templates it uses."""

    key: str
    binary: str
    label: str
    install: tuple[str, ...]
    remove: tuple[str, ...]
    refresh: tuple[str, ...] = ()
    query: tuple[str, ...] = ()

    def install_command(self, packages: list[str]) -> list[str]:
        return [self.binary, *self.install, *packages]

    def remove_command(self, packages: list[str]) -> list[str]:
        return [self.binary, *self.remove, *packages]

    def refresh_command(self) -> list[str]:
        return [self.binary, *self.refresh] if self.refresh else []


MANAGERS: dict[str, PackageManager] = {
    "apt": PackageManager(
        key="apt",
        binary="apt-get",
        label="APT (Debian / Ubuntu)",
        install=("install", "-y"),
        remove=("remove", "-y"),
        refresh=("update",),
        query=("dpkg-query", "-W", "-f=${Status}"),
    ),
    "dnf": PackageManager(
        key="dnf",
        binary="dnf",
        label="DNF (Fedora / RHEL)",
        install=("install", "-y"),
        remove=("remove", "-y"),
        refresh=("makecache",),
    ),
    "pacman": PackageManager(
        key="pacman",
        binary="pacman",
        label="Pacman (Arch / Manjaro)",
        install=("-S", "--noconfirm", "--needed"),
        remove=("-R", "--noconfirm"),
        refresh=("-Sy",),
    ),
    "zypper": PackageManager(
        key="zypper",
        binary="zypper",
        label="Zypper (openSUSE)",
        install=("install", "-y"),
        remove=("remove", "-y"),
        refresh=("refresh",),
    ),
    "apk": PackageManager(
        key="apk",
        binary="apk",
        label="APK (Alpine)",
        install=("add",),
        remove=("del",),
        refresh=("update",),
    ),
    "xbps": PackageManager(
        key="xbps",
        binary="xbps-install",
        label="XBPS (Void)",
        install=("-y",),
        remove=("-y",),
    ),
    "eopkg": PackageManager(
        key="eopkg",
        binary="eopkg",
        label="eopkg (Solus)",
        install=("install", "-y"),
        remove=("remove", "-y"),
    ),
    "emerge": PackageManager(
        key="emerge",
        binary="emerge",
        label="Portage (Gentoo)",
        install=("--noreplace",),
        remove=("--unmerge", "--quiet"),
    ),
    "rpm-ostree": PackageManager(
        key="rpm-ostree",
        binary="rpm-ostree",
        label="rpm-ostree (Silverblue / Kinoite)",
        install=("install", "--idempotent", "--apply-live"),
        remove=("uninstall", "--idempotent", "--apply-live"),
    ),
}

# Distro id (or ID_LIKE token) -> package manager key.
_DISTRO_MANAGERS = {
    "debian": "apt", "ubuntu": "apt", "pop": "apt", "linuxmint": "apt",
    "elementary": "apt", "zorin": "apt", "kali": "apt", "raspbian": "apt",
    "fedora": "dnf", "rhel": "dnf", "centos": "dnf", "rocky": "dnf",
    "almalinux": "dnf", "nobara": "dnf",
    "arch": "pacman", "manjaro": "pacman", "endeavouros": "pacman",
    "garuda": "pacman", "cachyos": "pacman",
    "opensuse": "zypper", "opensuse-leap": "zypper",
    "opensuse-tumbleweed": "zypper", "suse": "zypper", "sles": "zypper",
    "alpine": "apk", "postmarketos": "apk",
    "void": "xbps",
    "solus": "eopkg",
    "gentoo": "emerge", "funtoo": "emerge", "calculate": "emerge",
    "artix": "pacman", "arcolinux": "pacman", "steamos": "pacman",
    "deepin": "apt", "mx": "apt", "devuan": "apt", "neon": "apt",
    "ol": "dnf", "mageia": "dnf", "openmandriva": "dnf",
}


@dataclass
class Dependency:
    """One external tool the application can use."""

    key: str
    name: str
    description: str
    binaries: tuple[str, ...]
    packages: dict[str, list[str]] = field(default_factory=dict)
    notes: dict[str, str] = field(default_factory=dict)
    essential: bool = False
    version_args: tuple[str, ...] = ()

    def packages_for(self, manager: Optional[PackageManager]) -> list[str]:
        if manager is None:
            return []
        return self.packages.get(manager.key, [])

    def note_for(self, manager: Optional[PackageManager]) -> str:
        if manager is None:
            return ""
        return self.notes.get(manager.key, "")


DEPENDENCIES: list[Dependency] = [
    Dependency(
        key="unrar",
        name="UnRAR",
        description=(
            "Reads, extracts and tests RAR archives. Required to open .rar "
            "files at all."
        ),
        binaries=("unrar",),
        packages={
            "apt": ["unrar"],
            "dnf": ["unrar"],
            "pacman": ["unrar"],
            "zypper": ["unrar"],
            "apk": ["unrar"],
            "xbps": ["unrar"],
            "eopkg": ["unrar"],
        },
        notes={
            "apt": "On Ubuntu this package lives in the 'multiverse' "
                   "repository, which may need enabling first.",
        },
        essential=True,
    ),
    Dependency(
        key="rar",
        name="RAR",
        description=(
            "Creates and modifies RAR archives: compressing, deleting, "
            "renaming, comments, recovery records, locking and SFX."
        ),
        binaries=("rar",),
        packages={
            "apt": ["rar"],
            "dnf": ["rar"],
            "zypper": ["rar"],
            "apk": ["rar"],
            "eopkg": ["rar"],
        },
        notes={
            "apt": "Shareware from RARLAB; in Ubuntu's 'multiverse' "
                   "repository.",
            "dnf": "Provided by RPM Fusion (nonfree); that repository must be "
                   "enabled.",
            "pacman": "Not in the official repositories — install 'rar' from "
                      "the AUR, for example: yay -S rar",
            "xbps": "Not packaged for Void; install RARLAB's binary manually.",
        },
        essential=True,
    ),
    Dependency(
        key="sevenzip",
        name="7-Zip",
        description=(
            "Adds support for 7z, TAR, GZip, BZip2, XZ, ISO and CAB archives."
        ),
        binaries=("7z", "7za", "7zz"),
        packages={
            "apt": ["p7zip-full"],
            "dnf": ["p7zip", "p7zip-plugins"],
            "pacman": ["p7zip"],
            "zypper": ["p7zip-full"],
            "apk": ["p7zip"],
            "xbps": ["p7zip"],
            "eopkg": ["p7zip"],
        },
    ),
    Dependency(
        key="zip",
        name="Zip",
        description=(
            "Creates password-protected (AES) ZIP archives. Reading, writing "
            "and testing plain ZIP files is built in and needs no tool."
        ),
        binaries=("zip",),
        packages={
            "apt": ["zip"],
            "dnf": ["zip"],
            "pacman": ["zip"],
            "zypper": ["zip"],
            "apk": ["zip"],
            "xbps": ["zip"],
            "eopkg": ["zip"],
            "emerge": ["app-arch/zip"],
        },
    ),
    Dependency(
        key="squashfs",
        name="SquashFS tools",
        description=(
            "Builds the self-extracting AppImages produced by "
            "Commands > Convert to AppImage."
        ),
        binaries=("mksquashfs",),
        packages={
            "apt": ["squashfs-tools"],
            "dnf": ["squashfs-tools"],
            "pacman": ["squashfs-tools"],
            "zypper": ["squashfs"],
            "apk": ["squashfs-tools"],
            "xbps": ["squashfs-tools"],
            "eopkg": ["squashfs-tools"],
            "emerge": ["sys-fs/squashfs-tools"],
        },
        version_args=("-version",),
    ),
    Dependency(
        key="keyring",
        name="Keyring (secret-tool)",
        description=(
            "Stores saved passwords in your desktop's keyring. Without it "
            "they go to LinRAR's own file, obfuscated but not encrypted."
        ),
        binaries=("secret-tool",),
        packages={
            "apt": ["libsecret-tools"],
            "dnf": ["libsecret"],
            "pacman": ["libsecret"],
            "zypper": ["libsecret-tools"],
            "apk": ["libsecret"],
            "xbps": ["libsecret"],
            "eopkg": ["libsecret"],
            "emerge": ["app-crypt/libsecret"],
        },
        version_args=("--version",),
    ),
]


@dataclass
class DependencyStatus:
    """Where a dependency is installed and what version it reports."""

    dependency: Dependency
    path: Optional[str] = None
    version: str = ""

    @property
    def installed(self) -> bool:
        return self.path is not None


# ---------------------------------------------------------------- distro

def read_os_release() -> dict[str, str]:
    values: dict[str, str] = {}
    for candidate in ("/etc/os-release", "/usr/lib/os-release"):
        try:
            with open(candidate, "r", encoding="utf-8") as handle:
                for line in handle:
                    if "=" not in line or line.startswith("#"):
                        continue
                    key, _, value = line.partition("=")
                    values[key.strip()] = value.strip().strip('"').strip("'")
            break
        except OSError:
            continue
    return values


def distro_name() -> str:
    info = read_os_release()
    return info.get("PRETTY_NAME") or info.get("NAME") or "Unknown Linux"


def detect_manager() -> Optional[PackageManager]:
    """Pick the package manager for this system.

    The distro id is consulted first so that, for example, a Debian box with
    both ``apt-get`` and a stray ``dnf`` still resolves to APT.  If the id is
    unknown we fall back to whichever manager binary actually exists.
    """
    # An image-based system layers packages instead of installing them, and
    # that is true no matter what its distro id claims.
    if os.path.exists("/run/ostree-booted") and shutil.which("rpm-ostree"):
        return MANAGERS["rpm-ostree"]

    info = read_os_release()
    candidates: list[str] = []
    if identifier := info.get("ID", "").lower():
        candidates.append(identifier)
    candidates.extend(info.get("ID_LIKE", "").lower().split())

    for candidate in candidates:
        key = _DISTRO_MANAGERS.get(candidate)
        if key and shutil.which(MANAGERS[key].binary):
            return MANAGERS[key]

    for key in ("apt", "dnf", "pacman", "zypper", "apk", "xbps", "eopkg",
                "emerge"):
        if shutil.which(MANAGERS[key].binary):
            return MANAGERS[key]
    return None


# ---------------------------------------------------------------- status

def _probe_version(path: str, dependency: Dependency) -> str:
    """Ask a tool for its version, tolerating the odd conventions each uses."""
    attempts: list[list[str]] = []
    if dependency.version_args:
        attempts.append([path, *dependency.version_args])
    if dependency.key in ("rar", "unrar"):
        attempts.append([path])  # both print a banner when run bare
    else:
        attempts.append([path, "--version"])
        attempts.append([path])

    for argv in attempts:
        try:
            proc = subprocess.run(
                argv, capture_output=True, timeout=6,
                env={**os.environ, "LC_ALL": "C"},
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        text = (proc.stdout or b"").decode("utf-8", "replace")
        if not text.strip():
            text = (proc.stderr or b"").decode("utf-8", "replace")
        match = re.search(r"\b(\d+\.\d+(?:\.\d+)?)\b", text)
        if match:
            return match.group(1)
    return ""


def dependency_status(dependency: Dependency) -> DependencyStatus:
    for binary in dependency.binaries:
        path = shutil.which(binary)
        if path:
            return DependencyStatus(dependency, path, _probe_version(path, dependency))
    return DependencyStatus(dependency)


def all_statuses() -> list[DependencyStatus]:
    return [dependency_status(dep) for dep in DEPENDENCIES]


# ---------------------------------------------------------------- privilege
#
# Escalation itself lives in :mod:`linrar.core.elevation`, which can hold an
# authenticated session; these two are the thin wrappers package management
# uses.


def privileged(argv: list[str], requested: str = "auto") -> Optional[list[str]]:
    """*argv* rewritten to run as root, or ``None`` if that is not possible."""
    return elevation.SESSION.command(argv, requested)


def manual_instructions(argv: list[str]) -> str:
    """A copy-and-paste command for when we cannot escalate ourselves."""
    return elevation.manual_instructions(argv)
