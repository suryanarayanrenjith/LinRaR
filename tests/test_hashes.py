"""Checksums (Ctrl+K) and dragging files out of the list.

Both are things the interface previously implied it could do and could not:
the file list had dragging switched on but published Qt's private mime type,
which no file manager understands, so a drag out of LinRAR did nothing at all.
"""
import hashlib
import os
import shutil
import sys
import tempfile
import zlib

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SCRATCH = tempfile.mkdtemp(prefix="linrar-hash-conf-")
os.environ["XDG_CONFIG_HOME"] = SCRATCH
os.environ["LINRAR_SYSTEM_CONFIG"] = ""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

app = QApplication([])

from linrar.core import hashes
from linrar.core.backends.base import TaskContext
from linrar.ui.dialogs.checksum import ChecksumDialog
from linrar.ui.filelist import FileListModel, ListingItem

PASS = FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f"FAIL  {name}  {extra}")


root = tempfile.mkdtemp(prefix="linrar-hash-")
payload = b"hello\n"
sample = os.path.join(root, "sample.txt")
with open(sample, "wb") as handle:
    handle.write(payload)
big = os.path.join(root, "big.bin")
with open(big, "wb") as handle:
    handle.write(b"x" * (hashes.CHUNK * 2 + 17))

print("== the digests themselves")
digest = hashes.digest_file(sample)
check("MD5 agrees with hashlib",
      digest.get("MD5") == hashlib.md5(payload).hexdigest(), digest.get("MD5"))
check("SHA-1 agrees with hashlib",
      digest.get("SHA-1") == hashlib.sha1(payload).hexdigest())
check("SHA-256 agrees with hashlib",
      digest.get("SHA-256") == hashlib.sha256(payload).hexdigest())
check("SHA-512 agrees with hashlib",
      digest.get("SHA-512") == hashlib.sha512(payload).hexdigest())
check("CRC32 agrees with zlib, in the upper case an archive lists it in",
      digest.get("CRC32") == f"{zlib.crc32(payload) & 0xFFFFFFFF:08X}",
      digest.get("CRC32"))
check("the size is reported too", digest.size == len(payload), digest.size)
check("and it counts as readable", digest.ok)

spanning = hashes.digest_file(big)
with open(big, "rb") as handle:
    expected = hashlib.sha256(handle.read()).hexdigest()
check("a file larger than one read still hashes correctly",
      spanning.get("SHA-256") == expected, spanning.get("SHA-256"))

missing = hashes.digest_file(os.path.join(root, "nope.txt"))
check("a file that is not there reports the reason", not missing.ok and missing.error)
check("rather than raising", isinstance(missing, hashes.FileDigest))

single = hashes.digest_file(sample, ("SHA-256",))
check("asking for one algorithm computes only that one",
      list(single.digests) == ["SHA-256"], single.digests)

print("== several files at once")
pairs = [("sample.txt", sample), ("big.bin", big)]
results = hashes.digest_files(pairs)
check("every file comes back", [r.name for r in results] == ["sample.txt", "big.bin"],
      [r.name for r in results])
check("named the way they were asked for, not by their temporary path",
      results[0].name == "sample.txt")

seen = []
ctx = TaskContext(on_file=seen.append)
hashes.digest_files(pairs, ctx=ctx)
check("progress names each file as it starts", seen == ["sample.txt", "big.bin"], seen)

cancelled = TaskContext()
cancelled.cancel()
check("a cancelled run stops immediately",
      hashes.digest_files(pairs, ctx=cancelled) == [])

print("== the output formats")
text = hashes.as_text(results, "SHA-256")
check("the sha256sum layout is exactly two spaces",
      text.splitlines()[0] == f"{results[0].get('SHA-256').lower()}  sample.txt",
      text.splitlines()[0])
check("so it can be checked with the coreutils tool",
      all(len(line.split("  ")) == 2 for line in text.splitlines()), text)
table = hashes.as_table(results, hashes.ALGORITHMS)
check("the table lists every algorithm for every file",
      all(a in table for a in hashes.ALGORITHMS), table[:80])
check("and names the files", "sample.txt" in table and "big.bin" in table)

print("== comparing with a published checksum")
sha = results[0].get("SHA-256")
check("a bare digest matches", hashes.compare(results, sha) == {"sample.txt": "SHA-256"})
check("in any case", hashes.compare(results, sha.upper()) == {"sample.txt": "SHA-256"})
check("a whole sha256sum line matches too",
      hashes.compare(results, f"{sha}  sample.txt") == {"sample.txt": "SHA-256"})
check("surrounding whitespace is ignored",
      hashes.compare(results, f"  {sha}\n") == {"sample.txt": "SHA-256"})
check("a CRC32 from an archive listing matches as well",
      hashes.compare(results, results[0].get("CRC32")) == {"sample.txt": "CRC32"})
check("something else matches nothing", hashes.compare(results, "deadbeef") == {})
check("and neither does an empty string", hashes.compare(results, "   ") == {})

print("== the checksum window")
window = ChecksumDialog(None, results)
check("one row per file", window.tree.topLevelItemCount() == 2)
check("with a child per algorithm",
      window.tree.topLevelItem(0).childCount() == len(hashes.ALGORITHMS),
      window.tree.topLevelItem(0).childCount())
window.expected_edit.setText(sha)
check("a matching paste says which file and which algorithm",
      "sample.txt (SHA-256)" in window.verdict.text(), window.verdict.text())
window.expected_edit.setText("0000")
check("and a non-matching one says so rather than staying silent",
      "No file here" in window.verdict.text(), window.verdict.text())
window.expected_edit.setText("")
check("clearing the box clears the verdict", window.verdict.text() == "")
window.format_combo.setCurrentIndex(0)
check("the default copy is the whole table",
      "SHA-512" in window._text(), window._text()[:60])
window.format_combo.setCurrentIndex(
    window.format_combo.findData("SHA-256")
)
check("and one algorithm gives the sum-file layout",
      window._text() == hashes.as_text(results, "SHA-256"))

print("== dragging out of the list")
model = FileListModel()
model.set_items(
    [
        ListingItem(name="..", path="", is_dir=True, is_parent=True),
        ListingItem(name="sample.txt", path=sample),
        ListingItem(name="big.bin", path=big),
    ],
    archive_mode=False,
)
check("the mime type is the one file managers read",
      model.mimeTypes() == ["text/uri-list"], model.mimeTypes())
rows = {model.item_at(r).name: r for r in range(model.rowCount())}
check("a real row can be dragged",
      bool(model.flags(model.index(rows["sample.txt"], 0))
           & Qt.ItemFlag.ItemIsDragEnabled))
check("the '..' row cannot",
      not (model.flags(model.index(rows[".."], 0))
           & Qt.ItemFlag.ItemIsDragEnabled))

data = model.mimeData([model.index(rows["sample.txt"], 0)])
check("dragging one row carries its file URL",
      [u.toLocalFile() for u in data.urls()] == [sample],
      [u.toLocalFile() for u in data.urls()])
check("and the hint both GNOME and KDE read",
      data.hasFormat("x-special/gnome-copied-files"))
check("which asks for a copy, not a move",
      bytes(data.data("x-special/gnome-copied-files")).startswith(b"copy\n"))

several = model.mimeData(
    [model.index(rows["sample.txt"], 0), model.index(rows["big.bin"], 0)]
)
check("dragging several rows carries all of them",
      sorted(u.toLocalFile() for u in several.urls()) == sorted([big, sample]))
check("dragging the '..' row alone carries nothing",
      model.mimeData([model.index(rows[".."], 0)]) is None)

model.set_items([ListingItem(name="inside.txt", path="inside.txt")], archive_mode=True)
check("an archive row needs somewhere to unpack to, and says so by refusing",
      model.mimeData([model.index(0, 0)]) is None)
model.drag_paths = lambda items: [sample]
check("with an unpacker installed it carries the unpacked file",
      [u.toLocalFile() for u in model.mimeData([model.index(0, 0)]).urls()]
      == [sample])

shutil.rmtree(root, ignore_errors=True)
shutil.rmtree(SCRATCH, ignore_errors=True)
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
