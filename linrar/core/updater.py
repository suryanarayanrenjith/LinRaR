"""Updating LinRAR in place, from the releases its own pipeline publishes.

The release side of this is described in ``docs/VERSIONING.md``: every release
carries a ``latest.json`` at a permanent address giving the version, the notes,
what it needs to run, and every download with its SHA-256.  This module is the
other half — the part that reads that document on a user's machine and, if they
ask for it, replaces the copy they are running with the one it describes.

It is deliberately cautious, because it is the one part of LinRAR that rewrites
LinRAR:

* It refuses to touch a **source checkout**.  A working tree carries a version
  number but nobody published it, and replacing it with a tarball would throw
  away somebody's work.  The build stamp (``linrar/_build.py``) and a ``.git``
  directory are both taken as "hands off".
* Nothing is trusted because it arrived over the network.  The manifest's
  schema must be one this version understands, the version in it must really be
  newer, the download's SHA-256 must match, and the tarball may only contain
  ordinary files and directories underneath its own top folder.
* **Everything is backed up before anything is replaced**, and any failure —
  including one from ``install.sh`` — restores the backup before the error is
  reported.  A failed update leaves the version that was working.
* The whole run is verified at the end by asking the newly installed copy what
  version it is, in a fresh process.  If it does not answer correctly the
  update is rolled back even though every individual step succeeded.

No PyQt6, no widgets, nothing that needs a display: the work runs on a worker
thread (see :class:`linrar.core.tasks.UpdateTask`) and reports progress through
:class:`UpdateContext`, in the same shape the archive backends use.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import elevation
from .. import version as versions

#: Where the project this module belongs to lives — the folder holding the
#: ``linrar`` package, ``install.sh`` and the rest of the tree.  Everything the
#: updater replaces is inside it.
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

#: What install.sh writes, and what tells us how this copy got here.
RECEIPT_NAME = ".install-receipt"

#: Never replaced by an update: the virtual environment (rebuilding it would
#: mean a download and a compile for no reason) and the installer's own
#: bookkeeping, which describes *this machine* rather than this version.
PRESERVED = (".venv", "venv", RECEIPT_NAME, ".install-manifest")

#: Left out of the backup: enormous, reproducible, and never modified by us.
NOT_BACKED_UP = (".venv", "venv", "__pycache__", ".git")

#: How long to wait on the network, in seconds.  A check happens at startup
#: where a hung socket would be felt, so it is deliberately short.
CHECK_TIMEOUT = 15
DOWNLOAD_TIMEOUT = 60

#: Politeness, and it makes LinRAR's traffic identifiable in a log.
USER_AGENT = f"LinRAR/{versions.__version__} (+{versions.REPOSITORY_URL})"

#: A download must arrive over TLS.  The only thing that ever turns this off is
#: ``tests/test_updater.py``, which serves a real release over plain HTTP from
#: 127.0.0.1 to exercise the whole pipeline; nothing in the application sets
#: it, and a manifest that asks for ``http://`` is refused rather than warned
#: about.
REQUIRE_HTTPS = True

#: The stages an update goes through, with the share of the overall bar each
#: one is worth.  Downloading dominates because on any real connection it does.
STAGES: Tuple[Tuple[str, str, int], ...] = (
    ("check", "Checking for updates", 3),
    ("download", "Downloading the update", 52),
    ("verify", "Verifying the download", 7),
    ("unpack", "Unpacking", 8),
    ("backup", "Backing up the current version", 8),
    ("install", "Installing", 20),
    ("done", "Finished", 2),
)

_STAGE_TITLES = {key: title for key, title, _ in STAGES}


class UpdateError(Exception):
    """An update could not be done.  The message is meant for a user."""

    def __init__(self, message: str, detail: str = "") -> None:
        super().__init__(message)
        self.message = message
        #: Tool output or a traceback-ish explanation, for the details pane.
        self.detail = detail


class Cancelled(UpdateError):
    """The user stopped it.  Not a failure, and never reported as one."""

    def __init__(self, message: str = "Cancelled.") -> None:
        super().__init__(message)


def _noop(*_arguments: Any) -> None:
    """Default callback: does nothing, so a caller may supply none."""


@dataclass
class UpdateContext:
    """Carries progress out of the worker and cancellation into it.

    Shaped like :class:`linrar.core.backends.base.TaskContext` on purpose: the
    update window shows the same kind of thing the archive windows do, so it is
    fed the same way.
    """

    #: ``(stage key, human title)`` whenever a new stage begins.
    on_stage: Callable[[str, str], None] = _noop
    #: ``(percent, bytes done, bytes total)`` within the current stage.  The
    #: byte counts are 0 for a stage that is not moving bytes.
    on_progress: Callable[[int, int, int], None] = _noop
    #: A line for the details pane — everything the updater did, in order.
    on_message: Callable[[str], None] = _noop
    #: Consulted between steps and while downloading.
    should_cancel: Callable[[], bool] = lambda: False

    stage: str = ""

    def begin(self, key: str) -> None:
        self.stage = key
        self.on_stage(key, _STAGE_TITLES.get(key, key))
        self.on_progress(0, 0, 0)

    def progress(self, percent: int, done: int = 0, total: int = 0) -> None:
        self.on_progress(max(0, min(100, int(percent))), done, total)

    def log(self, message: str) -> None:
        self.on_message(message)

    def checkpoint(self) -> None:
        """Raise :class:`Cancelled` if the user has asked to stop."""
        if self.should_cancel():
            raise Cancelled()


def overall_percent(stage: str, percent: int) -> int:
    """Where the whole update is, given how far *stage* has got.

    Kept here rather than in the window so the weighting is stated once, beside
    the stage list it belongs to.
    """
    total = sum(weight for _, _, weight in STAGES) or 1
    done = 0
    for key, _title, weight in STAGES:
        if key == stage:
            return int((done + weight * max(0, min(100, percent)) / 100) * 100 / total)
        done += weight
    return int(done * 100 / total)


# --------------------------------------------------------------- this install


@dataclass
class Receipt:
    """What ``install.sh`` recorded about the install on this machine."""

    path: str = ""
    values: Dict[str, str] = field(default_factory=dict)

    @property
    def found(self) -> bool:
        return bool(self.values)

    @property
    def mode(self) -> str:
        """``user``, ``system``, or "" when there is no receipt."""
        return self.values.get("mode", "")

    @property
    def version(self) -> str:
        return self.values.get("version", "")

    @property
    def project(self) -> str:
        return self.values.get("project", "")

    @property
    def launcher(self) -> str:
        return self.values.get("launcher", "")


def read_receipt(project: str = "") -> Receipt:
    """Read ``.install-receipt``, tolerating every way it can be absent."""
    path = os.path.join(project or PROJECT_DIR, RECEIPT_NAME)
    values: Dict[str, str] = {}
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip()
    except OSError:
        return Receipt()
    return Receipt(path, values)


def cache_dir() -> str:
    """Where downloads and backups live: a cache, safe to delete at any time."""
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return os.path.join(base, "linrar", "updates")


@dataclass
class Eligibility:
    """Whether this copy of LinRAR may replace itself, and why not."""

    can_update: bool
    reason: str = ""
    #: What the user could do instead, when the answer is no.
    suggestion: str = ""

    def __bool__(self) -> bool:
        return self.can_update


def eligibility(project: str = "") -> Eligibility:
    """May this copy be updated in place?

    Answered before anything is downloaded, so that a machine which cannot be
    updated is told so instead of being taken through five stages and then
    refused.
    """
    project = project or PROJECT_DIR

    if not versions.is_release_build():
        return Eligibility(
            False,
            "This copy was not installed from a release.",
            "It is a source checkout, so it updates with git rather than from "
            "the releases page — LinRAR will not overwrite a working tree.",
        )
    if os.path.isdir(os.path.join(project, ".git")):
        return Eligibility(
            False,
            "This copy is a git checkout.",
            f"Update it with 'git pull' in {project}.",
        )
    if not os.path.isdir(project) or not os.access(project, os.W_OK):
        return Eligibility(
            False,
            f"{project} is not writable.",
            "LinRAR was probably installed by a package manager; update it "
            "the way the rest of the system is updated.",
        )
    if not os.path.isfile(os.path.join(project, "install.sh")):
        return Eligibility(
            False,
            "This does not look like a LinRAR install.",
            f"install.sh is missing from {project}.",
        )

    receipt = read_receipt(project)
    if receipt.mode == "system" and not elevation.is_root():
        if not elevation.available():
            return Eligibility(
                False,
                "LinRAR is installed for every user, and this session cannot "
                "become an administrator.",
                f"Run './install.sh --reinstall --system' in {project} "
                "as an administrator instead.",
            )
    return Eligibility(True)


# ------------------------------------------------------------------ checking


@dataclass
class Artifact:
    """One downloadable file belonging to a release."""

    name: str = ""
    kind: str = ""
    size: int = 0
    sha256: str = ""
    url: str = ""


@dataclass
class Update:
    """A release newer than the one running, as the manifest describes it."""

    version: str = ""
    tag: str = ""
    channel: str = "stable"
    prerelease: bool = False
    released: str = ""
    commit: str = ""
    notes: str = ""
    release_url: str = ""
    requires: Dict[str, str] = field(default_factory=dict)
    artifact: Optional[Artifact] = None
    manifest: Dict[str, Any] = field(default_factory=dict)

    @property
    def size(self) -> int:
        return self.artifact.size if self.artifact else 0

    @property
    def date(self) -> str:
        """The release date alone, for a window that has no room for a clock."""
        return self.released[:10]


def _fetch(url: str, timeout: int) -> bytes:
    """GET *url*, turning every network failure into one worth reading."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        if error.code == 404:
            raise UpdateError(
                "No release has been published yet.",
                f"{url} answered 404.",
            ) from None
        raise UpdateError(
            f"The update server answered {error.code}.", str(error)
        ) from None
    except urllib.error.URLError as error:
        raise UpdateError(
            "Could not reach the update server.",
            f"{error.reason}\n\nIs this machine online?",
        ) from None
    except OSError as error:
        raise UpdateError("Could not reach the update server.", str(error)) from None


def parse_manifest(document: bytes) -> Update:
    """Turn ``latest.json`` into an :class:`Update`, or refuse it.

    Every field is checked before it is used.  This is the one place where data
    from the network becomes something LinRAR will act on, so "looks about
    right" is not good enough: a manifest that cannot be understood must be
    rejected, never guessed at.

    Whether the release it describes is one *this user* wants is a separate
    question, and :func:`check` answers it: a pre-release parses perfectly
    well, it is simply not offered unless it was asked for.
    """
    try:
        manifest = json.loads(document.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as error:
        raise UpdateError(
            "The update server sent something that is not a manifest.",
            str(error),
        ) from None
    if not isinstance(manifest, dict):
        raise UpdateError("The update manifest is not a JSON object.")

    schema = manifest.get("schema")
    if schema != versions.MANIFEST_SCHEMA:
        raise UpdateError(
            "This release was published by a newer LinRAR than this one.",
            f"The manifest declares schema {schema!r}; this version "
            f"understands {versions.MANIFEST_SCHEMA}. Download the update by "
            f"hand from {versions.RELEASES_URL}.",
        )

    offered = versions.try_parse(str(manifest.get("version", "")))
    if offered is None:
        raise UpdateError(
            "The update manifest does not name a usable version.",
            f"It says version={manifest.get('version')!r}.",
        )

    artifact = _pick_artifact(manifest.get("artifacts"))
    return Update(
        version=str(offered),
        tag=str(manifest.get("tag") or offered.tag),
        channel=str(manifest.get("channel") or offered.channel),
        prerelease=bool(manifest.get("prerelease", offered.is_prerelease)),
        released=str(manifest.get("released", "")),
        commit=str(manifest.get("commit", "")),
        notes=str(manifest.get("notes", "")),
        release_url=str(manifest.get("release_url", versions.RELEASES_URL)),
        requires={str(k): str(v) for k, v in (manifest.get("requires") or {}).items()},
        artifact=artifact,
        manifest=manifest,
    )


def _pick_artifact(entries: Any) -> Artifact:
    """The source tarball out of the manifest's artifact list."""
    if not isinstance(entries, list):
        raise UpdateError("The update manifest lists no downloads.")
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("kind") != "source":
            continue
        artifact = Artifact(
            name=str(entry.get("name", "")),
            kind="source",
            size=int(entry.get("size") or 0),
            sha256=str(entry.get("sha256", "")).lower(),
            url=str(entry.get("url", "")),
        )
        if not artifact.name.endswith(".tar.gz") or not artifact.url:
            continue
        if len(artifact.sha256) != 64:
            raise UpdateError(
                "The update has no usable checksum, so it cannot be trusted.",
                f"{artifact.name} declares sha256={artifact.sha256!r}.",
            )
        if REQUIRE_HTTPS and not artifact.url.startswith("https://"):
            raise UpdateError(
                "The update would be downloaded over an insecure connection.",
                artifact.url,
            )
        return artifact
    raise UpdateError("The update manifest has no source download in it.")


def _requirements_met(update: Update) -> None:
    """Refuse an update this machine could not run."""
    needed = update.requires.get("python", "")
    if needed:
        try:
            wanted = tuple(int(part) for part in needed.split(".")[:2])
        except ValueError:
            wanted = ()
        if wanted and sys.version_info[:2] < wanted:
            raise UpdateError(
                f"LinRAR {update.version} needs Python {needed} or newer.",
                f"This machine runs Python "
                f"{sys.version_info.major}.{sys.version_info.minor}.",
            )
    system = update.requires.get("os", "")
    if system and not sys.platform.startswith(system):
        raise UpdateError(
            f"LinRAR {update.version} is for {system}.",
            f"This machine reports {sys.platform}.",
        )


def check(
    ctx: Optional[UpdateContext] = None,
    *,
    allow_prerelease: bool = False,
    current: str = "",
    url: str = "",
    timeout: int = CHECK_TIMEOUT,
) -> Optional[Update]:
    """Ask what the newest release is; return it only if it is newer.

    ``None`` means "already up to date", which is an answer rather than a
    failure.  Anything actually wrong raises :class:`UpdateError`.
    """
    ctx = ctx or UpdateContext()
    ctx.begin("check")
    ctx.log(f"Asking {url or versions.MANIFEST_URL}")
    document = _fetch(url or versions.MANIFEST_URL, timeout)
    ctx.progress(60)

    update = parse_manifest(document)
    installed = current or versions.__version__
    ctx.log(f"Installed {installed}, published {update.version}")

    if not versions.is_newer(update.version, installed,
                             allow_prerelease=allow_prerelease):
        ctx.progress(100)
        if update.prerelease and not allow_prerelease:
            # Not "up to date" — there is something newer, it is simply not
            # the kind of thing this user asked to be offered.
            ctx.log(f"{update.version} is a pre-release; not offering it.")
        else:
            ctx.log("Already up to date.")
        return None

    _requirements_met(update)
    ctx.progress(100)
    ctx.log(f"LinRAR {update.version} is available ({update.artifact.name}).")
    return update


# --------------------------------------------------------------- downloading


def _hash_file(path: str, ctx: UpdateContext, report: bool = False) -> str:
    digest = hashlib.sha256()
    size = os.path.getsize(path) or 1
    read = 0
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(256 * 1024), b""):
            digest.update(block)
            read += len(block)
            if report:
                ctx.progress(int(read * 100 / size), read, size)
            ctx.checkpoint()
    return digest.hexdigest()


def download(update: Update, ctx: UpdateContext, *, directory: str = "") -> str:
    """Fetch the tarball, reporting bytes as they arrive.  Returns its path.

    A download that is already in the cache and already hashes correctly is
    used as it is: an update interrupted at the install step should not have to
    come down the wire twice.
    """
    artifact = update.artifact
    if artifact is None:                     # pragma: no cover - refused earlier
        raise UpdateError("This update has nothing to download.")

    directory = directory or os.path.join(cache_dir(), update.version)
    os.makedirs(directory, exist_ok=True)
    target = os.path.join(directory, artifact.name)

    ctx.begin("download")
    if os.path.isfile(target) and os.path.getsize(target) == artifact.size:
        ctx.log(f"Found {artifact.name} in the cache; checking it.")
        if _hash_file(target, ctx) == artifact.sha256:
            ctx.log("The cached download is intact; not fetching it again.")
            ctx.progress(100, artifact.size, artifact.size)
            return target
        ctx.log("The cached copy does not match; downloading again.")

    ctx.log(f"Downloading {artifact.url}")
    request = urllib.request.Request(
        artifact.url, headers={"User-Agent": USER_AGENT}
    )
    partial = f"{target}.part"
    started = time.monotonic()
    received = 0
    try:
        with urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT) as response:
            declared = response.headers.get("Content-Length")
            total = int(declared) if declared and declared.isdigit() else artifact.size
            if total and artifact.size and total != artifact.size:
                raise UpdateError(
                    "The download is not the size the release says it is.",
                    f"The manifest says {artifact.size} bytes, the server "
                    f"offered {total}.",
                )
            with open(partial, "wb") as handle:
                while True:
                    ctx.checkpoint()
                    block = response.read(128 * 1024)
                    if not block:
                        break
                    handle.write(block)
                    received += len(block)
                    # A server that keeps sending would otherwise fill the
                    # disk.  Only enforceable when the release said how big it
                    # is, which every manifest LinRAR publishes does.
                    limit = max(total, artifact.size)
                    if limit and received > limit + 1024:
                        raise UpdateError(
                            "The download is longer than the release says it "
                            "is, so it was stopped.",
                            f"Expected {limit} bytes, still arriving after "
                            f"{received}.",
                        )
                    ctx.progress(
                        int(received * 100 / total) if total else 0, received, total
                    )
    except Cancelled:
        _remove(partial)
        raise
    except UpdateError:
        _remove(partial)
        raise
    except (OSError, urllib.error.URLError) as error:
        _remove(partial)
        raise UpdateError("The download failed.", str(error)) from None

    if artifact.size and received != artifact.size:
        _remove(partial)
        raise UpdateError(
            "The download ended early.",
            f"{received} bytes of an expected {artifact.size} arrived.",
        )

    os.replace(partial, target)
    seconds = max(time.monotonic() - started, 0.001)
    ctx.log(
        f"Downloaded {received} bytes in {seconds:.1f}s "
        f"({received / seconds / 1024:.0f} KB/s)."
    )
    ctx.progress(100, received, received)
    return target


def verify(path: str, update: Update, ctx: UpdateContext) -> None:
    """Re-read the file from disk and check its SHA-256 against the release.

    Deliberately reading it back rather than trusting a hash computed while it
    streamed past: this is what proves what is *on the disk* is what was
    published, and it is the last point at which a bad download is cheap.
    """
    artifact = update.artifact
    ctx.begin("verify")
    ctx.log(f"Expecting SHA-256 {artifact.sha256}")
    found = _hash_file(path, ctx, report=True)
    ctx.log(f"Computed SHA-256 {found}")
    if found != artifact.sha256:
        _remove(path)
        raise UpdateError(
            "The download does not match its checksum and was deleted.",
            f"Expected {artifact.sha256}\nFound    {found}\n\n"
            "Either the download was corrupted, or the file is not the one "
            "that was published. LinRAR will not install it.",
        )
    ctx.progress(100)
    ctx.log("The download is exactly what was published.")


# ----------------------------------------------------------------- unpacking


def _safe_members(archive: tarfile.TarFile, destination: str, prefix: str):
    """Every member, once it is proved harmless.

    A tarball off the network gets read with the same suspicion as an archive a
    user opens: nothing may escape the destination through ``..`` or an
    absolute path, nothing may be a symlink pointing out of it, and nothing may
    be a device node or a socket.  Refusing outright beats sanitising, because
    a member that needs sanitising has no business in a LinRAR release.
    """
    root = os.path.realpath(destination)
    for member in archive.getmembers():
        name = member.name
        if name.startswith("/") or os.path.isabs(name) or ".." in name.split("/"):
            raise UpdateError(
                "The update archive tries to write outside its own folder.",
                f"Refused member: {name}",
            )
        if not (member.isfile() or member.isdir()):
            raise UpdateError(
                "The update archive contains something that is not a file.",
                f"Refused member: {name} (type {member.type!r})",
            )
        top = name.split("/")[0]
        if top != prefix:
            raise UpdateError(
                "The update archive is not laid out the way a release is.",
                f"Expected everything under {prefix}/, found {name}",
            )
        target = os.path.realpath(os.path.join(root, name))
        if target != root and not target.startswith(root + os.sep):
            raise UpdateError(
                "The update archive tries to write outside its own folder.",
                f"Refused member: {name}",
            )
        yield member


def unpack(path: str, update: Update, ctx: UpdateContext, *, directory: str = "") -> str:
    """Extract the tarball and return the unpacked project folder."""
    ctx.begin("unpack")
    directory = directory or os.path.join(cache_dir(), update.version, "tree")
    shutil.rmtree(directory, ignore_errors=True)
    os.makedirs(directory, exist_ok=True)

    prefix = f"linrar-{update.version}"
    ctx.log(f"Unpacking {os.path.basename(path)}")
    try:
        with tarfile.open(path, "r:gz") as archive:
            members = list(_safe_members(archive, directory, prefix))
            # Python 3.12 grew a member filter for exactly this hazard.  The
            # checks above already refuse everything it would, but asking for
            # it as well costs nothing and keeps newer interpreters quiet.
            extra = {"filter": "data"} if hasattr(tarfile, "data_filter") else {}
            for index, member in enumerate(members, 1):
                archive.extract(member, directory, **extra)
                if index % 10 == 0 or index == len(members):
                    ctx.progress(int(index * 100 / len(members)))
                ctx.checkpoint()
    except (tarfile.TarError, OSError) as error:
        raise UpdateError("The update archive could not be unpacked.",
                          str(error)) from None

    unpacked = os.path.join(directory, prefix)
    _sanity_check(unpacked, update)
    ctx.progress(100)
    ctx.log(f"Unpacked {len(members)} files into {unpacked}")
    return unpacked


def _sanity_check(tree: str, update: Update) -> None:
    """Is what came out of the tarball really the LinRAR it claims to be?"""
    for needed in ("install.sh", os.path.join("linrar", "version.py"),
                   os.path.join("linrar", "_build.py"), "requirements.txt"):
        if not os.path.isfile(os.path.join(tree, needed)):
            raise UpdateError(
                "The update is missing part of the application and will not "
                "be installed.",
                f"{needed} is not in the archive.",
            )
    reported = _version_of(tree)
    if reported != update.version:
        raise UpdateError(
            "The update does not contain the version it claims to.",
            f"The release says {update.version}; the files say "
            f"{reported or 'nothing at all'}.",
        )


def _version_of(tree: str) -> str:
    """Read ``__version__`` out of a tree without importing it."""
    try:
        with open(os.path.join(tree, "linrar", "version.py"),
                  encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("__version__ = "):
                    return line.split('"')[1]
    except (OSError, IndexError):
        return ""
    return ""


# ------------------------------------------------------------------ applying


def _remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def _ignore_for_backup(_directory: str, names: List[str]) -> List[str]:
    return [name for name in names if name in NOT_BACKED_UP]


def back_up(project: str, ctx: UpdateContext) -> str:
    """Copy the whole project aside, and return where it went.

    Not an optimisation and not optional: it is what makes every step after
    this one reversible, so a failure half way through installing leaves the
    user with the LinRAR they had rather than neither.
    """
    ctx.begin("backup")
    root = cache_dir()
    os.makedirs(root, exist_ok=True)
    backup = os.path.join(
        root, f"backup-{versions.__version__}-{time.strftime('%Y%m%d-%H%M%S')}"
    )
    shutil.rmtree(backup, ignore_errors=True)
    ctx.log(f"Copying the current install to {backup}")
    try:
        shutil.copytree(project, backup, symlinks=True,
                        ignore=_ignore_for_backup)
    except OSError as error:
        raise UpdateError(
            "The current version could not be backed up, so nothing was "
            "changed.",
            str(error),
        ) from None
    ctx.progress(100)
    return backup


def _replace_tree(project: str, source: str) -> None:
    """Make *project* hold *source*, keeping the entries in PRESERVED."""
    for name in os.listdir(project):
        if name in PRESERVED:
            continue
        victim = os.path.join(project, name)
        if os.path.isdir(victim) and not os.path.islink(victim):
            shutil.rmtree(victim)
        else:
            os.remove(victim)
    for name in os.listdir(source):
        if name in PRESERVED:
            continue
        origin = os.path.join(source, name)
        target = os.path.join(project, name)
        if os.path.isdir(origin) and not os.path.islink(origin):
            shutil.copytree(origin, target, symlinks=True)
        else:
            shutil.copy2(origin, target)


def restore(project: str, backup: str) -> None:
    """Put the backup back.  Best effort, and never raises over a detail."""
    try:
        _replace_tree(project, backup)
    except OSError:
        pass


def _run(argv: List[str], ctx: UpdateContext, cwd: str, timeout: int = 900) -> int:
    """Run a command, streaming its output into the details pane."""
    ctx.log("$ " + " ".join(argv))
    try:
        process = subprocess.Popen(
            argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            # No standard input at all: an update runs with nobody at a
            # terminal, and a script that stops to ask something would
            # otherwise wait for an answer that can never come.
            stdin=subprocess.DEVNULL,
            text=True, errors="replace", env={**os.environ, "NO_COLOR": "1"},
        )
    except OSError as error:
        raise UpdateError(f"Could not run {argv[0]}.", str(error)) from None

    deadline = time.monotonic() + timeout
    assert process.stdout is not None
    for line in process.stdout:
        ctx.log("    " + line.rstrip())
        if time.monotonic() > deadline:
            process.kill()
            raise UpdateError(f"{argv[0]} took too long and was stopped.")
    return process.wait()


def _install_argv(project: str, receipt: Receipt) -> List[str]:
    """The install.sh call that re-wires the desktop for the new version.

    ``--keep-venv`` because the environment is unchanged by an update, and
    ``--no-deps`` because installing system packages would ask for a password
    in the middle of what may be an unattended update; a release that needs a
    new tool says so in its notes.
    """
    argv = [os.path.join(project, "install.sh"),
            "--reinstall", "--keep-venv", "--no-deps", "-y"]
    if receipt.mode == "system":
        argv.append("--system")
    return argv


def _refresh_requirements(project: str, backup: str, ctx: UpdateContext) -> None:
    """Install new Python requirements, but only when they actually changed."""
    new = os.path.join(project, "requirements.txt")
    old = os.path.join(backup, "requirements.txt")
    try:
        if os.path.isfile(old) and open(old).read() == open(new).read():
            return
    except OSError:
        return
    python = os.path.join(project, ".venv", "bin", "python")
    if not os.path.isfile(python):
        ctx.log("Requirements changed but there is no .venv here; skipping.")
        return
    ctx.log("The requirements changed; updating the virtual environment.")
    code = _run([python, "-m", "pip", "install", "--upgrade", "-r", new],
                ctx, project, timeout=600)
    if code != 0:
        raise UpdateError(
            "The new version needs Python packages that could not be "
            "installed.",
            "See the details for what pip said.",
        )


def _verify_installed(project: str, update: Update, ctx: UpdateContext) -> None:
    """Ask the freshly installed copy what it is, in a process of its own.

    Every step can succeed and still leave something that does not run, so the
    update is not called finished until a new interpreter has imported the new
    files and answered with the new version.
    """
    python = os.path.join(project, ".venv", "bin", "python")
    if not os.path.isfile(python):
        python = sys.executable
    finished = subprocess.run(
        [python, "-c", "import linrar, sys; sys.stdout.write(linrar.__version__)"],
        cwd=project, capture_output=True, text=True, timeout=120,
    )
    reported = finished.stdout.strip()
    ctx.log(f"The installed copy reports version {reported or '(nothing)'}.")
    if finished.returncode != 0 or reported != update.version:
        raise UpdateError(
            "The update was installed but does not run, so it was rolled back.",
            (finished.stdout + finished.stderr).strip()[-800:],
        )


def install(
    project: str,
    unpacked: str,
    update: Update,
    ctx: UpdateContext,
    *,
    elevate: str = "auto",
    run_installer: bool = True,
) -> str:
    """Replace *project* with *unpacked*, rolling back if anything fails.

    Returns the backup folder, which is left on disk: an update that went in
    cleanly can still turn out to have been a bad idea an hour later.
    """
    backup = back_up(project, ctx)

    ctx.begin("install")
    receipt = read_receipt(project)
    try:
        ctx.log(f"Replacing the files in {project}")
        _replace_tree(project, unpacked)
        ctx.progress(25)

        _refresh_requirements(project, backup, ctx)
        ctx.progress(40)

        if run_installer and receipt.found:
            argv = _install_argv(project, receipt)
            if receipt.mode == "system" and not elevation.is_root():
                elevated = elevation.SESSION.command(argv, elevate)
                if elevated is None:
                    raise UpdateError(
                        "Administrator rights are needed to finish a "
                        "system-wide update, and none are available.",
                        elevation.manual_instructions(argv),
                    )
                argv = elevated
            ctx.log("Re-running the installer for the new version.")
            code = _run(argv, ctx, project)
            if code != 0:
                raise UpdateError(
                    "The installer refused the new version.",
                    f"install.sh exited {code}; see the details above.",
                )
        elif run_installer:
            ctx.log("No install receipt here, so the desktop wiring is left "
                    "alone; only the files were replaced.")
        ctx.progress(80)

        _verify_installed(project, update, ctx)
        ctx.progress(100)
    except Cancelled:
        ctx.log("Cancelled: putting the previous version back.")
        restore(project, backup)
        raise
    except UpdateError:
        ctx.log("Something went wrong: putting the previous version back.")
        restore(project, backup)
        raise
    except Exception as error:  # noqa: BLE001 - a rollback must cover anything
        ctx.log(f"Unexpected failure ({error}): putting the previous version back.")
        restore(project, backup)
        raise UpdateError("The update failed and was rolled back.",
                          str(error)) from None

    ctx.begin("done")
    ctx.log(f"LinRAR {update.version} is installed.")
    ctx.log(f"The previous version is kept at {backup}")
    ctx.progress(100)
    return backup


def prune_cache(keep: int = 1) -> None:
    """Delete all but the newest *keep* backups, and every stale download."""
    root = cache_dir()
    try:
        entries = sorted(
            (name for name in os.listdir(root) if name.startswith("backup-")),
            reverse=True,
        )
    except OSError:
        return
    for name in entries[keep:]:
        shutil.rmtree(os.path.join(root, name), ignore_errors=True)


def run_update(
    update: Update,
    ctx: UpdateContext,
    *,
    project: str = "",
    elevate: str = "auto",
) -> str:
    """Download, verify, unpack and install *update*.  Returns the backup path.

    The whole pipeline in one call, so the window only has to know about
    stages and the worker thread only has to call one function.
    """
    project = project or PROJECT_DIR
    allowed = eligibility(project)
    if not allowed:
        raise UpdateError(allowed.reason, allowed.suggestion)

    archive = download(update, ctx)
    verify(archive, update, ctx)
    unpacked = unpack(archive, update, ctx)
    backup = install(project, unpacked, update, ctx, elevate=elevate)

    shutil.rmtree(os.path.dirname(unpacked), ignore_errors=True)
    prune_cache()
    return backup


# ----------------------------------------------------------------- restarting


def restart_command(project: str = "") -> List[str]:
    """How to start the new version, best answer first.

    The installed launcher if there is one — it is what the desktop uses and
    what the user's PATH points at — otherwise this project's own interpreter.
    """
    project = project or PROJECT_DIR
    receipt = read_receipt(project)
    launcher = receipt.launcher
    if launcher and os.path.isfile(launcher) and os.access(launcher, os.X_OK):
        return [launcher]
    python = os.path.join(project, ".venv", "bin", "python")
    if os.path.isfile(python):
        return [python, "-m", "linrar"]
    return [sys.executable, "-m", "linrar"]
