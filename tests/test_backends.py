"""End-to-end backend tests for LinRAR (no GUI). Run on the host."""
import os, shutil, subprocess, sys, tempfile, zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from linrar.core.backends.rar import RarBackend
from linrar.core.backends.zip import ZipBackend
from linrar.core.backends.sevenzip import SevenZipBackend
from linrar.core.models import (
    ArchiveFormat, CompressOptions, CompressionMethod, ExtractOptions,
    OverwriteMode, UpdateMode, PasswordRequired, OperationError,
)
from linrar.core.registry import detect_format, REGISTRY
from linrar.core import convert as convert_mod

PASS = FAIL = 0
def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f"FAIL  {name}  {extra}")

root = tempfile.mkdtemp(prefix="linrar-suite-")
os.chdir(root)

def fresh(name):
    d = os.path.join(root, name)
    os.makedirs(d, exist_ok=True)
    return d

src = fresh("src")
with open(f"{src}/a.txt", "w") as f: f.write("hello world\n")
with open(f"{src}/b.txt", "w") as f: f.write("second file\n")
os.makedirs(f"{src}/sub", exist_ok=True)
with open(f"{src}/sub/deep.txt", "w") as f: f.write("deep\n")
os.makedirs(f"{src}/nest", exist_ok=True)
with open(f"{src}/nest/a.txt", "w") as f: f.write("decoy same name\n")
os.symlink("a.txt", f"{src}/link.txt")

rar = RarBackend()
zipb = ZipBackend()
seven = SevenZipBackend()

# ---------------- RAR: no-password create must NOT be encrypted -------------
print("== RAR create (no password)")
arc = f"{root}/plain.rar"
rar.create([f"{src}/a.txt", f"{src}/sub"],
           CompressOptions(archive_path=arc, base_folder=src))
info = rar.read_info(arc)
names = sorted(e.name for e in info.entries)
check("entries stored w/ paths", names == ["a.txt", "sub", "sub/deep.txt"], names)
check("no entry encrypted", not any(e.encrypted for e in info.entries))
check("no decoy nest/a.txt swept in", "nest/a.txt" not in names)
out = fresh("out-plain")
rar.extract(arc, ExtractOptions(destination=out, overwrite_mode=OverwriteMode.OVERWRITE))
check("extract wrote files", open(f"{out}/a.txt").read() == "hello world\n")
check("extract wrote subdir", os.path.isfile(f"{out}/sub/deep.txt"))

# external unrar with no password must succeed (the old bug failed here)
proc = subprocess.run(["unrar", "-p-", "t", "-y", arc], capture_output=True)
check("external unrar -p- test exit 0", proc.returncode == 0, proc.returncode)

# ---------------- RAR: SFX no password ---------------------------------
print("== RAR SFX (no password)")
sfx = f"{root}/self.sfx"
opts = CompressOptions(archive_path=f"{root}/self.rar", create_sfx=True, base_folder=src)
rar.create([f"{src}/a.txt"], opts)
check("archive_path normalised to .sfx", opts.archive_path == sfx, opts.archive_path)
check("sfx file exists", os.path.isfile(sfx))
outdir = fresh("out-sfx")
proc = subprocess.run([sfx, f"-d{outdir}"], capture_output=True, timeout=30,
                      stdin=subprocess.DEVNULL, cwd=outdir)
text = proc.stdout.decode() + proc.stderr.decode()
check("sfx runs w/o password prompt", "password" not in text.lower(), text[:200])
check("sfx extracted file", os.path.isfile(f"{outdir}/a.txt"), text[:200])
check("detect_format sees sfx as RAR", detect_format(sfx) in (ArchiveFormat.RAR4, ArchiveFormat.RAR5))

# ---------------- RAR: password + header encryption --------------------
print("== RAR with password")
enc = f"{root}/enc.rar"
rar.create([f"{src}/a.txt"], CompressOptions(
    archive_path=enc, base_folder=src, password="Sekret1", encrypt_headers=True))
try:
    rar.read_info(enc)
    check("enc headers require password", False)
except PasswordRequired:
    check("enc headers require password", True)
info = rar.read_info(enc, "Sekret1")
check("password lists entries", [e.name for e in info.entries] == ["a.txt"])
out = fresh("out-enc")
rar.extract(enc, ExtractOptions(destination=out, password="Sekret1",
                                overwrite_mode=OverwriteMode.OVERWRITE))
check("password extract", open(f"{out}/a.txt").read() == "hello world\n")
try:
    rar.extract(enc, ExtractOptions(destination=out, password="wrong",
                                    overwrite_mode=OverwriteMode.OVERWRITE))
    check("wrong password raises", False)
except PasswordRequired:
    check("wrong password raises", True)

# ---------------- RAR: store_paths=False (-ep) --------------------------
print("== RAR -ep")
ep = f"{root}/ep.rar"
rar.create([f"{src}/sub/deep.txt"], CompressOptions(
    archive_path=ep, base_folder=src, store_paths=False))
info = rar.read_info(ep)
check("no path stored", [e.name for e in info.entries] == ["deep.txt"],
      [e.name for e in info.entries])

# ---------------- RAR: rename folder w/ children ------------------------
print("== RAR rename pairs")
rn = f"{root}/rn.rar"
rar.create([f"{src}/sub"], CompressOptions(archive_path=rn, base_folder=src))
rar.rename_members(rn, [("sub", "renamed"), ("sub/deep.txt", "renamed/deep.txt")])
info = rar.read_info(rn)
names = sorted(e.name for e in info.entries)
check("folder + child renamed", names == ["renamed", "renamed/deep.txt"], names)

# ---------------- RAR: comment, lock, recovery record, test -------------
print("== RAR misc write ops")
rar.set_comment(arc, "A test comment")
info = rar.read_info(arc)
check("comment set", info.comment == "A test comment", repr(info.comment))
rar.set_comment(arc, "")
check("comment cleared", rar.read_info(arc).comment == "")
rar.add_recovery_record(arc, 3)
check("recovery record", rar.read_info(arc).recovery_record)
rar.test(arc)
check("rar test ok", True)
# rar convert to sfx stub
stub = rar.convert_to_sfx(arc)
check("convert_to_sfx output exists", os.path.isfile(stub), stub)
# no -p- pollution: the stub extracts without password
outdir2 = fresh("out-stub")
proc = subprocess.run([stub, f"-d{outdir2}"], capture_output=True, timeout=30,
                      stdin=subprocess.DEVNULL, cwd=outdir2)
check("stub extracts w/o password",
      "password" not in (proc.stdout.decode() + proc.stderr.decode()).lower())

# ---------------- ZIP: create + update modes ----------------------------
print("== ZIP")
z = f"{root}/test.zip"
zipb.create([f"{src}/a.txt", f"{src}/sub"], CompressOptions(
    archive_path=z, format=ArchiveFormat.ZIP, base_folder=src))
info = zipb.read_info(z)
names = sorted(e.name for e in info.entries)
check("zip entries", "a.txt" in names and "sub/deep.txt" in names, names)

# duplicate-add must replace, not duplicate
zipb.create([f"{src}/a.txt"], CompressOptions(
    archive_path=z, format=ArchiveFormat.ZIP, base_folder=src))
with zipfile.ZipFile(z) as zz:
    dupes = [n for n in zz.namelist() if n == "a.txt"]
check("no duplicate entries after re-add", len(dupes) == 1, dupes)
info = zipb.read_info(z)
check("other entries kept", any(e.name == "sub/deep.txt" for e in info.entries))

# SKIP_EXISTING leaves original content
with open(f"{src}/a.txt", "w") as f: f.write("changed!\n")
zipb.create([f"{src}/a.txt"], CompressOptions(
    archive_path=z, format=ArchiveFormat.ZIP, base_folder=src,
    update_mode=UpdateMode.SKIP_EXISTING))
with zipfile.ZipFile(z) as zz:
    check("skip existing kept old data", zz.read("a.txt") == b"hello world\n")
# ADD_REPLACE replaces
zipb.create([f"{src}/a.txt"], CompressOptions(
    archive_path=z, format=ArchiveFormat.ZIP, base_folder=src))
with zipfile.ZipFile(z) as zz:
    check("replace updated data", zz.read("a.txt") == b"changed!\n")
# SYNCHRONIZE drops entries not in the selection
zipb.create([f"{src}/a.txt"], CompressOptions(
    archive_path=z, format=ArchiveFormat.ZIP, base_folder=src,
    update_mode=UpdateMode.SYNCHRONIZE))
with zipfile.ZipFile(z) as zz:
    check("synchronize dropped others", zz.namelist() == ["a.txt"], zz.namelist())

# exclusions
z2 = f"{root}/ex.zip"
zipb.create([src], CompressOptions(
    archive_path=z2, format=ArchiveFormat.ZIP, base_folder=os.path.dirname(src),
    exclude_patterns=["*.txt"]))
with zipfile.ZipFile(z2) as zz:
    check("exclude *.txt", not any(n.endswith(".txt") for n in zz.namelist()),
          zz.namelist())

# symlink round trip
z3 = f"{root}/links.zip"
subprocess.run(["zip", "-q", "--symlinks", "-r", z3, "src/link.txt", "src/a.txt"],
               cwd=root, check=True)
out = fresh("out-zlink")
zipb.extract(z3, ExtractOptions(destination=out, overwrite_mode=OverwriteMode.OVERWRITE))
check("zip symlink recreated", os.path.islink(f"{out}/src/link.txt"),
      "not a link" if os.path.exists(f"{out}/src/link.txt") else "missing")

# zip-slip guard
evil = f"{root}/evil.zip"
with zipfile.ZipFile(evil, "w") as zz:
    zz.writestr("../../evil.txt", "bad")
out = fresh("out-evil")
zipb.extract(evil, ExtractOptions(destination=out, overwrite_mode=OverwriteMode.OVERWRITE))
check("zip slip blocked", not os.path.exists(os.path.join(root, "evil.txt"))
      and not os.path.exists(os.path.join(os.path.dirname(root), "evil.txt")))

# encrypted zip creation (was completely broken: zip -e needs a tty)
print("== ZIP encrypted create")
ez = f"{root}/enc.zip"
zipb.create([f"{src}/a.txt"], CompressOptions(
    archive_path=ez, format=ArchiveFormat.ZIP, base_folder=src, password="pw123"))
check("encrypted zip created", os.path.isfile(ez))
with zipfile.ZipFile(ez) as zz:
    zz.setpassword(b"pw123")
    check("encrypted zip readable with pw", zz.read("a.txt") == b"changed!\n")
try:
    zipb.extract(ez, ExtractOptions(destination=fresh("out-ez"),
                                    overwrite_mode=OverwriteMode.OVERWRITE))
    check("encrypted zip w/o pw raises", False)
except PasswordRequired:
    check("encrypted zip w/o pw raises", True)

# zip folder rename renames children
print("== ZIP rename")
zr = f"{root}/rn.zip"
zipb.create([f"{src}/sub"], CompressOptions(
    archive_path=zr, format=ArchiveFormat.ZIP, base_folder=src))
zipb.rename_member(zr, "sub", "moved")
with zipfile.ZipFile(zr) as zz:
    nn = sorted(zz.namelist())
check("zip prefix rename", all(n.startswith("moved") for n in nn), nn)

# ---------------- 7z ---------------------------------------------------
print("== 7z")
s7 = f"{root}/test.7z"
seven.create([f"{src}/a.txt", f"{src}/sub"], CompressOptions(
    archive_path=s7, format=ArchiveFormat.SEVENZIP, base_folder=src))
info = seven.read_info(s7)
names = sorted(e.name for e in info.entries)
check("7z relative paths stored", "a.txt" in names and "sub/deep.txt" in names, names)
out = fresh("out-7z")
seven.extract(s7, ExtractOptions(destination=out, overwrite_mode=OverwriteMode.OVERWRITE))
check("7z extract", os.path.isfile(f"{out}/sub/deep.txt"))

# guard: refuse to "add" into a tar
tarpath = f"{root}/x.tar"
subprocess.run(["tar", "cf", tarpath, "-C", src, "a.txt"], check=True)
try:
    seven.create([f"{src}/b.txt"], CompressOptions(
        archive_path=tarpath, format=ArchiveFormat.SEVENZIP, base_folder=src))
    check("7z refuses to add into tar", False)
except OperationError:
    check("7z refuses to add into tar", True)

# read a tar via 7z: format must be reported as TAR, not 7z
info = seven.read_info(tarpath)
check("tar reported as TAR", info.format is ArchiveFormat.TAR, info.format)

# wrong format guard
try:
    seven.create([f"{src}/b.txt"], CompressOptions(
        archive_path=f"{root}/no.tar", format=ArchiveFormat.TAR, base_folder=src))
    check("7z rejects non-7z format", False)
except OperationError:
    check("7z rejects non-7z format", True)

# ---------------- convert ----------------------------------------------
print("== convert")
res = convert_mod.convert_archive(arc, convert_mod.ConvertOptions(
    target_format=ArchiveFormat.ZIP))
check("rar->zip convert ok", res.ok, res.message)
if res.ok:
    with zipfile.ZipFile(res.output) as zz:
        check("converted zip has entries", "a.txt" in zz.namelist(), zz.namelist())

res = convert_mod.convert_archive(enc, convert_mod.ConvertOptions(
    target_format=ArchiveFormat.ZIP, passwords=["Sekret1"]))
check("encrypted rar convert w/ saved pw", res.ok, res.message)

# ---------------- detect_format ----------------------------------------
print("== detect")
check("detect rar", detect_format(arc) in (ArchiveFormat.RAR4, ArchiveFormat.RAR5))
check("detect zip", detect_format(z) is ArchiveFormat.ZIP)
check("detect 7z", detect_format(s7) is ArchiveFormat.SEVENZIP)
check("detect tar", detect_format(tarpath) is ArchiveFormat.TAR)
with open(f"{root}/plain.txt", "w") as f: f.write("not an archive")
check("detect text unknown", detect_format(f"{root}/plain.txt") is ArchiveFormat.UNKNOWN)

print(f"\n{PASS} passed, {FAIL} failed")
shutil.rmtree(root, ignore_errors=True)
sys.exit(1 if FAIL else 0)
