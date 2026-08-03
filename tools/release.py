#!/usr/bin/env python3
"""The release tool: bump the version, cut the notes, describe the result.

Everything about a LinRAR release is derived from two files — ``__version__``
in ``linrar/version.py`` and the ``## Unreleased`` section of ``CHANGELOG.md``.
This script is the only thing that edits them, so a release cannot half-happen:
the number and the notes always move together.

    tools/release.py current                 what this tree is
    tools/release.py bump patch              2.0.0  -> 2.0.1
    tools/release.py bump minor --pre rc     2.0.0  -> 2.1.0-rc.1
    tools/release.py bump 3.0.0              an exact number
    tools/release.py check                   is this tree releasable?
    tools/release.py notes                   the notes for this version
    tools/release.py manifest --dir dist     the update manifest

``bump`` renames the CHANGELOG's "Unreleased" heading to the new version and
today's date, and opens an empty "Unreleased" above it.  That is the whole
ceremony: commit the two files, push, and .github/workflows/release.yml sees a
version with no tag and publishes it.

Standard library only, and no import of anything graphical: this runs in CI on
a machine with no Qt, no display and no virtual environment.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from typing import List, Optional, Tuple

# Before linrar is imported, and it matters.  This script rewrites the very
# module it imports, and CPython decides a cached .pyc is still good from the
# source's *seconds* mtime and its size — both of which survive replacing
# "2.0.0" with "2.1.0" in the same second.  Leaving no cache behind, and
# dropping the one the file already had (see write()), is what stops a bump
# from being invisible to the next process that imports it.
sys.dont_write_bytecode = True

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from linrar import version as versions  # noqa: E402  (needs ROOT on the path)
from linrar.version import Version  # noqa: E402

VERSION_FILE = os.path.join(ROOT, "linrar", "version.py")
CHANGELOG_FILE = os.path.join(ROOT, "CHANGELOG.md")

#: The assignment in linrar/version.py, matched the same way install.sh's sed
#: matches it: at the start of a line, double quoted, nothing else on it.
_ASSIGNMENT = re.compile(r'^__version__ = "(?P<version>[^"]*)"$', re.MULTILINE)

#: A CHANGELOG entry: "## Unreleased", "## 2.0.0", "## 2.1.0 — 2026-08-02".
_HEADING = re.compile(r"^## +(?P<title>\S.*?)[ \t]*$", re.MULTILINE)

#: What a pre-release may be called.  Deliberately narrower than the
#: specification allows: a label that starts with a letter reads as a stage
#: ("rc", "beta") and can never be mistaken for a version part.
_PRE_LABEL = re.compile(r"^[a-zA-Z][0-9a-zA-Z-]*$")

#: How the file names an artifact's purpose in the manifest, longest suffix
#: first so ".tar.gz" is not read as ".gz".
_ARTIFACT_KINDS: Tuple[Tuple[str, str], ...] = (
    ("SHA256SUMS", "checksums"),
    (".tar.gz", "source"),
    (".tar.xz", "source"),
    (".AppImage", "appimage"),
    (".whl", "wheel"),
    (".zip", "archive"),
)


class ReleaseError(Exception):
    """Something is wrong with the tree; the message is for a human."""


# ------------------------------------------------------------------ reading


def read(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def write(path: str, text: str) -> None:
    """Replace *path* atomically, so an interrupted bump cannot truncate it."""
    temporary = f"{path}.tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.replace(temporary, path)

    if path.endswith(".py"):
        # A stale .pyc would answer for the file we just changed: the cache is
        # validated against the source's mtime in whole seconds and its size,
        # and rewriting a version in place changes neither.  Dropping it costs
        # one recompile and removes the whole class of "the bump did not take".
        try:
            cached = importlib.util.cache_from_source(path)
        except (NotImplementedError, ValueError):  # pragma: no cover
            return
        if os.path.exists(cached):
            try:
                os.remove(cached)
            except OSError:  # pragma: no cover - read-only cache, harmless
                pass


def current_version() -> Version:
    """The version this tree declares, read from the file rather than imported.

    The file is the authority: a bump earlier in the same process would leave
    an imported module stale, and CI runs several of these commands in a row.
    """
    match = _ASSIGNMENT.search(read(VERSION_FILE))
    if not match:
        raise ReleaseError(
            f"no '__version__ = \"...\"' line in {_relative(VERSION_FILE)}; "
            "install.sh reads it with sed, so it has to stay on one plain line"
        )
    try:
        return versions.parse(match.group("version"))
    except ValueError as error:
        raise ReleaseError(f"{_relative(VERSION_FILE)}: {error}") from None


def _relative(path: str) -> str:
    return os.path.relpath(path, ROOT)


# --------------------------------------------------------------- CHANGELOG


class Section:
    """One ``## ...`` block of the CHANGELOG."""

    def __init__(self, title: str, body: str, start: int, end: int) -> None:
        self.title = title
        self.body = body
        self.start = start          # index of the "#" of the heading
        self.end = end              # index just past the body
        #: The version the heading names, or None for "Unreleased".
        self.version = versions.try_parse(title.split()[0]) if title.split() else None

    @property
    def is_unreleased(self) -> bool:
        return self.title.strip().lower().startswith("unreleased")

    @property
    def has_content(self) -> bool:
        return bool(self.body.strip())


def sections(text: Optional[str] = None) -> List[Section]:
    """Every ``## `` block in the CHANGELOG, in the order they appear."""
    text = read(CHANGELOG_FILE) if text is None else text
    found = list(_HEADING.finditer(text))
    result = []
    for index, match in enumerate(found):
        body_start = match.end()
        body_end = found[index + 1].start() if index + 1 < len(found) else len(text)
        result.append(
            Section(match.group("title"), text[body_start:body_end],
                    match.start(), body_end)
        )
    return result


def find_section(wanted: Version, text: Optional[str] = None) -> Optional[Section]:
    """The section describing *wanted*, whatever date its heading carries."""
    for section in sections(text):
        if section.version is not None and section.version == wanted:
            return section
    return None


def unreleased_section(text: Optional[str] = None) -> Optional[Section]:
    for section in sections(text):
        if section.is_unreleased:
            return section
    return None


def newest_documented() -> Optional[Version]:
    """The highest version the CHANGELOG describes."""
    numbered = [s.version for s in sections() if s.version is not None]
    return max(numbered) if numbered else None


# ---------------------------------------------------------------------- git


def git(*arguments: str) -> str:
    """Run git in the project, returning "" rather than raising."""
    try:
        finished = subprocess.run(
            ["git", "-C", ROOT, *arguments],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return finished.stdout.strip() if finished.returncode == 0 else ""


def is_checkout() -> bool:
    return git("rev-parse", "--is-inside-work-tree") == "true"


def released_versions() -> List[Version]:
    """Every version that already has a tag, newest last."""
    found = []
    for line in git("tag", "--list", "v*").splitlines():
        parsed = versions.try_parse(line.strip())
        if parsed is not None:
            found.append(parsed)
    return sorted(found)


def tag_exists(tag: str) -> bool:
    return bool(git("rev-parse", "--verify", "--quiet", f"refs/tags/{tag}"))


# ------------------------------------------------------------------ bumping


def next_version(current: Version, spec: str, pre: str = "") -> Version:
    """The version *spec* asks for, checked against the one we are on.

    *spec* is ``major``, ``minor``, ``patch`` or an exact number.  ``--pre``
    turns the result into a pre-release, continuing the current series when it
    is already one: ``2.1.0-rc.1`` bumped again with ``--pre rc`` is
    ``2.1.0-rc.2``, not ``2.2.0-rc.1``.
    """
    if spec in ("major", "minor", "patch"):
        target = current.bump(spec)
    else:
        try:
            target = versions.parse(spec)
        except ValueError:
            raise ReleaseError(
                f"{spec!r} is neither major, minor, patch nor a version number"
            ) from None
        if target.build:
            raise ReleaseError(
                f"{target} carries build metadata; that is stamped onto an "
                "artifact when it is built, never written into the source"
            )

    if pre:
        if not _PRE_LABEL.match(pre):
            raise ReleaseError(
                f"{pre!r} is not a usable pre-release label; use a word that "
                "starts with a letter, such as 'rc', 'beta' or 'alpha'"
            )
        continuing = (
            current.is_prerelease
            and current.release == target.release
            and current.prerelease[0] == pre
        )
        counter = 1
        if continuing and len(current.prerelease) > 1 and current.prerelease[1].isdigit():
            counter = int(current.prerelease[1]) + 1
        target = Version(*target.release, prerelease=(pre, str(counter)))

    if not current < target:
        raise ReleaseError(
            f"{target} does not come after {current}; a version number only "
            f"ever goes up, or an updater that already has {current} would be "
            f"offered {target} as an upgrade to it"
        )
    return target


def apply_version(target: Version) -> str:
    """Write *target* into linrar/version.py, returning the new file."""
    text = read(VERSION_FILE)
    updated, count = _ASSIGNMENT.subn(
        lambda _: f'__version__ = "{target}"', text, count=1
    )
    if count != 1:
        raise ReleaseError(f"could not rewrite {_relative(VERSION_FILE)}")
    return updated


def apply_changelog(target: Version, date: str, *, allow_empty: bool) -> str:
    """Promote "Unreleased" to *target*, returning the new CHANGELOG."""
    text = read(CHANGELOG_FILE)
    section = unreleased_section(text)
    if section is None:
        raise ReleaseError(
            f"{_relative(CHANGELOG_FILE)} has no '## Unreleased' section; that "
            "is where a release's notes come from, so add one and describe the "
            "change before releasing it"
        )
    if not section.has_content and not allow_empty:
        raise ReleaseError(
            "'## Unreleased' is empty, so this release would ship with no "
            "notes. Describe the change first, or pass --allow-empty if there "
            "is genuinely nothing a user would notice"
        )
    if find_section(target, text) is not None:
        raise ReleaseError(
            f"{_relative(CHANGELOG_FILE)} already has a section for {target}"
        )

    heading_end = text.index("\n", section.start)
    return (
        text[:section.start]
        + f"## Unreleased\n\n## {target} — {date}"
        + text[heading_end:]
    )


# ------------------------------------------------------------------- manifest


def sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def artifact_kind(name: str) -> str:
    for suffix, kind in _ARTIFACT_KINDS:
        if name == suffix or name.endswith(suffix):
            return kind
    return "asset"


def build_manifest(
    version: Version,
    *,
    commit: str,
    released: str,
    directory: str,
    notes: str,
) -> dict:
    """The document an updater reads: what the newest release is, and where.

    Deliberately flat and self-contained.  A checker only has to fetch this one
    file to answer "is there something newer, and what do I download" — which
    is why the download URLs and the checksums are in it rather than left to be
    discovered through the API.
    """
    tag = version.tag
    manifest = {
        "schema": versions.MANIFEST_SCHEMA,
        "app": "LinRAR",
        "version": str(version),
        "tag": tag,
        "channel": version.channel,
        "prerelease": version.is_prerelease,
        "released": released,
        "commit": commit,
        "requires": {"os": "linux", "python": versions.REQUIRES_PYTHON},
        "release_url": f"{versions.RELEASES_URL}/tag/{tag}",
        "notes": notes,
        "artifacts": [],
    }

    if directory and os.path.isdir(directory):
        for name in sorted(os.listdir(directory)):
            path = os.path.join(directory, name)
            # The manifest never lists itself: it is written into the same
            # directory, and its own size and hash change as it is written.
            if not os.path.isfile(path) or name == versions.MANIFEST_NAME:
                continue
            manifest["artifacts"].append({
                "name": name,
                "kind": artifact_kind(name),
                "size": os.path.getsize(path),
                "sha256": sha256(path),
                "url": f"{versions.RELEASES_URL}/download/{tag}/{name}",
            })
    return manifest


# ------------------------------------------------------------------ commands


def command_current(options: argparse.Namespace) -> int:
    version = current_version()
    if options.json:
        print(json.dumps({
            "version": str(version),
            "tag": version.tag,
            "channel": version.channel,
            "prerelease": version.is_prerelease,
        }, indent=2))
    elif options.tag:
        print(version.tag)
    else:
        print(version)
    return 0


def command_bump(options: argparse.Namespace) -> int:
    current = current_version()
    target = next_version(current, options.spec, options.pre)
    date = options.date or dt.datetime.now(dt.timezone.utc).date().isoformat()

    version_text = apply_version(target)
    changelog_text = apply_changelog(target, date, allow_empty=options.allow_empty)

    if options.dry_run:
        print(f"{current} -> {target}   (dry run, nothing written)")
        return 0

    # The CHANGELOG first: if the disk fills between the two writes, a tree
    # with notes and no bump is a great deal easier to understand than a tree
    # claiming a version nobody wrote notes for.
    write(CHANGELOG_FILE, changelog_text)
    write(VERSION_FILE, version_text)
    print(f"{current} -> {target}")
    print(f"  {_relative(VERSION_FILE)}")
    print(f"  {_relative(CHANGELOG_FILE)}  ## {target} — {date}")
    return 0


def command_notes(options: argparse.Namespace) -> int:
    version = versions.parse(options.version) if options.version else current_version()
    section = find_section(version)
    if section is None or not section.has_content:
        if not options.allow_missing:
            raise ReleaseError(
                f"{_relative(CHANGELOG_FILE)} has nothing under {version}; "
                "release notes are written by hand, not generated from commits"
            )
        print(f"See {versions.REPOSITORY_URL} for what changed in {version}.")
        return 0
    print(section.body.strip())
    return 0


def command_check(options: argparse.Namespace) -> int:
    """Is this tree in a state that may be released? Report every answer."""
    failures = 0

    def report(passed: bool, message: str, detail: str = "") -> None:
        nonlocal failures
        if passed:
            print(f"  ok    {message}")
        else:
            failures += 1
            print(f"  FAIL  {message}" + (f"\n        {detail}" if detail else ""))

    version = current_version()
    print(f"LinRAR {version}  ({_relative(VERSION_FILE)})")

    report(True, f"the version parses as semantic versioning: {version}")

    # The file said one thing; make sure an import says the same, which is what
    # every consumer of the version actually sees.
    imported = subprocess.run(
        [sys.executable, "-c",
         "import linrar; print(linrar.__version__)"],
        capture_output=True, text=True, cwd=ROOT, timeout=60,
    )
    report(
        imported.returncode == 0 and imported.stdout.strip() == str(version),
        "importing linrar reports the same version",
        (imported.stdout + imported.stderr).strip()[-200:],
    )

    section = find_section(version)
    report(
        section is not None and section.has_content,
        f"CHANGELOG.md documents {version}",
        "run 'tools/release.py bump ...', which moves '## Unreleased' under "
        "the new number",
    )

    newest = newest_documented()
    report(
        newest is None or newest <= version,
        "no CHANGELOG section describes a version newer than this one",
        f"CHANGELOG.md documents {newest}, which is ahead of {version}",
    )

    if is_checkout():
        existing = released_versions()
        already = version.tag if tag_exists(version.tag) else ""
        report(
            not already or options.allow_existing_tag,
            f"{version.tag} has not been released yet",
            "that tag exists, so this version has already been published; "
            "bump before releasing again",
        )
        report(
            not existing or existing[-1] < version or bool(already),
            f"{version} comes after the newest tag",
            f"the newest tag is {existing[-1].tag if existing else '-'}",
        )
    else:
        print("  --    not a git checkout, so tags were not inspected")

    print()
    if failures:
        print(f"{failures} problem(s); this tree is not ready to release")
        return 1
    print(f"ready to release {version} as {version.tag}")
    return 0


def command_manifest(options: argparse.Namespace) -> int:
    version = versions.parse(options.version) if options.version else current_version()
    commit = options.commit or git("rev-parse", "HEAD")
    released = options.date or dt.datetime.now(dt.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    notes = ""
    section = find_section(version)
    if section is not None:
        notes = section.body.strip()

    manifest = build_manifest(
        version, commit=commit, released=released,
        directory=options.dir, notes=notes,
    )
    document = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"

    if options.output == "-":
        sys.stdout.write(document)
    else:
        output = options.output or os.path.join(options.dir, versions.MANIFEST_NAME)
        write(output, document)
        print(f"{_relative(output)}  ({len(manifest['artifacts'])} artifact(s))")
    return 0


# --------------------------------------------------------------------- main


def parser() -> argparse.ArgumentParser:
    main_parser = argparse.ArgumentParser(
        prog="tools/release.py",
        description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subcommands = main_parser.add_subparsers(dest="command", required=True)

    show = subcommands.add_parser("current", help="print this tree's version")
    show.add_argument("--tag", action="store_true", help="print v2.1.0 instead")
    show.add_argument("--json", action="store_true", help="print every field")
    show.set_defaults(run=command_current)

    bump = subcommands.add_parser(
        "bump", help="raise the version and promote the CHANGELOG"
    )
    bump.add_argument("spec", help="major, minor, patch, or an exact version")
    bump.add_argument("--pre", default="",
                      help="make it a pre-release with this label, e.g. rc")
    bump.add_argument("--date", default="",
                      help="the release date to write (default: today, UTC)")
    bump.add_argument("--allow-empty", action="store_true",
                      help="release even though '## Unreleased' is empty")
    bump.add_argument("--dry-run", action="store_true",
                      help="say what would change and write nothing")
    bump.set_defaults(run=command_bump)

    notes = subcommands.add_parser(
        "notes", help="print a version's CHANGELOG section"
    )
    notes.add_argument("version", nargs="?", default="",
                       help="which version (default: this tree's)")
    notes.add_argument("--allow-missing", action="store_true",
                       help="print a placeholder instead of failing")
    notes.set_defaults(run=command_notes)

    check = subcommands.add_parser(
        "check", help="verify the tree is consistent and releasable"
    )
    check.add_argument("--allow-existing-tag", action="store_true",
                       help="do not fail when this version is already tagged")
    check.set_defaults(run=command_check)

    manifest = subcommands.add_parser(
        "manifest", help="write the update manifest an updater polls"
    )
    manifest.add_argument("--dir", default="dist",
                          help="the directory holding the release artifacts")
    manifest.add_argument("--output", default="",
                          help="where to write it ('-' for standard output)")
    manifest.add_argument("--version", default="", help="override the version")
    manifest.add_argument("--commit", default="", help="the commit released")
    manifest.add_argument("--date", default="",
                          help="the release timestamp, ISO 8601 UTC")
    manifest.set_defaults(run=command_manifest)

    return main_parser


def main(argv: List[str]) -> int:
    options = parser().parse_args(argv[1:])
    try:
        return options.run(options)
    except ReleaseError as error:
        print(f"release: {error}", file=sys.stderr)
        return 1
    except (OSError, ValueError) as error:
        print(f"release: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
