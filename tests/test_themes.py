"""Theme packs: the loader, the pack -> live theme binding, and the manager."""
import json, os, shutil, sys, tempfile, zipfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Point the search path at a scratch directory *before* anything imports the
# theme modules, so this file can never touch the user's real themes.
WORK = tempfile.mkdtemp(prefix="linrar-themes-")
BUNDLED = os.path.join(WORK, "bundled")
USER = os.path.join(WORK, "user")
os.makedirs(BUNDLED)
os.makedirs(USER)
os.environ["LINRAR_THEMES_DIR"] = f"{BUNDLED}{os.pathsep}{USER}"

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QLabel, QToolButton
app = QApplication([])

from linrar.core import themes as loader
from linrar.core.settings import DEFAULT_TOOLBAR, SETTINGS, SystemConfig
from linrar.ui import icons, theme
from linrar.ui.main_window import MainWindow, TOOLBAR_CATALOGUE
from linrar.ui.dialogs.customize import _ICONS
from linrar.ui.dialogs.misc import SettingsDialog
from linrar.ui.dialogs.themes import ThemeManagerDialog, _swatch

PASS = FAIL = 0
def check(name, cond, extra=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ok  {name}")
    else: FAIL += 1; print(f"FAIL  {name}  {extra}")


def write(folder, name, body):
    path = os.path.join(folder, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(body if isinstance(body, str) else json.dumps(body))
    return path


MINIMAL = {
    "name": "Test Ocean",
    "author": "the test suite",
    "version": "2.0",
    "description": "a deliberately small manifest",
    "base": "dark",
    "accent": "#0088CC",
    "font": {"size": "10pt"},
    "metrics": {"radius": 7, "button_radius": 9, "card_radius": 11},
    "colors": {"window": "#0B1D2A", "sel_bottom": "#0088CC"},
    "icons": {"folder": ["#BBDDFF", "#3399DD", "#115577"]},
    "stylesheet": "QLabel#Heading { letter-spacing: 1px; }",
}

print("== where themes are looked for")
check("the env override replaces the search path",
      loader.search_paths() == [BUNDLED, USER], loader.search_paths())
check("and its last entry is the writable one", loader.user_dir() == USER)
check("nothing installed yet", loader.discover(rescan=True) == {})
SEARCH = "LINRAR_THEMES_DIR"
del os.environ[SEARCH]
check("without it, the folder themes are dropped into is searched last",
      loader.search_paths()[-1] == loader.writable_dir(),
      loader.search_paths()[-1])
check("and that folder is themes/ beside the application when writable",
      loader.writable_dir() == os.path.join(ROOT, "themes"),
      loader.writable_dir())
check("with the machine-wide directories below it",
      any("/usr/share" in p for p in loader.search_paths()),
      loader.search_paths())
os.environ[SEARCH] = f"{BUNDLED}{os.pathsep}{USER}"

print("== reading a manifest")
write(BUNDLED, "test-ocean/theme.json", MINIMAL)
found = loader.discover(rescan=True)
check("the directory is found", list(found) == ["test-ocean"], list(found))
pack = found["test-ocean"]
check("name, author and version read", (pack.name, pack.author, pack.version)
      == ("Test Ocean", "the test suite", "2.0"))
check("it is a dark theme", pack.base == "dark")
check("nothing is wrong with it", pack.problems == [], pack.problems)
check("summary reads as a byline", pack.summary() == "2.0 by the test suite")
check("a theme in a writable folder can be removed", pack.removable)
check("the manifest's path is kept", pack.path.endswith("test-ocean"))

print("== a pack becomes a live theme")
theme.reload_packs()
check("it is selectable", "test-ocean" in theme.available())
check("the built-ins still come first",
      theme.available()[:2] == ["light", "dark"])
colors = theme.colors_for("test-ocean")
check("what it set is set", colors.window == "#0B1D2A")
check("what it left alone comes from its base",
      colors.text == theme.DARK_COLORS.text)
check("it counts as a dark theme", theme.variant_of(colors) == "dark")
check("its metrics arrive",
      (colors.radius, colors.button_radius, colors.card_radius) == (7, 9, 11))
check("its font size arrives", colors.font_size == "10pt")
check("the glyph cache is keyed by the pack, not by dark",
      colors.mode == "test-ocean")
sheet = theme.stylesheet(colors)
check("the metrics reach the style sheet", "border-radius: 9px" in sheet)
check("the font size reaches it", "font-size: 10pt" in sheet)
check("its own style sheet is appended last",
      sheet.rstrip().endswith("QLabel#Heading { letter-spacing: 1px; }"))
check("resolve knows it", theme.resolve("test-ocean") == "test-ocean")
check("resolve falls back for anything else", theme.resolve("wat") == "light")
check("normalize still only knows the built-ins",
      theme.normalize("test-ocean") == "light")
check("label is the pack's name", theme.label("test-ocean") == "Test Ocean")
check("is_pack tells them apart",
      theme.is_pack("test-ocean") and not theme.is_pack("dark"))

print("== the icon set follows")
check("a build was registered", "test-ocean" in icons.builds())
plain = icons.pixmap_for("dark", "folder", 32).toImage()
tinted = icons.pixmap_for("test-ocean", "folder", 32).toImage()
check("the pack's folder is not the dark one", plain != tinted)
check("what it did not re-tune matches its base",
      icons.pixmap_for("dark", "help", 32).toImage()
      == icons.pixmap_for("test-ocean", "help", 32).toImage())
check("an unknown build falls back rather than raising",
      not icons.pixmap_for("nope", "folder", 16).isNull())
check("the built-in build names are reserved",
      icons.register_build("dark", "light") is False
      and icons.pixmap_for("dark", "folder", 32).toImage() == plain)

print("== applying one")
check("apply returns the pack id", theme.apply(app, "test-ocean") == "test-ocean")
check("active() is the pack", theme.active() == "test-ocean")
check("mode() is still light-or-dark", theme.mode() == "dark")
check("the icons switched with it", icons._MODE == "test-ocean")
check("the application is wearing it", "#0B1D2A" in app.styleSheet())
theme.apply(app, "light")

print("== SVG that replaces a drawn glyph")
write(BUNDLED, "test-ocean/icons/folder.svg",
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48">'
      '<rect x="4" y="12" width="40" height="26" fill="#FF00FF"/></svg>')
loader.reload()
theme.reload_packs()
check("the file is picked up",
      list(theme.pack("test-ocean").icon_svg) == ["folder"])
replaced = icons.pixmap_for("test-ocean", "folder", 32).toImage()
check("and it is what gets drawn", replaced != tinted)
check("other glyphs are untouched",
      icons.pixmap_for("dark", "help", 32).toImage()
      == icons.pixmap_for("test-ocean", "help", 32).toImage())

print("== a manifest full of mistakes keeps whatever was right")
write(USER, "sloppy.json", {
    "name": "Sloppy",
    "base": "puce",
    "colors": {"window": "#202020", "nope": "#111111", "text": "blue",
               "radius": "#111111"},
    "icons": {"folder": "#FF0000", "bogus": ["#111111", "#222222", "#333333"],
              "ink": "#445566"},
    "metrics": {"radius": 99, "wobble": 3},
    "icon_style": "shiny",
    "font": {"size": "enormous"},
    "accent": "puce",
    "stylesheet": 42,
})
loader.reload()
theme.reload_packs()
sloppy = theme.pack("sloppy")
complaints = " | ".join(p.detail() for p in sloppy.problems)
check("it still loads", sloppy is not None)
check("a bad base falls back to light", sloppy.base == "light")
for expect, needle in (
    ('an unreadable base is named', 'puce'),
    ("a colour that is not one is named", "a hex colour"),
    ("and says why a colour name is not one", "different colour on different"),
    ("an invented colour field is named", "colors.nope"),
    ("a radius among the colours is named", 'move it:  "metrics"'),
    ("with a did-you-mean where there is one", "did you mean"),
    ("an out-of-range metric is named", "0 to 24 pixels"),
    ("an invented metric is named", "metrics.wobble"),
    ("a colour where a triple belongs is named",
     "three colours: light, middle and dark"),
    ("and offers a worked triple to paste in", '["#FF6666", "#FF0000"'),
    ("an invented ink field is named", "icons.bogus"),
    ("a nonsense font size is named", "enormous"),
    ("a stylesheet that is not text is named", "one string of Qt style sheet"),
):
    check(expect, needle in complaints, complaints[:400])
check("and every complaint says both what is expected and how to fix it",
      all(p.fix and p.expected for p in sloppy.problems))
check("an unknown icon style is named too, with the four that exist",
      any("icon_style" in p.where and "gloss" in p.expected
          for p in sloppy.problems),
      [p.where for p in sloppy.problems])
good = theme.colors_for("sloppy")
check("and the parts that were right are used", good.window == "#202020")
check("the parts that were wrong are not",
      good.text == theme.LIGHT_COLORS.text and good.radius
      == theme.LIGHT_COLORS.radius)
check("a good ink value in the same file still lands",
      icons.pixmap_for("sloppy", "file-text", 32).toImage()
      != icons.pixmap_for("light", "file-text", 32).toImage())

print("== files that are not themes")
write(USER, "broken.json", "{ not json at all")
write(USER, "empty.json", {"name": "Nothing"})
write(USER, "dark.json", {"colors": {"window": "#111111"}})
os.makedirs(os.path.join(USER, "no-manifest"), exist_ok=True)
loader.reload()
reported = " | ".join(b.report() for b in loader.broken())
check("still finds the good ones",
      {"test-ocean", "sloppy"} <= set(loader.discover()), list(loader.discover()))
check("bad JSON is reported, not fatal", "valid JSON" in reported, reported)
check("and says where in the file", "line 1" in reported, reported)
check("a manifest that says nothing is refused",
      'at least a "colors"' in reported, reported)
check("a pack may not be called dark",
      "built-in theme" in reported, reported)
check("a folder with no manifest is simply not a theme",
      "no-manifest" not in reported, reported)
check("every broken file explains how to fix itself",
      all(b.problem.fix and b.problem.fatal for b in loader.broken()),
      [b.problem for b in loader.broken()])
for name in ("broken.json", "empty.json", "dark.json"):
    os.remove(os.path.join(USER, name))
os.rmdir(os.path.join(USER, "no-manifest"))

print("== precedence")
write(USER, "test-ocean/theme.json",
      {**MINIMAL, "name": "Test Ocean (mine)", "colors": {"window": "#FF0000"}})
loader.reload()
theme.reload_packs()
check("the user's copy shadows the bundled one",
      theme.label("test-ocean") == "Test Ocean (mine)")
check("and is the one that gets used",
      theme.colors_for("test-ocean").window == "#FF0000")
check("and is removable", theme.pack("test-ocean").removable)
shutil.rmtree(os.path.join(USER, "test-ocean"))
loader.reload()
theme.reload_packs()

print("== installing")
zip_path = os.path.join(WORK, "Some Theme.linrar-theme")
with zipfile.ZipFile(zip_path, "w") as archive:
    # Wrapped in a folder, the way every zip tool produces one.
    archive.writestr("some-theme/theme.json", json.dumps(
        {**MINIMAL, "name": "Some Theme"}))
    archive.writestr(
        "some-theme/icons/add.svg",
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48">'
        '<circle cx="24" cy="24" r="20" fill="#00FF00"/></svg>')
installed = loader.install(zip_path)
check("a zip installs", installed.id == "some-theme", installed.id)
check("the id is slugged from the file name", installed.label == "Some Theme")
check("it landed in the writable directory",
      os.path.dirname(installed.path) == USER, installed.path)
check("it is removable", installed.removable)
check("its icon override came with it", list(installed.icon_svg) == ["add"])
check("a second install of the same name does not overwrite",
      loader.install(zip_path).path.endswith("some-theme-2"))
loader.remove("some-theme-2")

flat = os.path.join(WORK, "flat.linrar-theme")
with zipfile.ZipFile(flat, "w") as archive:
    archive.writestr("theme.json", json.dumps({**MINIMAL, "name": "Flat"}))
check("a zip with the manifest at the top installs too",
      loader.install(flat).label == "Flat")
loader.remove("flat")

bare = write(WORK, "bare.json", {**MINIMAL, "name": "Bare"})
got = loader.install(bare)
check("a bare manifest installs into a folder of its own",
      got.id == "bare" and os.path.isdir(got.path))
loader.remove("bare")

folder = os.path.join(WORK, "copied")
write(folder, "theme.json", {**MINIMAL, "name": "Copied"})
check("an unpacked folder installs", loader.install(folder).label == "Copied")
loader.remove("copied")

print("== an install is treated as hostile")
escape = os.path.join(WORK, "escape.linrar-theme")
with zipfile.ZipFile(escape, "w") as archive:
    archive.writestr("../../../../tmp/linrar-pwned.json", "{}")
    archive.writestr("theme.json", json.dumps(MINIMAL))
try:
    loader.install(escape)
    check("a path that escapes the folder is refused", False, "it installed")
except loader.ThemeError as error:
    check("a path that escapes the folder is refused",
          ".." in error.problem.found, error.problem.found)
check("and nothing was written", not os.path.exists("/tmp/linrar-pwned.json"))

absolute = os.path.join(WORK, "absolute.linrar-theme")
with zipfile.ZipFile(absolute, "w") as archive:
    info = zipfile.ZipInfo("/etc/linrar-pwned.json")
    archive.writestr(info, "{}")
    archive.writestr("theme.json", json.dumps(MINIMAL))
try:
    loader.install(absolute)
    check("an absolute path is refused", False, "it installed")
except loader.ThemeError as error:
    check("an absolute path is refused",
          "absolute path" in error.problem.found, error.problem.found)

link = os.path.join(WORK, "link.linrar-theme")
with zipfile.ZipFile(link, "w") as archive:
    archive.writestr("theme.json", json.dumps(MINIMAL))
    info = zipfile.ZipInfo("evil")
    info.external_attr = (0o120777 << 16)
    archive.writestr(info, "/etc/passwd")
try:
    loader.install(link)
    check("a symbolic link is refused", False, "it installed")
except loader.ThemeError as error:
    check("a symbolic link is refused",
          "symbolic link" in error.problem.found, error.problem.found)

reserved = write(WORK, "light.linrar-theme", MINIMAL)
try:
    loader.install(reserved)
    check("a pack may not be installed as light", False, "it installed")
except loader.ThemeError as error:
    check("a pack may not be installed as light",
          "own themes" in error.problem.fix
          and "light-mine" in error.problem.fix, error.problem.fix)

huge = write(WORK, "huge.json", "x" * (loader.MAX_BYTES + 10))
try:
    loader.load(huge)
    check("an absurdly large manifest is refused", False, "it loaded")
except loader.ThemeError as error:
    check("an absurdly large manifest is refused",
          "KiB" in error.problem.found, error.problem.found)

print("== a themes folder takes whatever shape a theme arrives in")
shapes = os.path.join(WORK, "shapes")
os.makedirs(shapes)
os.environ[SEARCH] = shapes
write(shapes, "plain/theme.json", {**MINIMAL, "name": "Plain"})
write(shapes, "nested/inner/theme.json", {**MINIMAL, "name": "Nested"})
write(shapes, "oddname/whatever.json", {**MINIMAL, "name": "Odd"})
write(shapes, "bare.json", {**MINIMAL, "name": "Bare"})
write(shapes, "winrarish.theme", {**MINIMAL, "name": "WinRARish"})
write(shapes, "not-a-theme/notes.txt", "hello")
zipped_in_place = os.path.join(shapes, "zipped.linrar-theme")
with zipfile.ZipFile(zipped_in_place, "w") as archive:
    archive.writestr("zipped/theme.json", json.dumps({**MINIMAL, "name": "Zipped"}))
    archive.writestr(
        "zipped/icons/folder.svg",
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48">'
        '<rect x="6" y="14" width="36" height="24" fill="#FF00AA"/></svg>')
shaped = loader.reload()
theme.reload_packs()
check("a plain folder is a theme", "plain" in shaped)
check("so is one a zip tool nested a level deeper", "nested" in shaped)
check("so is a folder holding one JSON of any name", "oddname" in shaped)
check("so is a bare manifest", "bare" in shaped)
check("so is a .theme file, which is what WinRAR calls its own",
      "winrarish" in shaped)
check("and a zip is read in place, without unpacking anything",
      "zipped" in shaped and shaped["zipped"].zipped, list(shaped))
check("including the icons inside it",
      list(shaped["zipped"].icon_svg) == ["folder"],
      list(shaped.get("zipped").icon_svg) if "zipped" in shaped else None)
check("a folder that holds no manifest is simply not a theme, and not broken",
      "not-a-theme" not in shaped
      and not any("not-a-theme" in b.path for b in loader.broken()),
      [b.path for b in loader.broken()])
check("all six really load", len(shaped) == 6, sorted(shaped))
os.environ[SEARCH] = f"{BUNDLED}{os.pathsep}{USER}"
loader.reload()
theme.reload_packs()

print("== removing")
mine = loader.install(write(WORK, "mine.json", {**MINIMAL, "name": "Mine"}))
check("installed to be removed", mine.removable)
check("remove says it removed it", loader.remove("mine") is True)
check("and it is gone", "mine" not in loader.discover())
check("removing what is not there is False", loader.remove("mine") is False)
# A theme outside every search path is nobody's to delete, however writable
# the folder it happens to sit in.
outside = write(WORK, "stray/theme.json", MINIMAL)
stray = loader.load(os.path.dirname(outside))
stray.removable = True
loader._CACHE["stray"] = stray
try:
    loader.remove("stray")
    check("a theme outside the theme folders refuses to be removed",
          False, "it was removed")
except loader.ThemeError as error:
    check("a theme outside the theme folders refuses to be removed",
          "outside" in error.problem.found, error.problem.found)
check("and is still there", os.path.isfile(outside))
loader.reload()

print("== a theme folder full of themes")
# There used to be ten generated into themes/ by a script in this repository,
# and this file checked every one of them.  The generator now lives on the
# website -- themes are downloaded, not built here -- so what is left to check is
# the loader's behaviour with a folder full of them, against themes this file
# writes itself.  The legibility gate those ten were held to went with the
# generator; it is now the theme builder's job, in linrar-ui/src/theme-engine.
crowd = os.path.join(WORK, "crowd")
os.makedirs(crowd, exist_ok=True)
os.environ[SEARCH] = crowd
FAMILY = [
    ("first-light", "light", "gloss", "#F2F0EC", "#316AC5"),
    ("second-dark", "dark", "flat", "#20242C", "#4A90D9"),
    ("third-neon", "dark", "neon", "#12141C", "#22C8E6"),
    ("fourth-soft", "light", "soft", "#F8F4FA", "#C2477E"),
]
for name, base, style, window, accent in FAMILY:
    write(crowd, f"{name}/theme.json", {
        "name": name.replace("-", " ").title(),
        "base": base,
        "icon_style": style,
        "description": f"A {base} theme for the test suite.",
        "accent": accent,
        "metrics": {"radius": 3, "button_radius": 4, "card_radius": 5},
        "colors": {"window": window, "sel_bottom": accent},
        "icons": {"folder": ["#FFE0A0", "#E0A020", "#A06010"]},
    })
packs = loader.reload()
theme.reload_packs()
check("all four are found", len(packs) == 4, sorted(packs))
check("nothing is wrong with any of them",
      {i: p.problems for i, p in packs.items() if p.problems} == {},
      {i: [q.line() for q in p.problems] for i, p in packs.items() if p.problems})
check("each keeps the base it asked for",
      sorted((p.id, p.base) for p in packs.values())
      == sorted((name, base) for name, base, _s, _w, _a in FAMILY))
check("each gets the icon style it asked for",
      all(icons.style_of(name) == style
          for name, _b, style, _w, _a in FAMILY),
      {name: icons.style_of(name) for name, _b, _s, _w, _a in FAMILY})
check("and the icon styles really do draw differently",
      len({icons.svg("folder", name) for name, *_rest in FAMILY}) == 4)
for name, _base, _style, window, _accent in FAMILY:
    applied = theme.apply(app, name)
    colours = theme.current()
    check(f"{name} applies cleanly",
          applied == name and colours.mode == name
          and window in app.styleSheet())
theme.apply(app, "light")
# Everything from here on is about the window and its dialogs, so the search path
# stays pointed at this folderful of themes: it is what a real install looks
# like, and the sections below need something to choose between.
os.environ[SEARCH] = f"{crowd}{os.pathsep}{USER}"
loader.reload()
theme.reload_packs()

print("== the window")
SETTINGS.set("view/theme", "light")
SETTINGS.sync()
win = MainWindow()
# One command, one control.  There is no light/dark switch and no per-theme
# submenu: both showed two of the twelve themes and neither could preview one.
options = next(m for m in (a.menu() for a in win.menuBar().actions())
               if m is not None and m.title().replace("&", "") == "Options")
entries = [a.text().replace("&", "") for a in options.actions()
           if not a.isSeparator()]
check("Options has exactly one theme entry",
      entries.count("Themes...") == 1, entries)
check("and no submenu of themes",
      not any(a.menu() is not None
              and "theme" in a.text().replace("&", "").lower()
              for a in options.actions()))
check("the light/dark switch is gone", not hasattr(win, "act_toggle_theme"))
check("and so are the per-theme menu entries",
      not hasattr(win, "theme_actions"))
win.set_theme("third-neon")
check("selecting a pack applies it", theme.active() == "third-neon")
check("and is remembered", SETTINGS.get("view/theme") == "third-neon")
check("the button says which theme is in use",
      "Third Neon" in win.act_themes.toolTip(), win.act_themes.toolTip())
win.set_theme("nonsense")
check("an unknown theme falls back", theme.active() == "light")
SETTINGS.set("view/theme", "no-such-theme")
SETTINGS.sync()
check("so does one the settings file names but nobody installed",
      theme.apply(app, SETTINGS.get("view/theme")) == "light")
check("the Themes button is catalogued for the toolbar",
      ("themes", "act_themes", "Themes") in TOOLBAR_CATALOGUE)
check("and the Customize picker has its icon", _ICONS.get("themes") == "themes")
check("every catalogued button still has an icon",
      [k for k, _a, _c in TOOLBAR_CATALOGUE if k not in _ICONS] == [])
SETTINGS.set("toolbar/items", ["themes", "theme"])
win.rebuild_toolbar()
check("it can go on the toolbar",
      isinstance(win.toolbar.widgetForAction(win.act_themes), QToolButton))
SETTINGS.reset("toolbar/items")

print("== the manager")
dialog = ThemeManagerDialog(win)
check("it lists every theme", dialog.list.count() == len(theme.available()))
check("it opens on the one in force", dialog.current_id() == theme.active())
check("the preview wears the selected theme, not the live one",
      theme.colors_for(dialog.current_id()).window
      in dialog.preview.styleSheet())
# Regression: the frame has to paint its own 3D face.  The style sheet names
# QMainWindow and QDialog for that, neither of which the preview is, so
# everything transparent inside it showed the *dialog's* background instead --
# and a dark theme's text landed on a light grey group box.
check("and paints its own background rather than the dialog's",
      "#ThemePreview {" in dialog.preview.styleSheet()
      and dialog.preview.testAttribute(
          Qt.WidgetAttribute.WA_StyledBackground))
check("Apply is off for the theme already in force",
      not dialog.apply_button.isEnabled())
check("a built-in theme cannot be removed",
      not dialog.remove_button.isEnabled())
dialog._select("second-dark")
check("selecting another one moves the preview",
      "#20242C" in dialog.preview.styleSheet())
check("its icons come from its own build",
      dialog.preview._build_name == "second-dark")
check("Apply woke up", dialog.apply_button.isEnabled())
dialog._apply_selected()
check("Apply repaints the application", theme.active() == "second-dark")
check("and the window went with it",
      "#20242C" in QApplication.instance().styleSheet())
dialog.reject()
check("Cancel puts back what was in force", theme.active() == "light")
dialog.close()

dialog = ThemeManagerDialog(win)
dialog._select("fourth-soft")
dialog._accept()
check("OK applies and closes", theme.active() == "fourth-soft")
win.set_theme("light")

print("== a theme in the manager that has problems says so")
os.environ[SEARCH] = f"{crowd}{os.pathsep}{USER}"
write(USER, "grumpy/theme.json",
      {"name": "Grumpy", "colors": {"window": "#123456", "nope": "#111111"}})
# Nothing told the window; opening the manager is what looks again.
dialog = ThemeManagerDialog(win)
dialog._select("grumpy")
check("it is in the list", dialog.current_id() == "grumpy")
# isVisibleTo, not isVisible: nothing offscreen is ever really on screen.
check("and its problems are shown, with how to fix them",
      dialog.problems.isVisibleTo(dialog)
      and "colors.nope" in dialog.problems.toPlainText()
      and "to fix it" in dialog.problems.toPlainText(),
      dialog.problems.toPlainText()[:200])
check("with a button to copy the whole report",
      dialog.copy_problems.isVisibleTo(dialog))
check("while a sound theme shows none",
      (dialog._select("fourth-soft"),
       not dialog.problems.isVisibleTo(dialog))[1])
dialog.close()
check("and the window can still be pointed at it",
      (win.set_theme("grumpy"), theme.active())[1] == "grumpy")
win.set_theme("light")

print("== drag and drop, and the card that says you can")
os.environ[SEARCH] = f"{crowd}{os.pathsep}{USER}"
loader.reload()
theme.reload_packs()
win.set_theme("light")
dialog = ThemeManagerDialog(win)
check("the drop card names the folder themes go into",
      "Drag a theme here" in dialog.drop_card.text()
      and os.path.basename(loader.writable_dir()) in dialog.drop_card.text(),
      dialog.drop_card.text())
plain = dialog.drop_card.styleSheet()
dialog.drop_card.set_active(True)
check("and lights up while something is over it",
      dialog.drop_card.styleSheet() != plain
      and "Let go" in dialog.drop_card.text())
dialog.drop_card.set_active(False)

from PyQt6.QtCore import QMimeData, QPoint, QUrl
from PyQt6.QtGui import QDragEnterEvent

drops = os.path.join(WORK, "drops")
os.makedirs(drops, exist_ok=True)
write(drops, "Dropped One.json", {**MINIMAL, "name": "Dropped One"})
with zipfile.ZipFile(os.path.join(drops, "dropped-two.linrar-theme"), "w") as z:
    z.writestr("theme.json", json.dumps({**MINIMAL, "name": "Dropped Two"}))
write(drops, "rubbish.linrar-theme", "this is not a theme")

def mime(*paths):
    data = QMimeData()
    data.setUrls([QUrl.fromLocalFile(p) for p in paths])
    return data

# The payloads are kept in named variables on purpose: QDragEnterEvent does not
# take ownership of its QMimeData, so a temporary would be collected out from
# under the event and reading it segfaults the interpreter.
good = mime(os.path.join(drops, "Dropped One.json"))
enter = QDragEnterEvent(QPoint(10, 10), Qt.DropAction.CopyAction, good,
                        Qt.MouseButton.LeftButton,
                        Qt.KeyboardModifier.NoModifier)
dialog.dragEnterEvent(enter)
check("a drag carrying files is accepted", enter.isAccepted())
check("and the card lit up on its own", "Let go" in dialog.drop_card.text())

nothing = QMimeData()
empty = QDragEnterEvent(QPoint(10, 10), Qt.DropAction.CopyAction, nothing,
                        Qt.MouseButton.LeftButton,
                        Qt.KeyboardModifier.NoModifier)
dialog.dragEnterEvent(empty)
check("a drag carrying nothing is not", not empty.isAccepted())
dialog.drop_card.set_active(False)   # what dragLeaveEvent does
check("and the card goes back to its prompt",
      "Drag a theme here" in dialog.drop_card.text())

# install_paths() ends in a message box, which offscreen nobody can answer, so
# what it does is exercised through the call it makes.
done, failed = loader.install_all([
    os.path.join(drops, "Dropped One.json"),
    os.path.join(drops, "dropped-two.linrar-theme"),
    os.path.join(drops, "rubbish.linrar-theme"),
])
check("dropping several installs the good ones",
      sorted(p.id for p in done) == ["dropped-one", "dropped-two"],
      [p.id for p in done])
check("and reports the one that was not a theme, with how to fix it",
      len(failed) == 1 and failed[0][1].problem.fix, failed)
check("they landed in the folder the card names",
      all(os.path.dirname(p.path) == loader.writable_dir() for p in done))
theme.reload_packs()
check("and are selectable straight away",
      {"dropped-one", "dropped-two"} <= set(theme.available()))
dialog.reload(rescan=True)
check("the list shows them", any(
    dialog.list.item(r).data(0x0101) == "dropped-one"
    for r in range(dialog.list.count())))
for gone in ("dropped-one", "dropped-two"):
    loader.remove(gone)
dialog.close()

print("== a file that is not a usable theme is listed, not swallowed")
write(USER, "trailing-comma.json",
      '{"name": "Trailing", "colors": {"window": "#101010",}}')
write(USER, "empty-manifest/theme.json", '{"name": "Nothing at all"}')
loader.reload()
theme.reload_packs()
broken_now = loader.broken()
check("both are reported", len(broken_now) == 2,
      [b.label for b in broken_now])
dialog = ThemeManagerDialog(win)
rows = [dialog.list.item(r).text() for r in range(dialog.list.count())]
check("the list has a section for them", "needs fixing" in rows, rows)
check("with a row per file",
      {"trailing-comma", "empty-manifest"} <= set(rows), rows)
dialog._select(os.path.join(USER, "trailing-comma.json"))
entry = dialog.current_broken()
check("selecting one shows it", entry is not None and entry.id == "trailing-comma")
check("the right-hand side switches to the diagnosis",
      dialog.pages.currentIndex() == 1)
report = dialog.broken_view.toPlainText()
check("which says where the mistake is", "line 1" in report, report[:120])
check("and what usually causes it", "comma after the last item" in report)
check("and how to get back", "Rescan" in report)
check("Apply is off for something that cannot be applied",
      not dialog.apply_button.isEnabled())
check("and it offers to delete the file", dialog.delete_broken.isEnabled())
dialog._select("fourth-soft")
check("choosing a real theme goes back to the preview",
      dialog.pages.currentIndex() == 0)
dialog.close()
os.remove(os.path.join(USER, "trailing-comma.json"))
shutil.rmtree(os.path.join(USER, "empty-manifest"))
loader.reload()
theme.reload_packs()

print("== the window says where more themes come from")
# LinRAR has two themes of its own and ships no others, so a chooser that never
# mentions the website is a dead end for anybody who opens it on a fresh install.
from PyQt6.QtWidgets import QPushButton
from linrar.version import THEMES_URL, THEME_BUILDER_URL

dialog = ThemeManagerDialog(win)
# Found by the object name the style sheet uses, not by anything in the
# caption: a test that looked for a particular glyph in the text broke the
# moment the wording changed, which is not what it is meant to be pinning.
links = [b for b in dialog.findChildren(QPushButton)
         if b.objectName() == "LinkButton"]
check("there are two links out to the site", len(links) == 2,
      [b.text() for b in links])
check("one to download themes",
      any("Download" in b.text() and THEMES_URL in b.toolTip() for b in links),
      [(b.text(), b.toolTip()) for b in links])
check("one to build one",
      any("Create" in b.text() and THEME_BUILDER_URL in b.toolTip()
          for b in links),
      [(b.text(), b.toolTip()) for b in links])
blurb = " | ".join(label.text() for label in dialog.findChildren(QLabel))
check("and it says why they are needed",
      "light and dark themes only" in blurb, blurb[:200])
check("the URLs are built from one place",
      THEMES_URL.startswith("https://linrar.vercel.app/")
      and THEME_BUILDER_URL.startswith("https://linrar.vercel.app/"))
dialog.close()

print("== the manager is easy to get to, and is the only way in")
check("it has a shortcut", win.act_themes.shortcut().toString() == "Ctrl+Shift+M")
check("it is the whole of the menu bar's corner",
      win.menuBar().cornerWidget() is win.themes_button
      and win.themes_button.defaultAction() is win.act_themes)
# Not on the toolbar as it ships: the corner button is already there, in the
# place the light/dark switch used to occupy, so a second one would be a second
# button for the same command.
check("and not duplicated on the default toolbar",
      "themes" not in DEFAULT_TOOLBAR, DEFAULT_TOOLBAR)
check("though it can still be put there from Customize",
      "themes" in [key for key, _a, _c in TOOLBAR_CATALOGUE])
check("the light/dark switch is not in the catalogue at all",
      "theme" not in [key for key, _a, _c in TOOLBAR_CATALOGUE],
      [key for key, _a, _c in TOOLBAR_CATALOGUE])
SETTINGS.set("toolbar/items", ["themes", "add"])
win.rebuild_toolbar()
check("and works when it is", win.act_themes in win.toolbar.actions())
SETTINGS.reset("toolbar/items")
win.rebuild_toolbar()

print("== the Settings dialog offers them too")
settings = SettingsDialog(win)
check("the combo lists every theme",
      settings.theme_combo.count() == len(theme.available()))
check("and follows the live theme",
      settings.theme_combo.currentData() == theme.active())
check("with a way through to the manager",
      settings.theme_button.isEnabled())
settings.close()
win.close()

print("== a locked theme locks the packs too")
locked_conf = write(WORK, "locked.conf",
                    "[view]\ntheme=fourth-soft\n\n[policy]\nlocked=view/theme\n")
# The system layer is swapped on the singleton itself rather than on the
# module that holds it: every part of the interface shares that one object, and
# rebinding the name in one module would leave the others looking elsewhere.
saved_system = SETTINGS.system
SETTINGS.system = SystemConfig([locked_conf])
check("an administrator can name a pack for every user",
      SETTINGS.get("view/theme") == "fourth-soft")
check("and the user cannot write over it",
      SETTINGS.set("view/theme", "light") is False)
check("the administrator's pack is what applies",
      theme.apply(app, SETTINGS.get("view/theme")) == "fourth-soft")
guarded = MainWindow()
check("the Themes entry is not clickable", not guarded.act_themes.isEnabled())
check("nor its button in the corner", not guarded.themes_button.isEnabled())
check("and it says who decided",
      "administrator" in guarded.act_themes.toolTip(),
      guarded.act_themes.toolTip())
check("and it is reported as locked",
      "view/theme" in guarded.locked_settings, guarded.locked_settings)
guarded_dialog = ThemeManagerDialog(guarded)
check("the manager says who decided", guarded_dialog.lock_banner is not None)
guarded_dialog._select("second-dark")
check("Apply stays off", not guarded_dialog.apply_button.isEnabled())
guarded_dialog._apply_selected()
check("and applying does nothing", theme.active() == "fourth-soft")
guarded_dialog.close()
guarded.close()
SETTINGS.system = saved_system

print("== the swatch")
check("a swatch is drawn for every theme",
      all(not _swatch(theme.colors_for(n)).isNull() for n in theme.available()))

theme.apply(app, "light")
SETTINGS.set("view/theme", "light")
SETTINGS.sync()
shutil.rmtree(WORK, ignore_errors=True)
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
