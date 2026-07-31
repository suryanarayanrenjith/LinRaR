"""Vector icon set drawn in WinRAR's classic style.

The icons are inline SVG rendered on demand, so they stay sharp at any size
without shipping binary assets.  They deliberately avoid a flat look: every
glyph is built from gradient-filled 3D solids with highlights and a soft drop
shadow, matching the glossy toolbar icons WinRAR has used since v3.

The signature glyph is the stack of three banded books.

Each theme gets its own build of the set: the shapes never change, but paper
whites, steel and the drop shadow are re-tuned so nothing glares on the dark
chrome.  :func:`set_theme` swaps the active build, and the render cache is
keyed by theme so both can live side by side.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass

from PyQt6.QtCore import QByteArray, QRectF, Qt
from PyQt6.QtGui import QIcon, QImage, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer

# ---------------------------------------------------------------- palette


@dataclass(frozen=True)
class Ink:
    """The colours one build of the icon set is drawn with."""

    books: tuple[tuple[str, str, str], ...]
    page_light: str
    page_dark: str
    strap_light: str
    strap_dark: str
    strap_deep: str
    green: tuple[str, str, str]
    red: tuple[str, str, str]
    blue: tuple[str, str, str]
    amber: tuple[str, str, str]
    folder: tuple[str, str, str]
    steel: tuple[str, str, str]
    paper_light: str
    paper_dark: str
    paper_edge: str
    ink: str
    gloss: str
    shadow_color: str
    shadow_opacity: str


LIGHT_INK = Ink(
    books=(
        ("#8FD4CB", "#31A99A", "#1B7A6E"),  # bottom book: teal
        ("#C89BE0", "#9A55BE", "#6E2E90"),  # middle book: violet
        ("#8FC0EE", "#3F86CE", "#1E5FA4"),  # top book: blue
    ),
    page_light="#FFFDF4",
    page_dark="#DCCFAE",
    strap_light="#6E6E7C",
    strap_dark="#2A2A34",
    strap_deep="#1A1A22",
    green=("#8BE08B", "#35B04A", "#1C7A2E"),
    red=("#F09A8E", "#D6412F", "#93231A"),
    blue=("#9CCBF2", "#2C7FC4", "#14548C"),
    amber=("#FBDF95", "#EDA92C", "#B0740E"),
    folder=("#FBE09B", "#F2C14E", "#C68F22"),
    steel=("#E2E8EF", "#98A5B4", "#5C6774"),
    paper_light="#FFFFFF",
    paper_dark="#E9EDF2",
    paper_edge="#8A94A2",
    ink="#5A6472",
    gloss="#FFFFFF",
    shadow_color="#101820",
    shadow_opacity="0.38",
)

# Slightly deeper solids, dimmed paper and a heavier shadow: on the dark chrome
# a pure-white document glares and a light shadow disappears.
DARK_INK = Ink(
    books=(
        ("#93DCD2", "#2FB0A0", "#177F72"),
        ("#CCA2E4", "#9C5AC4", "#6B3092"),
        ("#96C6F2", "#4189D4", "#1B62AC"),
    ),
    page_light="#F4EFE0",
    page_dark="#C9BC9A",
    strap_light="#7A7A88",
    strap_dark="#33333E",
    strap_deep="#1F1F27",
    green=("#93E39A", "#3BB855", "#1F8535"),
    red=("#F4A79B", "#DC4A38", "#9C2820"),
    blue=("#A6D2F5", "#3389CC", "#175E97"),
    amber=("#FCE5A6", "#F0B23C", "#B87C12"),
    folder=("#FCE6AC", "#F4C75E", "#C9942A"),
    steel=("#D2DAE4", "#8D9AAA", "#525D6A"),
    paper_light="#EDF1F6",
    paper_dark="#C6CEDA",
    paper_edge="#767F8C",
    ink="#4C5563",
    gloss="#FFFFFF",
    shadow_color="#000000",
    shadow_opacity="0.5",
)

_INKS = {"light": LIGHT_INK, "dark": DARK_INK}
_P = LIGHT_INK          # the build in progress; see _build_set()
_MODE = "light"         # the build that icon()/pixmap() serve


def _lin(name: str, stops: list[tuple[float, str]], vertical: bool = True) -> str:
    """A linear gradient definition."""
    coords = 'x1="0" y1="0" x2="0" y2="1"' if vertical else 'x1="0" y1="0" x2="1" y2="0"'
    body = "".join(
        f'<stop offset="{offset}" stop-color="{color}"/>' for offset, color in stops
    )
    return f'<linearGradient id="{name}" {coords}>{body}</linearGradient>'


def _diag(name: str, stops: list[tuple[float, str]]) -> str:
    body = "".join(
        f'<stop offset="{offset}" stop-color="{color}"/>' for offset, color in stops
    )
    return f'<linearGradient id="{name}" x1="0" y1="0" x2="1" y2="1">{body}</linearGradient>'


def _shadow() -> str:
    return f"""
<filter id="sh" x="-30%" y="-30%" width="170%" height="170%">
  <feDropShadow dx="0" dy="1.1" stdDeviation="1.1"
                flood-color="{_P.shadow_color}"
                flood-opacity="{_P.shadow_opacity}"/>
</filter>
"""


def _book(x: float, y: float, w: float, h: float, d: float, index: int) -> str:
    """One 3D book: front cover, top cover, page block and a gloss highlight."""
    light, mid, dark = _P.books[index]
    gid = f"bk{index}"
    return f"""
    <linearGradient id="{gid}" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{light}"/>
      <stop offset="0.45" stop-color="{mid}"/>
      <stop offset="1" stop-color="{dark}"/>
    </linearGradient>
    <linearGradient id="{gid}t" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="{light}"/>
      <stop offset="1" stop-color="{mid}"/>
    </linearGradient>
    <g>
      <!-- page block peeking out on the right -->
      <path d="M{x + w - 1} {y + 1.4} l{d} -{d} v{h - 2.4} l-{d} {d} z"
            fill="url(#pg)"/>
      <!-- top cover -->
      <path d="M{x} {y} l{d} -{d} h{w} l-{d} {d} z" fill="url(#{gid}t)"/>
      <!-- front cover -->
      <rect x="{x}" y="{y}" width="{w}" height="{h}" rx="1.2"
            fill="url(#{gid})"/>
      <!-- gloss -->
      <path d="M{x + 0.9} {y + 0.9} h{w - 1.8} v{h * 0.36} h-{w - 1.8} z"
            fill="#ffffff" opacity="0.22"/>
    </g>
    """


def _books(tx: float = 0, ty: float = 0, scale: float = 1.0) -> str:
    """WinRAR's stack of three banded books."""
    w, h, d = 31.0, 8.6, 4.6
    x = 5.0
    layers = "".join(
        _book(x, y, w, h, d, index)
        for index, y in ((0, 33.2), (1, 24.0), (2, 14.8))
    )
    return f"""
    <g transform="translate({tx},{ty}) scale({scale})" filter="url(#sh)">
      {layers}
      <!-- binding strap across the whole stack -->
      <path d="M{x + 20.5} {14.8} l{d} -{d} h5 l-{d} {d} z" fill="url(#stt)"/>
      <rect x="{x + 20.5}" y="14.8" width="5" height="27" fill="url(#st)"/>
      <rect x="{x + 21.4}" y="14.8" width="1.2" height="27" fill="#8A8A98"
            opacity="0.65"/>
    </g>
    """


def _folder(x: float = 3, y: float = 11, w: float = 42, h: float = 29) -> str:
    """A classic 3D manila folder."""
    return f"""
    <g filter="url(#sh)">
      <path d="M{x} {y + 3} a2.5 2.5 0 0 1 2.5-2.5 h12 l4 4 h{w - 20}
               a2.5 2.5 0 0 1 2.5 2.5 v3 h-{w} z" fill="url(#fdb)"/>
      <path d="M{x + 1} {y + 8} h{w - 2} a2.5 2.5 0 0 1 2.5 2.5 v{h - 12}
               a2.5 2.5 0 0 1 -2.5 2.5 h-{w - 2} a2.5 2.5 0 0 1 -2.5 -2.5
               v-{h - 12} a2.5 2.5 0 0 1 2.5 -2.5 z" fill="url(#fdf)"/>
      <path d="M{x + 1} {y + 8} h{w - 2} v{(h - 12) * 0.42} h-{w - 2} z"
            fill="#ffffff" opacity="0.28"/>
    </g>
    """


def _document(x: float = 11, y: float = 5) -> str:
    return f"""
    <g filter="url(#sh)">
      <path d="M{x} {y + 2} a2 2 0 0 1 2-2 h15 l9 9 v26 a2 2 0 0 1 -2 2
               h-22 a2 2 0 0 1 -2 -2 z" fill="url(#pap)" stroke="{_P.paper_edge}"
            stroke-width="1.3"/>
      <path d="M{x + 17} {y} v9 h9 z" fill="#DCE4EC" stroke="{_P.paper_edge}"
            stroke-width="1.1" stroke-linejoin="round"/>
      <g stroke="{_P.ink}" stroke-width="1.7" stroke-linecap="round" opacity="0.75">
        <path d="M{x + 5} {y + 16} h15"/>
        <path d="M{x + 5} {y + 22} h15"/>
        <path d="M{x + 5} {y + 28} h10"/>
      </g>
    </g>
    """


def _badge(cx: float, cy: float, r: float, light: str, mid: str, dark: str) -> str:
    """A glossy circular badge used for the small overlay marks."""
    return f"""
    <g filter="url(#sh)">
      <circle cx="{cx}" cy="{cy}" r="{r}" fill="{dark}"/>
      <circle cx="{cx}" cy="{cy}" r="{r - 1.2}" fill="{mid}"/>
      <path d="M{cx - r + 1.6} {cy - 1} a{r - 1.6} {r - 1.6} 0 0 1 {2 * (r - 1.6)} 0
               a{r - 1.6} {r * 0.7} 0 0 0 -{2 * (r - 1.6)} 0 z"
            fill="{light}" opacity="0.8"/>
    </g>
    """


def _defs() -> str:
    return f"""
<defs>
  {_shadow()}
  {_lin("pg", [(0, _P.page_light), (1, _P.page_dark)])}
  {_lin("st", [(0, _P.strap_light), (0.5, _P.strap_dark), (1, _P.strap_deep)])}
  {_lin("stt", [(0, "#82828E"), (1, _P.strap_light)], vertical=False)}
  {_lin("fdf", [(0, _P.folder[0]), (0.55, _P.folder[1]), (1, _P.folder[2])])}
  {_lin("fdb", [(0, _P.folder[0]), (1, _P.folder[2])])}
  {_lin("pap", [(0, _P.paper_light), (1, _P.paper_dark)])}
  {_lin("grn", [(0, _P.green[0]), (0.5, _P.green[1]), (1, _P.green[2])])}
  {_lin("red", [(0, _P.red[0]), (0.5, _P.red[1]), (1, _P.red[2])])}
  {_lin("blu", [(0, _P.blue[0]), (0.5, _P.blue[1]), (1, _P.blue[2])])}
  {_lin("amb", [(0, _P.amber[0]), (0.5, _P.amber[1]), (1, _P.amber[2])])}
  {_lin("stl", [(0, _P.steel[0]), (0.5, _P.steel[1]), (1, _P.steel[2])])}
  {_diag("gls", [(0, "#ffffff"), (1, "#ffffff")])}
</defs>
"""


def _wrap(body: str) -> str:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" '
        f'width="48" height="48">{_defs()}{body}</svg>'
    )


def _arrow_down(cx: float, cy: float, scale: float, fill: str) -> str:
    return f"""
    <g transform="translate({cx},{cy}) scale({scale})" filter="url(#sh)">
      <path d="M-4.5 -11 h9 v9 h5.5 l-10 11 l-10 -11 h5.5 z" fill="{fill}"
            stroke="#ffffff" stroke-width="1.5" stroke-linejoin="round"/>
    </g>
    """


def _arrow_up(cx: float, cy: float, scale: float, fill: str) -> str:
    return f"""
    <g transform="translate({cx},{cy}) scale({scale})" filter="url(#sh)">
      <path d="M-4.5 11 h9 v-9 h5.5 l-10 -11 l-10 11 h5.5 z" fill="{fill}"
            stroke="#ffffff" stroke-width="1.5" stroke-linejoin="round"/>
    </g>
    """


def _magnifier(cx: float, cy: float, r: float) -> str:
    return f"""
    <g filter="url(#sh)">
      <circle cx="{cx}" cy="{cy}" r="{r + 2.2}" fill="url(#stl)"/>
      <circle cx="{cx}" cy="{cy}" r="{r}" fill="#DFF0FB" opacity="0.95"/>
      <path d="M{cx - r * 0.62} {cy - r * 0.2} a{r * 0.8} {r * 0.8} 0 0 1
               {r * 0.55} -{r * 0.6}" stroke="#ffffff" stroke-width="2.6"
            fill="none" stroke-linecap="round" opacity="0.9"/>
      <path d="M{cx + r * 0.78} {cy + r * 0.78} L{cx + r * 1.9} {cy + r * 1.9}"
            stroke="{_P.steel[2]}" stroke-width="6.4" stroke-linecap="round"/>
      <path d="M{cx + r * 0.78} {cy + r * 0.78} L{cx + r * 1.9} {cy + r * 1.9}"
            stroke="url(#stl)" stroke-width="4" stroke-linecap="round"/>
    </g>
    """


def _icon_svg() -> dict[str, str]:
    """Build the whole set with the colours in `_P`."""
    return {
        "archive": _wrap(_books()),
        "archive-small": _wrap(_books()),
        "app": _wrap(_books()),
        "add": _wrap(
            _books(ty=-3, scale=0.94)
            + _badge(35, 36, 11.5, _P.green[0], _P.green[1], _P.green[2])
            + """
            <path d="M35 29.5 v13 M28.5 36 h13" stroke="#ffffff" stroke-width="3.8"
                  stroke-linecap="round"/>
            """
        ),
        "extract": _wrap(
            _books(ty=-6, scale=0.8)
            + _folder(x=17, y=24, w=28, h=19)
            + _arrow_down(14, 30, 0.82, "url(#grn)")
        ),
        "extract-to": _wrap(
            _folder(x=3, y=15, w=42, h=27) + _arrow_down(24, 13, 1.0, "url(#grn)")
        ),
        "test": _wrap(
            _books(ty=-3, scale=0.94)
            + _badge(35, 36, 11.5, _P.green[0], _P.green[1], _P.green[2])
            + """
            <path d="M28.8 36.2 l4.4 4.6 L41.6 31" stroke="#ffffff"
                  stroke-width="4" fill="none" stroke-linecap="round"
                  stroke-linejoin="round"/>
            """
        ),
        "view": _wrap(_document(x=8, y=4) + _magnifier(31, 31, 9)),
        "delete": _wrap(
            _badge(24, 24, 18, _P.red[0], _P.red[1], _P.red[2])
            + """
            <path d="M16.5 16.5 L31.5 31.5 M31.5 16.5 L16.5 31.5" stroke="#ffffff"
                  stroke-width="5.4" stroke-linecap="round"/>
            """
        ),
        "find": _wrap(_magnifier(20, 20, 12)),
        "wizard": _wrap(
            f"""
            <g filter="url(#sh)">
              <path d="M9 39.5 L31.5 17 l5.2 5.2 L14.2 44.7 z" fill="url(#blu)"/>
              <path d="M9 39.5 L31.5 17 l2.6 2.6 L11.6 42.1 z" fill="#ffffff"
                    opacity="0.25"/>
              <path d="M31.5 17 l5.2 5.2 l3.4 -3.4 a3.7 3.7 0 0 0 -5.2 -5.2 z"
                    fill="url(#amb)"/>
            </g>
            <g fill="url(#amb)" filter="url(#sh)">
              <path d="M11 4 l1.9 4.4 L17.3 10.3 l-4.4 1.9 L11 16.6 l-1.9-4.4
                       L4.7 10.3 l4.4-1.9 z"/>
              <path d="M39.5 27 l1.3 3 L43.8 31.3 l-3 1.3 L39.5 35.6 l-1.3-3
                       L35.2 31.3 l3-1.3 z"/>
            </g>
            """
        ),
        "info": _wrap(
            _badge(24, 24, 18, _P.blue[0], _P.blue[1], _P.blue[2])
            + """
            <circle cx="24" cy="14.5" r="3" fill="#ffffff"/>
            <path d="M24 20.5 v14.5" stroke="#ffffff" stroke-width="5.2"
                  stroke-linecap="round"/>
            """
        ),
        "repair": _wrap(
            f"""
            <g filter="url(#sh)">
              <path d="M34 5 a11.5 11.5 0 0 0 -10.6 15.8 L7.6 36.6 a3.8 3.8 0 0 0
                       5.4 5.4 L28.8 26.2 A11.5 11.5 0 0 0 43.6 11.4 l-6.3 6.3
                       l-6.2 -1.1 l-1.1 -6.2 z" fill="url(#stl)"
                    stroke="{_P.steel[2]}" stroke-width="1.3"
                    stroke-linejoin="round"/>
              <path d="M9.6 38.6 L25 23.2" stroke="#ffffff" stroke-width="1.6"
                    opacity="0.55" stroke-linecap="round"/>
            </g>
            """
        ),
        "comment": _wrap(
            f"""
            <g filter="url(#sh)">
              <path d="M4.5 9.5 a3.2 3.2 0 0 1 3.2-3.2 h32.6 a3.2 3.2 0 0 1 3.2 3.2
                       v19.4 a3.2 3.2 0 0 1 -3.2 3.2 h-18.6 l-9.4 8.4 v-8.4 h-4.6
                       a3.2 3.2 0 0 1 -3.2 -3.2 z" fill="url(#pap)"
                    stroke="{_P.blue[1]}" stroke-width="2.1" stroke-linejoin="round"/>
              <path d="M6.6 8.4 h34.8 v8 h-34.8 z" fill="{_P.blue[0]}"
                    opacity="0.35"/>
              <g stroke="{_P.ink}" stroke-width="2.2" stroke-linecap="round"
                 opacity="0.7">
                <path d="M11 15.5 h26"/><path d="M11 22.5 h18"/>
              </g>
            </g>
            """
        ),
        "protect": _wrap(
            f"""
            <g filter="url(#sh)">
              <path d="M24 3.5 L41.5 9.6 v12.9 c0 11.4 -7.3 18.6 -17.5 22.5
                       c-10.2 -3.9 -17.5 -11.1 -17.5 -22.5 V9.6 z"
                    fill="url(#blu)" stroke="{_P.blue[2]}" stroke-width="1.4"/>
              <path d="M24 3.5 L41.5 9.6 v12.9 c0 4.2 -1 7.8 -2.6 10.9
                       C33 30 28.7 28.6 24 28.6 z" fill="#ffffff" opacity="0.16"/>
              <path d="M15.5 24 l6.2 6.2 L33.5 17.4" stroke="#ffffff"
                    stroke-width="4.6" fill="none" stroke-linecap="round"
                    stroke-linejoin="round"/>
            </g>
            """
        ),
        "sfx": _wrap(
            _books(ty=-4, scale=0.86)
            + f"""
            <g transform="translate(34,34)" filter="url(#sh)">
              <g fill="url(#stl)" stroke="{_P.steel[2]}" stroke-width="0.9">
                <circle r="11.5"/>
                <rect x="-2.4" y="-15" width="4.8" height="6" rx="1.2"/>
                <rect x="-2.4" y="9" width="4.8" height="6" rx="1.2"/>
                <rect x="-15" y="-2.4" width="6" height="4.8" rx="1.2"/>
                <rect x="9" y="-2.4" width="6" height="4.8" rx="1.2"/>
              </g>
              <circle r="4.8" fill="#F2F6FA" stroke="{_P.steel[2]}"
                      stroke-width="0.9"/>
            </g>
            """
        ),
        "lock": _wrap(
            f"""
            <g filter="url(#sh)">
              <path d="M15 23 v-6.5 a9 9 0 0 1 18 0 V23" fill="none"
                    stroke="url(#stl)" stroke-width="5.4"/>
              <path d="M15 23 v-6.5 a9 9 0 0 1 18 0 V23" fill="none"
                    stroke="{_P.steel[2]}" stroke-width="1.1" opacity="0.5"/>
              <rect x="9" y="21.5" width="30" height="20.5" rx="3.2"
                    fill="url(#amb)" stroke="{_P.amber[2]}" stroke-width="1.3"/>
              <rect x="10.4" y="23" width="27.2" height="8" rx="2.4" fill="#ffffff"
                    opacity="0.3"/>
              <circle cx="24" cy="30.5" r="3.6" fill="{_P.amber[2]}"/>
              <path d="M24 32.5 v6" stroke="{_P.amber[2]}" stroke-width="3.6"
                    stroke-linecap="round"/>
            </g>
            """
        ),
        "key": _wrap(
            f"""
            <g filter="url(#sh)">
              <circle cx="15.5" cy="16.5" r="9.5" fill="none" stroke="url(#amb)"
                      stroke-width="5.6"/>
              <circle cx="15.5" cy="16.5" r="4" fill="#F5F8FB"/>
              <path d="M21.5 23 L40.5 42" stroke="url(#amb)" stroke-width="5.6"
                    stroke-linecap="round"/>
              <path d="M33.5 35 l5 -5 M28.5 30 l4.4 -4.4" stroke="url(#amb)"
                    stroke-width="5.2" stroke-linecap="round"/>
            </g>
            """
        ),
        "convert": _wrap(
            _books(ty=-8, scale=0.74)
            + """
            <g filter="url(#sh)">
              <path d="M13 41 a13 13 0 1 1 13 6.5" fill="none" stroke="url(#grn)"
                    stroke-width="4.8" stroke-linecap="round"/>
              <path d="M26 40 l-7 6.5 l7 6.5 z" fill="url(#grn)"/>
            </g>
            """
        ),
        "up": _wrap(
            _folder(x=4, y=16, w=40, h=26) + _arrow_up(24, 12, 0.86, "url(#grn)")
        ),
        "folder": _wrap(_folder()),
        "folder-open": _wrap(_folder()),
        "folder-up": _wrap(
            _folder()
            + """
            <path d="M24 17 l8.5 10 l-5.2 0 l0 8 l-6.6 0 l0 -8 l-5.2 0 z"
                  fill="#6E7A88" opacity="0.85"/>
            """
        ),
        "file": _wrap(_document()),
        "disk": _wrap(
            f"""
            <g filter="url(#sh)">
              <rect x="4" y="14" width="40" height="21" rx="3.4" fill="url(#stl)"
                    stroke="{_P.steel[2]}" stroke-width="1.2"/>
              <rect x="5.6" y="15.6" width="36.8" height="8" rx="2.6"
                    fill="#ffffff" opacity="0.4"/>
              <circle cx="37" cy="29" r="3.2" fill="url(#grn)"/>
              <rect x="9" y="26.4" width="16" height="3.2" rx="1.6"
                    fill="{_P.steel[2]}" opacity="0.45"/>
            </g>
            """
        ),
        "refresh": _wrap(
            """
            <g filter="url(#sh)">
              <path d="M39 24 a15 15 0 1 1 -5.4 -11.5" fill="none"
                    stroke="url(#grn)" stroke-width="5.4" stroke-linecap="round"/>
              <path d="M37.5 3 l1.4 13 l-13 -1.2 z" fill="url(#grn)"/>
            </g>
            """
        ),
        "package": _wrap(
            f"""
            <g filter="url(#sh)">
              <path d="M24 5 l17 8.2 v21.6 L24 43 L7 34.8 V13.2 z"
                    fill="url(#amb)" stroke="{_P.amber[2]}" stroke-width="1.3"
                    stroke-linejoin="round"/>
              <path d="M7 13.2 L24 21.4 l17 -8.2" fill="none" stroke="{_P.amber[2]}"
                    stroke-width="1.3" stroke-linejoin="round"/>
              <path d="M24 21.4 V43" fill="none" stroke="{_P.amber[2]}"
                    stroke-width="1.3"/>
              <path d="M7 13.2 L24 5 l17 8.2 L24 21.4 z" fill="#ffffff"
                    opacity="0.22"/>
            </g>
            """
        ),
        "download": _wrap(
            f"""
            {_arrow_down(24, 18, 1.05, "url(#grn)")}
            <g filter="url(#sh)">
              <path d="M7 32 v7 a3 3 0 0 0 3 3 h28 a3 3 0 0 0 3 -3 v-7"
                    fill="none" stroke="url(#stl)" stroke-width="4.4"
                    stroke-linecap="round"/>
            </g>
            """
        ),
        "trash": _wrap(
            f"""
            <g filter="url(#sh)">
              <rect x="17" y="5" width="14" height="4.4" rx="1.6"
                    fill="url(#stl)" stroke="{_P.steel[2]}" stroke-width="1"/>
              <rect x="8" y="9.5" width="32" height="5.4" rx="2"
                    fill="url(#stl)" stroke="{_P.steel[2]}" stroke-width="1"/>
              <path d="M11.5 15.5 h25 l-2.4 25 a3 3 0 0 1 -3 2.7 h-14.2
                       a3 3 0 0 1 -3 -2.7 z" fill="url(#red)"
                    stroke="{_P.red[2]}" stroke-width="1.1"/>
              <g stroke="#ffffff" stroke-width="2.2" opacity="0.75"
                 stroke-linecap="round">
                <path d="M19 21 v15"/><path d="M24 21 v15"/><path d="M29 21 v15"/>
              </g>
            </g>
            """
        ),
        "theme-dark": _wrap(
            f"""
            <g filter="url(#sh)">
              <path d="M31.5 5.5 a19 19 0 1 0 12 26.5 a15.5 15.5 0 0 1 -12 -26.5 z"
                    fill="url(#blu)" stroke="{_P.blue[2]}" stroke-width="1.3"
                    stroke-linejoin="round"/>
              <path d="M31.5 5.5 a19 19 0 0 0 -12.6 30 a19 19 0 0 1 12.6 -30 z"
                    fill="#ffffff" opacity="0.22"/>
            </g>
            <g fill="url(#amb)" filter="url(#sh)">
              <path d="M11 6.5 l1.5 3.5 l3.5 1.5 l-3.5 1.5 l-1.5 3.5 l-1.5 -3.5
                       l-3.5 -1.5 l3.5 -1.5 z"/>
              <path d="M17.5 19 l1 2.3 l2.3 1 l-2.3 1 l-1 2.3 l-1 -2.3
                       l-2.3 -1 l2.3 -1 z"/>
            </g>
            """
        ),
        "theme-light": _wrap(
            f"""
            <g stroke="url(#amb)" stroke-width="3.6" stroke-linecap="round"
               filter="url(#sh)">
              <path d="M24 3.5 v6"/><path d="M24 38.5 v6"/>
              <path d="M3.5 24 h6"/><path d="M38.5 24 h6"/>
              <path d="M9.5 9.5 l4.3 4.3"/><path d="M34.2 34.2 l4.3 4.3"/>
              <path d="M38.5 9.5 l-4.3 4.3"/><path d="M13.8 34.2 l-4.3 4.3"/>
            </g>
            <g filter="url(#sh)">
              <circle cx="24" cy="24" r="10.5" fill="url(#amb)"
                      stroke="{_P.amber[2]}" stroke-width="1.3"/>
              <path d="M24 14.5 a9.5 9.5 0 0 0 -8.2 14.2 a9.5 9.5 0 0 1 8.2 -14.2 z"
                    fill="#ffffff" opacity="0.45"/>
            </g>
            """
        ),
        "help": _wrap(
            _badge(24, 24, 18, _P.blue[0], _P.blue[1], _P.blue[2])
            + """
            <path d="M17.5 18.5 a6.5 6.5 0 1 1 8 6.3 v3.7" fill="none"
                  stroke="#ffffff" stroke-width="4.2" stroke-linecap="round"/>
            <circle cx="25.5" cy="35" r="2.9" fill="#ffffff"/>
            """
        ),
        "settings": _wrap(
            f"""
            <g filter="url(#sh)">
              <path d="M24 6 l3.6 1 l1.6 3.4 l3.7 -0.5 l2.6 2.6 l-0.5 3.7
                       l3.4 1.6 l1 3.6 l-1 3.6 l-3.4 1.6 l0.5 3.7 l-2.6 2.6
                       l-3.7 -0.5 l-1.6 3.4 l-3.6 1 l-3.6 -1 l-1.6 -3.4
                       l-3.7 0.5 l-2.6 -2.6 l0.5 -3.7 l-3.4 -1.6 l-1 -3.6
                       l1 -3.6 l3.4 -1.6 l-0.5 -3.7 l2.6 -2.6 l3.7 0.5
                       l1.6 -3.4 z" fill="url(#stl)" stroke="{_P.steel[2]}"
                    stroke-width="1.2" stroke-linejoin="round"/>
              <circle cx="24" cy="22.5" r="6.6" fill="url(#blu)"
                      stroke="{_P.blue[2]}" stroke-width="1.2"/>
              <circle cx="24" cy="22.5" r="3" fill="#F2F7FC"/>
            </g>
            """
        ),
        "package-alert": _wrap(
            f"""
            <g filter="url(#sh)">
              <path d="M22 6 l15 7.2 v19 L22 39.4 L7 32.2 V13.2 z"
                    fill="url(#amb)" stroke="{_P.amber[2]}" stroke-width="1.3"
                    stroke-linejoin="round"/>
              <path d="M7 13.2 L22 20.4 l15 -7.2" fill="none"
                    stroke="{_P.amber[2]}" stroke-width="1.3"
                    stroke-linejoin="round"/>
              <path d="M22 20.4 V39.4" fill="none" stroke="{_P.amber[2]}"
                    stroke-width="1.3"/>
              <path d="M7 13.2 L22 6 l15 7.2 L22 20.4 z" fill="#ffffff"
                    opacity="0.22"/>
            </g>
            """
            + _badge(36, 34, 11.5, _P.red[0], _P.red[1], _P.red[2])
            + """
            <path d="M36 27.5 v8.4" stroke="#ffffff" stroke-width="3.6"
                  stroke-linecap="round"/>
            <circle cx="36" cy="40.5" r="2.2" fill="#ffffff"/>
            """
        ),
        "globe": _wrap(
            f"""
            <g filter="url(#sh)">
              <circle cx="24" cy="24" r="18" fill="url(#blu)"
                      stroke="{_P.blue[2]}" stroke-width="1.3"/>
              <g fill="none" stroke="#ffffff" stroke-width="2" opacity="0.85">
                <ellipse cx="24" cy="24" rx="8.4" ry="18"/>
                <path d="M6.6 18 h34.8"/><path d="M6.6 30 h34.8"/>
                <path d="M24 6 v36"/>
              </g>
            </g>
            """
        ),
    }


_BUILDS: dict[str, dict[str, str]] = {}


def set_theme(mode: str) -> None:
    """Serve the build that matches *mode* ("light" or "dark")."""
    global _MODE
    _MODE = mode if mode in _INKS else "light"


def _set(mode: str) -> dict[str, str]:
    """The icon table for *mode*, built once and kept."""
    global _P
    if mode not in _BUILDS:
        _P = _INKS[mode]
        _BUILDS[mode] = _icon_svg()
        _P = _INKS[_MODE]
    return _BUILDS[mode]


@functools.lru_cache(maxsize=1024)
def _render(mode: str, name: str, size: int) -> QPixmap:
    table = _set(mode)
    svg = table.get(name) or table["file"]
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    ratio = 2  # render at 2x so icons stay crisp on HiDPI screens
    image = QImage(size * ratio, size * ratio, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    renderer.render(painter, QRectF(0, 0, size * ratio, size * ratio))
    painter.end()
    pixmap = QPixmap.fromImage(image)
    pixmap.setDevicePixelRatio(ratio)
    return pixmap


@functools.lru_cache(maxsize=1024)
def _icon(mode: str, name: str) -> QIcon:
    result = QIcon()
    for size in (16, 20, 24, 32, 48, 64):
        result.addPixmap(_render(mode, name, size))
    return result


def icon(name: str) -> QIcon:
    """Return a multi-resolution :class:`QIcon` for *name*."""
    return _icon(_MODE, name)


def pixmap(name: str, size: int = 32) -> QPixmap:
    return _render(_MODE, name, size)


def names() -> list[str]:
    """Every icon name in the set."""
    return sorted(_set(_MODE))


def svg(name: str, mode: str = "") -> str:
    """The raw SVG for *name*, for exporting to a file."""
    table = _set(mode if mode in _INKS else _MODE)
    return table.get(name) or table["file"]


def export_png(name: str, size: int, path: str, mode: str = "light") -> bool:
    """Write *name* to *path* as an exactly ``size``x``size`` PNG.

    The desktop's icon themes want real raster sizes next to the SVG: some
    launchers never rasterise SVG at all, and the ones that do look for the
    PNG first.  Always drawn from the light build, which is what an icon on a
    desktop wallpaper wants.
    """
    renderer = QSvgRenderer(QByteArray(svg(name, mode).encode("utf-8")))
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    return image.save(path, "PNG")
