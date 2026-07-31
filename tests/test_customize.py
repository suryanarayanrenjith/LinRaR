"""Toolbar/view/layout customization, the dependency button, elevation, CLI."""
import os, subprocess, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QToolButton
app = QApplication([])

from linrar.ui import filelist, theme
from linrar.core import elevation, packages
from linrar.core.settings import DEFAULT_TOOLBAR, SETTINGS
from linrar.ui.main_window import MainWindow, TOOLBAR_CATALOGUE
from linrar.ui.dialogs.customize import CustomizeDialog

PASS = FAIL = 0
def check(name, cond, extra=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ok  {name}")
    else: FAIL += 1; print(f"FAIL  {name}  {extra}")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
work = tempfile.mkdtemp(prefix="linrar-custom-")
for name in ("a.txt", "b.txt"):
    open(f"{work}/{name}", "w").write("data" * 50)

# a clean slate, so a previous run cannot colour the results
SETTINGS.reset(*[k for k in ("toolbar/items", "toolbar/icon_size",
                             "toolbar/style", "view/mode", "view/tree_side",
                             "view/comment_side", "view/show_toolbar",
                             "view/show_address", "view/show_status",
                             "view/toolbar_area", "view/row_height",
                             "view/grid_lines", "view/alternate_rows",
                             "view/show_tree", "view/show_comment")])
SETTINGS.sync()
theme.apply(app, "light")
win = MainWindow()
win.navigate_to(work)
win.show()

print("== toolbar")
def toolbar_keys(window):
    return [
        key for key, attribute, _c in TOOLBAR_CATALOGUE
        if getattr(window, attribute, None) in window.toolbar.actions()
    ]
check("default toolbar built", "add" in toolbar_keys(win) and "dependencies" in toolbar_keys(win))
check("separators present",
      sum(1 for a in win.toolbar.actions() if a.isSeparator()) >= 3)
check("captions are the short ones", win.act_extract_to.iconText() == "Extract To")

SETTINGS.set("toolbar/items", ["find", "|", "add", "bogus-key"])
SETTINGS.set("toolbar/icon_size", 16)
SETTINGS.set("toolbar/style", "beside")
win.rebuild_toolbar()
keys = toolbar_keys(win)
check("custom order honoured", keys == ["add", "find"], keys)
check("unknown key ignored", "bogus-key" not in [a.text() for a in win.toolbar.actions()])
check("icon size applied", win.toolbar.iconSize().width() == 16)
check("button style applied",
      win.toolbar.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonTextBesideIcon)

SETTINGS.set("toolbar/items", DEFAULT_TOOLBAR)
SETTINGS.set("toolbar/icon_size", 32)
SETTINGS.set("toolbar/style", "under")
win.rebuild_toolbar()

print("== the dependency button")
deps_button = win.toolbar.widgetForAction(win.act_dependencies)
check("dependencies is on the toolbar", isinstance(deps_button, QToolButton))
check("and is highlighted",
      deps_button.objectName() in ("DependencyButton", "DependencyAlertButton"),
      deps_button.objectName())

menus = {m.title().replace("&", ""): m for m in
         (a.menu() for a in win.menuBar().actions()) if m is not None}
def has(menu, action):
    return action in menu.actions()
check("Dependencies lives under Tools", has(menus["Tools"], win.act_dependencies))
check("and no longer under Options", not has(menus["Options"], win.act_dependencies))
check("Options offers Customize", has(menus["Options"], win.act_customize))
check("Options has a Layout submenu",
      any(a.text().replace("&", "") == "Layout" for a in menus["Options"].actions()))

real_statuses = packages.all_statuses
packages.all_statuses = lambda: [
    packages.DependencyStatus(packages.DEPENDENCIES[0]),  # unrar, missing
]
win.update_dependency_state()
check("missing tools raise the alarm",
      win.toolbar.widgetForAction(win.act_dependencies).objectName()
      == "DependencyAlertButton")
check("and say so in the tooltip", "Missing" in win.act_dependencies.toolTip())
packages.all_statuses = real_statuses
win.update_dependency_state()
essentials_present = all(
    s.installed for s in packages.all_statuses() if s.dependency.essential
)
if essentials_present:
    check("back to normal when nothing is missing",
          win.toolbar.widgetForAction(win.act_dependencies).objectName()
          == "DependencyButton")
else:
    print("  --  rar/unrar not installed, the alarm is correct; skipping")

print("== view modes")
check("five modes", len(filelist.VIEW_MODES) == 5, filelist.VIEW_MODES)
for mode in filelist.VIEW_MODES:
    win.set_view_mode(mode)
    expected = win.list_view.details if mode == "details" else win.list_view.icons
    check(f"{mode} view active", win.list_view.view is expected)
    check(f"{mode} saved", SETTINGS.get("view/mode") == mode)
win.set_view_mode("large")
win.list_view.selectAll()
selected_icons = len(win.list_view.selected_items())
win.set_view_mode("details")
check("selection survives a view switch",
      len(win.list_view.selected_items()) == selected_icons and selected_icons > 0)
win.set_view_mode("nonsense")
check("a bad mode falls back to Details", win.list_view.mode == "details")

SETTINGS.set("view/row_height", "relaxed")
SETTINGS.set("view/grid_lines", True)
SETTINGS.set("view/alternate_rows", True)
win.apply_view_options()
check("row separators on", win.list_view.details.property("gridLines") == "on")
check("alternating rows on", win.list_view.details.alternatingRowColors())
check("menu checkmarks follow", win.act_grid_lines.isChecked()
      and win.act_alternate_rows.isChecked())

print("== layout")
win.set_tree_side("right")
check("tree moves right", win.splitter.indexOf(win.tree) == 1)
win.set_tree_side("left")
check("tree moves back", win.splitter.indexOf(win.tree) == 0)
SETTINGS.set("view/show_comment", True)
win.set_comment_side("top")
check("comment pane on top", win.right_splitter.indexOf(win.comment_pane) == 0)
check("and visible", win.comment_pane.isVisible())
win.set_comment_side("bottom")
check("comment pane back below", win.right_splitter.indexOf(win.comment_pane) == 1)
win.toggle_address_bar(False)
check("address bar hides", not win.address_bar.isVisible())
win.toggle_address_bar(True)
win.toggle_status_bar(False)
check("status bar hides", not win.statusBar().isVisible())
win.toggle_status_bar(True)
win.toggle_toolbar(False)
check("toolbar hides", not win.toolbar.isVisible())
win.toggle_toolbar(True)
SETTINGS.set("view/toolbar_area", "bottom")
win.apply_layout()
check("toolbar moves to the bottom",
      win.toolBarArea(win.toolbar) == Qt.ToolBarArea.BottomToolBarArea)
SETTINGS.set("view/toolbar_area", "top")
win.apply_layout()

print("== the Customize dialog")
dialog = CustomizeDialog(win)
check("three tabs", dialog.tabs.count() == 3)
check("every catalogue entry is offered",
      dialog.shown_list.count() + dialog.available_list.count()
      == len(TOOLBAR_CATALOGUE) + sum(1 for k in DEFAULT_TOOLBAR if k == "|"))
dialog.shown_list.setCurrentRow(0)
dialog._move_down()
check("move down reorders", dialog._current_items()[1] == "add",
      dialog._current_items()[:3])
dialog.shown_list.selectAll()
dialog._remove()
dialog._save()
check("an empty toolbar falls back to the default",
      SETTINGS.string_list("toolbar/items") == DEFAULT_TOOLBAR)
dialog._restore_defaults()
check("restore defaults resets the view mode", SETTINGS.get("view/mode") == "details")
dialog.close()

win.cmd_reset_layout  # exists
check("reset command present", callable(win.cmd_reset_layout))

print("== elevation")
check("methods are known", {m.key for m in elevation.METHODS}
      == {"pkexec", "sudo", "doas"})
check("root check works", elevation.is_root() == (os.geteuid() == 0))
session = elevation.Session()
check("no session yet", not session.active)
check("describe says something useful", len(session.describe()) > 20)
if elevation.available():
    built = session.command(["apt-get", "install", "rar"])
    check("command prefixes the tool",
          built is None or built[0].endswith(("pkexec", "sudo", "doas")), built)
else:
    check("no methods -> no command", session.command(["true"]) is None)
check("session expires cleanly", (session.stop(), not session.active)[1])
check("packages.privileged delegates",
      packages.privileged(["true"]) == elevation.SESSION.command(["true"]))

print("== command line actions")
from linrar import app as app_module
check("actions declared", set(app_module._ACTIONS) ==
      {"--extract-here", "--extract-to", "--add", "--test"})
check("extract_paths exists", callable(win.extract_paths))
check("test_paths exists", callable(win.test_paths))

print("== install scripts")
import shutil as _shutil
BASH = _shutil.which("bash")
for script in ("install.sh", "uninstall.sh"):
    path = os.path.join(ROOT, script)
    check(f"{script} is executable", os.access(path, os.X_OK))
    if BASH:
        check(f"{script} parses",
              subprocess.run([BASH, "-n", path], capture_output=True).returncode == 0)
        check(f"{script} has a --help",
              subprocess.run([BASH, path, "--help"], capture_output=True,
                             timeout=30).returncode == 0)
    else:
        print(f"  --  bash not on PATH, not running {script}")
text = open(os.path.join(ROOT, "install.sh")).read()
for needle in ("nautilus/scripts", "kio/servicemenus", "nemo/actions",
               "Thunar", "--extract-here", "PYTHONPATH", "install-manifest"):
    check(f"install.sh covers {needle}", needle in text)
removal = open(os.path.join(ROOT, "uninstall.sh")).read()
check("uninstall keeps the project folder",
      "rm -rf \"${APP_DIR}\"" not in removal.replace('delete it yourself', ''))
check("uninstall removes the launcher", ".local/bin/${APP_ID}" in removal)

win.close()
SETTINGS.reset("view/row_height", "view/grid_lines", "view/alternate_rows",
               "view/show_comment", "view/mode", "toolbar/items")
SETTINGS.sync()
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
