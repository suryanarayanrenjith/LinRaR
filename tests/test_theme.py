"""Theme, painted chrome glyphs, themed icons, and the About/Help rework."""
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtWidgets import QApplication, QLabel
app = QApplication([])

from linrar.ui import icons, theme
from linrar.core.settings import SETTINGS
from linrar.ui.main_window import MainWindow
from linrar.ui.dialogs.misc import AboutDialog, HelpDialog, SettingsDialog, PORTFOLIO

PASS = FAIL = 0
def check(name, cond, extra=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ok  {name}")
    else: FAIL += 1; print(f"FAIL  {name}  {extra}")

work = tempfile.mkdtemp(prefix="linrar-theme-")
open(f"{work}/a.txt", "w").write("x")

print("== palettes")
check("two modes", theme.MODES == ("light", "dark"), theme.MODES)
check("normalize junk", theme.normalize("chartreuse") == "light")
check("normalize dark", theme.normalize("DARK") == "dark")
light, dark = theme.LIGHT_COLORS, theme.DARK_COLORS
check("every colour differs by mode",
      all(getattr(light, f) != getattr(dark, f)
          for f in ("window", "base", "text", "bar_mid", "menu_bg")))

print("== painted glyphs")
art = theme._artwork(dark)
check("glyphs generated", len(art) >= 20, len(art))
for key in ("arrow-down", "arrow-down-off", "arrow-up", "check-on", "radio-on",
            "twisty-closed"):
    check(f"glyph {key} on disk", key in art and os.path.isfile(art[key]))
check("hidpi twin written",
      os.path.isfile(art["arrow-down"].replace(".png", "@2x.png")))

qss = theme.stylesheet(dark, art)
check("combo arrow styled", "QComboBox::down-arrow" in qss and
      art["arrow-down"] in qss)
check("check box styled", "QCheckBox::indicator:checked" in qss)
check("scrollbar arrows styled", "QScrollBar::add-line:vertical" in qss)
check("no glyphs -> no glyph rules",
      "QComboBox::down-arrow" not in theme.stylesheet(dark, {}))

print("== themed icons")
icons.set_theme("light")
light_png = icons.pixmap("file", 32).toImage()
icons.set_theme("dark")
dark_png = icons.pixmap("file", 32).toImage()
check("icon build follows theme", light_png != dark_png)
check("new icons present",
      {"theme-light", "theme-dark", "help", "globe"} <= set(icons.names()))
check("unknown icon falls back", not icons.pixmap("nope", 16).isNull())

print("== applying a theme")
check("apply returns mode", theme.apply(app, "dark") == "dark")
check("mode reported", theme.mode() == "dark")
check("palette followed", theme.current() is theme.DARK_COLORS)
check("icons followed", icons._MODE == "dark")
check("stylesheet installed", "QToolBar#MainToolBar" in app.styleSheet())
check("window text is light",
      app.palette().windowText().color().lightness() > 128)

print("== the window switches live")
theme.apply(app, "light")
win = MainWindow()
win.navigate_to(work)
check("starts light", theme.mode() == "light")
win.set_theme("dark")
check("switched to dark", theme.mode() == "dark")
check("setting saved", SETTINGS.get("view/theme") == "dark")
# One button, one place: there is no light/dark switch and no per-theme menu.
check("one Themes button and nothing else",
      not hasattr(win, "act_toggle_theme")
      and not hasattr(win, "theme_actions")
      and win.menuBar().cornerWidget().defaultAction() is win.act_themes)
check("and it says which theme is in use",
      "Dark" in win.act_themes.toolTip(), win.act_themes.toolTip())
check("listing survives", [i.name for i in win.model.items if not i.is_parent]
      == ["a.txt"])
win.set_theme("light")
check("switched back", theme.mode() == "light")
check("bad mode falls back", (win.set_theme("nonsense"), theme.mode())[1] == "light")

print("== help and about")
about = AboutDialog(win)
texts = " ".join(label.text() for label in about.findChildren(QLabel))
check("credits shown", "Surya" in texts and PORTFOLIO in texts)
check("detected tools gone", "Detected tools" not in texts
      and "/usr/bin/unrar" not in texts)
about.close()

helper = HelpDialog(win, page=HelpDialog.SHORTCUTS)
check("help opens on the asked-for page", helper.tabs.currentIndex() == 1)
check("help has three pages", helper.tabs.count() == 3)
helper.close()

settings = SettingsDialog(win)
check("settings theme combo follows the live theme",
      settings.theme_combo.currentData() == theme.mode())
settings.close()
win.close()

SETTINGS.set("view/theme", "light")
SETTINGS.sync()
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
