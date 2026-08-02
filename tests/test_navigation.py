"""Browsing: Back and Forward, the cursor, the tree, and refusing gracefully."""
import os, shutil, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# A scratch configuration, so a developer's own settings are neither read nor
# written by the test.
_CONFIG = tempfile.mkdtemp(prefix="linrar-navcfg-")
os.environ["XDG_CONFIG_HOME"] = _CONFIG
os.environ["LINRAR_SYSTEM_CONFIG"] = ""

from PyQt6.QtWidgets import QApplication
app = QApplication([])

from linrar.core.settings import SETTINGS
from linrar.ui import main_window as mw
from linrar.ui.main_window import MainWindow

PASS = FAIL = 0
def check(name, cond, extra=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ok  {name}")
    else: FAIL += 1; print(f"FAIL  {name}  {extra}")

#: Every problem the window reports, instead of a window nobody can close.
reports = []

class Recorder:
    @staticmethod
    def report(parent, problem, actions=None):
        reports.append(problem)
        return ""

mw.ProblemDialog = Recorder

root = os.path.realpath(tempfile.mkdtemp(prefix="linrar-nav-"))
alpha = os.path.join(root, "alpha")
beta = os.path.join(root, "beta")
deep = os.path.join(alpha, "deep")
os.makedirs(deep)
os.makedirs(beta)
for path, text in (
    (os.path.join(root, "notes.txt"), "a plain text file, nothing more\n"),
    (os.path.join(root, "renamed.rar"), "a plain text file, nothing more\n"),
    (os.path.join(alpha, "one.txt"), "one\n"),
):
    with open(path, "w") as handle:
        handle.write(text)

win = MainWindow()

print("== going places")
check("a fresh window has nowhere to go back to", not win.act_back.isEnabled())
check("navigate_to reports success", win.navigate_to(root) is True)
check("and lands there", win.current_folder == root)
listed = [i.name for i in win.model.items if not i.is_parent]
check("the folder is listed", {"alpha", "beta", "notes.txt"} <= set(listed), listed)

win.navigate_to(alpha)
check("Back becomes available", win.act_back.isEnabled())
check("Back names where it goes", root in win.act_back.toolTip(),
      win.act_back.toolTip())
check("Forward stays unavailable", not win.act_forward.isEnabled())

win.go_back()
check("Back returns to the parent", win.current_folder == root)
check("Forward becomes available", win.act_forward.isEnabled())
win.go_forward()
check("Forward returns again", win.current_folder == alpha)

print("== the cursor follows the eye")
win.go_up()
check("Up leaves the folder", win.current_folder == root)
check("and selects the folder just left",
      [i.name for i in win.list_view.selected_items()] == ["alpha"],
      [i.name for i in win.list_view.selected_items()])

win.navigate_to(beta)
win.go_back()
check("stepping back restores the remembered row",
      [i.name for i in win.list_view.selected_items()] == ["alpha"],
      [i.name for i in win.list_view.selected_items()])

print("== archives are a place too")
win.navigate_to(root)
depth = len(win._back)
import subprocess, shutil as _shutil
if _shutil.which("rar"):
    archive = os.path.join(root, "browse.rar")
    subprocess.run(["rar", "a", "-idq", archive, os.path.join(alpha, "one.txt")],
                   check=True, capture_output=True)
    win.navigate_to(root)
    check("an archive opens", win.open_archive(archive) is True)
    check("opening it counts as a step", len(win._back) == depth + 1)
    win.close_archive()
    check("closing returns to the folder", win.current_folder == root)
    check("and does not leave a repeat on the Back stack",
          len(win._back) == depth, win._back[-2:])
    check("the archive is selected on the way out",
          [i.name for i in win.list_view.selected_items()] == ["browse.rar"],
          [i.name for i in win.list_view.selected_items()])
    win.open_archive(archive)
    win.go_back()
    check("Back leaves an archive", not win.in_archive and
          win.current_folder == root)
else:
    print("  --  rar not installed, skipping the archive navigation checks")

print("== the top of the tree")
win.navigate_to("/")
check("/ can be listed", win.current_folder == "/")
check("Up is disabled at the root", not win.act_up.isEnabled())
win.navigate_to(root)
check("Up is enabled again", win.act_up.isEnabled())

print("== the folder tree survives navigation")
win.tree.reveal(deep)
branches = win.tree.topLevelItemCount()
win.navigate_to(beta)
check("the tree is not rebuilt on every step",
      win.tree.topLevelItemCount() == branches)
check("the tree reloads a branch on demand",
      win.tree.reload(root) is None)

print("== history reaches the address bar")
history = SETTINGS.history()
check("visited folders are remembered", root in history, history[:4])
check("the newest is first", history[0] == beta, history[:2])

print("== F5")
win.navigate_to(root)
win._filter = lambda item: item.name == "nothing-matches-this"
win._populate_filesystem()
check("a filter empties the listing",
      len([i for i in win.model.items if not i.is_parent]) == 0)
win.refresh()
check("F5 clears the filter",
      len([i for i in win.model.items if not i.is_parent]) > 0)
check("and the filter is really gone", win._filter is None)

print("== refusing, with an explanation")
before = len(reports)
check("a missing folder is refused",
      win.navigate_to(os.path.join(root, "no-such-folder")) is False)
check("and reported", len(reports) == before + 1 and reports[-1].kind == "missing",
      reports[-1].kind if reports else None)
check("the window stays where it was", win.current_folder == root)

before = len(reports)
check("a text file named .rar is refused",
      win.open_archive(os.path.join(root, "renamed.rar")) is False)
check("and reported as not an archive",
      len(reports) == before + 1 and reports[-1].kind == "not-archive",
      reports[-1].kind if reports else None)
check("the report says what it really is",
      "plain text" in reports[-1].explanation, reports[-1].explanation)
check("the window is still browsing", not win.in_archive)

before = len(reports)
check("a missing file is refused",
      win.open_archive(os.path.join(root, "gone.rar")) is False)
check("and reported as missing", reports[-1].kind == "missing")

check("a folder handed to open_archive is browsed",
      win.open_archive(alpha) is True and win.current_folder == alpha)

print("== the window can report a path on request")
before = len(reports)
win.report_path(os.path.join(root, "notes.txt"))
check("report_path is public and works",
      len(reports) == before + 1 and reports[-1].kind == "not-archive")

print("== every shortcut is unique")
from PyQt6.QtGui import QAction
seen = {}
clashes = []
for action in win.findChildren(QAction):
    for sequence in action.shortcuts():
        key = sequence.toString()
        if not key:
            continue
        if key in seen and seen[key] is not action:
            clashes.append(f"{key}: {seen[key].text()} / {action.text()}")
        seen[key] = action
check("no two actions share a shortcut", not clashes, clashes)
check("Ctrl+D is add-to-favorites",
      seen.get("Ctrl+D") is win.act_add_favorite,
      seen.get("Ctrl+D").text() if seen.get("Ctrl+D") else None)
check("Ctrl+G goes to a folder", seen.get("Ctrl+G") is win.act_change_folder)
check("Ctrl+L focuses the address bar",
      seen.get("Ctrl+L") is win.act_focus_address)
check("Alt+Left goes back", seen.get("Alt+Left") is win.act_back)

print("== one command, one place")
menus = {}
def walk(menu, path):
    for action in menu.actions():
        if action.isSeparator():
            continue
        label = action.text().replace("&", "")
        if action.menu() is not None:
            walk(action.menu(), f"{path} > {label}")
        else:
            menus.setdefault(action, []).append(f"{path} > {label}")

for entry in win.menuBar().actions():
    if entry.menu() is not None:
        walk(entry.menu(), entry.text().replace("&", ""))

repeated = {
    action.text().replace("&", ""): places
    for action, places in menus.items() if len(places) > 1
}
check("no command is offered by two menu entries", not repeated, repeated)
check("there is one SFX command, not two",
      sum(1 for a in menus if "SFX" in a.text()) == 1,
      [a.text() for a in menus if "SFX" in a.text()])
check("the retired stub command is gone", not hasattr(win, "act_sfx_stub"))
check("so is the duplicate convert action", not hasattr(win, "act_convert"))
check("Repair is only under Tools",
      menus.get(win.act_repair, []) == ["Tools > Repair archive"],
      menus.get(win.act_repair))
check("Compression profiles is only under Options",
      menus.get(win.act_profiles, []) ==
      ["Options > Compression profiles..."],
      menus.get(win.act_profiles))

print("== the SFX dialog offers both formats")
from linrar.core.sfx import APPIMAGE, RAR_STUB
from linrar.ui.dialogs.sfx import SfxDialog

sfx_dialog = SfxDialog(win, archive_path=os.path.join(root, "demo.rar"))
check("AppImage is the default", sfx_dialog.sfx_format == APPIMAGE)
check("its option pages are live", sfx_dialog.tabs.isEnabled())
sfx_dialog.stub_radio.setChecked(True)
check("the stub can be chosen", sfx_dialog.sfx_format == RAR_STUB)
check("and takes no options", not sfx_dialog.tabs.isEnabled())
sfx_dialog.appimage_radio.setChecked(True)
check("switching back restores them", sfx_dialog.tabs.isEnabled())
stub_only = SfxDialog(win, sfx_format=RAR_STUB, allow_stub=False)
check("the stub can be withheld",
      not stub_only.stub_radio.isVisible() and
      stub_only.sfx_format == APPIMAGE)
sfx_dialog.close()
stub_only.close()

print("== the toolbar can hold the new buttons")
keys = {key for key, _attribute, _caption in mw.TOOLBAR_CATALOGUE}
check("Back is offered on the toolbar", "back" in keys)
check("Forward is offered on the toolbar", "forward" in keys)
for key, attribute, _caption in mw.TOOLBAR_CATALOGUE:
    check(f"toolbar entry '{key}' has its action", hasattr(win, attribute))

win.close()
shutil.rmtree(root, ignore_errors=True)
shutil.rmtree(_CONFIG, ignore_errors=True)
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
