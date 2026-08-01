"""Final round: volumes, recovery volumes, AES-zip delegation, misc."""
import os, subprocess, sys, tempfile, shutil
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from linrar.core.backends.rar import RarBackend
from linrar.core.backends.zip import ZipBackend
from linrar.core.models import (
    CompressOptions, ExtractOptions, OverwriteMode,
    PasswordRequired,
)

PASS = FAIL = 0
def check(name, cond, extra=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ok  {name}")
    else: FAIL += 1; print(f"FAIL  {name}  {extra}")

root = tempfile.mkdtemp(prefix="linrar-final-")
src = os.path.join(root, "src"); os.makedirs(src)
with open(f"{src}/big.bin", "wb") as f:
    f.write(os.urandom(300 * 1024))

rar = RarBackend()
zipb = ZipBackend()

# multi-volume creation (100 KB volumes)
print("== RAR volumes")
vol = f"{root}/vols.rar"
rar.create([f"{src}/big.bin"], CompressOptions(
    archive_path=vol, base_folder=src, volume_size=100 * 1024))
parts = sorted(p for p in os.listdir(root) if p.startswith("vols.part"))
check("volumes created", len(parts) >= 3, parts)
first = os.path.join(root, parts[0])
info = rar.read_info(first)
check("volume flag detected", info.volume, info.detail_line)

# recovery volumes + reconstruction of a deleted part
rar.add_recovery_volumes(first, "30%")
revs = [p for p in os.listdir(root) if p.endswith(".rev")]
check("rev files created", len(revs) >= 1, revs)
victim = os.path.join(root, parts[1])
os.unlink(victim)
rar.reconstruct_volumes(first)
check("missing volume rebuilt", os.path.isfile(victim))
out = os.path.join(root, "vout"); os.makedirs(out)
rar.extract(first, ExtractOptions(destination=out,
                                  overwrite_mode=OverwriteMode.OVERWRITE))
check("volume set extracts after rebuild",
      os.path.getsize(f"{out}/big.bin") == 300 * 1024)

# AES-encrypted zip made by 7z: built-in reader must delegate to 7z
print("== AES zip delegation")
aes = f"{root}/aes.zip"
subprocess.run(["7z", "a", "-tzip", "-pSecret", "-mem=AES256", "-bso0",
                aes, f"{src}/big.bin"], check=True)
out2 = os.path.join(root, "aesout"); os.makedirs(out2)
zipb.extract(aes, ExtractOptions(destination=out2, password="Secret",
                                 overwrite_mode=OverwriteMode.OVERWRITE))
check("AES zip extracted via delegate",
      os.path.isfile(f"{out2}/big.bin") and
      os.path.getsize(f"{out2}/big.bin") == 300 * 1024)
try:
    zipb.extract(aes, ExtractOptions(destination=out2, password="nope",
                                     overwrite_mode=OverwriteMode.OVERWRITE))
    check("AES zip wrong pw raises", False)
except PasswordRequired:
    check("AES zip wrong pw raises", True)

# repair: archive with recovery record survives corruption
print("== repair")
prot = f"{root}/prot.rar"
rar.create([f"{src}/big.bin"], CompressOptions(
    archive_path=prot, base_folder=src, recovery_record=True,
    recovery_percent=10))
size = os.path.getsize(prot)
with open(prot, "r+b") as f:
    f.seek(size // 2)
    f.write(b"\x00" * 512)
fixed = rar.repair(prot, root)
check("repair produced a file", fixed is not None and os.path.isfile(fixed), fixed)
if fixed:
    rar.test(fixed)
    check("repaired archive passes test", True)

# rar update modes still behave (freshen doesn't add new files)
print("== RAR freshen")
fr = f"{root}/fresh.rar"
rar.create([f"{src}/big.bin"], CompressOptions(archive_path=fr, base_folder=src))
with open(f"{src}/newfile.txt", "w") as f: f.write("new")
from linrar.core.models import UpdateMode
rar.create([f"{src}/big.bin", f"{src}/newfile.txt"], CompressOptions(
    archive_path=fr, base_folder=src, update_mode=UpdateMode.FRESHEN))
info = rar.read_info(fr)
check("freshen did not add new file",
      sorted(e.name for e in info.entries) == ["big.bin"],
      [e.name for e in info.entries])

shutil.rmtree(root, ignore_errors=True)
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
