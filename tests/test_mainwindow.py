"""Headless smoke test of the main window's archive browsing and task flow."""
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# A scratch config: this file writes to the recent-archives list and the saved
# password store, and neither belongs in the real one.
_CONF = tempfile.mkdtemp(prefix="linrar-mw-conf-")
os.environ["XDG_CONFIG_HOME"] = _CONF
os.environ["LINRAR_SYSTEM_CONFIG"] = ""

from PyQt6.QtWidgets import QApplication
app = QApplication([])

from linrar.ui.main_window import MainWindow, _StoredPasswords
from linrar.core.backends.rar import RarBackend
from linrar.core.models import CompressOptions, ExtractOptions, OverwriteMode
from linrar.core.passwords import PASSWORDS, PasswordEntry
from linrar.core.settings import SETTINGS

PASS = FAIL = 0
def check(name, cond, extra=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ok  {name}")
    else: FAIL += 1; print(f"FAIL  {name}  {extra}")

root = tempfile.mkdtemp(prefix="linrar-mw-")
src = os.path.join(root, "files"); os.makedirs(src)
open(f"{src}/one.txt", "w").write("1")
os.makedirs(f"{src}/inner")
open(f"{src}/inner/two.txt", "w").write("2")

rar = RarBackend()
arc = f"{root}/browse.rar"
rar.create([f"{src}/one.txt", f"{src}/inner"],
           CompressOptions(archive_path=arc, base_folder=src))

w = MainWindow()

# navigation
w.navigate_to(root)
check("navigate_to", w.current_folder == root)
names = [i.name for i in w.model.items if not i.is_parent]
check("listing shows archive + folder", "browse.rar" in names and "files" in names, names)

# open the archive
check("open_archive returns True", w.open_archive(arc))
check("in_archive", w.in_archive)
names = [i.name for i in w.model.items if not i.is_parent]
check("root level entries", sorted(names) == ["inner", "one.txt"], names)

# enter a folder inside the archive
w.enter_archive_folder("inner")
names = [i.name for i in w.model.items if not i.is_parent]
check("inner entries", names == ["two.txt"], names)

# go up inside archive
w.go_up()
check("go_up to archive root", w.archive_folder == "")
w.go_up()
check("go_up leaves archive", not w.in_archive)

# _expand_selection folds folders into member lists
w.open_archive(arc)
class FakeItem:
    def __init__(self, path, is_dir): self.path, self.is_dir = path, is_dir
members = w._expand_selection([FakeItem("inner", True)])
check("expand folder selection", members == ["inner", "inner/two.txt"], members)

# _resolve_overwrites: no conflicts -> silently switches to overwrite
opts = ExtractOptions(destination=os.path.join(root, "fresh"),
                      overwrite_mode=OverwriteMode.ASK)
resolved = w._resolve_overwrites(w.archive_info, opts)
check("no-conflict resolve", resolved is not None
      and resolved.overwrite_mode is OverwriteMode.OVERWRITE)

# _run_task executes work on a thread and returns the result
def work(ctx):
    ctx.on_total(100)
    return "result!"
ok, result, error = w._run_task(work, "Smoke task")
check("_run_task success", ok is True and result == "result!" and error is None,
      (ok, result, error))

# _run_task surfaces OperationError
from linrar.core.models import OperationError
def bad(ctx):
    raise OperationError("boom")
ok, result, error = w._run_task(bad, "Failing task")
check("_run_task failure", ok is False and error is not None and error.message == "boom")

# archive rename pairs building (folder rename must include children)
w.close_archive()
w.open_archive(arc)
check("archive info present", w.archive_info is not None)

# -- saved passwords actually unlock things -----------------------------
# Tools > Organize passwords could always store a password; nothing ever read
# one back, so an archive it would have opened still stopped and asked.
print("== saved passwords")
locked = f"{root}/locked.rar"
rar.create([f"{src}/one.txt"], CompressOptions(
    archive_path=locked, base_folder=src,
    password="Sekret1", encrypt_headers=True))
PASSWORDS.save([PasswordEntry(label="suite", mask="locked*.rar",
                              password="Sekret1")])
check("the store offers a password whose mask fits",
      PASSWORDS.candidates_for("locked.rar") == ["Sekret1"],
      PASSWORDS.candidates_for("locked.rar"))
check("and none whose mask does not",
      PASSWORDS.candidates_for("something-else.rar") == [],
      PASSWORDS.candidates_for("something-else.rar"))

w.password = None
result = w.read_archive(locked)
check("a header-encrypted archive opens without asking",
      result is not None, "read_archive returned None (it would have prompted)")
if result is not None:
    _backend, info, used, _path = result
    check("with the saved password", used == "Sekret1", used)
    check("and its contents really are readable",
          [e.name for e in info.entries] == ["one.txt"],
          [e.name for e in info.entries])

queue = _StoredPasswords(locked)
check("each saved password is offered once", queue.next_after(None) == "Sekret1")
check("and then the user is asked", queue.next_after("Sekret1") is None)
check("a password that has just failed is not offered again",
      _StoredPasswords(locked).next_after("Sekret1") is None)
check("nothing is offered for an archive with no saved password",
      _StoredPasswords(f"{root}/browse.rar").next_after(None) is None)

# The awkward case: contents encrypted, headers not.  Listing works with no
# password at all, so the demand only arrives at extraction time -- and the
# extraction path is reached without the archive ever being opened.
sealed_src = os.path.join(root, "sealed-src")
os.makedirs(sealed_src)
open(f"{sealed_src}/payload.txt", "w").write("top secret")
sealed = f"{root}/sealed.rar"
rar.create([f"{sealed_src}/payload.txt"], CompressOptions(
    archive_path=sealed, base_folder=sealed_src, password="Sekret1"))
PASSWORDS.save([PasswordEntry(label="suite", mask="sealed*.rar",
                              password="Sekret1")])
from linrar.ui.dialogs import password as password_dialog
_asked = []
_real_ask = password_dialog.PasswordDialog.ask
password_dialog.PasswordDialog.ask = staticmethod(
    lambda *a, **k: _asked.append(a) or None
)
w.close_archive()
w.password = None
w.navigate_to(root)
extracted = w.extract_archive(sealed, ask_options=False)
password_dialog.PasswordDialog.ask = _real_ask
check("extracting an archive that was never opened uses the saved password",
      extracted and not _asked, (extracted, len(_asked)))
check("and the files really arrive", os.path.isfile(f"{root}/payload.txt"))
check("with the right contents",
      os.path.isfile(f"{root}/payload.txt")
      and open(f"{root}/payload.txt").read() == "top secret")
PASSWORDS.save([])

# -- recently opened archives -------------------------------------------
print("== recent archives")
w.open_archive(arc)
check("opening an archive remembers it", arc in SETTINGS.recent(), SETTINGS.recent())
check("and the menu lists it",
      any(os.path.basename(arc) in a.text() for a in w.recent_menu.actions()),
      [a.text() for a in w.recent_menu.actions()])
w._clear_recent()
check("clearing empties the list", SETTINGS.recent() == [], SETTINGS.recent())
check("and the menu says so rather than going blank",
      any("No archives" in a.text() for a in w.recent_menu.actions()),
      [a.text() for a in w.recent_menu.actions()])

# -- free space ----------------------------------------------------------
w.navigate_to(root)
check("the status bar reports the free space", "free" in w.space_label.text(),
      w.space_label.text())
check("and names the filesystem in its tooltip",
      "% used" in w.space_label.toolTip(), w.space_label.toolTip())

w.close()
import shutil; shutil.rmtree(root, ignore_errors=True)
shutil.rmtree(_CONF, ignore_errors=True)
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
