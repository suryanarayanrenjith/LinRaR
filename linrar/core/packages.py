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
from . import platform as platform_check


@dataclass(frozen=True)
class PackageManager:
    """A native package manager and the command templates it uses."""

    key: str
    binary: str
    label: str
    install: tuple[str, ...]
    remove: tuple[str, ...]

    def install_command(self, packages: list[str]) -> list[str]:
        return [self.binary, *self.install, *packages]

    def remove_command(self, packages: list[str]) -> list[str]:
        return [self.binary, *self.remove, *packages]


MANAGERS: dict[str, PackageManager] = {
    "apt": PackageManager(
        key="apt",
        binary="apt-get",
        label="APT (Debian / Ubuntu)",
        install=("install", "-y"),
        remove=("remove", "-y"),
    ),
    "dnf": PackageManager(
        key="dnf",
        binary="dnf",
        label="DNF (Fedora / RHEL)",
        install=("install", "-y"),
        remove=("remove", "-y"),
    ),
    "pacman": PackageManager(
        key="pacman",
        binary="pacman",
        label="Pacman (Arch / Manjaro)",
        install=("-S", "--noconfirm", "--needed"),
        remove=("-R", "--noconfirm"),
    ),
    "zypper": PackageManager(
        key="zypper",
        binary="zypper",
        label="Zypper (openSUSE)",
        install=("install", "-y"),
        remove=("remove", "-y"),
    ),
    "apk": PackageManager(
        key="apk",
        binary="apk",
        label="APK (Alpine)",
        install=("add",),
        remove=("del",),
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
    # apt driven against an RPM database, which is what ALT Linux ships.  The
    # command line is Debian's; every package name is not.
    "apt-rpm": PackageManager(
        key="apt-rpm",
        binary="apt-get",
        label="APT-RPM (ALT Linux)",
        install=("install", "-y"),
        remove=("remove", "-y"),
    ),
    "urpmi": PackageManager(
        key="urpmi",
        binary="urpmi",
        label="urpmi (Mageia / ROSA)",
        install=("--auto",),
        remove=("--auto",),
    ),
    "guix": PackageManager(
        key="guix",
        binary="guix",
        label="Guix (GNU Guix System)",
        install=("install",),
        remove=("remove",),
    ),
    "opkg": PackageManager(
        key="opkg",
        binary="opkg",
        label="opkg (OpenWrt / Entware)",
        install=("install",),
        remove=("remove",),
    ),
    "prt-get": PackageManager(
        key="prt-get",
        binary="prt-get",
        label="prt-get (CRUX)",
        install=("depinst",),
        remove=("remove",),
    ),
    "cards": PackageManager(
        key="cards",
        binary="cards",
        label="cards (NuTyX)",
        install=("install",),
        remove=("remove",),
    ),
    "tazpkg": PackageManager(
        key="tazpkg",
        binary="tazpkg",
        label="tazpkg (SliTaz)",
        install=("get-install",),
        remove=("remove",),
    ),
    "slackpkg": PackageManager(
        key="slackpkg",
        binary="slackpkg",
        label="slackpkg (Slackware)",
        install=("install",),
        remove=("remove",),
    ),
    "swupd": PackageManager(
        key="swupd",
        binary="swupd",
        label="swupd (Clear Linux)",
        install=("bundle-add",),
        remove=("bundle-remove",),
    ),
}

# Distro id (or ID_LIKE token) -> package manager key.  Kept deliberately in
# step with the case statement in install.sh: the Dependencies manager and the
# installer must never disagree about how packages get onto a machine, and a
# test checks that neither list has grown an entry the other lacks.
_DISTRO_MANAGERS = {
    # -- Debian and its descendants --
    "debian": "apt", "ubuntu": "apt", "pop": "apt", "linuxmint": "apt",
    "elementary": "apt", "zorin": "apt", "kali": "apt", "raspbian": "apt",
    "deepin": "apt", "mx": "apt", "devuan": "apt", "neon": "apt",
    "tuxedo": "apt", "parrot": "apt", "pureos": "apt", "trisquel": "apt",
    "nitrux": "apt", "siduction": "apt", "sparky": "apt", "antix": "apt",
    "q4os": "apt", "bodhi": "apt", "peppermint": "apt", "linuxlite": "apt",
    "feren": "apt", "regolith": "apt", "ubuntukylin": "apt", "kylin": "apt",
    "openkylin": "apt", "uos": "apt", "astra": "apt", "lmde": "apt",
    "bunsenlabs": "apt", "armbian": "apt", "endless": "apt",
    "vanilla": "apt", "blendos": "apt", "pika": "apt", "pardus": "apt",
    # -- Red Hat and its descendants --
    "fedora": "dnf", "rhel": "dnf", "centos": "dnf", "rocky": "dnf",
    "almalinux": "dnf", "nobara": "dnf", "ol": "dnf", "scientific": "dnf",
    "amzn": "dnf", "qubes": "dnf", "mageia": "dnf", "openmandriva": "dnf",
    "pclinuxos": "dnf", "rosa": "dnf", "openeuler": "dnf", "anolis": "dnf",
    "circle": "dnf", "eurolinux": "dnf", "springdale": "dnf",
    "ultramarine": "dnf", "asahi": "dnf", "azurelinux": "dnf",
    "mariner": "dnf", "tencentos": "dnf", "alinux": "dnf",
    # -- Arch and its descendants --
    "arch": "pacman", "manjaro": "pacman", "endeavouros": "pacman",
    "garuda": "pacman", "cachyos": "pacman", "artix": "pacman",
    "arcolinux": "pacman", "steamos": "pacman", "archcraft": "pacman",
    "archbang": "pacman", "blackarch": "pacman", "parabola": "pacman",
    "rebornos": "pacman", "obarun": "pacman", "athena": "pacman",
    "biglinux": "pacman", "xerolinux": "pacman", "bluestar": "pacman",
    # -- SUSE --
    "opensuse": "zypper", "opensuse-leap": "zypper",
    "opensuse-tumbleweed": "zypper", "suse": "zypper", "sles": "zypper",
    "sled": "zypper", "geckolinux": "zypper", "aeon": "zypper",
    "kalpa": "zypper", "microos": "zypper", "slowroll": "zypper",
    # -- everything else --
    "alpine": "apk", "postmarketos": "apk", "chimera": "apk",
    "wolfi": "apk", "adelie": "apk",
    "void": "xbps",
    "solus": "eopkg",
    "gentoo": "emerge", "funtoo": "emerge", "calculate": "emerge",
    "redcore": "emerge", "sabayon": "emerge", "pentoo": "emerge",
    "guix": "guix", "guixsd": "guix",
    "altlinux": "apt-rpm", "alt": "apt-rpm",
    "slackware": "slackpkg", "salix": "slackpkg", "zenwalk": "slackpkg",
    "clear-linux-os": "swupd",
    "crux": "prt-get",
    "nutyx": "cards",
    "slitaz": "tazpkg",
    "openwrt": "opkg", "lede": "opkg",
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
    #: True when the tool is only distributed as a pre-built binary, so it
    #: exists for the architectures its publisher chose and nowhere else.
    #: ``rar`` is the only one: everything else here is open source and gets
    #: built by each distribution for every machine it supports.
    binary_only: bool = False

    def packages_for(self, manager: Optional[PackageManager]) -> list[str]:
        if manager is None:
            return []
        return self.packages.get(manager.key, [])

    def note_for(self, manager: Optional[PackageManager]) -> str:
        if manager is None:
            return ""
        return self.notes.get(manager.key, "")

    def available_here(self) -> bool:
        """Can this tool exist on this machine at all?

        Not "is it installed" — whether anybody publishes it for the
        architecture.  Offering to install something that has never been built
        for the machine is worse than saying so.
        """
        if not self.binary_only:
            return True
        return platform_check.architecture().rarlab

    def unavailable_reason(self) -> str:
        """Why it cannot be had here, or "" when it can."""
        if self.available_here():
            return ""
        arch = platform_check.architecture()
        supported = ", ".join(
            label
            for label, has_rar, _appimage, _bits
            in sorted(platform_check.ARCHITECTURES.values())
            if has_rar
        )
        return (
            f"RARLAB publishes {self.name} for {supported} only, and this "
            f"machine is {arch.label}. Everything except creating RAR "
            "archives works without it."
        )


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
            "emerge": ["app-arch/unrar"],
            "rpm-ostree": ["unrar"],
            "apt-rpm": ["unrar"],
            "urpmi": ["unrar"],
            "prt-get": ["unrar"],
            "cards": ["unrar"],
            "tazpkg": ["unrar"],
            "opkg": ["unrar"],
            # Guix carries only the free reimplementation, which reads the
            # older RAR formats but not RAR5.
            "guix": ["unrar-free"],
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
            "apt-rpm": ["rar"],
            "urpmi": ["rar"],
            "emerge": ["app-arch/rar"],
        },
        notes={
            "apt": "Shareware from RARLAB; in Ubuntu's 'multiverse' "
                   "repository.",
            "dnf": "Provided by RPM Fusion (nonfree); that repository must be "
                   "enabled.",
            "pacman": "Not in the official repositories: install 'rar' from "
                      "the AUR, for example: yay -S rar",
            "xbps": "Not packaged for Void; install RARLAB's binary manually.",
        },
        essential=True,
        binary_only=True,
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
            "emerge": ["app-arch/p7zip"],
            "rpm-ostree": ["p7zip", "p7zip-plugins"],
            "apt-rpm": ["p7zip"],
            "urpmi": ["p7zip"],
            "prt-get": ["p7zip"],
            "cards": ["p7zip"],
            "tazpkg": ["p7zip"],
            "opkg": ["p7zip"],
            "guix": ["p7zip"],
            "slackpkg": ["p7zip"],
            "swupd": ["archive-tools"],
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
            "rpm-ostree": ["zip"],
            "apt-rpm": ["zip"],
            "urpmi": ["zip"],
            "prt-get": ["zip"],
            "cards": ["zip"],
            "tazpkg": ["zip"],
            "opkg": ["zip"],
            "guix": ["zip"],
            "slackpkg": ["zip"],
            "swupd": ["archive-tools"],
        },
    ),
    Dependency(
        key="squashfs",
        name="SquashFS tools",
        description=(
            "Builds the self-extracting AppImages produced by "
            "Commands > Convert archive to SFX."
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
            "rpm-ostree": ["squashfs-tools"],
            "apt-rpm": ["squashfs-tools"],
            "urpmi": ["squashfs-tools"],
            "prt-get": ["squashfs-tools"],
            "cards": ["squashfs-tools"],
            "guix": ["squashfs-tools"],
            "slackpkg": ["squashfs-tools"],
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
            "rpm-ostree": ["libsecret"],
            "apt-rpm": ["libsecret"],
            "urpmi": ["libsecret"],
            "prt-get": ["libsecret"],
            "cards": ["libsecret"],
            "guix": ["libsecret"],
            "slackpkg": ["libsecret"],
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
    """Where this tool is, asked exactly the way the backends ask it.

    Using ``shutil.which`` here instead would let the manager report "Missing"
    for a tool LinRAR is quite happily running: one installed in /opt/rar or a
    Nix profile, say, which :mod:`linrar.core.tools` finds and PATH does not.
    """
    from . import tools

    path = tools.find(dependency.key) if dependency.key in tools.CANDIDATES else ""
    if not path:
        for binary in dependency.binaries:
            path = shutil.which(binary) or ""
            if path:
                break
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
