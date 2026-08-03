"""LinRAR's version, and everything that has to agree about it.

One string — :data:`__version__` — is the whole truth.  The About box, the
``--version`` line, the installer's receipt, the git tag, the release tarball's
name and the update manifest are all derived from it, so there is no second
copy anywhere to drift out of step.  ``install.sh`` reads it out of this file
with ``sed``, which is why the assignment below is kept on one plain line.

The numbering is `Semantic Versioning <https://semver.org/>`_, and it is a
promise rather than decoration, because a future updater has to be able to
decide *on its own* whether what it found on the server is worth installing:

``MAJOR``
    Something a user relies on changed or went away — a command line flag, a
    settings key that is no longer read, a dropped format.
``MINOR``
    New behaviour, nothing taken away.  Upgrading is always safe.
``PATCH``
    Fixes only.

A pre-release (``2.1.0-rc.1``) always ranks *below* the release it leads to, so
an updater that only wants stable builds can simply skip any version whose
:attr:`Version.is_prerelease` is true.

Two versions are compared with :func:`compare` or :func:`is_newer`, never by
comparing the strings: ``"2.10.0" < "2.9.0"`` is true for text and false for
software.  Build metadata (the ``+g1a2b3c`` an artifact is stamped with) is
ignored when ranking, exactly as the specification requires — it says *which
build*, not *which version*.

This module imports nothing but the standard library, and deliberately no
PyQt6: an updater, the installer's check and ``python -c "import linrar"`` must
all be able to ask for the version on a machine where the GUI cannot even
start.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from functools import total_ordering
from typing import Any, Dict, Optional, Tuple, Union

__all__ = [
    "__version__",
    "VERSION",
    "Version",
    "parse",
    "try_parse",
    "compare",
    "is_newer",
    "tag",
    "full_version",
    "describe",
    "describe_state",
    "installed_version",
    "restart_pending",
    "build_info",
    "is_release_build",
    "channel",
    "MANIFEST_SCHEMA",
    "MANIFEST_NAME",
    "REQUIRES_PYTHON",
    "MANIFEST_URL",
    "LATEST_RELEASE_API",
    "RELEASES_URL",
    "REPOSITORY_URL",
    "PROJECT",
]

#: The version of LinRAR this source tree *is*.  Bump it with
#: ``tools/release.py bump {patch|minor|major|X.Y.Z}`` rather than by hand: the
#: same command moves the CHANGELOG's "Unreleased" section under the new
#: number, which is what the release notes are cut from.
__version__ = "2.1.0"

#: The oldest Python this release runs on.  ``install.sh`` refuses anything
#: older, the update manifest advertises it, and a test keeps the two honest —
#: an updater must not hand a machine a version its interpreter cannot run.
REQUIRES_PYTHON = "3.9"

#: ``owner/repo`` on GitHub.  Every URL below is built from it so that a fork
#: only has to change this one line to get its own releases and updates.
PROJECT = "suryanarayanrenjith/LinRAR"

REPOSITORY_URL = f"https://github.com/{PROJECT}"
RELEASES_URL = f"{REPOSITORY_URL}/releases"

#: The unauthenticated GitHub API endpoint describing the newest release.
#: Usable, but rate limited to 60 requests an hour per address — which is why
#: :data:`MANIFEST_URL` exists and is what an updater should actually poll.
LATEST_RELEASE_API = f"https://api.github.com/repos/{PROJECT}/releases/latest"

#: The update manifest attached to every release.  See :data:`MANIFEST_SCHEMA`.
MANIFEST_NAME = "latest.json"

#: A permanent URL: GitHub redirects ``releases/latest/download/<asset>`` to
#: the newest release's copy of that asset, so an updater can hard-code this
#: and never has to discover a version-numbered path first.  It is a plain
#: static download, so it is not rate limited the way the API is.
MANIFEST_URL = f"{RELEASES_URL}/latest/download/{MANIFEST_NAME}"

#: The shape of that manifest.  A consumer must refuse a document whose
#: ``schema`` it does not know rather than guess at the fields: this number
#: only ever goes up, and only when a field changes meaning or disappears.
MANIFEST_SCHEMA = 1

# Semantic Versioning 2.0.0, with an optional leading "v" so that a git tag
# ("v2.1.0") and the version it stands for parse the same way.  The identifier
# rules are the specification's: no leading zeros on numeric parts, and an
# alphanumeric identifier must contain something that is not a digit.
_SEMVER = re.compile(
    r"""
    ^\s*[vV]?
    (?P<major>0|[1-9]\d*)\.
    (?P<minor>0|[1-9]\d*)\.
    (?P<patch>0|[1-9]\d*)
    (?:-(?P<prerelease>
        (?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)
        (?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*
    ))?
    (?:\+(?P<build>[0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?
    \s*$
    """,
    re.VERBOSE,
)


@total_ordering
@dataclass(frozen=True, eq=False)
class Version:
    """A parsed semantic version that knows how to rank itself.

    Equality and ordering follow the specification, which means build metadata
    is ignored by both: ``2.0.0+g1a2b3c`` and ``2.0.0`` are the same version
    built twice, and an updater must not offer one as an upgrade to the other.
    """

    major: int
    minor: int
    patch: int
    #: The dot-separated identifiers after "-", already split; empty for a
    #: final release.  Kept as text because "rc" and "1" are both legal and
    #: the specification ranks them differently.
    prerelease: Tuple[str, ...] = ()
    #: Whatever followed "+", verbatim and unparsed.
    build: str = ""

    # -- what it is --------------------------------------------------------

    @property
    def release(self) -> Tuple[int, int, int]:
        """``(major, minor, patch)`` — the part that carries the promise."""
        return (self.major, self.minor, self.patch)

    @property
    def is_prerelease(self) -> bool:
        return bool(self.prerelease)

    @property
    def channel(self) -> str:
        """``"stable"`` or ``"prerelease"`` — which audience it is for."""
        return "prerelease" if self.is_prerelease else "stable"

    @property
    def tag(self) -> str:
        """The git tag this version is released under."""
        return f"v{self}"

    # -- ranking -----------------------------------------------------------

    @property
    def _key(self) -> Tuple[Any, ...]:
        """A tuple that sorts the way the specification says versions rank."""
        if self.prerelease:
            # Numeric identifiers rank below alphanumeric ones, and numeric
            # ones compare as numbers, so each identifier becomes a triple of
            # a fixed shape: (kind, number, text).
            identifiers = tuple(
                (0, int(part), "") if part.isdigit() else (1, 0, part)
                for part in self.prerelease
            )
            tail: Tuple[int, Tuple[Any, ...]] = (0, identifiers)
        else:
            # A release outranks every pre-release of the same number, and the
            # empty tuple keeps both branches the same shape.
            tail = (1, ())
        return (self.major, self.minor, self.patch, tail)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, str):
            other = try_parse(other)
        if not isinstance(other, Version):
            return NotImplemented
        return self._key == other._key

    def __lt__(self, other: object) -> bool:
        if isinstance(other, str):
            other = try_parse(other)
        if not isinstance(other, Version):
            return NotImplemented
        return self._key < other._key

    def __hash__(self) -> int:
        return hash(self._key)

    # -- deriving one from another ----------------------------------------

    def bump(self, part: str) -> "Version":
        """The next ``major``, ``minor`` or ``patch`` after this one.

        Dropping a pre-release counts as the bump it was leading to, the way
        every release tool does it: ``2.1.0-rc.1`` bumped by ``minor`` is
        ``2.1.0``, not ``2.2.0``.  Build metadata never survives a bump.
        """
        if part == "major":
            if self.is_prerelease and (self.minor, self.patch) == (0, 0):
                return Version(self.major, 0, 0)
            return Version(self.major + 1, 0, 0)
        if part == "minor":
            if self.is_prerelease and self.patch == 0:
                return Version(self.major, self.minor, 0)
            return Version(self.major, self.minor + 1, 0)
        if part == "patch":
            if self.is_prerelease:
                return Version(self.major, self.minor, self.patch)
            return Version(self.major, self.minor, self.patch + 1)
        raise ValueError(f"cannot bump {part!r}: expected major, minor or patch")

    def __str__(self) -> str:
        text = f"{self.major}.{self.minor}.{self.patch}"
        if self.prerelease:
            text += "-" + ".".join(self.prerelease)
        if self.build:
            text += "+" + self.build
        return text


def parse(text: Union[str, Version]) -> Version:
    """Turn ``2.1.0``, ``v2.1.0`` or ``2.1.0-rc.1+g1a2b3c`` into a version.

    Raises :class:`ValueError` on anything else, and does not try to be clever
    about it: an updater that silently accepts a version it cannot understand
    is an updater that installs the wrong thing.
    """
    if isinstance(text, Version):
        return text
    match = _SEMVER.match(text or "")
    if not match:
        raise ValueError(f"not a semantic version: {text!r}")
    prerelease = match.group("prerelease")
    return Version(
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch")),
        tuple(prerelease.split(".")) if prerelease else (),
        match.group("build") or "",
    )


def try_parse(text: Union[str, Version, None]) -> Optional[Version]:
    """:func:`parse`, but ``None`` instead of an exception.

    For reading a version out of something that may be malformed — a manifest
    off the network, a receipt written by an older install.
    """
    if text is None:
        return None
    try:
        return parse(text)
    except (ValueError, TypeError):
        return None


def compare(left: Union[str, Version], right: Union[str, Version]) -> int:
    """``-1``, ``0`` or ``1`` as *left* is older than, equal to, or newer."""
    first, second = parse(left), parse(right)
    if first < second:
        return -1
    return 1 if second < first else 0


def is_newer(
    candidate: Union[str, Version],
    current: Union[str, Version, None] = None,
    *,
    allow_prerelease: bool = False,
) -> bool:
    """Is *candidate* an upgrade from *current* (this build, by default)?

    This is the one question an updater has to get right, so it is answered
    here rather than in the updater: it also refuses pre-releases unless they
    were asked for, and refuses a candidate it cannot parse instead of
    treating an unreadable version as newer.
    """
    found = try_parse(candidate)
    if found is None:
        return False
    if found.is_prerelease and not allow_prerelease:
        return False
    installed = parse(current if current is not None else __version__)
    return installed < found


# --------------------------------------------------------------- this build
#
# tools/package.sh writes linrar/_build.py into a release artifact, recording
# which commit it was cut from and when.  A source checkout has no such file —
# and must not, or every working tree would claim to be a release — so its
# absence is the normal case and never an error.

_BUILD: Dict[str, str] = {}
try:
    from ._build import BUILD as _STAMPED  # type: ignore[attr-defined]
except Exception:  # pragma: no cover - the ordinary case, in a checkout
    pass
else:  # pragma: no cover - only ever true inside a packaged release
    if isinstance(_STAMPED, dict):
        _BUILD = {str(key): str(value) for key, value in _STAMPED.items()}


#: This source tree's version, parsed once.
VERSION: Version = parse(__version__)


def build_info() -> Dict[str, str]:
    """What is known about *this* build: commit, date, tag, where from.

    Empty in a checkout.  A copy is returned, so a caller cannot edit the
    record of what it is running.
    """
    return dict(_BUILD)


def is_release_build() -> bool:
    """True only inside an artifact produced by the release pipeline."""
    return bool(_BUILD.get("commit"))


def channel() -> str:
    """``stable``, ``prerelease`` or ``source`` — what this copy is.

    ``source`` means a working tree or a plain clone: it carries a version
    number, but nobody published it, so an updater should leave it alone.
    """
    if not is_release_build():
        return "source"
    return VERSION.channel


def tag() -> str:
    """The git tag for this version, ``v2.1.0``."""
    return VERSION.tag


def full_version() -> str:
    """The version with this build's identity attached, when it has one.

    ``2.1.0`` from a checkout, ``2.1.0+g1a2b3c`` from a release artifact.  Still
    a legal semantic version, and still equal to ``2.1.0`` when ranked.
    """
    commit = _BUILD.get("commit", "")
    return f"{__version__}+g{commit[:7]}" if commit else __version__


def describe() -> str:
    """One line for ``--version`` and the About box.

    Machine-readable at the front — the version is always the first field —
    with the build's identity in brackets when there is one to give.
    """
    if not is_release_build():
        return __version__
    parts = [f"g{_BUILD['commit'][:7]}"]
    if _BUILD.get("date"):
        parts.append(_BUILD["date"][:10])
    return f"{__version__} ({', '.join(parts)})"


# ------------------------------------------------------- running vs installed
#
# An update replaces this very file underneath a running process.  From that
# moment there are two versions of LinRAR on the machine and they are not the
# same number: the one in memory, which goes on running until the program is
# restarted, and the one on disk, which is what will start next time.
#
# Everything that reports a version has to know which of the two it means.
# ``__version__`` is the running one -- it cannot be anything else, it was read
# at import.  :func:`installed_version` re-reads the file, so it answers for
# the copy on disk however many times it has been replaced since.


def installed_version() -> str:
    """The version of the files on disk, which is not always the one running.

    Read out of the file rather than taken from this module, because after an
    update this module is a copy of what *used* to be there.  Falls back to the
    running version if the file cannot be read, which keeps every caller's
    arithmetic sane even on a half-broken install.
    """
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "version.py")
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("__version__ = "):
                    found = line.split('"')[1]
                    return found if try_parse(found) else __version__
    except (OSError, IndexError):
        pass
    return __version__


def restart_pending() -> bool:
    """Has an update replaced the files this process is still running from?"""
    return installed_version() != __version__


def describe_state() -> str:
    """What to show a user who may be running one version and have another.

    The same as :func:`describe` until an update lands mid-session, and after
    that it says both — an About box that reports the old number with no
    explanation reads as an update that did not work.
    """
    if not restart_pending():
        return describe()
    return (f"{describe()} — {installed_version()} is installed, "
            "restart to use it")
