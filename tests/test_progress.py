"""The two progress bars, and extraction that leaves the window alone."""
import os, shutil, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_CONFIG = tempfile.mkdtemp(prefix="linrar-progcfg-")
os.environ["XDG_CONFIG_HOME"] = _CONFIG
os.environ["LINRAR_SYSTEM_CONFIG"] = ""

from linrar.core.backends.base import TaskContext
from linrar.core.process import parse_file_line

PASS = FAIL = 0
def check(name, cond, extra=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ok  {name}")
    else: FAIL += 1; print(f"FAIL  {name}  {extra}")


def recorder():
    """A context that records everything it is told, for inspection."""
    log = {"files": [], "file_pct": [], "total_pct": [], "stats": []}
    ctx = TaskContext(
        on_file=log["files"].append,
        on_percent=log["file_pct"].append,
        on_total=log["total_pct"].append,
        on_stats=lambda *args: log["stats"].append(args),
    )
    return ctx, log


print("== rar's output is prose as well as progress")
check("a member line is a member",
      parse_file_line("Extracting  photos/a.jpg     OK") ==
      ("Extracting", "photos/a.jpg"))
check("the archive header is not a member",
      parse_file_line("Extracting from /tmp/backup.rar") is None,
      parse_file_line("Extracting from /tmp/backup.rar"))
check("nor is any single-spaced prose",
      parse_file_line("Extracting whatever") is None)
check("a percentage glued to a long name is not part of it",
      parse_file_line("Extracting  a/very/long/path/name.bin 100%") ==
      ("Extracting", "a/very/long/path/name.bin"))
check("neither is a tight OK",
      parse_file_line("Extracting  a/very/long/path/name.bin OK") ==
      ("Extracting", "a/very/long/path/name.bin"))
check("nor a tight Failed",
      parse_file_line("Extracting  some/file.bin Failed") ==
      ("Extracting", "some/file.bin"))
check("padding still works", parse_file_line("Adding    photos/a.jpg") ==
      ("Adding", "photos/a.jpg"))

print("== the overall bar is weighted by bytes, not by file count")
ctx, log = recorder()
# One large member among small ones: counting files would claim three quarters
# done before the large one has started.
ctx.plan({"a.txt": 10, "b.txt": 10, "c.txt": 10, "big.bin": 970})
check("the plan totals the bytes", ctx.total_bytes == 1000, ctx.total_bytes)
check("and counts the members", ctx.total_items == 4, ctx.total_items)

for name in ("a.txt", "b.txt", "c.txt"):
    ctx.start_file(name)
    ctx.advance(100)
after_small = log["total_pct"][-1]
check("three small files of four are only 3% of the work",
      after_small == 3, after_small)
ctx.start_file("big.bin")
ctx.advance(50)
check("half of the large one is about half the work",
      48 <= log["total_pct"][-1] <= 52, log["total_pct"][-1])
check("the file bar shows the file, not the job", log["file_pct"][-1] == 50)
ctx.advance(100)
check("and the job finishes with it", log["total_pct"][-1] == 100)

print("== the two bars are genuinely different")
ctx, log = recorder()
ctx.plan({f"part{i}.bin": 1000 for i in range(4)})
pairs = []
for i in range(4):
    ctx.start_file(f"part{i}.bin")
    for pct in (25, 50, 75, 100):
        ctx.advance(pct)
        pairs.append((log["file_pct"][-1], log["total_pct"][-1]))
different = sum(1 for f, t in pairs if f != t)
check("they disagree most of the time", different >= len(pairs) - 4,
      pairs)
check("the file bar returns to the start of each file",
      log["file_pct"].count(25) == 4, log["file_pct"])
check("the total bar only ever climbs",
      all(b >= a for a, b in zip(log["total_pct"], log["total_pct"][1:])),
      log["total_pct"])

print("== the total bar never retreats, even when rar's does")
ctx, log = recorder()
ctx.plan({"one.bin": 100})
ctx.start_file("one.bin")
ctx.advance(80)
ctx.advance(20)          # rar makes a second pass over some files
check("a backwards file percentage is reported as such",
      log["file_pct"][-1] == 20)
check("but the total holds its ground", log["total_pct"][-1] == 80,
      log["total_pct"])

print("== counters for the window")
ctx, log = recorder()
ctx.plan({"a": 100, "b": 300})
ctx.start_file("a")
ctx.advance(100)
ctx.start_file("b")
ctx.advance(50)
files_done, files_total, bytes_done, bytes_total = log["stats"][-1]
check("files are counted", (files_done, files_total) == (2, 2),
      (files_done, files_total))
check("bytes are counted", (bytes_done, bytes_total) == (250, 400),
      (bytes_done, bytes_total))
ctx.finish()
check("finishing fills both bars",
      log["file_pct"][-1] == 100 and log["total_pct"][-1] == 100)

print("== names are matched however the tool spells them")
ctx, _log = recorder()
ctx.plan({"src/photo.jpg": 500, "src/deep/notes.txt": 20})
check("exact name", ctx.size_of("src/photo.jpg") == 500)
check("the destination prefix unrar prints",
      ctx.size_of("/tmp/out/src/photo.jpg") == 500)
check("a backslash spelling", ctx.size_of("src\\photo.jpg") == 500)
check("a flattened name still resolves by basename",
      ctx.size_of("photo.jpg") == 500)
check("a nested member", ctx.size_of("/tmp/out/src/deep/notes.txt") == 20)
check("something not in the plan", ctx.size_of("stranger.bin") == 0)

print("== with no plan at all, the bars still behave")
ctx, log = recorder()
ctx.total_items = 4
ctx.start_file("a")
ctx.advance(100)
check("count weighting takes over", log["total_pct"][-1] == 25,
      log["total_pct"])
ctx, log = recorder()
ctx.start_file("a")
ctx.advance(42)
check("and with nothing known the file's own figure is used",
      log["total_pct"][-1] == 42)

print("== 7-Zip reports the whole job, and the file is derived from it")
ctx, log = recorder()
ctx.plan({"a.bin": 500, "b.bin": 500})
ctx.start_file("a.bin")
ctx.set_overall(25)
check("the total bar takes the figure", log["total_pct"][-1] == 25)
check("the file bar is worked back out", log["file_pct"][-1] == 50,
      log["file_pct"])
ctx.start_file("b.bin")
ctx.set_overall(75)
check("and again for the next member", log["file_pct"][-1] == 50,
      log["file_pct"])

print("== a second phase starts its own count")
ctx, log = recorder()
ctx.plan({"a": 100})
ctx.start_file("a")
ctx.advance(100)
check("the first phase finishes", log["total_pct"][-1] == 100)
ctx.reset_progress("Wrapping")
check("the bars go back to nothing", log["total_pct"][-1] == 0)
check("and the phase names itself", log["files"][-1] == "Wrapping")
ctx.plan({"b": 100})
ctx.start_file("b")
ctx.advance(50)
check("the second phase counts on its own", log["total_pct"][-1] == 50,
      log["total_pct"])

print("== extraction leaves the window where it was")
from PyQt6.QtWidgets import QApplication, QMessageBox

app = QApplication([])
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)

import shutil as _shutil
if not _shutil.which("rar"):
    print("  --  rar not installed, skipping the extraction checks")
else:
    from linrar.core.backends.rar import RarBackend
    from linrar.core.models import CompressOptions
    from linrar.ui.main_window import MainWindow

    root = os.path.realpath(tempfile.mkdtemp(prefix="linrar-prog-"))
    src = os.path.join(root, "src")
    os.makedirs(src)
    for name in ("one.txt", "two.txt"):
        with open(os.path.join(src, name), "w") as handle:
            handle.write(name * 200)
    archive = os.path.join(root, "pack.rar")
    RarBackend().create(
        [os.path.join(src, n) for n in ("one.txt", "two.txt")],
        CompressOptions(archive_path=archive, base_folder=src),
    )

    window = MainWindow()
    window.navigate_to(root)
    folder, title, back = window.current_folder, window.windowTitle(), list(window._back)

    check("a whole archive extracts", window.extract_archive(archive, False))
    check("the browser has not moved", window.current_folder == folder)
    check("the archive was never opened", not window.in_archive)
    check("the title is untouched", window.windowTitle() == title)
    check("Back was not given a step to undo", window._back == back)
    check("the files are beside the archive",
          os.path.isfile(os.path.join(root, "one.txt")) and
          os.path.isfile(os.path.join(root, "two.txt")))

    for name in ("one.txt", "two.txt"):
        os.unlink(os.path.join(root, name))
    window.extract_paths([archive], ask_options=False)
    check("the file-manager entry point stays put too",
          not window.in_archive and window.current_folder == folder)
    check("and the listing shows what arrived",
          "one.txt" in [item.name for item in window.model.items])

    window.test_paths([archive])
    check("testing does not open it either", not window.in_archive)

    check("reading an archive reports what it found",
          window.read_archive(archive) is not None)
    backend, info, password, resolved = window.read_archive(archive)
    check("and hands back the path it really used", resolved == archive)
    check("with the listing", len(info.entries) == 2, len(info.entries))

    window.close()
    shutil.rmtree(root, ignore_errors=True)

shutil.rmtree(_CONFIG, ignore_errors=True)
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
