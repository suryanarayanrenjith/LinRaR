"""Bugs that were fixed, each pinned by the check that would have caught it.

Every case here is something the application really did: a column width that
was saved and then thrown away on the way back in, a compression profile that
undid the settings the dialog had just restored, a UTF-16 README shown as a
hex dump.  They need no archive tools, so this file always runs.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRATCH = tempfile.mkdtemp(prefix="linrar-regress-")
os.environ["XDG_CONFIG_HOME"] = SCRATCH
os.environ["LINRAR_SYSTEM_CONFIG"] = ""

from PyQt6.QtWidgets import QApplication

app = QApplication([])

from linrar.core import filetypes
from linrar.core.backends.sevenzip import SevenZipBackend
from linrar.core.profiles import DEFAULT_PROFILES, Profile, PROFILES
from linrar.core.settings import SETTINGS, Settings
from linrar.ui import filelist
from linrar.ui.dialogs.archive import ArchiveDialog
from linrar.ui.dialogs.customize import _ICONS
from linrar.ui.main_window import TOOLBAR_CATALOGUE, MainWindow, _shorten_path

PASS = FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f"FAIL  {name}  {extra}")


print("== column widths survive a restart")
# configure_columns applied its factory widths the first time a listing was
# built, and the first listing is built *after* the saved header state is
# restored — so the widths the user chose were overwritten on every launch.
window = MainWindow()
window.list_view.details.setColumnWidth(filelist.COL_NAME, 417)
SETTINGS.save_geometry("columns", window.list_view.header_state())
SETTINGS.sync()
again = MainWindow()
check("a width chosen by the user comes back",
      again.list_view.details.columnWidth(filelist.COL_NAME) == 417,
      again.list_view.details.columnWidth(filelist.COL_NAME))

print("== resetting the interface really resets the columns")
# QHeaderView.reset() is the model-reset slot and does nothing to section
# sizes, so "Reset the interface" used to leave the widths exactly as they were.
again.list_view.details.setColumnWidth(filelist.COL_NAME, 500)
again.list_view.reset_columns()
check("the name column goes back to its shipped width",
      again.list_view.details.columnWidth(filelist.COL_NAME)
      == dict(filelist.DEFAULT_COLUMN_WIDTHS)[filelist.COL_NAME],
      again.list_view.details.columnWidth(filelist.COL_NAME))
header = again.list_view.details.header()
check("and the columns go back to their shipped order",
      [header.visualIndex(i) for i in range(header.count())]
      == list(range(header.count())))
check("every column has a default to go back to",
      len(filelist.DEFAULT_COLUMN_WIDTHS) == len(filelist.HEADERS))

print("== recently opened archives")
store = Settings(os.path.join(SCRATCH, "recent.conf"))
store.push_recent("/tmp/one.rar")
store.push_recent("/tmp/two.rar")
store.push_recent("/tmp/one.rar")
check("the newest is first", store.recent()[0] == "/tmp/one.rar", store.recent())
check("and is not listed twice", store.recent().count("/tmp/one.rar") == 1,
      store.recent())
for index in range(20):
    store.push_recent(f"/tmp/fill{index}.rar")
check("the list is bounded", len(store.recent()) <= 12, len(store.recent()))
store.sync()
check("and survives a restart — in a second process, never one",
      Settings(store.path).recent() == store.recent())
check("recent archives are kept apart from the folder history",
      "/tmp/one.rar" not in store.history(), store.history())

print("== the default profile no longer undoes the remembered settings")
# cmd_add applied PROFILES.default() over the dialog, and the profile LinRAR
# ships as "Default" holds nothing but the factory values -- so changing the
# compression method, making an archive and opening the dialog again put the
# method straight back to Normal.
PROFILES.save(PROFILES.builtin())
check("an untouched built-in default is not applied over anything",
      PROFILES.chosen_default() is None, PROFILES.chosen_default())
check("but the profile itself is still there to be chosen",
      PROFILES.default().name == "Default")
configured = Profile(**{**PROFILES.default().__dict__, "solid": True})
PROFILES.upsert(configured)
PROFILES.set_default("Default")
check("a default the user actually configured is applied",
      PROFILES.chosen_default() is not None
      and PROFILES.chosen_default().solid)
PROFILES.set_default("Fastest")
check("and so is a different profile marked as the default",
      (PROFILES.chosen_default() or Profile(name="?")).name == "Fastest",
      PROFILES.chosen_default())

print("== a profile file from another version is not thrown away")
mixed = json.dumps([
    {"name": "From the future", "method": 5, "some_new_key": "ignored"},
    {"name": "Fine", "method": 1},
    {"no name": "at all"},
])
SETTINGS.set(PROFILES.KEY, mixed)
names = [p.name for p in PROFILES.load()]
check("keys this version does not know about are skipped, not fatal",
      "From the future" in names and "Fine" in names, names)
check("and the settings it does know about survive",
      PROFILES.get("From the future").method == 5)
check("an entry with no name is dropped", len(names) == 2, names)
SETTINGS.set(PROFILES.KEY, "{not json at all")
check("and unreadable JSON falls back to the built-ins",
      [p.name for p in PROFILES.load()]
      == [p.name for p in DEFAULT_PROFILES])
SETTINGS.set(PROFILES.KEY, "")

print("== UTF-16 text is text")
# decode() tried UTF-8 first, and UTF-8 accepts NUL bytes happily, so a
# BOM-less UTF-16 file came back as "h\\x00e\\x00l\\x00l\\x00o" -- unreadable
# in the viewer and unsearchable.
wide = "Hello, world\nsecond line\n".encode("utf-16-le")
check("it is recognised without a byte order mark",
      filetypes.looks_utf16(wide) == "utf-16-le", filetypes.looks_utf16(wide))
check("big endian too",
      filetypes.looks_utf16("Hello, world".encode("utf-16-be")) == "utf-16-be")
check("and decodes to the real text", filetypes.decode(wide).startswith("Hello, world"))
check("so the viewer shows it as text rather than hex",
      filetypes._looks_textual(wide))
check("a single stray NUL is still binary",
      not filetypes._looks_textual(b"hello\x00world"))
check("and so is a run of control bytes",
      not filetypes._looks_textual(bytes(range(0, 32)) * 10))
check("plain ASCII is not mistaken for UTF-16",
      filetypes.looks_utf16(b"hello world, this is plain text") is None)
check("nor is something too short to tell",
      filetypes.looks_utf16(b"h\x00") is None)

print("== 7z's scan warnings are read, not just its exit status")
warning = (
    "Scan WARNINGS for files and folders:\n"
    "\n"
    "missing.txt : No more files\n"
    "----------------\n"
    "Scan WARNINGS: 1\n"
)
try:
    SevenZipBackend._reject_missing_sources(warning)
    check("a scan warning is turned into an error", False, "nothing raised")
except Exception as exc:
    check("a scan warning is turned into an error", True)
    check("and names the file it could not read", "missing.txt" in str(exc), str(exc))
SevenZipBackend._reject_missing_sources("Everything is Ok\n")
check("ordinary output raises nothing", True)

print("== the Customize picker knows every toolbar button")
keys = [key for key, _attribute, _caption in TOOLBAR_CATALOGUE]
check("no button is offered without its icon",
      [k for k in keys if k not in _ICONS] == [],
      [k for k in keys if k not in _ICONS])
check("and no icon is left behind for a button that is gone",
      [k for k in _ICONS if k not in keys] == [],
      [k for k in _ICONS if k not in keys])
check("every catalogued button has a real action",
      all(hasattr(window, attribute)
          for _key, attribute, _caption in TOOLBAR_CATALOGUE),
      [a for _k, a, _c in TOOLBAR_CATALOGUE if not hasattr(window, a)])

print("== the archive dialog measures the files it is actually given")
# base_folder was fixed when the dialog opened, so files added afterwards on
# the Files tab were measured against the wrong folder and stored under "../".
work = tempfile.mkdtemp(prefix="linrar-base-")
os.makedirs(os.path.join(work, "left", "inner"))
os.makedirs(os.path.join(work, "right"))
for relative in ("left/one.txt", "left/inner/two.txt", "right/three.txt"):
    with open(os.path.join(work, relative), "w") as handle:
        handle.write("x")
dialog = ArchiveDialog(
    None,
    files=[os.path.join(work, "left", "one.txt")],
    base_folder=os.path.join(work, "left"),
    default_name=os.path.join(work, "out.rar"),
)
check("one file from the opening folder keeps that folder as the base",
      dialog.options().base_folder == os.path.join(work, "left"),
      dialog.options().base_folder)
dialog.files_list.addItem(os.path.join(work, "right", "three.txt"))
check("a file added from elsewhere widens the base to a common ancestor",
      dialog.options().base_folder == work, dialog.options().base_folder)
check("so no member is stored with a leading '..'",
      not os.path.relpath(os.path.join(work, "right", "three.txt"),
                          dialog.options().base_folder).startswith(".."))
dialog.name_edit.setText(os.path.join(work, "bare"))
check("a name with no extension gets the format's own",
      dialog.options().archive_path.endswith(".rar"),
      dialog.options().archive_path)

print("== dot files are a disk idea, not an archive one")
source = open(os.path.join(ROOT, "linrar/ui/main_window.py")).read()
body = source.split("def toggle_hidden", 1)[1].split("\n    def ", 1)[0]
check("toggling hidden files does not re-read the open archive",
      "self.refresh()" not in body, body.strip()[:160])

print("== a keyring that is not there must not swallow passwords")
# secret-tool installed with no service behind it (a headless box, a minimal
# desktop, a container, a CI runner) reports "Could not connect" on stderr and
# still exits 1 -- which is also the ordinary "nothing stored yet".  The check
# used to look for the word "cannot", which that message does not contain, so
# LinRAR believed in a keyring that was not there: every password saved went
# nowhere and came back empty, and the archive it should have opened put a
# modal prompt on screen instead.  Offscreen, that hangs forever.
from linrar.core import passwords as passwords_module

store = passwords_module.PasswordStore()
store.save([passwords_module.PasswordEntry(
    label="probe", mask="probe*.rar", password="Sekret1")])
check("a saved password reads back whatever it was stored in",
      [e.password for e in store.load()] == ["Sekret1"],
      f"backend={store.backend_name} failure={store.failure!r}")
check("and is offered for an archive its mask fits",
      store.candidates_for("probe1.rar") == ["Sekret1"],
      store.candidates_for("probe1.rar"))
check("but not for one it does not",
      store.candidates_for("other.rar") == [], store.candidates_for("other.rar"))

# A keyring that accepts a write and then holds nothing is the failure that
# actually happened.  Forced here, because it cannot be arranged for real.
broken = passwords_module.PasswordStore()
broken._use_keyring = True
broken._keyring_set = lambda label, password: False
broken._keyring_get = lambda label: None
broken._keyring_delete = lambda label: None
broken.save([passwords_module.PasswordEntry(
    label="probe", mask="*", password="Fallback9")])
check("a keyring that refuses the write demotes the store",
      not broken.secure, broken.backend_name)
check("rather than losing the password",
      [e.password for e in broken.load()] == ["Fallback9"],
      [e.password for e in broken.load()])
check("and says so, instead of quietly changing its mind",
      "kept in LinRAR's own file" in broken.failure, broken.failure)

recovered = passwords_module.PasswordStore()
recovered._use_keyring = True
recovered._keyring_get = lambda label: None
check("a keyring with nothing in it falls back to the local copy",
      [e.password for e in recovered.load()] == ["Fallback9"],
      [e.password for e in recovered.load()])

check("the service probe is a name no dialog can produce",
      passwords_module._PROBE.strip() != passwords_module._PROBE,
      passwords_module._PROBE)
check("and it has no NUL byte, which argv cannot carry",
      "\x00" not in passwords_module._PROBE)

print("== the runner cannot be hung by one file")
runner = open(os.path.join(ROOT, "tests/run_all.py")).read()
check("every test file runs under a timeout", "timeout=TIMEOUT" in runner)
check("a hang is reported rather than waited on", "TimeoutExpired" in runner)
check("and named, so the file to blame is obvious", "TIMED OUT" in runner)
check("the limit can be lowered from the environment",
      "LINRAR_TEST_TIMEOUT" in runner)

print("== paths shown in a menu stay short")
long_path = os.path.expanduser("~/") + "/".join(["a-fairly-long-folder"] * 5) \
    + "/archive.rar"
shown = _shorten_path(long_path)
check("a long path is elided", len(shown) <= 58, (len(shown), shown))
check("but the file name survives", shown.endswith("archive.rar"), shown)
check("and home is written as ~", _shorten_path(os.path.expanduser("~/a.rar"))
      == "~/a.rar", _shorten_path(os.path.expanduser("~/a.rar")))
check("a short path is left alone", _shorten_path("/tmp/a.rar") == "/tmp/a.rar")

shutil.rmtree(work, ignore_errors=True)
shutil.rmtree(SCRATCH, ignore_errors=True)
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
