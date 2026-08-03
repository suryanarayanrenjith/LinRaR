"""Find: the name mask, and the text search behind the "Text to find" box.

The text box existed long before anything read it — the dialog collected the
string and the window filtered on the *name* mask alone, so typing text and
pressing Find quietly did nothing.  These checks cover the search that now
stands behind it, on disk and inside an archive, plus the results window.
"""
import os
import shutil
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SCRATCH = tempfile.mkdtemp(prefix="linrar-find-conf-")
os.environ["XDG_CONFIG_HOME"] = SCRATCH
os.environ["LINRAR_SYSTEM_CONFIG"] = ""

from PyQt6.QtWidgets import QApplication

app = QApplication([])

from linrar.core import search
from linrar.core.models import ArchiveEntry, ArchiveInfo, ExtractOptions
from linrar.ui.dialogs.misc import FindDialog
from linrar.ui.dialogs.search import SearchResultsDialog, result_summary

PASS = FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f"FAIL  {name}  {extra}")


root = tempfile.mkdtemp(prefix="linrar-find-")
os.makedirs(os.path.join(root, "deep", "deeper"))
os.makedirs(os.path.join(root, ".hidden"))


def write(relative, text, encoding="utf-8"):
    path = os.path.join(root, relative)
    with open(path, "wb") as handle:
        handle.write(text.encode(encoding))
    return path


write("top.txt", "alpha beta\nnothing\nALPHA again\n")
write("other.log", "alpha lives here too\n")
write("deep/mid.txt", "no match\n")
write("deep/deeper/bottom.txt", "the alpha at the bottom\n")
write("wide.txt", "alpha in utf-16\n", "utf-16-le")
write(".hidden/secret.txt", "alpha hiding\n")
with open(os.path.join(root, "blob.bin"), "wb") as handle:
    handle.write(b"\x00\x01alpha\x02\x00")

print("== the query itself")
q = search.SearchQuery(mask="*.TXT")
check("a mask is case-blind by default", q.matches_name("top.txt"))
check("and case-exact when asked",
      not search.SearchQuery(mask="*.TXT", case_sensitive=True)
      .matches_name("top.txt"))
check("an empty text means 'filter by name'",
      not search.SearchQuery(mask="*").wants_text)
check("and any text means 'read the files'",
      search.SearchQuery(mask="*", text="a").wants_text)

print("== searching a folder")
found = search.search_folder(
    root, search.SearchQuery(mask="*.txt", text="alpha", recurse=True)
)
names = sorted({m.name for m in found.matches})
check("every matching file is found, at any depth",
      names == ["deep/deeper/bottom.txt", "top.txt", "wide.txt"], names)
check("a file that does not match the mask is never read",
      "other.log" not in names, names)
check("each occurrence is its own result",
      sum(1 for m in found.matches if m.name == "top.txt") == 2,
      [m.line_number for m in found.matches if m.name == "top.txt"])
check("with the line number the eye needs",
      sorted(m.line_number for m in found.matches if m.name == "top.txt")
      == [1, 3])
check("and the line itself",
      any(m.line == "alpha beta" for m in found.matches),
      [m.line for m in found.matches])
check("dot directories are left alone",
      not any(".hidden" in m.name for m in found.matches), names)
check("the count of files read is reported — including the ones with no hit",
      found.searched == 4, found.searched)

shallow = search.search_folder(
    root, search.SearchQuery(mask="*.txt", text="alpha", recurse=False)
)
check("'look in subfolders' off really stops at the top",
      sorted({m.name for m in shallow.matches}) == ["top.txt", "wide.txt"],
      sorted({m.name for m in shallow.matches}))

exact = search.search_folder(
    root,
    search.SearchQuery(mask="*.txt", text="ALPHA", case_sensitive=True,
                       recurse=True),
)
check("a case-sensitive search matches only that case",
      [(m.name, m.line_number) for m in exact.matches] == [("top.txt", 3)],
      [(m.name, m.line_number) for m in exact.matches])

nothing = search.search_folder(
    root, search.SearchQuery(mask="*.txt", text="nowhere at all", recurse=True)
)
check("text that is not there finds nothing", nothing.matches == [])
check("but still says how hard it looked", nothing.searched == 4, nothing.searched)

print("== the awkward files")
wide = [m for m in found.matches if m.name == "wide.txt"]
check("UTF-16 without a byte order mark is searched as text",
      wide and wide[0].line_number == 1, wide)
check("and the line comes back readable",
      wide and "alpha in utf-16" in wide[0].line, wide)

binary = search.search_folder(root, search.SearchQuery(mask="*.bin", text="alpha"))
check("a binary file that holds the bytes is reported",
      len(binary.matches) == 1, binary.matches)

names_only = search.search_folder(root, search.SearchQuery(mask="*.log", text=""))
check("no text means the names alone answer",
      [m.name for m in names_only.matches] == ["other.log"],
      names_only.matches)

huge = os.path.join(root, "huge.txt")
with open(huge, "wb") as handle:
    handle.seek(search.MAX_FILE + 1)
    handle.write(b"\0")
oversize = search.search_folder(root, search.SearchQuery(mask="huge.txt", text="a"))
check("a file too big to search says so rather than being skipped silently",
      len(oversize.matches) == 1 and oversize.matches[0].skipped,
      oversize.matches)
check("and is not counted as a result",
      oversize.found_names == [], oversize.found_names)
os.unlink(huge)

print("== searching an archive")
info = ArchiveInfo(
    path="/tmp/pretend.rar",
    entries=[
        ArchiveEntry(name="top.txt", size=30),
        ArchiveEntry(name="deep/deeper/bottom.txt", size=24),
        ArchiveEntry(name="other.log", size=21),
        ArchiveEntry(name="deep", is_dir=True),
    ],
)


class FakeBackend:
    """Stands in for a real archive tool: copies the fixture files across."""

    def __init__(self):
        self.asked = None

    def extract(self, path, options: ExtractOptions, ctx=None):
        self.asked = list(options.members)
        for member in options.members:
            target = os.path.join(options.destination, member)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copyfile(os.path.join(root, member), target)


backend = FakeBackend()
archived = search.search_archive(
    "/tmp/pretend.rar", backend, info,
    search.SearchQuery(mask="*.txt", text="alpha"),
)
check("only the members whose names match are unpacked",
      sorted(backend.asked) == ["deep/deeper/bottom.txt", "top.txt"],
      backend.asked)
check("the folder entry is never asked for",
      "deep" not in (backend.asked or []), backend.asked)
check("hits carry the member name, not a temporary path",
      sorted({m.name for m in archived.matches})
      == ["deep/deeper/bottom.txt", "top.txt"],
      [m.name for m in archived.matches])
check("and no path into a folder that has already been deleted",
      all(m.path == "" for m in archived.matches),
      [m.path for m in archived.matches])

names_in_archive = search.search_archive(
    "/tmp/pretend.rar", FakeBackend(), info, search.SearchQuery(mask="*.log")
)
check("a name-only search over an archive unpacks nothing",
      [m.name for m in names_in_archive.matches] == ["other.log"],
      names_in_archive.matches)

print("== cancelling")
from linrar.core.backends.base import TaskContext

ctx = TaskContext()
ctx.cancel()
stopped = search.search_folder(
    root, search.SearchQuery(mask="*", text="alpha", recurse=True), ctx
)
check("a cancelled search stops", stopped.cancelled is True)
check("and says its list is partial", stopped.matches == [])

print("== the Find dialog")
dialog = FindDialog(None, in_archive=False)
dialog.mask_edit.setText("*.py")
dialog.text_edit.setText("import")
dialog.case_check.setChecked(True)
dialog.recurse_check.setChecked(True)
query = dialog.query()
check("the dialog hands over everything it collected",
      (query.mask, query.text, query.case_sensitive, query.recurse)
      == ("*.py", "import", True, True), query)
check("it explains that it will read the files",
      "lists every line" in dialog.scope_label.text(), dialog.scope_label.text())
dialog.text_edit.setText("")
check("and explains the filter when there is no text",
      "Filters the list" in dialog.scope_label.text(), dialog.scope_label.text())

in_archive = FindDialog(None, in_archive=True)
check("subfolders cannot be switched off inside an archive",
      not in_archive.recurse_check.isEnabled())
check("because the whole archive is always searched",
      in_archive.recurse_check.isChecked())

print("== the results window")
result = search.SearchResult(
    matches=[
        search.Match(name="a.txt", line_number=2, line="one"),
        search.Match(name="a.txt", line_number=7, line="two"),
        search.Match(name="b.txt", skipped="could not be read"),
    ],
    searched=9,
)
query = search.SearchQuery(mask="*", text="one")
window = SearchResultsDialog(None, query, result, "the folder")
check("one row per file, not one per hit",
      window.tree.topLevelItemCount() == 2, window.tree.topLevelItemCount())
check("hits are grouped under their file",
      window.tree.topLevelItem(0).childCount() == 2)
check("the count in the caption is the number of hits",
      "(2)" in window.tree.topLevelItem(0).text(0),
      window.tree.topLevelItem(0).text(0))
emitted = []
window.goTo.connect(emitted.append)
window.tree.setCurrentItem(window.tree.topLevelItem(0).child(1))
window._go_to_selected()
check("asking to go to a hit names its file, not the line",
      emitted == ["a.txt"], emitted)
check("a file that could not be read is not counted as a find",
      result.found_names == ["a.txt"], result.found_names)
check("the summary counts files, not hits",
      result_summary(result, query) == "'one' found in 1 file(s)",
      result_summary(result, query))
empty = search.SearchResult(searched=4)
check("and says so plainly when nothing matched",
      "was not found" in result_summary(empty, query),
      result_summary(empty, query))

shutil.rmtree(root, ignore_errors=True)
shutil.rmtree(SCRATCH, ignore_errors=True)
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
