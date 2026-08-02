"""Format sniffing and the reports that explain a file that will not open."""
import os, shutil, stat, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from linrar.core import diagnose
from linrar.core.models import ArchiveFormat, OperationError, PasswordRequired
from linrar.core.registry import (
    ARCHIVE_EXTENSIONS,
    REGISTRY,
    detect_format,
    detect_format_source,
    first_volume,
    volume_number,
)

PASS = FAIL = 0
def check(name, cond, extra=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ok  {name}")
    else: FAIL += 1; print(f"FAIL  {name}  {extra}")

root = tempfile.mkdtemp(prefix="linrar-diag-")

def write(name, data):
    path = os.path.join(root, name)
    with open(path, "wb") as handle:
        handle.write(data if isinstance(data, bytes) else data.encode())
    return path

print("== every format has a label")
for fmt in ArchiveFormat:
    check(f"{fmt.name} has a label", bool(fmt.label))
check("read_only marks the 7-Zip-only formats",
      ArchiveFormat.DEB.read_only and ArchiveFormat.CPIO.read_only and
      not ArchiveFormat.ZIP.read_only and not ArchiveFormat.RAR5.read_only)

print("== detection by content")
cases = [
    ("a.rar", b"Rar!\x1a\x07\x01\x00" + b"\x00" * 40, ArchiveFormat.RAR5),
    ("b.rar", b"Rar!\x1a\x07\x00" + b"\x00" * 40, ArchiveFormat.RAR4),
    ("c.zip", b"PK\x03\x04" + b"\x00" * 40, ArchiveFormat.ZIP),
    ("d.7z", b"7z\xbc\xaf\x27\x1c" + b"\x00" * 40, ArchiveFormat.SEVENZIP),
    ("e.gz", b"\x1f\x8b" + b"\x00" * 40, ArchiveFormat.GZIP),
    ("f.zst", b"\x28\xb5\x2f\xfd" + b"\x00" * 40, ArchiveFormat.ZSTD),
    ("pkg.deb", b"!<arch>\ndebian-binary" + b"\x00" * 40, ArchiveFormat.DEB),
    ("lib.a", b"!<arch>\n" + b"\x00" * 40, ArchiveFormat.AR),
    ("p.rpm", b"\xed\xab\xee\xdb" + b"\x00" * 40, ArchiveFormat.RPM),
    ("i.cpio", b"070701" + b"0" * 40, ArchiveFormat.CPIO),
    ("s.squashfs", b"hsqs" + b"\x00" * 40, ArchiveFormat.SQUASHFS),
    ("w.wim", b"MSWIM\x00\x00\x00" + b"\x00" * 40, ArchiveFormat.WIM),
    ("l.lz", b"LZIP" + b"\x00" * 40, ArchiveFormat.LZIP),
    ("z.Z", b"\x1f\x9d" + b"\x00" * 40, ArchiveFormat.COMPRESS),
    ("q.lz4", b"\x04\x22\x4d\x18" + b"\x00" * 40, ArchiveFormat.LZ4),
    ("j.arj", b"\x60\xea" + b"\x00" * 40, ArchiveFormat.ARJ),
    ("h.lzh", b"\x00\x00-lh5-" + b"\x00" * 40, ArchiveFormat.LZH),
]
for name, data, expected in cases:
    path = write(name, data)
    found, source = detect_format_source(path)
    check(f"{name} detected as {expected.label}", found is expected, found)
    check(f"{name} proven by content", source == "content", source)

print("== ambiguous signatures need the name to agree")
ole = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 40
check("an .msi with the compound header is an archive",
      detect_format(write("setup.msi", ole)) is ArchiveFormat.MSI)
check("a .doc with the same header is not",
      detect_format(write("letter.doc", ole)) is ArchiveFormat.UNKNOWN)

print("== everything openable is listed as an archive extension")
for extension in (".deb", ".rpm", ".cpio", ".wim", ".msi", ".squashfs", ".lz",
                  ".lz4", ".dmg", ".snap"):
    check(f"{extension} counts as an archive name",
          extension in ARCHIVE_EXTENSIONS)

print("== volumes")
check("part 1 is the first", volume_number("/x/set.part1.rar") == 1)
check("part 07 is the seventh", volume_number("/x/set.part07.rar") == 7)
check("r00 is the second part", volume_number("/x/set.r00") == 2)
check("7z .002 is the second", volume_number("/x/set.7z.002") == 2)
check("a plain name is not a volume", volume_number("/x/set.rar") == 0)
for name in ("set.part1.rar", "set.part2.rar", "set.part3.rar"):
    write(name, b"Rar!\x1a\x07\x01\x00" + b"\x00" * 40)
check("first volume found",
      first_volume(os.path.join(root, "set.part3.rar")) ==
      os.path.join(root, "set.part1.rar"))
check("first volume of the first volume is nothing",
      first_volume(os.path.join(root, "set.part1.rar")) == "")
check("no first volume when it is absent",
      first_volume("/nowhere/other.part4.rar") == "")

print("== inspect_path")
text = write("notes.txt", "the quick brown fox\n" * 4)
facts = diagnose.inspect_path(text)
check("a text file is a file", facts.kind == "file" and facts.exists)
check("a text file is readable", facts.readable)
check("a text file is recognised as text", facts.content == "plain text",
      facts.content)
check("a text file is not an archive", not facts.is_archive)
check("size is reported", facts.size == len("the quick brown fox\n") * 4)
check("the first bytes are kept", facts.magic.startswith(b"the quick"))
check("facts render as rows", any(n == "Size" for n, _ in facts.rows()))

renamed = write("renamed.rar", "the quick brown fox\n")
facts = diagnose.inspect_path(renamed)
check("a renamed text file is guessed from its name",
      facts.format is ArchiveFormat.RAR5 and facts.format_source == "name")
check("but it is not confirmed", not facts.confirmed)
check("and it is flagged as mislabelled", facts.mislabelled)

pdf = write("guide.rar", b"%PDF-1.7\n" + b"\x00" * 30)
check("a PDF is named as such",
      diagnose.inspect_path(pdf).content == "a PDF document")
elf = write("prog.bin", b"\x7fELF\x02\x01\x01" + b"\x00" * 40)
check("an ELF is named as such",
      "ELF" in diagnose.inspect_path(elf).content)

missing = diagnose.inspect_path(os.path.join(root, "nothing-here"))
check("a missing path does not exist", not missing.exists)
check("a missing path is 'missing'", missing.kind == "missing")

folder = diagnose.inspect_path(root)
check("a folder is a directory", folder.kind == "directory")

empty = write("empty.zip", b"")
check("an empty file has no format",
      diagnose.inspect_path(empty).format is ArchiveFormat.UNKNOWN)

link = os.path.join(root, "dangling")
os.symlink(os.path.join(root, "not-there"), link)
broken = diagnose.inspect_path(link)
check("a dangling link is spotted", broken.broken_link, broken)

print("== describe: one report per kind of failure")
def kind_of(path, error=None):
    return diagnose.describe(path, error).kind

check("missing -> missing", kind_of(os.path.join(root, "nope.rar")) == "missing")
check("folder -> directory", kind_of(root) == "directory")
check("empty -> empty", kind_of(empty) == "empty")
check("text -> not-archive", kind_of(text) == "not-archive")
check("renamed text -> not-archive", kind_of(renamed) == "not-archive")
check("dangling link -> broken-link", kind_of(link) == "broken-link")
check("part 3 of a set -> volume",
      kind_of(os.path.join(root, "set.part3.rar"),
              OperationError("cannot find volume")) == "volume")
check("encrypted -> password",
      kind_of(os.path.join(root, "a.rar"),
              PasswordRequired("needs a password")) == "password")
check("a real archive that failed -> damaged",
      kind_of(os.path.join(root, "a.rar"), OperationError("boom", 3)) == "damaged")

print("== a report says enough to act on")
report = diagnose.describe(renamed)
check("it has a headline", "renamed.rar" in report.headline, report.headline)
check("it explains itself", "plain text" in report.explanation,
      report.explanation)
check("it lists what was found", len(report.facts) >= 5)
check("it suggests something", report.suggestions)
check("it offers actions", diagnose.ACTION_VIEW in report.actions)
check("it carries technical detail", "first bytes:" in report.details)
check("the details include a hex dump", "00000000" in report.details)
check("as_text holds all of it",
      all(part in report.as_text()
          for part in (report.headline, "What you can do", "Technical details")))
check("summarise is as_text", diagnose.summarise(renamed) == report.as_text())

volume_report = diagnose.describe(os.path.join(root, "set.part3.rar"),
                                  OperationError("cannot find volume"))
check("a volume report offers the first volume",
      diagnose.ACTION_FIRST_VOLUME in volume_report.actions)
check("a volume report names the first volume",
      "set.part1.rar" in volume_report.explanation, volume_report.explanation)

print("== permissions")
if os.getuid() == 0:
    print("  --  running as root, skipping the permission checks")
else:
    locked = write("locked.rar", b"Rar!\x1a\x07\x01\x00" + b"\x00" * 40)
    os.chmod(locked, 0)
    check("an unreadable file is reported as such",
          diagnose.describe(locked).kind == "permission")
    os.chmod(locked, stat.S_IRUSR | stat.S_IWUSR)

    shut = os.path.join(root, "shut")
    os.makedirs(shut)
    os.chmod(shut, 0)
    check("an unreadable folder is reported as such",
          diagnose.describe_folder(shut).kind == "permission")
    check("and it offers somewhere else to go",
          diagnose.ACTION_PARENT in diagnose.describe_folder(shut).actions)
    os.chmod(shut, 0o755)

print("== folders and handlers")
absent = diagnose.describe_folder(os.path.join(root, "no-such-folder"))
check("a missing folder is reported", absent.kind == "missing")
check("a missing folder points somewhere real",
      diagnose.nearest_existing(os.path.join(root, "a", "b", "c")) == root)
check("nearest_existing always answers",
      os.path.isdir(diagnose.nearest_existing("/no/such/path/at/all")))
check("a file is not a folder",
      diagnose.describe_folder(text).kind == "not-a-folder")
handler = diagnose.describe_no_handler(text)
check("no handler is explained", handler.kind == "no-handler")
check("no handler offers the viewer", diagnose.ACTION_VIEW in handler.actions)

print("== the tool a format needs")
tool, package, installed = REGISTRY.requirement(ArchiveFormat.RAR5)
check("RAR needs unrar", tool == "unrar" and package == "unrar")
check("ZIP needs nothing", REGISTRY.requirement(ArchiveFormat.ZIP)[0] == "")
check("7z formats need 7z",
      REGISTRY.requirement(ArchiveFormat.DEB)[0] == "7z")

print("== hexdump")
dump = diagnose.hexdump(b"AB\x00\xff")
check("hexdump shows the offset", dump.startswith("00000000"))
check("hexdump shows the bytes", "41 42 00 FF" in dump, dump)
check("hexdump shows the text", dump.rstrip().endswith("AB.."), dump)
check("an empty file dumps to a note", "empty" in diagnose.hexdump(b""))

shutil.rmtree(root, ignore_errors=True)
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
