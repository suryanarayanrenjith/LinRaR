"""LinRAR's window chrome, in a light and a dark flavour.

WinRAR has always kept the light, three-dimensional Windows look: beveled
toolbar buttons, sunken white list panes with raised column headers, etched
group boxes and inset status-bar cells.  LinRAR pins the Fusion base style plus
its own palette instead of following the desktop theme, so a foreign GTK theme
cannot bleed through and destroy the resemblance.

Every colour lives in a :class:`Colors` record, and the style sheet is built
from one, which is what makes the dark theme possible: the same chrome, a
different set of values.

Qt stops drawing a sub-control's built-in glyph as soon as the sub-control is
styled at all -- that is why the combo boxes used to lose their drop-down
arrows.  The small monochrome parts (arrows, check boxes, radios, tree
twisties) are therefore painted here into PNGs in the cache directory and fed
back to the style sheet, tinted to match the active theme.  If that cache
cannot be written we simply leave those sub-controls unstyled so the Fusion
style keeps drawing them.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass

from PyQt6.QtCore import QPointF, QRectF, QStandardPaths, Qt
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QImage,
    QPainter,
    QPalette,
    QPen,
    QPolygonF,
)

LIGHT = "light"
DARK = "dark"
MODES = (LIGHT, DARK)
MODE_LABELS = {LIGHT: "Light", DARK: "Dark"}


@dataclass(frozen=True)
class Colors:
    """Every colour the chrome needs, for one theme."""

    mode: str

    # -- surfaces --
    window: str          # 3D face
    base: str            # list / input background
    alt_base: str
    text: str
    text_dim: str        # secondary captions
    disabled: str
    link: str

    # -- chrome bars --
    bar_top: str
    bar_mid: str
    bar_bottom: str
    bar_edge: str
    menubar_top: str
    menubar_bottom: str
    menu_bg: str
    menu_border: str
    menu_sep: str
    header_top: str
    header_mid: str
    header_bottom: str
    header_line: str
    header_edge: str
    status_top: str
    status_bottom: str
    pane_bg: str
    pane_border: str

    # -- edges --
    frame: str           # edit-control border
    border: str
    shadow: str
    dark_shadow: str
    light_edge: str
    soft_edge: str
    group_border: str
    group_title: str
    focus_border: str

    # -- hover / pressed accent --
    hot_top: str
    hot_mid: str
    hot_bottom: str
    hot_border: str
    press_top: str
    press_bottom: str
    press_border: str

    # -- selection --
    sel_top: str
    sel_bottom: str
    sel_text: str
    sel_idle: str
    sel_idle_text: str
    row_hover: str

    # -- push buttons --
    btn_top: str
    btn_upper: str
    btn_lower: str
    btn_bottom: str
    btn_border: str
    btn_off: str

    # -- tabs --
    tab_top: str
    tab_mid: str
    tab_bottom: str

    # -- progress --
    prog_bg: str
    prog_1: str
    prog_2: str
    prog_3: str
    prog_4: str

    # -- tooltips --
    tip_bg: str
    tip_text: str
    tip_border: str

    # -- scrollbars --
    sb_bg: str
    sb_top: str
    sb_bottom: str
    sb_border: str

    # -- small painted parts --
    arrow: str
    arrow_off: str
    arrow_hot: str
    twisty: str
    check_bg: str
    check_border: str
    check_mark: str

    # -- semantic text --
    alert_top: str
    alert_bottom: str

    ok: str
    warn: str
    error: str
    info: str

    splitter_hot: str


LIGHT_COLORS = Colors(
    mode=LIGHT,
    window="#F0F0F0",
    base="#FFFFFF",
    alt_base="#F5F7FA",
    text="#000000",
    text_dim="#555F6B",
    disabled="#8C8C8C",
    link="#0645AD",
    bar_top="#FBFCFD",
    bar_mid="#EEF1F5",
    bar_bottom="#DCE1E8",
    bar_edge="#A6AEB8",
    menubar_top="#FDFDFE",
    menubar_bottom="#E9ECF1",
    menu_bg="#FBFBFB",
    menu_border="#8D8D8D",
    menu_sep="#D3D3D3",
    header_top="#FFFFFF",
    header_mid="#F2F4F7",
    header_bottom="#DFE3E9",
    header_line="#C3C9D1",
    header_edge="#8D8D8D",
    status_top="#F6F7F9",
    status_bottom="#E4E8ED",
    pane_bg="#EDEFF2",
    pane_border="#B7BDC5",
    frame="#7F9DB9",
    border="#C8CCD2",
    shadow="#8D8D8D",
    dark_shadow="#696969",
    light_edge="#FFFFFF",
    soft_edge="#DFDFDF",
    group_border="#C8CCD2",
    group_title="#17365D",
    focus_border="#3C7FB1",
    hot_top="#FEFAEC",
    hot_mid="#FCEFC0",
    hot_bottom="#F7DE93",
    hot_border="#D4AB48",
    press_top="#E8CE84",
    press_bottom="#FCF3D8",
    press_border="#B8952F",
    sel_top="#4A8AD8",
    sel_bottom="#316AC5",
    sel_text="#FFFFFF",
    sel_idle="#C6D3E8",
    sel_idle_text="#000000",
    row_hover="#E3EDFA",
    btn_top="#FDFDFE",
    btn_upper="#F0F2F5",
    btn_lower="#E4E8ED",
    btn_bottom="#D6DBE2",
    btn_border="#9AA3AD",
    btn_off="#F2F2F2",
    tab_top="#FDFDFE",
    tab_mid="#EFF2F6",
    tab_bottom="#DCE1E8",
    prog_bg="#EDEFF2",
    prog_1="#A9E4A9",
    prog_2="#5FC45F",
    prog_3="#3FAC3F",
    prog_4="#2E9440",
    tip_bg="#FFFFE1",
    tip_text="#000000",
    tip_border="#767676",
    sb_bg="#F1F3F6",
    sb_top="#FDFDFE",
    sb_bottom="#D5DBE3",
    sb_border="#A6AEB8",
    arrow="#303030",
    arrow_off="#ADADAD",
    arrow_hot="#1B3E63",
    twisty="#5A6472",
    check_bg="#FFFFFF",
    check_border="#7F9DB9",
    check_mark="#1B4B8F",
    alert_top="#FDECEC",
    alert_bottom="#F7D2D2",
    ok="#0B6E4F",
    warn="#8A5A00",
    error="#B00020",
    info="#1F6FB2",
    splitter_hot="#D6E2F2",
)

DARK_COLORS = Colors(
    mode=DARK,
    window="#2B2F36",
    base="#1F232A",
    alt_base="#262B33",
    text="#E7EAEE",
    text_dim="#A3ABB6",
    disabled="#6D7580",
    link="#6BB3F2",
    bar_top="#3A404A",
    bar_mid="#31363E",
    bar_bottom="#272C33",
    bar_edge="#14171B",
    menubar_top="#363C45",
    menubar_bottom="#2A2F36",
    menu_bg="#2E343C",
    menu_border="#4A515B",
    menu_sep="#3C434C",
    header_top="#3B424C",
    header_mid="#343A43",
    header_bottom="#2C323A",
    header_line="#262B32",
    header_edge="#191D22",
    status_top="#333942",
    status_bottom="#2A2F36",
    pane_bg="#242931",
    pane_border="#3E4550",
    frame="#4C545F",
    border="#3A414A",
    shadow="#191D22",
    dark_shadow="#101317",
    light_edge="#4A515B",
    soft_edge="#363C44",
    group_border="#3E4550",
    group_title="#9CC4EA",
    focus_border="#5B9BD5",
    hot_top="#3F4E60",
    hot_mid="#374553",
    hot_bottom="#303C48",
    hot_border="#5C7691",
    press_top="#26303B",
    press_bottom="#36434F",
    press_border="#6E8CAA",
    sel_top="#3E82CC",
    sel_bottom="#2A66A8",
    sel_text="#FFFFFF",
    sel_idle="#414C5A",
    sel_idle_text="#E7EAEE",
    row_hover="#2C3846",
    btn_top="#434A55",
    btn_upper="#3B424C",
    btn_lower="#343A43",
    btn_bottom="#2C3138",
    btn_border="#545C68",
    btn_off="#2E333A",
    tab_top="#383F49",
    tab_mid="#313841",
    tab_bottom="#2A3038",
    prog_bg="#242931",
    prog_1="#7FD79A",
    prog_2="#47AE68",
    prog_3="#379055",
    prog_4="#2A7645",
    tip_bg="#3A414B",
    tip_text="#E7EAEE",
    tip_border="#5A626D",
    sb_bg="#262B32",
    sb_top="#474F5A",
    sb_bottom="#373E48",
    sb_border="#1B1F25",
    arrow="#C8CFD8",
    arrow_off="#5F6771",
    arrow_hot="#EAF1F8",
    twisty="#98A2AE",
    check_bg="#1F232A",
    check_border="#5A626D",
    check_mark="#7FB8F0",
    alert_top="#4A2E33",
    alert_bottom="#3A252A",
    ok="#4FC08D",
    warn="#E0A94A",
    error="#F2707A",
    info="#6BB3F2",
    splitter_hot="#3A4657",
)

PALETTES = {LIGHT: LIGHT_COLORS, DARK: DARK_COLORS}


def normalize(mode: str | None) -> str:
    """Map anything the settings file may hold onto a real theme name."""
    text = str(mode or "").strip().lower()
    return text if text in MODES else LIGHT


# ---------------------------------------------------------------- artwork

_ARROW_LONG, _ARROW_SHORT = 9, 5   # a classic 9x5 Windows triangle
_BOX = 13                          # check box / radio side


def _cache_dir(mode: str) -> str:
    base = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.CacheLocation
    )
    if not base:
        base = os.path.join(tempfile.gettempdir(), "linrar-cache")
    path = os.path.join(base, "chrome", mode)
    os.makedirs(path, exist_ok=True)
    return path


def _canvas(width: int, height: int, scale: int) -> tuple[QImage, QPainter]:
    image = QImage(
        width * scale, height * scale, QImage.Format.Format_ARGB32_Premultiplied
    )
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.scale(scale, scale)
    return image, painter


def _arrow(direction: str, color: str, scale: int) -> QImage:
    """A hard-edged triangle, stepped row by row like the Windows original."""
    horizontal = direction in ("down", "up")
    width = _ARROW_LONG if horizontal else _ARROW_SHORT
    height = _ARROW_SHORT if horizontal else _ARROW_LONG
    image, painter = _canvas(width, height, scale)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    brush = QBrush(QColor(color))
    for step in range(_ARROW_SHORT):
        length = _ARROW_LONG - 2 * step
        if direction == "down":
            rect = QRectF(step, step, length, 1)
        elif direction == "up":
            rect = QRectF(step, _ARROW_SHORT - 1 - step, length, 1)
        elif direction == "right":
            rect = QRectF(step, step, 1, length)
        else:  # left
            rect = QRectF(_ARROW_SHORT - 1 - step, step, 1, length)
        painter.fillRect(rect, brush)
    painter.end()
    return image


def _indicator(
    colors: Colors,
    scale: int,
    *,
    round_shape: bool = False,
    checked: bool = False,
    partial: bool = False,
    enabled: bool = True,
    hover: bool = False,
) -> QImage:
    """One check-box or radio indicator in a given state."""
    image, painter = _canvas(_BOX, _BOX, scale)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    if not enabled:
        fill, edge = QColor(colors.window), QColor(colors.disabled)
    elif hover:
        fill, edge = QColor(colors.row_hover), QColor(colors.focus_border)
    else:
        fill, edge = QColor(colors.check_bg), QColor(colors.check_border)
    # A disabled tick still has to be readable: the archive-information sheet
    # reports its flags with check boxes nobody can toggle.
    mark = QColor(colors.check_mark if enabled else colors.text_dim)

    painter.setPen(QPen(edge, 1))
    painter.setBrush(fill)
    body = QRectF(0.5, 0.5, _BOX - 1, _BOX - 1)
    if round_shape:
        painter.drawEllipse(body)
    else:
        painter.drawRoundedRect(body, 2.0, 2.0)

    if checked and round_shape:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(mark)
        painter.drawEllipse(QRectF(3.6, 3.6, 5.8, 5.8))
    elif checked:
        pen = QPen(mark, 2.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPolyline(
            QPolygonF([QPointF(3.0, 6.9), QPointF(5.4, 9.4), QPointF(10.0, 3.4)])
        )
    elif partial:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(mark)
        painter.drawRoundedRect(QRectF(3.5, 3.5, 6.0, 6.0), 1.0, 1.0)

    painter.end()
    return image


def _artwork(colors: Colors) -> dict[str, str]:
    """Paint the theme's small parts and return ``name -> file path``.

    Every glyph is written twice, once at 1x and once as an ``@2x`` twin, so a
    HiDPI screen can pick the sharper file.
    """
    try:
        folder = _cache_dir(colors.mode)
        art: dict[str, str] = {}

        def save(name: str, factory) -> None:
            for scale, suffix in ((1, ""), (2, "@2x")):
                path = os.path.join(folder, f"{name}{suffix}.png")
                # Written aside and moved into place so a second LinRAR
                # starting at the same moment can never read a half file.
                staging = f"{path}.{os.getpid()}.tmp"
                if not factory(scale).save(staging, "PNG"):
                    raise OSError(f"could not write {staging}")
                os.replace(staging, path)
                if not suffix:
                    art[name] = path.replace("\\", "/")

        for direction in ("down", "up", "left", "right"):
            for suffix, tint in (
                ("", colors.arrow),
                ("-off", colors.arrow_off),
                ("-hot", colors.arrow_hot),
            ):
                save(
                    f"arrow-{direction}{suffix}",
                    lambda scale, d=direction, t=tint: _arrow(d, t, scale),
                )
        save("twisty-closed", lambda s: _arrow("right", colors.twisty, s))
        save("twisty-open", lambda s: _arrow("down", colors.twisty, s))

        for prefix, round_shape in (("check", False), ("radio", True)):
            for name, kwargs in (
                ("off", {}),
                ("off-hot", {"hover": True}),
                ("off-dis", {"enabled": False}),
                ("on", {"checked": True}),
                ("on-hot", {"checked": True, "hover": True}),
                ("on-dis", {"checked": True, "enabled": False}),
            ):
                save(
                    f"{prefix}-{name}",
                    lambda scale, r=round_shape, k=kwargs: _indicator(
                        colors, scale, round_shape=r, **k
                    ),
                )
        save("check-part", lambda s: _indicator(colors, s, partial=True))
        return art
    except OSError:
        # No writable cache: fall back to the Fusion style's own glyphs.
        return {}


# ---------------------------------------------------------------- stylesheet


def _base_sheet(c: Colors) -> str:
    """Everything that does not depend on the painted artwork."""
    return f"""
QMainWindow, QDialog, QWizard {{
    background: {c.window};
}}
QWidget {{
    color: {c.text};
    font-size: 9pt;
}}
QWidget:disabled {{
    color: {c.disabled};
}}

/* ================= menu bar ================= */
QMenuBar {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {c.menubar_top}, stop:1 {c.menubar_bottom});
    border-bottom: 1px solid {c.bar_edge};
    padding: 1px 3px;
}}
QMenuBar::item {{
    background: transparent;
    padding: 4px 10px;
    border: 1px solid transparent;
    border-radius: 3px;
}}
QMenuBar::item:selected {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {c.hot_top}, stop:1 {c.hot_bottom});
    border: 1px solid {c.hot_border};
    color: {c.text};
}}
QMenuBar::item:pressed {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {c.press_top}, stop:1 {c.press_bottom});
    border: 1px solid {c.press_border};
}}

QMenu {{
    background: {c.menu_bg};
    border: 1px solid {c.menu_border};
    padding: 3px 2px;
}}
QMenu::item {{
    padding: 5px 34px 5px 30px;
    border: 1px solid transparent;
    border-radius: 3px;
}}
QMenu::item:selected {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {c.hot_top}, stop:1 {c.hot_bottom});
    border: 1px solid {c.hot_border};
    color: {c.text};
}}
QMenu::item:disabled {{
    color: {c.disabled};
    background: transparent;
    border: 1px solid transparent;
}}
QMenu::separator {{
    height: 1px;
    background: {c.menu_sep};
    margin: 4px 8px 4px 28px;
}}
QMenu::icon {{
    padding-left: 8px;
}}

/* ================= toolbar ================= */
QToolBar#MainToolBar {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {c.bar_top}, stop:0.55 {c.bar_mid}, stop:1 {c.bar_bottom});
    border: 0px;
    border-bottom: 1px solid {c.bar_edge};
    padding: 3px 4px 2px 4px;
    spacing: 0px;
}}
QToolBar#MainToolBar QToolButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 3px;
    padding: 3px 4px 2px 4px;
    margin: 0px 1px;
    min-width: 46px;
    color: {c.text};
}}
QToolBar#MainToolBar QToolButton:hover {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {c.hot_top}, stop:0.5 {c.hot_mid}, stop:1 {c.hot_bottom});
    border: 1px solid {c.hot_border};
}}
QToolBar#MainToolBar QToolButton:pressed,
QToolBar#MainToolBar QToolButton:checked {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {c.press_top}, stop:1 {c.press_bottom});
    border: 1px solid {c.press_border};
}}
QToolBar#MainToolBar QToolButton:disabled {{
    color: {c.disabled};
}}
/* the Dependencies button is called out: it is where missing tools get fixed */
QToolBar#MainToolBar QToolButton#DependencyButton {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {c.hot_top}, stop:1 {c.hot_bottom});
    border: 1px solid {c.hot_border};
}}
QToolBar#MainToolBar QToolButton#DependencyButton:hover {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {c.hot_top}, stop:0.5 {c.hot_mid}, stop:1 {c.hot_bottom});
    border: 1px solid {c.press_border};
}}
QToolBar#MainToolBar QToolButton#DependencyAlertButton {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {c.alert_top}, stop:1 {c.alert_bottom});
    border: 1px solid {c.error};
    color: {c.error};
}}
QToolBar#MainToolBar QToolButton#DependencyAlertButton:hover {{
    background: {c.alert_bottom};
    border: 1px solid {c.error};
}}
QMenuBar QToolButton#CornerButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 3px;
    margin: 1px 4px 1px 1px;
    padding: 2px;
}}
QMenuBar QToolButton#CornerButton:hover {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {c.hot_top}, stop:1 {c.hot_bottom});
    border: 1px solid {c.hot_border};
}}
QMenuBar QToolButton#CornerButton:pressed {{
    background: {c.press_top};
    border: 1px solid {c.press_border};
}}
QToolBar::separator {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 rgba(0,0,0,0), stop:0.5 {c.shadow}, stop:1 rgba(0,0,0,0));
    width: 1px;
    margin: 5px 6px;
}}

/* ================= address bar ================= */
QWidget#AddressBar {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {c.bar_mid}, stop:1 {c.bar_bottom});
    border-bottom: 1px solid {c.bar_edge};
}}
QWidget#AddressBar QToolButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 3px;
    padding: 2px;
}}
QWidget#AddressBar QToolButton:hover {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {c.hot_top}, stop:1 {c.hot_bottom});
    border: 1px solid {c.hot_border};
}}
QWidget#AddressBar QToolButton:pressed {{
    background: {c.press_top};
    border: 1px solid {c.press_border};
}}
QLabel#AddressLabel {{
    color: {c.text_dim};
    padding-left: 2px;
}}

/* ================= combo boxes ================= */
QComboBox {{
    background: {c.base};
    border: 1px solid {c.frame};
    border-radius: 2px;
    padding: 2px 4px;
    min-height: 20px;
    color: {c.text};
    selection-background-color: {c.sel_bottom};
    selection-color: {c.sel_text};
}}
QComboBox:hover {{
    border: 1px solid {c.focus_border};
}}
QComboBox:focus, QComboBox:on {{
    border: 1px solid {c.focus_border};
}}
QComboBox:disabled {{
    background: {c.btn_off};
    color: {c.disabled};
    border: 1px solid {c.border};
}}
QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 18px;
    border-left: 1px solid {c.border};
    border-top-right-radius: 2px;
    border-bottom-right-radius: 2px;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {c.btn_top}, stop:0.5 {c.btn_upper}, stop:1 {c.btn_bottom});
}}
QComboBox::drop-down:hover {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {c.hot_top}, stop:1 {c.hot_bottom});
}}
QComboBox::drop-down:disabled {{
    background: {c.btn_off};
    border-left: 1px solid {c.border};
}}
QComboBox QAbstractItemView {{
    background: {c.base};
    border: 1px solid {c.menu_border};
    selection-background-color: {c.sel_bottom};
    selection-color: {c.sel_text};
    outline: none;
    padding: 1px;
}}

/* ================= list / tree panes ================= */
QTreeView, QListView, QTableView, QListWidget, QTreeWidget {{
    background: {c.base};
    alternate-background-color: {c.alt_base};
    border: 1px solid {c.frame};
    outline: none;
    selection-background-color: {c.sel_bottom};
    selection-color: {c.sel_text};
    show-decoration-selected: 1;
}}
QTreeView::item, QListView::item {{
    padding: 2px 3px;
    border: 0px;
}}
QTreeView::item:hover, QListView::item:hover {{
    background: {c.row_hover};
    color: {c.text};
}}
QTreeView::item:selected, QListView::item:selected {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {c.sel_top}, stop:1 {c.sel_bottom});
    color: {c.sel_text};
}}
QTreeView::item:selected:!active, QListView::item:selected:!active {{
    background: {c.sel_idle};
    color: {c.sel_idle_text};
}}
QTreeView::branch {{
    background: {c.base};
}}
/* optional row separators, switched on from Customize > File list */
QTreeView[gridLines="on"]::item {{
    border-bottom: 1px solid {c.border};
}}

/* raised classic column headers */
/* the header's own background shows past the last column, so it carries the
   same gradient and rule as the sections do */
QHeaderView {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {c.header_top}, stop:0.5 {c.header_mid},
                stop:1 {c.header_bottom});
    border: 0px;
    border-bottom: 1px solid {c.header_edge};
}}
QHeaderView::section {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {c.header_top}, stop:0.5 {c.header_mid},
                stop:1 {c.header_bottom});
    color: {c.text};
    border: 0px;
    border-right: 1px solid {c.header_line};
    border-bottom: 1px solid {c.header_edge};
    padding: 4px 6px;
}}
QHeaderView::section:hover {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {c.header_top}, stop:1 {c.row_hover});
}}
QHeaderView::section:pressed {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {c.header_bottom}, stop:1 {c.header_mid});
}}

/* ================= status bar ================= */
QStatusBar {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {c.status_top}, stop:1 {c.status_bottom});
    border-top: 1px solid {c.bar_edge};
}}
QStatusBar::item {{
    border: 0px;
}}
QStatusBar QLabel {{
    padding: 1px 5px;
    color: {c.text};
}}
QLabel#StatusPane {{
    border: 1px solid {c.pane_border};
    border-top-color: {c.shadow};
    border-left-color: {c.shadow};
    background: {c.pane_bg};
    padding: 2px 6px;
}}
QToolButton#StatusButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 3px;
    padding: 2px;
    margin: 0px 1px;
}}
QToolButton#StatusButton:hover {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {c.hot_top}, stop:1 {c.hot_bottom});
    border: 1px solid {c.hot_border};
}}
QToolButton#StatusButton:pressed {{
    background: {c.press_top};
    border: 1px solid {c.press_border};
}}

/* ================= push buttons ================= */
QPushButton {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {c.btn_top}, stop:0.45 {c.btn_upper}, stop:0.46 {c.btn_lower},
                stop:1 {c.btn_bottom});
    border: 1px solid {c.btn_border};
    border-radius: 3px;
    padding: 4px 15px;
    min-width: 76px;
    min-height: 18px;
    color: {c.text};
}}
QPushButton:hover {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {c.hot_top}, stop:0.45 {c.hot_mid}, stop:0.46 {c.hot_mid},
                stop:1 {c.hot_bottom});
    border: 1px solid {c.hot_border};
}}
QPushButton:pressed {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {c.press_top}, stop:1 {c.press_bottom});
    border: 1px solid {c.press_border};
    padding-top: 5px;
}}
QPushButton:default, QPushButton:focus {{
    border: 1px solid {c.focus_border};
}}
QPushButton:disabled {{
    background: {c.btn_off};
    color: {c.disabled};
    border: 1px solid {c.border};
}}
QPushButton#LinkButton {{
    background: transparent;
    border: 1px solid transparent;
    color: {c.link};
    min-width: 0px;
    padding: 2px 4px;
    text-align: left;
}}
QPushButton#LinkButton:hover {{
    text-decoration: underline;
}}
QDialogButtonBox QPushButton {{
    min-width: 84px;
}}

/* ================= group boxes (etched) ================= */
QGroupBox {{
    border: 1px solid {c.group_border};
    border-top-color: {c.shadow};
    border-left-color: {c.shadow};
    border-radius: 3px;
    margin-top: 11px;
    padding: 10px 8px 8px 8px;
    background: transparent;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 9px;
    padding: 0 4px;
    color: {c.group_title};
    font-weight: bold;
}}

/* ================= tabs ================= */
QTabWidget::pane {{
    border: 1px solid {c.shadow};
    background: {c.window};
    top: -1px;
}}
QTabBar::tab {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {c.tab_top}, stop:0.5 {c.tab_mid}, stop:1 {c.tab_bottom});
    border: 1px solid {c.shadow};
    border-bottom: none;
    border-top-left-radius: 3px;
    border-top-right-radius: 3px;
    padding: 5px 14px;
    margin-right: 2px;
    color: {c.text};
}}
QTabBar::tab:selected {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {c.base}, stop:1 {c.window});
    margin-bottom: -1px;
    padding-bottom: 6px;
}}
QTabBar::tab:!selected {{
    margin-top: 2px;
}}
QTabBar::tab:!selected:hover {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {c.hot_top}, stop:1 {c.hot_bottom});
}}
QTabBar::tab:disabled {{
    color: {c.disabled};
}}

/* ================= inputs (sunken) ================= */
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox,
QAbstractSpinBox, QTextBrowser {{
    background: {c.base};
    border: 1px solid {c.frame};
    border-radius: 2px;
    padding: 3px 4px;
    color: {c.text};
    selection-background-color: {c.sel_bottom};
    selection-color: {c.sel_text};
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus,
QAbstractSpinBox:focus, QTextBrowser:focus {{
    border: 1px solid {c.focus_border};
}}
QLineEdit:disabled, QTextEdit:disabled, QPlainTextEdit:disabled,
QSpinBox:disabled, QAbstractSpinBox:disabled {{
    background: {c.btn_off};
    color: {c.disabled};
    border: 1px solid {c.border};
}}
QLineEdit:read-only {{
    background: {c.alt_base};
}}

/* ================= progress ================= */
QProgressBar {{
    background: {c.prog_bg};
    border: 1px solid {c.frame};
    border-radius: 2px;
    text-align: center;
    height: 18px;
    color: {c.text};
}}
QProgressBar::chunk {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {c.prog_1}, stop:0.45 {c.prog_2}, stop:0.5 {c.prog_3},
                stop:1 {c.prog_4});
    margin: 0px;
}}

/* ================= splitter ================= */
QSplitter::handle {{
    background: {c.window};
}}
QSplitter::handle:horizontal {{
    width: 5px;
    image: none;
}}
QSplitter::handle:vertical {{
    height: 5px;
}}
QSplitter::handle:hover {{
    background: {c.splitter_hot};
}}

/* ================= misc ================= */
QToolTip {{
    background: {c.tip_bg};
    color: {c.tip_text};
    border: 1px solid {c.tip_border};
    padding: 3px 5px;
}}
QLabel {{
    background: transparent;
}}
QLabel:disabled {{
    color: {c.disabled};
}}
QLabel#Hint {{
    color: {c.text_dim};
}}
QLabel#Success {{
    color: {c.ok};
}}
QLabel#Warning {{
    color: {c.warn};
}}
QLabel#Failure {{
    color: {c.error};
}}
QLabel#Heading {{
    color: {c.group_title};
    font-size: 11pt;
    font-weight: bold;
}}
QWidget#Banner, QLabel#Banner {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {c.base}, stop:1 {c.alt_base});
    border-bottom: 1px solid {c.bar_edge};
    color: {c.text};
}}
QWidget#Rule {{
    background: {c.border};
    max-height: 1px;
    min-height: 1px;
    border: 0px;
}}
QWidget#Card, QLabel#Card {{
    background: {c.alt_base};
    border: 1px solid {c.frame};
    border-radius: 4px;
    padding: 10px;
}}
"""


def _chrome_sheet(c: Colors, art: dict[str, str]) -> str:
    """The rules that need the painted glyphs; empty when they are missing."""
    if not art:
        return ""

    def u(name: str) -> str:
        return f'url("{art[name]}")'

    return f"""
/* ================= painted glyphs ================= */
QComboBox::down-arrow {{
    image: {u('arrow-down')};
    width: 9px;
    height: 5px;
}}
QComboBox::down-arrow:disabled {{
    image: {u('arrow-down-off')};
}}
QComboBox::down-arrow:hover, QComboBox::down-arrow:on {{
    image: {u('arrow-down-hot')};
}}
QComboBox::down-arrow:on {{
    top: 1px;
}}

QAbstractSpinBox::up-button {{
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 17px;
    margin: 1px 1px 0px 0px;
    border-left: 1px solid {c.border};
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {c.btn_top}, stop:1 {c.btn_upper});
}}
QAbstractSpinBox::down-button {{
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 17px;
    margin: 0px 1px 1px 0px;
    border-left: 1px solid {c.border};
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {c.btn_lower}, stop:1 {c.btn_bottom});
}}
QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {c.hot_top}, stop:1 {c.hot_bottom});
}}
QAbstractSpinBox::up-button:pressed, QAbstractSpinBox::down-button:pressed {{
    background: {c.press_top};
}}
QAbstractSpinBox::up-arrow {{
    image: {u('arrow-up')};
    width: 9px;
    height: 5px;
}}
QAbstractSpinBox::down-arrow {{
    image: {u('arrow-down')};
    width: 9px;
    height: 5px;
}}
QAbstractSpinBox::up-arrow:disabled, QAbstractSpinBox::up-arrow:off {{
    image: {u('arrow-up-off')};
}}
QAbstractSpinBox::down-arrow:disabled, QAbstractSpinBox::down-arrow:off {{
    image: {u('arrow-down-off')};
}}

QMenu::right-arrow {{
    image: {u('arrow-right')};
    width: 5px;
    height: 9px;
    margin-right: 8px;
}}
QMenu::right-arrow:selected {{
    image: {u('arrow-right-hot')};
}}
QToolButton::menu-indicator {{
    image: {u('arrow-down')};
    width: 9px;
    height: 5px;
    subcontrol-origin: padding;
    subcontrol-position: bottom right;
    bottom: 2px;
    right: 2px;
}}
/* the ">>" a full toolbar folds its extra buttons into: Qt draws that glyph
   itself, which a styled QToolButton would suppress */
QToolBar QToolButton#qt_toolbar_ext_button {{
    qproperty-icon: {u('arrow-right')};
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {c.bar_mid}, stop:1 {c.bar_bottom});
    border: 1px solid {c.border};
    border-radius: 3px;
    min-width: 16px;
    max-width: 20px;
    margin: 3px 1px;
    padding: 0px;
}}
QToolBar QToolButton#qt_toolbar_ext_button:hover {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {c.hot_top}, stop:1 {c.hot_bottom});
    border: 1px solid {c.hot_border};
}}

QTreeView::branch:has-children:!has-siblings:closed,
QTreeView::branch:closed:has-children:has-siblings {{
    border-image: none;
    image: {u('twisty-closed')};
}}
QTreeView::branch:open:has-children:!has-siblings,
QTreeView::branch:open:has-children:has-siblings {{
    border-image: none;
    image: {u('twisty-open')};
}}

QHeaderView::up-arrow {{
    image: {u('arrow-up')};
    width: 9px;
    height: 5px;
    padding-right: 4px;
}}
QHeaderView::down-arrow {{
    image: {u('arrow-down')};
    width: 9px;
    height: 5px;
    padding-right: 4px;
}}

/* ---- check boxes and radio buttons ---- */
QCheckBox, QRadioButton {{
    spacing: 7px;
    background: transparent;
    color: {c.text};
}}
QCheckBox:disabled, QRadioButton:disabled {{
    color: {c.disabled};
}}
QCheckBox::indicator, QRadioButton::indicator, QGroupBox::indicator,
QMenu::indicator, QTreeWidget::indicator, QListWidget::indicator {{
    width: 13px;
    height: 13px;
}}
QCheckBox::indicator:unchecked, QGroupBox::indicator:unchecked,
QTreeWidget::indicator:unchecked, QListWidget::indicator:unchecked {{
    image: {u('check-off')};
}}
QCheckBox::indicator:unchecked:hover, QGroupBox::indicator:unchecked:hover,
QTreeWidget::indicator:unchecked:hover, QListWidget::indicator:unchecked:hover {{
    image: {u('check-off-hot')};
}}
QCheckBox::indicator:unchecked:disabled, QGroupBox::indicator:unchecked:disabled,
QTreeWidget::indicator:unchecked:disabled {{
    image: {u('check-off-dis')};
}}
QCheckBox::indicator:checked, QGroupBox::indicator:checked,
QTreeWidget::indicator:checked, QListWidget::indicator:checked {{
    image: {u('check-on')};
}}
QCheckBox::indicator:checked:hover, QGroupBox::indicator:checked:hover,
QTreeWidget::indicator:checked:hover, QListWidget::indicator:checked:hover {{
    image: {u('check-on-hot')};
}}
QCheckBox::indicator:checked:disabled, QGroupBox::indicator:checked:disabled,
QTreeWidget::indicator:checked:disabled {{
    image: {u('check-on-dis')};
}}
QCheckBox::indicator:indeterminate, QTreeWidget::indicator:indeterminate {{
    image: {u('check-part')};
}}
QRadioButton::indicator:unchecked {{
    image: {u('radio-off')};
}}
QRadioButton::indicator:unchecked:hover {{
    image: {u('radio-off-hot')};
}}
QRadioButton::indicator:unchecked:disabled {{
    image: {u('radio-off-dis')};
}}
QRadioButton::indicator:checked {{
    image: {u('radio-on')};
}}
QRadioButton::indicator:checked:hover {{
    image: {u('radio-on-hot')};
}}
QRadioButton::indicator:checked:disabled {{
    image: {u('radio-on-dis')};
}}
QMenu::indicator:non-exclusive:checked {{
    image: {u('check-on')};
    left: 7px;
}}
QMenu::indicator:exclusive:checked {{
    image: {u('radio-on')};
    left: 7px;
}}

/* ---- scroll bars ---- */
QScrollBar:vertical {{
    background: {c.sb_bg};
    width: 16px;
    margin: 16px 0px 16px 0px;
    border: 1px solid {c.border};
}}
QScrollBar:horizontal {{
    background: {c.sb_bg};
    height: 16px;
    margin: 0px 16px 0px 16px;
    border: 1px solid {c.border};
}}
QScrollBar::handle:vertical {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 {c.sb_top}, stop:1 {c.sb_bottom});
    border: 1px solid {c.sb_border};
    border-radius: 2px;
    min-height: 28px;
    margin: -1px;
}}
QScrollBar::handle:horizontal {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {c.sb_top}, stop:1 {c.sb_bottom});
    border: 1px solid {c.sb_border};
    border-radius: 2px;
    min-width: 28px;
    margin: -1px;
}}
QScrollBar::handle:hover {{
    border: 1px solid {c.hot_border};
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {c.btn_top}, stop:1 {c.btn_bottom});
    border: 1px solid {c.sb_border};
    subcontrol-origin: margin;
}}
QScrollBar::add-line:hover, QScrollBar::sub-line:hover {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {c.hot_top}, stop:1 {c.hot_bottom});
}}
QScrollBar::sub-line:vertical {{
    height: 16px;
    subcontrol-position: top;
    image: {u('arrow-up')};
}}
QScrollBar::add-line:vertical {{
    height: 16px;
    subcontrol-position: bottom;
    image: {u('arrow-down')};
}}
QScrollBar::sub-line:horizontal {{
    width: 16px;
    subcontrol-position: left;
    image: {u('arrow-left')};
}}
QScrollBar::add-line:horizontal {{
    width: 16px;
    subcontrol-position: right;
    image: {u('arrow-right')};
}}
QScrollBar::add-page, QScrollBar::sub-page {{
    background: transparent;
}}
QScrollBar::handle:disabled, QScrollBar::add-line:disabled,
QScrollBar::sub-line:disabled {{
    background: {c.btn_off};
}}
"""


def stylesheet(colors: Colors, art: dict[str, str] | None = None) -> str:
    art = _artwork(colors) if art is None else art
    return _base_sheet(colors) + _chrome_sheet(colors, art)


# ---------------------------------------------------------------- palette


def qt_palette(c: Colors) -> QPalette:
    """A fixed palette so a foreign desktop theme cannot bleed through."""
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(c.window))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(c.text))
    palette.setColor(QPalette.ColorRole.Base, QColor(c.base))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(c.alt_base))
    palette.setColor(QPalette.ColorRole.Text, QColor(c.text))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(c.disabled))
    palette.setColor(QPalette.ColorRole.Button, QColor(c.window))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(c.text))
    palette.setColor(QPalette.ColorRole.BrightText, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(c.sel_bottom))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(c.sel_text))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(c.tip_bg))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(c.tip_text))
    palette.setColor(QPalette.ColorRole.Link, QColor(c.link))
    palette.setColor(QPalette.ColorRole.LinkVisited, QColor(c.link))
    palette.setColor(QPalette.ColorRole.Light, QColor(c.light_edge))
    palette.setColor(QPalette.ColorRole.Midlight, QColor(c.soft_edge))
    palette.setColor(QPalette.ColorRole.Mid, QColor(c.border))
    palette.setColor(QPalette.ColorRole.Dark, QColor(c.shadow))
    palette.setColor(QPalette.ColorRole.Shadow, QColor(c.dark_shadow))
    for role in (
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
        QPalette.ColorRole.WindowText,
    ):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(c.disabled))
    palette.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.Base, QColor(c.btn_off)
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.Highlight, QColor(c.sel_idle)
    )
    return palette


# ---------------------------------------------------------------- entry point

_mode = LIGHT
_colors = LIGHT_COLORS


def current() -> Colors:
    """The colours of the theme in force."""
    return _colors


def mode() -> str:
    return _mode


def apply(app, requested: str | None = None) -> str:
    """Install the LinRAR look on *app* and return the theme that was used."""
    global _mode, _colors

    if requested is None:
        try:                                  # avoid a circular import at load
            from ..core.settings import SETTINGS

            requested = SETTINGS.get("view/theme")
        except Exception:                     # pragma: no cover - defensive
            requested = LIGHT

    _mode = normalize(requested)
    _colors = PALETTES[_mode]

    # The icon set follows the chrome, so glyphs never sit on a hostile
    # background.
    from . import icons

    icons.set_theme(_mode)

    app.setStyle("Fusion")
    app.setPalette(qt_palette(_colors))
    app.setStyleSheet(stylesheet(_colors))
    app.setWindowIcon(icons.icon("app"))
    return _mode
