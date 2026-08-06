"""Theme packs: the colour schemes a user can drop in, as WinRAR has always had.

WinRAR ships a handful of themes and lets anybody install more from a file.
LinRAR does the same, except that its chrome is a Qt style sheet built from a
record of colours and its icons are SVG drawn from a second record of colours
(see :mod:`linrar.ui.theme` and :mod:`linrar.ui.icons`).  A theme pack is
therefore *data*: the two colour records, a few metrics, and optionally raw SVG
for individual icons.  Nothing in a pack is executed, which is the whole point
-- a theme is something you download from a stranger.

**Anything in a theme folder that could be a theme is treated as one.**  People
drop in what they were given, which is a folder, or a zip, or a zip that
unpacked into a folder inside a folder, and being clever about only one of those
would just mean the theme silently not appearing.  So all of these load:

``themes/midnight-neon/theme.json``
    A directory.  ``icons/<name>.svg`` beside the manifest replaces individual
    glyphs; ``preview.png`` is shown by the manager if it is there.

``themes/midnight-neon/midnight-neon/theme.json``
    The same, one level down -- what a zip tool leaves behind.

``themes/midnight-neon/anything.json``
    A directory holding exactly one JSON file, whatever it is called.

``themes/midnight-neon.linrar-theme``
    One file: the JSON manifest on its own, **or a zip** of the directory
    above, read in place without unpacking anything.  Told apart by the first
    bytes rather than the suffix.  ``.theme``, ``.json`` and ``.zip`` work too.

The manifest, with every key optional except the colours:

.. code-block:: json

    {
      "name": "Midnight Neon",
      "author": "you",
      "version": "1.0",
      "description": "one line for the manager",
      "base": "dark",
      "accent": "#4DD9FF",
      "font": {"family": "", "size": "9pt"},
      "metrics": {"radius": 0, "button_radius": 0, "card_radius": 0},
      "colors": {"window": "#12141C", "...": "..."},
      "icons":  {"folder": ["#FBE09B", "#F2C14E", "#C68F22"], "...": "..."},
      "icon_svg": {"add": "<svg ...>"},
      "stylesheet": "QToolBar#MainToolBar { padding: 6px; }"
    }

``base`` picks the built-in palette the pack starts from, so a manifest only
has to say what it changes.  Anything it does not name keeps the built-in
value, which is what stops a half-written theme from producing black text on a
black list.

**Nothing is ever silently dropped.**  Every mistake becomes a :class:`Problem`
that says where it is, what was found, what belongs there and how to fix it,
with a line of JSON to copy.  A theme with mistakes in it still loads and uses
the parts that were right; a theme that cannot load at all becomes a
:class:`BrokenTheme`, which the manager *lists*, because a theme somebody just
dropped in and cannot see is the one failure they cannot debug.

Where packs are looked for: the ``themes/`` folder beside the application, the
system data directories, and ``$XDG_DATA_HOME/LinRAR/themes``.  Whichever of
those is writable is searched **last**, so a theme you dropped in always wins
over one installed for the whole machine, and it is the only one
:func:`install` writes to or :func:`remove` deletes from.
``LINRAR_THEMES_DIR`` replaces the whole search path with a colon-separated
list of its own, which is what the test suite uses.

This module deliberately knows nothing about Qt widgets or about the *names* of
the colour fields: it validates the shape of the data and hands over plain
dictionaries.  The UI layer owns the field lists, and reports anything it does
not recognise back into :attr:`ThemePack.problems`.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any

#: The extensions a distributable theme may use.  ``.theme`` is what WinRAR
#: calls its own, and somebody will try it.
SUFFIXES = (".linrar-theme", ".theme", ".json", ".zip")

#: What a theme directory should contain.  A lone JSON file of any other name is
#: accepted too -- see :func:`_manifest_in`.
MANIFEST = "theme.json"

#: Optional extras inside a theme directory.
ICON_DIR = "icons"
PREVIEW = "preview.png"

#: Replaces the whole search path when set; colon-separated, lowest first.
SEARCH_ENV = "LINRAR_THEMES_DIR"

#: The two built-in themes.  Reserved: a pack may not claim either id, or
#: selecting "dark" would stop meaning the dark theme.
BUILTIN_IDS = ("light", "dark")

#: A colour, as a style sheet can use it: ``#rgb``, ``#rrggbb``, ``#aarrggbb``.
#: Deliberately strict.  Qt would also take a colour *name*, but those come
#: from a table that varies, and a theme that renders differently on another
#: machine is worse than one that is rejected here.
_COLOR = re.compile(r"^#(?:[0-9A-Fa-f]{3}|[0-9A-Fa-f]{4}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})$")

#: An id: what the settings file stores and what a directory is called.
_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")

#: How much of a file to read before deciding it cannot be a manifest.  A
#: theme is a few kilobytes; anything far larger is somebody's mistake, and
#: reading it into memory to find that out is the mistake being repeated.
MAX_BYTES = 2 * 1024 * 1024

#: Icon overrides are SVG source, so they are size-capped too.
MAX_ICON_BYTES = 512 * 1024

#: How far down a dropped folder is searched for a manifest.  One level covers
#: the wrapper a zip tool adds; more would start finding things nobody meant.
MAX_DEPTH = 2

_ZIP_MAGIC = b"PK\x03\x04"

#: Files that live in theme folders and are not themes, so finding one is not
#: worth a complaint.
_IGNORED_NAMES = ("index.theme", "readme.json", "package.json")


# ---------------------------------------------------------------- diagnostics


@dataclass(frozen=True)
class Problem:
    """One thing wrong with a theme, and what to do about it.

    Four separate fields rather than a sentence, because the manager shows them
    as a table and the four questions a person actually has are *where*, *what
    did I write*, *what belongs there* and *what do I write instead*.
    """

    where: str            #: "colors.window", "metrics.radius", the file itself
    found: str            #: what was there, as written
    expected: str         #: what belongs there
    fix: str              #: a concrete instruction, with JSON to copy
    #: True when this is why the whole theme could not load.
    fatal: bool = False

    def line(self) -> str:
        """One line, for a list or a tooltip."""
        head = f"{self.where}: " if self.where else ""
        return f"{head}{self.expected}" + (f" (found {self.found})"
                                           if self.found else "")

    def detail(self) -> str:
        """The whole thing, for the panel under the preview."""
        rows = [f"{self.where}" if self.where else "the file"]
        if self.found:
            rows.append(f"    you wrote   {self.found}")
        rows.append(f"    expected    {self.expected}")
        rows.append(f"    to fix it   {self.fix}")
        return "\n".join(rows)


def _quote(value: Any, limit: int = 60) -> str:
    """A value as it would read in a manifest, short enough to show."""
    try:
        text = json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        text = repr(value)
    return text if len(text) <= limit else text[: limit - 1] + "..."


def color_problem(where: str, value: Any) -> Problem:
    """The one mistake everybody makes: a colour that is not one."""
    hint = ""
    if isinstance(value, str) and value.strip() and not value.startswith("#"):
        hint = (
            f' Colour *names* are not accepted, because "{value.strip()}" is a '
            "different colour on different systems."
        )
    return Problem(
        where=where,
        found=_quote(value),
        expected='a hex colour: "#rrggbb", "#rgb" or "#aarrggbb"',
        fix=f'write it as hex, e.g.  "{where.rsplit(".", 1)[-1]}": "#3C6EA5"'
            + hint,
    )


def _closest(name: str, known) -> str:
    """"did you mean" for a misspelled key, or "" when nothing is close."""
    import difflib

    matches = difflib.get_close_matches(name, sorted(known), n=3, cutoff=0.6)
    if not matches:
        return ""
    if len(matches) == 1:
        return matches[0]
    return ", ".join(matches[:-1]) + f" or {matches[-1]}"


def unknown_key_problem(section: str, name: str, known, doc: str) -> Problem:
    """A key nobody recognises, with the names it was probably meant to be."""
    close = _closest(name, known)
    return Problem(
        where=f"{section}.{name}",
        found=_quote(name),
        expected=f"one of the {len(known)} names {doc}",
        fix=(f"did you mean {close}?  Otherwise remove the line: an "
             "unrecognised name is ignored, so it has no effect."
             if close else
             f'remove the line; "{name}" is not something a theme can set, '
             "so it has no effect."),
    )


@dataclass
class BrokenTheme:
    """Something in a theme folder that meant to be a theme and is not.

    Kept and *shown* rather than skipped: a theme somebody just dropped in and
    cannot find anywhere is the one failure they have no way to look into.
    """

    path: str
    id: str
    problem: Problem

    @property
    def label(self) -> str:
        return self.id or os.path.basename(self.path)

    def report(self) -> str:
        return f"{self.path}\n{self.problem.detail()}"


# ---------------------------------------------------------------- the record


@dataclass
class ThemePack:
    """One installed theme, as read off the disk."""

    id: str
    name: str
    base: str = "light"
    author: str = ""
    version: str = ""
    description: str = ""
    accent: str = ""
    path: str = ""
    #: True when it sits somewhere this user can delete it from.
    removable: bool = False
    #: True when it was read out of a zip rather than a folder, which is worth
    #: saying: editing it means unpacking it first.
    zipped: bool = False
    #: How the icon set is drawn -- see :data:`linrar.ui.icons.STYLES`.  Left as
    #: written; this module does not know the list, the UI layer does.
    icon_style: str = ""
    colors: dict[str, str] = field(default_factory=dict)
    ink: dict[str, Any] = field(default_factory=dict)
    #: icon name -> SVG source, replacing the drawn glyph outright.
    icon_svg: dict[str, str] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    font_family: str = ""
    font_size: str = ""
    stylesheet: str = ""
    preview: str = ""
    #: Everything wrong with it that was not fatal.
    problems: list[Problem] = field(default_factory=list)

    @property
    def label(self) -> str:
        return self.name or self.id

    def summary(self) -> str:
        """One line: "1.0 by somebody", as much of it as there is."""
        parts = []
        if self.version:
            parts.append(self.version)
        if self.author:
            parts.append(f"by {self.author}")
        return " ".join(parts)

    def report(self) -> str:
        """Everything wrong with it, for Copy report."""
        lines = [f"{self.label}  ({self.id})", self.path, ""]
        if not self.problems:
            lines.append("No problems.")
        else:
            count = len(self.problems)
            lines.append(f"{count} problem{'' if count == 1 else 's'}. "
                         "The rest of the theme was used.")
            lines.append("")
            for index, problem in enumerate(self.problems, 1):
                lines.append(f"{index}. {problem.detail()}")
                lines.append("")
        return "\n".join(lines)


class ThemeError(Exception):
    """A pack could not be read, or installed, at all.

    Carries the :class:`Problem` explaining it, so the same instructions reach
    the manager whether the theme was found on disk or being installed.
    """

    def __init__(self, problem: Problem | str, where: str = "") -> None:
        if isinstance(problem, str):
            problem = Problem(where=where, found="", expected=problem,
                              fix="see above", fatal=True)
        self.problem = problem
        super().__init__(problem.expected)


# ---------------------------------------------------------------- where to look


def _package_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def bundled_dirs() -> list[str]:
    """``themes/`` as it ships: beside the package, and inside it.

    The folder is deliberately outside version control -- it holds downloaded
    data, not source -- so it may well not exist, and both spellings are
    checked because a packager may put it either place.
    """
    package = _package_root()
    return [
        os.path.join(os.path.dirname(package), "themes"),
        os.path.join(package, "themes"),
    ]


def system_dirs() -> list[str]:
    """The machine-wide theme directories, lowest precedence first."""
    found: list[str] = []
    search = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    # XDG lists these most-important first, so they are walked in reverse.
    for base in reversed([d for d in search.split(os.pathsep) if d]):
        for name in ("linrar", "LinRAR"):
            found.append(os.path.join(base, name, "themes"))
    return found


def user_dir() -> str:
    """``$XDG_DATA_HOME/LinRAR/themes``: always this user's, always writable."""
    override = os.environ.get(SEARCH_ENV)
    if override is not None:
        parts = [p for p in override.split(os.pathsep) if p]
        return parts[-1] if parts else ""
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "LinRAR", "themes")


def _writable(path: str) -> bool:
    return bool(path) and os.path.isdir(path) and os.access(path, os.W_OK)


def writable_dir() -> str:
    """The folder a dropped or installed theme is written into.

    The project's own ``themes/`` whenever this user can write to it: that is
    the folder the documentation names, the one **Open themes folder** opens and
    the one people expect to drop a theme into.  On a system-wide install it
    belongs to root, and then it is ``$XDG_DATA_HOME/LinRAR/themes`` instead,
    which is why nothing anywhere assumes it knows which of the two it is.
    """
    if os.environ.get(SEARCH_ENV) is not None:
        return user_dir()
    for candidate in bundled_dirs():
        if _writable(candidate):
            return candidate
    # Not there yet: it can be created if its parent allows it.
    first = bundled_dirs()[0]
    if _writable(os.path.dirname(first)):
        return first
    return user_dir()


def search_paths() -> list[str]:
    """Every directory searched, lowest precedence first.

    The writable one goes last, so a theme dropped in by hand always beats one
    of the same name installed for the whole machine.
    """
    override = os.environ.get(SEARCH_ENV)
    if override is not None:
        return [p for p in override.split(os.pathsep) if p]
    found: list[str] = []
    for path in bundled_dirs() + system_dirs() + [user_dir()]:
        if path and path not in found:
            found.append(path)
    writable = writable_dir()
    if writable:
        if writable in found:
            found.remove(writable)
        found.append(writable)
    return found


def ensure_writable_dir() -> str:
    """Create the folder themes are dropped into, and return it ("" if not)."""
    path = writable_dir()
    if not path:
        return ""
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        return ""
    return path


# ---------------------------------------------------------------- reading


def _slug(text: str) -> str:
    """A file or theme name reduced to something an id may be."""
    cooked = re.sub(r"[^a-z0-9._-]+", "-", str(text or "").strip().lower())
    return cooked.strip("-._")[:64]


def _strip_suffix(name: str) -> str:
    lowered = name.lower()
    for suffix in SUFFIXES:
        if lowered.endswith(suffix):
            return name[: -len(suffix)]
    return name


def _colors(raw: Any, problems: list[Problem], where: str) -> dict[str, str]:
    """The ``colors`` map, keeping only real colours."""
    result: dict[str, str] = {}
    if raw in (None, ""):
        return result
    if not isinstance(raw, dict):
        problems.append(Problem(
            where=where, found=_quote(raw),
            expected="an object of name/colour pairs",
            fix='write it as  "colors": { "window": "#2B2F36" }',
        ))
        return result
    for key, value in raw.items():
        name = str(key).strip()
        if not isinstance(value, str) or not _COLOR.match(value.strip()):
            problems.append(color_problem(f"{where}.{name}", value))
            continue
        result[name] = value.strip()
    return result


def _ink(raw: Any, problems: list[Problem]) -> dict[str, Any]:
    """The ``icons`` map: a colour, a list of colours, or a bare number.

    The icon palette is not flat -- ``folder`` is a light/mid/dark triple and
    ``books`` is three of those -- so anything nested is walked rather than
    guessed at, and the UI layer decides which shape each name wanted.
    """
    result: dict[str, Any] = {}
    if raw in (None, ""):
        return result
    if not isinstance(raw, dict):
        problems.append(Problem(
            where="icons", found=_quote(raw),
            expected="an object of name/colour pairs",
            fix='write it as  "icons": { "folder": ["#FBE09B", "#F2C14E", '
                '"#C68F22"] }',
        ))
        return result

    def convert(value: Any, where: str, depth: int = 0):
        if isinstance(value, str):
            text = value.strip()
            if _COLOR.match(text):
                return text
            # shadow_opacity is a number written as text; anything else is not
            # a value this file understands.
            try:
                return f"{float(text):g}"
            except ValueError:
                problems.append(color_problem(f"icons.{where}", value))
                return None
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return f"{float(value):g}"
        if isinstance(value, (list, tuple)):
            if depth >= 2:
                problems.append(Problem(
                    where=f"icons.{where}", found=_quote(value),
                    expected="a colour, or a list of colours, nothing deeper",
                    fix='the deepest a theme goes is "books", which is three '
                        'triples: [["#a","#b","#c"], ...]',
                ))
                return None
            items = [convert(item, where, depth + 1) for item in value]
            return None if any(i is None for i in items) else items
        problems.append(color_problem(f"icons.{where}", value))
        return None

    for key, value in raw.items():
        name = str(key).strip()
        converted = convert(value, name)
        if converted is not None:
            result[name] = converted
    return result


def _svg_map(raw: Any, problems: list[Problem]) -> dict[str, str]:
    """Inline ``icon_svg`` overrides, rejected unless they really are SVG."""
    result: dict[str, str] = {}
    if raw in (None, ""):
        return result
    if not isinstance(raw, dict):
        problems.append(Problem(
            where="icon_svg", found=_quote(raw),
            expected="an object of icon name/SVG source pairs",
            fix='write it as  "icon_svg": { "add": "<svg ...>...</svg>" }, or '
                'put the file at  icons/add.svg  beside the manifest instead',
        ))
        return result
    for key, value in raw.items():
        name = str(key).strip()
        if not isinstance(value, str) or "<svg" not in value:
            problems.append(Problem(
                where=f"icon_svg.{name}", found=_quote(value),
                expected="SVG source, starting with <svg",
                fix='paste the whole file, e.g.  "add": "<svg '
                    'xmlns=\\"http://www.w3.org/2000/svg\\" viewBox=\\"0 0 48 '
                    '48\\">...</svg>"',
            ))
            continue
        if len(value.encode("utf-8", "replace")) > MAX_ICON_BYTES:
            problems.append(Problem(
                where=f"icon_svg.{name}",
                found=f"{len(value) // 1024} KiB of SVG",
                expected=f"under {MAX_ICON_BYTES // 1024} KiB",
                fix="an icon is a few hundred bytes of paths; this is probably "
                    "a traced photograph, which will not draw well at 16 pixels "
                    "anyway",
            ))
            continue
        result[name] = value
    return result


def _metrics(raw: Any, problems: list[Problem]) -> dict[str, int]:
    """Corner radii and the like: small whole numbers, clamped."""
    result: dict[str, int] = {}
    if raw in (None, ""):
        return result
    if not isinstance(raw, dict):
        problems.append(Problem(
            where="metrics", found=_quote(raw),
            expected="an object of name/number pairs",
            fix='write it as  "metrics": { "radius": 3, "button_radius": 4 }',
        ))
        return result
    for key, value in raw.items():
        name = str(key).strip()
        try:
            number = int(round(float(value)))
        except (TypeError, ValueError):
            problems.append(Problem(
                where=f"metrics.{name}", found=_quote(value),
                expected="a whole number of pixels, 0 to 24",
                fix=f'write it as  "{name}": 4, with no quotes around it',
            ))
            continue
        if not 0 <= number <= 24:
            problems.append(Problem(
                where=f"metrics.{name}", found=_quote(value),
                expected="0 to 24 pixels",
                fix=f'use something in range, e.g.  "{name}": '
                    f'{0 if number < 0 else 24}; 0 is square, 3 is the '
                    'built-in look, 8 is very round',
            ))
            continue
        result[name] = number
    return result


def _read_text(path: str, limit: int = MAX_BYTES) -> str:
    size = os.path.getsize(path)
    if size > limit:
        raise ThemeError(Problem(
            where=os.path.basename(path),
            found=f"{size // 1024} KiB",
            expected=f"a manifest under {limit // 1024} KiB",
            fix="a theme manifest is a few KiB of JSON; this is not one. Check "
                "you did not rename something else by mistake.",
            fatal=True,
        ))
    with open(path, "rb") as handle:
        blob = handle.read(limit + 1)
    return _decode(blob, os.path.basename(path))


def _decode(blob: bytes, name: str) -> str:
    if blob.startswith(_ZIP_MAGIC):
        raise ThemeError(Problem(
            where=name, found="a zip archive",
            expected="JSON text",
            fix="this is a zip, not a manifest; it is read as a theme on its "
                "own, so it does not need unpacking; if you meant to edit it, "
                "unpack it into a folder of its own first.",
            fatal=True,
        ))
    return blob.decode("utf-8-sig", "replace")


def parse(text: str, pack_id: str, path: str = "") -> ThemePack:
    """Turn manifest JSON into a :class:`ThemePack`.

    Raises :class:`ThemeError` only for a file that is not a manifest at all.
    Everything else -- a bad colour, an unknown shape -- becomes a
    :class:`Problem` and is skipped, so one typo costs one value rather than
    the theme.
    """
    try:
        raw = json.loads(text)
    except ValueError as error:
        line = getattr(error, "lineno", 0)
        column = getattr(error, "colno", 0)
        where = f"line {line}, column {column}" if line else ""
        raise ThemeError(Problem(
            where=where or "the manifest",
            found=str(error),
            expected="valid JSON",
            fix="the usual causes are a comma after the last item in a list or "
                "object, a missing closing brace, a single quote where a double "
                'one belongs, or a "// comment"; JSON has none. Paste the file '
                "into any JSON validator to find it.",
            fatal=True,
        )) from error
    if not isinstance(raw, dict):
        raise ThemeError(Problem(
            where="the manifest", found=_quote(raw),
            expected="a JSON object",
            fix='the whole file has to be wrapped in braces:  { "name": "...", '
                '"colors": { ... } }',
            fatal=True,
        ))

    problems: list[Problem] = []
    declared = _slug(raw.get("id") or "")
    name = str(raw.get("name") or "").strip()[:80]
    if not pack_id:
        # The file name gave nothing usable.  Fall back rather than refuse.
        pack_id = declared or _slug(name)
    elif declared and declared != pack_id:
        # The id is what the settings file stores, so it follows the file name:
        # renaming a pack must not silently keep pointing at the old one.
        problems.append(Problem(
            where='"id"', found=_quote(declared),
            expected=f'nothing, or "{pack_id}"; the file name decides the id',
            fix=f'rename the folder or file to "{declared}" if that is the id '
                f'you want; otherwise drop the "id" line, since it is ignored.',
        ))
    if pack_id in BUILTIN_IDS:
        raise ThemeError(Problem(
            where=pack_id, found=f'a theme called "{pack_id}"',
            expected="any name that is not a built-in theme's",
            fix=f'"light" and "dark" are LinRAR\'s own two themes. Rename the '
                f'folder or file; "{pack_id}-mine" would do.',
            fatal=True,
        ))
    if not _ID.match(pack_id):
        raise ThemeError(Problem(
            where=pack_id or "the file name",
            found=_quote(pack_id) if pack_id else "nothing usable",
            expected="a name of lower-case letters, digits, dot, dash or "
                     "underscore",
            fix="rename the folder or file to something like  my-theme, or "
                'give the manifest a  "name": "My Theme"  and LinRAR will use '
                "that.",
            fatal=True,
        ))

    base = str(raw.get("base") or "").strip().lower()
    if base not in BUILTIN_IDS:
        if base:
            problems.append(Problem(
                where='"base"', found=_quote(base),
                expected='"light" or "dark"',
                fix='"base" says which built-in theme yours starts from, so '
                    'every colour you do not set has a sensible value: write  '
                    '"base": "dark"  for a dark theme.',
            ))
        base = "light"

    font = raw.get("font") or {}
    if not isinstance(font, dict):
        problems.append(Problem(
            where='"font"', found=_quote(font),
            expected="an object with family and size",
            fix='write it as  "font": { "family": "Inter", "size": "9pt" }',
        ))
        font = {}
    size = str(font.get("size") or "").strip()
    if size and not re.match(r"^\d{1,2}(\.\d+)?(pt|px)$", size):
        problems.append(Problem(
            where="font.size", found=_quote(size),
            expected='a size with its unit: "9pt" or "12px"',
            fix='write  "size": "9pt"; a bare number has no unit, and Qt '
                "needs one.",
        ))
        size = ""

    accent = str(raw.get("accent") or "").strip()
    if accent and not _COLOR.match(accent):
        problems.append(color_problem('"accent"', raw.get("accent")))
        accent = ""

    sheet = raw.get("stylesheet") or ""
    if not isinstance(sheet, str):
        problems.append(Problem(
            where='"stylesheet"', found=_quote(sheet),
            expected="one string of Qt style sheet",
            fix='write it as one string:  "stylesheet": "QToolBar '
                '{ padding: 6px; }"; a list of lines has to be joined with '
                "\\n into a single value.",
        ))
        sheet = ""

    colors = _colors(raw.get("colors"), problems, "colors")
    pack = ThemePack(
        id=pack_id,
        name=name or pack_id,
        base=base,
        author=str(raw.get("author") or "").strip()[:80],
        version=str(raw.get("version") or "").strip()[:24],
        description=str(raw.get("description") or "").strip()[:400],
        accent=accent or colors.get("sel_bottom", ""),
        path=path,
        colors=colors,
        ink=_ink(raw.get("icons"), problems),
        icon_svg=_svg_map(raw.get("icon_svg"), problems),
        metrics=_metrics(raw.get("metrics"), problems),
        font_family=str(font.get("family") or "").strip()[:80],
        font_size=size,
        stylesheet=sheet,
        icon_style=str(raw.get("icon_style") or "").strip().lower()[:16],
        problems=problems,
    )
    if not pack.colors and not pack.ink:
        raise ThemeError(Problem(
            where="the manifest",
            found="no usable colours",
            expected='at least a "colors" or an "icons" object',
            fix='a theme has to change something. The smallest one that works '
                'is:  { "name": "Mine", "base": "dark", "colors": '
                '{ "window": "#202430" } }',
            fatal=True,
        ))
    return pack


# -- finding the manifest in whatever was dropped in -----------------------


def _manifest_in(folder: str) -> str:
    """The manifest inside *folder*, at any of the places people put it.

    ``theme.json`` first, then a lone JSON file of any name, then one level
    down -- which is the wrapper folder every zip tool creates.  Returns "" for
    a folder that holds no theme at all, which is not an error: a themes
    directory can perfectly well contain something else.
    """
    direct = os.path.join(folder, MANIFEST)
    if os.path.isfile(direct):
        return direct
    try:
        entries = sorted(os.listdir(folder))
    except OSError:
        return ""
    jsons = [
        e for e in entries
        if e.lower().endswith(".json") and e.lower() not in _IGNORED_NAMES
        and os.path.isfile(os.path.join(folder, e))
    ]
    if len(jsons) == 1:
        return os.path.join(folder, jsons[0])
    return ""


def _theme_root(folder: str, depth: int = 0) -> tuple[str, str]:
    """(the folder that is the theme, its manifest), searching downwards."""
    manifest = _manifest_in(folder)
    if manifest:
        return folder, manifest
    if depth + 1 >= MAX_DEPTH:
        return "", ""
    try:
        entries = sorted(os.listdir(folder))
    except OSError:
        return "", ""
    inner = [
        e for e in entries
        if not e.startswith(".") and os.path.isdir(os.path.join(folder, e))
    ]
    for entry in inner:
        root, manifest = _theme_root(os.path.join(folder, entry), depth + 1)
        if manifest:
            return root, manifest
    return "", ""


def load(path: str) -> ThemePack:
    """Read one pack: a folder, a single JSON file, or a zip, read in place."""
    path = os.path.abspath(path)
    if os.path.isdir(path):
        root, manifest = _theme_root(path)
        if not manifest:
            raise ThemeError(Problem(
                where=os.path.basename(path),
                found="a folder with no manifest in it",
                expected=f"a {MANIFEST} in the folder, or one level inside it",
                fix=f"put the theme's {MANIFEST} at  "
                    f"{os.path.basename(path)}/{MANIFEST}. If you unpacked a "
                    "zip, the manifest may be one folder deeper than expected.",
                fatal=True,
            ))
        pack = parse(_read_text(manifest), _slug(os.path.basename(path)), path)
        _load_icon_dir(pack, os.path.join(root, ICON_DIR))
        preview = os.path.join(root, PREVIEW)
        if os.path.isfile(preview):
            pack.preview = preview
        return pack

    if not os.path.isfile(path):
        raise ThemeError(Problem(
            where=path, found="nothing",
            expected="a theme folder or file",
            fix="check the path; it may have been moved or deleted.",
            fatal=True,
        ))
    if _is_zip(path):
        return _load_zip(path)
    return parse(
        _read_text(path), _slug(_strip_suffix(os.path.basename(path))), path
    )


def _is_zip(path: str) -> bool:
    try:
        with open(path, "rb") as handle:
            return handle.read(4) == _ZIP_MAGIC
    except OSError:
        return False


def _load_zip(path: str) -> ThemePack:
    """Read a zipped theme without unpacking it.

    A ``.linrar-theme`` dropped into the themes folder is a theme, full stop,
    asking somebody to run an installer on a file that is already in the right
    place would be a strange thing to insist on.
    """
    import zipfile

    try:
        archive = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as error:
        raise ThemeError(Problem(
            where=os.path.basename(path), found=str(error),
            expected="a readable zip archive",
            fix="the download may be incomplete or corrupt; fetch it again.",
            fatal=True,
        )) from error
    with archive:
        members = _safe_members(archive)
        root = _manifest_member(members, path)
        prefix = root[: root.rindex("/") + 1] if "/" in root else ""
        try:
            text = _decode(archive.read(root), os.path.basename(root))
        except (KeyError, OSError) as error:      # pragma: no cover - defensive
            raise ThemeError(Problem(
                where=os.path.basename(path), found=str(error),
                expected="a readable manifest inside the archive",
                fix="repack the theme, or unpack it into a folder instead.",
                fatal=True,
            )) from error
        pack = parse(text, _slug(_strip_suffix(os.path.basename(path))), path)
        pack.zipped = True
        icon_prefix = f"{prefix}{ICON_DIR}/"
        for member in members:
            name = member.replace("\\", "/")
            if not name.startswith(icon_prefix) or not name.endswith(".svg"):
                continue
            leaf = name[len(icon_prefix):]
            if "/" in leaf:
                continue
            try:
                source = _decode(archive.read(member), leaf)
            except (KeyError, OSError):           # pragma: no cover - defensive
                continue
            if "<svg" in source:
                pack.icon_svg[leaf[:-4]] = source
        return pack


def _manifest_member(names: list[str], path: str) -> str:
    """The manifest inside a zip, wherever the packer put it."""
    candidates: dict[int, list[str]] = {}
    for name in names:
        parts = [p for p in name.replace("\\", "/").split("/") if p not in ("", ".")]
        if not parts or not parts[-1].lower().endswith(".json"):
            continue
        if parts[-1].lower() in _IGNORED_NAMES:
            continue
        candidates.setdefault(len(parts) - 1, []).append(name)
    for depth in sorted(candidates):
        at_depth = candidates[depth]
        exact = [n for n in at_depth
                 if n.replace("\\", "/").rsplit("/", 1)[-1] == MANIFEST]
        if exact:
            return exact[0]
        if len(at_depth) == 1:
            return at_depth[0]
    raise ThemeError(Problem(
        where=os.path.basename(path),
        found="a zip with no manifest in it",
        expected=f"a {MANIFEST} inside the archive",
        fix=f"zip the theme's *folder*, or the {MANIFEST} itself; an archive "
            "of unrelated files is not a theme.",
        fatal=True,
    ))


def _load_icon_dir(pack: ThemePack, folder: str) -> None:
    """``icons/add.svg`` and friends, replacing the drawn glyph."""
    if not os.path.isdir(folder):
        return
    try:
        entries = sorted(os.listdir(folder))
    except OSError as error:
        pack.problems.append(Problem(
            where=f"{ICON_DIR}/", found=error.strerror or str(error),
            expected="a readable folder",
            fix="check the folder's permissions, or delete it; the theme "
                "works without it.",
        ))
        return
    for entry in entries:
        if not entry.lower().endswith(".svg"):
            continue
        name = entry[:-4]
        target = os.path.join(folder, entry)
        try:
            source = _read_text(target, MAX_ICON_BYTES)
        except (OSError, ThemeError) as error:
            problem = getattr(error, "problem", None)
            pack.problems.append(problem or Problem(
                where=f"{ICON_DIR}/{entry}", found=str(error),
                expected="readable SVG",
                fix="check the file, or remove it.",
            ))
            continue
        if "<svg" not in source:
            pack.problems.append(Problem(
                where=f"{ICON_DIR}/{entry}", found="a file that is not SVG",
                expected="an SVG file, starting with <svg",
                fix="only SVG can be used: a PNG or a JPEG here is ignored. "
                    "Export the icon as plain SVG.",
            ))
            continue
        # A file on disk outranks the same name written inline: it is the one
        # the user can open in an editor and see change.
        pack.icon_svg[name] = source


# ---------------------------------------------------------------- discovery

#: id -> pack, built by :func:`discover` and kept until :func:`reload`.
_CACHE: dict[str, ThemePack] | None = None

#: Things that meant to be themes and are not.
_BROKEN: list[BrokenTheme] = []


def _candidates(folder: str) -> list[str]:
    """Everything in *folder* that might be a theme."""
    try:
        entries = sorted(os.listdir(folder))
    except OSError:
        return []
    found = []
    for entry in entries:
        if entry.startswith("."):
            continue
        full = os.path.join(folder, entry)
        if os.path.isdir(full):
            # Only folders that really do hold a manifest, so an unrelated
            # folder in the themes directory is not reported as broken.
            if _theme_root(full)[1]:
                found.append(full)
        elif entry.lower().endswith(SUFFIXES):
            if entry.lower() in _IGNORED_NAMES:
                continue
            found.append(full)
    return found


def discover(rescan: bool = False) -> dict[str, ThemePack]:
    """Every readable pack, by id, later directories winning."""
    global _CACHE
    if _CACHE is not None and not rescan:
        return _CACHE
    packs: dict[str, ThemePack] = {}
    broken: dict[str, BrokenTheme] = {}
    for folder in search_paths():
        if not folder or not os.path.isdir(folder):
            continue
        for candidate in _candidates(folder):
            try:
                pack = load(candidate)
            except ThemeError as error:
                broken[os.path.abspath(candidate)] = BrokenTheme(
                    path=candidate,
                    id=_slug(_strip_suffix(os.path.basename(candidate))),
                    problem=error.problem,
                )
                continue
            except OSError as error:
                broken[os.path.abspath(candidate)] = BrokenTheme(
                    path=candidate,
                    id=_slug(_strip_suffix(os.path.basename(candidate))),
                    problem=Problem(
                        where=os.path.basename(candidate),
                        found=error.strerror or str(error),
                        expected="a readable file",
                        fix="check that you can read it, and that the disk it "
                            "is on is still there.",
                        fatal=True,
                    ),
                )
                continue
            pack.removable = _can_delete(pack.path)
            packs[pack.id] = pack
            # A folder that loads is not broken, even if an earlier directory
            # had something broken under the same path.
            broken.pop(os.path.abspath(candidate), None)
    _CACHE = dict(sorted(packs.items(), key=lambda kv: kv[1].label.lower()))
    _BROKEN[:] = sorted(broken.values(), key=lambda b: b.label.lower())
    return _CACHE


def _can_delete(path: str) -> bool:
    """Can this user remove *path*, and is it somewhere LinRAR should be?"""
    if not path:
        return False
    target = os.path.abspath(path)
    parent = os.path.dirname(target)
    if not os.access(parent, os.W_OK):
        return False
    return any(
        os.path.abspath(folder) == parent
        for folder in search_paths() if folder
    )


def reload() -> dict[str, ThemePack]:
    """Look again, after something was installed or edited."""
    return discover(rescan=True)


def find(pack_id: str) -> ThemePack | None:
    return discover().get(str(pack_id or "").strip())


def broken() -> list[BrokenTheme]:
    """What was found in a theme folder and could not be read."""
    discover()
    return list(_BROKEN)


# ---------------------------------------------------------------- installing


def _unique_target(folder: str, base: str, suffix: str = "") -> str:
    """``base`` in ``folder``, with -2, -3 ... if that name is taken."""
    candidate = os.path.join(folder, base + suffix)
    index = 2
    while os.path.exists(candidate):
        candidate = os.path.join(folder, f"{base}-{index}{suffix}")
        index += 1
    return candidate


def _safe_members(archive) -> list[str]:
    """The names in a zip that are safe to write, and where they came from.

    A theme is something downloaded, so the archive is treated as hostile: no
    absolute paths, no ``..``, no symlinks, nothing outside the one directory
    being created.  Anything else and the whole thing is refused rather than
    partly done.
    """
    names: list[str] = []
    for info in archive.infolist():
        name = info.filename.replace("\\", "/")
        if name.endswith("/"):
            continue
        if name.startswith("/") or os.path.isabs(name) or ":" in name.split("/")[0]:
            raise ThemeError(Problem(
                where=name, found="an absolute path inside the archive",
                expected="paths relative to the archive's own folder",
                fix="repack the theme from inside its folder so the names are "
                    "relative. An archive that names absolute paths is refused "
                    "outright, because unpacking it would write outside the "
                    "themes folder.",
                fatal=True,
            ))
        parts = [p for p in name.split("/") if p not in ("", ".")]
        if any(part == ".." for part in parts):
            raise ThemeError(Problem(
                where=name, found='a path containing ".."',
                expected="paths that stay inside the archive's own folder",
                fix="repack the theme without the parent-directory steps. This "
                    "archive would write outside the themes folder, so it is "
                    "refused.",
                fatal=True,
            ))
        # Zip stores the unix mode in the top 16 bits; 0xA000 is a symlink.
        if (info.external_attr >> 16) & 0o170000 == 0o120000:
            raise ThemeError(Problem(
                where=name, found="a symbolic link",
                expected="ordinary files",
                fix="repack the theme with the real files in it (`zip -r` "
                    "follows links with `-y` left off). A link could point "
                    "anywhere on the system, so it is refused.",
                fatal=True,
            ))
        if info.file_size > MAX_BYTES:
            raise ThemeError(Problem(
                where=name, found=f"{info.file_size // 1024} KiB",
                expected=f"files under {MAX_BYTES // 1024} KiB",
                fix="a theme is a manifest and some SVG. Take the large file "
                    "out and repack.",
                fatal=True,
            ))
        names.append(info.filename)
    if not names:
        raise ThemeError(Problem(
            where="the archive", found="nothing",
            expected="a theme folder or manifest",
            fix="the zip is empty; check what you downloaded.",
            fatal=True,
        ))
    return names


def install(source: str, folder: str = "") -> ThemePack:
    """Copy the theme at *source* into the folder themes are kept in.

    Accepts what a user is likely to have: a zip however it was made, a single
    JSON manifest, or an unpacked theme folder.  The pack is read back from
    where it landed, so a successful return means the theme really is installed
    and really does load.
    """
    import shutil
    import zipfile

    source = os.path.abspath(os.path.expanduser(source))
    if not os.path.exists(source):
        raise ThemeError(Problem(
            where=source, found="nothing", expected="a theme folder or file",
            fix="check the path.", fatal=True,
        ))
    target_dir = folder or ensure_writable_dir()
    if not target_dir:
        raise ThemeError(Problem(
            where=writable_dir(), found="a folder that cannot be created",
            expected="a writable themes folder",
            fix="create it by hand, or check the permissions on its parent.",
            fatal=True,
        ))
    os.makedirs(target_dir, exist_ok=True)

    # Already in place: reading it is the whole job.
    if os.path.dirname(source) == os.path.abspath(target_dir):
        reload()
        existing = load(source)
        return _CACHE.get(existing.id, existing) if _CACHE else existing

    stem = _slug(_strip_suffix(os.path.basename(source.rstrip("/")))) or "theme"
    if stem in BUILTIN_IDS:
        raise ThemeError(Problem(
            where=os.path.basename(source), found=f'a theme called "{stem}"',
            expected="any name that is not a built-in theme's",
            fix=f'"light" and "dark" are LinRAR\'s own themes. Rename the file '
                f'to something like "{stem}-mine{os.path.splitext(source)[1]}" '
                "and install it again.",
            fatal=True,
        ))

    if os.path.isdir(source):
        if not _theme_root(source)[1]:
            raise ThemeError(Problem(
                where=os.path.basename(source),
                found="a folder with no manifest in it",
                expected=f"a {MANIFEST} in the folder, or one level inside it",
                fix=f"pick the folder that has {MANIFEST} in it.",
                fatal=True,
            ))
        destination = _unique_target(target_dir, stem)
        shutil.copytree(source, destination)
        return _verify(destination)

    if zipfile.is_zipfile(source):
        with zipfile.ZipFile(source) as archive:
            members = _safe_members(archive)
            manifest = _manifest_member(members, source)
            root = manifest[: manifest.rindex("/")] if "/" in manifest else ""
            destination = _unique_target(target_dir, stem)
            prefix = f"{root}/" if root else ""
            wanted = [
                m for m in members if m.replace("\\", "/").startswith(prefix)
            ]
            try:
                for member in wanted:
                    relative = member.replace("\\", "/")[len(prefix):]
                    if not relative:
                        continue
                    out = os.path.join(destination, *relative.split("/"))
                    os.makedirs(os.path.dirname(out), exist_ok=True)
                    with archive.open(member) as reader, open(out, "wb") as writer:
                        shutil.copyfileobj(reader, writer, 64 * 1024)
            except Exception:
                shutil.rmtree(destination, ignore_errors=True)
                raise
        return _verify(destination)

    # A bare manifest.  Given a folder of its own so icon overrides can be
    # dropped in beside it later without moving anything.
    destination = _unique_target(target_dir, stem)
    os.makedirs(destination)
    try:
        shutil.copyfile(source, os.path.join(destination, MANIFEST))
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    return _verify(destination)


def install_all(sources: list[str]) -> tuple[list[ThemePack], list[tuple[str, ThemeError]]]:
    """Install several at once, as a drop of many files is.

    Returns what worked and what did not, rather than stopping at the first
    failure: dropping five themes and being told about one is not a report.
    """
    done: list[ThemePack] = []
    failed: list[tuple[str, ThemeError]] = []
    for source in sources:
        try:
            done.append(install(source))
        except ThemeError as error:
            failed.append((source, error))
        except OSError as error:
            failed.append((source, ThemeError(Problem(
                where=os.path.basename(source),
                found=error.strerror or str(error),
                expected="a readable theme",
                fix="check the file and the permissions on the themes folder.",
                fatal=True,
            ))))
    if done or failed:
        reload()
    return done, failed


def _verify(destination: str) -> ThemePack:
    """Load what was just written; take it back out again if it will not."""
    import shutil

    try:
        pack = load(destination)
    except (ThemeError, OSError):
        shutil.rmtree(destination, ignore_errors=True)
        raise
    pack.removable = True
    reload()
    return _CACHE.get(pack.id, pack) if _CACHE else pack


def remove(pack_id: str) -> bool:
    """Delete an installed pack.  Only from a folder this user can write to."""
    import shutil

    pack = find(pack_id)
    if pack is None:
        return False
    if not pack.removable or not pack.path:
        raise ThemeError(Problem(
            where=pack.path or pack.label,
            found="a theme installed outside your own themes folder",
            expected="a theme in a folder you can write to",
            fix=f"{pack.label} was installed for every user of this machine, so "
                "it is the system administrator's to remove.",
            fatal=True,
        ))
    target = os.path.abspath(pack.path)
    # Belt and braces: removable was worked out from where it was found, and
    # this is a recursive delete.
    if not _can_delete(target):
        raise ThemeError(Problem(
            where=target, found="a path outside the theme folders",
            expected="a theme inside one of LinRAR's theme folders",
            fix="delete it by hand if that is really what you want.",
            fatal=True,
        ))
    if os.path.isdir(target):
        shutil.rmtree(target)
    else:
        os.remove(target)
    reload()
    return True


def remove_broken(path: str) -> bool:
    """Delete something that was listed as broken.  Same safety as above."""
    import shutil

    target = os.path.abspath(path)
    if not os.path.exists(target):
        return False
    if not _can_delete(target):
        raise ThemeError(Problem(
            where=target, found="a path outside the theme folders",
            expected="a file inside a themes folder you can write to",
            fix="delete it by hand.",
            fatal=True,
        ))
    if os.path.isdir(target):
        shutil.rmtree(target)
    else:
        os.remove(target)
    reload()
    return True
