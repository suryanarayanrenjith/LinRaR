"""Headless smoke test of the main window's archive browsing and task flow."""
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtWidgets import QApplication
app = QApplication([])

from linrar.ui.main_window import MainWindow
from linrar.core.backends.rar import RarBackend
from linrar.core.models import CompressOptions, ExtractOptions, OverwriteMode

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

w.close()
import shutil; shutil.rmtree(root, ignore_errors=True)
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
