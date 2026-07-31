"""Build a self-extracting AppImage and actually run it.

Needs an AppImage *runtime* stub, which LinRAR takes from its cache, from
`appimagetool`, or by harvesting any AppImage already on the machine.  A
build server usually has none of the three and downloading one is not this
test's job, so the whole file steps aside when there is nothing to build with.
"""
import os, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from linrar.core.backends.rar import RarBackend
from linrar.core.models import CompressOptions, OperationError
from linrar.core import sfx

PASS = FAIL = 0
def check(name, cond, extra=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ok  {name}")
    else: FAIL += 1; print(f"FAIL  {name}  {extra}")

try:
    sfx.acquire_runtime(allow_download=False)
except OperationError:
    print("  --  no AppImage runtime available offline; skipping this file")
    print("\n0 passed, 0 failed")
    sys.exit(0)

root = tempfile.mkdtemp(prefix="linrar-appimage-")
src = os.path.join(root, "src"); os.makedirs(src)
open(f"{src}/hello.txt", "w").write("payload data\n")

rar = RarBackend()
arc = f"{root}/pay.rar"
rar.create([f"{src}/hello.txt"], CompressOptions(archive_path=arc, base_folder=src))

out = sfx.build_sfx_appimage(
    arc, f"{root}/Pay.AppImage",
    sfx.SfxOptions(title="Test SFX", ask_destination=False, default_path=""),
    allow_download=False,
)
check("appimage built", os.path.isfile(out) and os.access(out, os.X_OK), out)

# run it: --appimage-extract-and-run avoids needing FUSE; -d dest, no prompts
dest = os.path.join(root, "unpacked"); os.makedirs(dest)
proc = subprocess.run(
    [out, "--appimage-extract-and-run", "-d", dest, "-y", "--no-gui"],
    capture_output=True, timeout=60, stdin=subprocess.DEVNULL, cwd=root,
)
text = proc.stdout.decode() + proc.stderr.decode()
check("appimage sfx ran", proc.returncode == 0, f"rc={proc.returncode} {text[:300]}")
check("no password prompt", "password" not in text.lower(), text[:300])
check("payload extracted", os.path.isfile(f"{dest}/hello.txt"), text[:300])

# --list mode
proc = subprocess.run([out, "--appimage-extract-and-run", "--list"],
                      capture_output=True, timeout=60, stdin=subprocess.DEVNULL)
check("--list works", b"hello.txt" in proc.stdout, proc.stdout[:200])

# LinRAR itself can open the AppImage as an archive
from linrar.core.registry import detect_format, REGISTRY
from linrar.core.models import ArchiveFormat
fmt = detect_format(out)
check("appimage detected as RAR sfx", fmt in (ArchiveFormat.RAR4, ArchiveFormat.RAR5), fmt)
backend, fmt = REGISTRY.for_path(out)
info = backend.read_info(out)
check("appimage listable", any(e.name.endswith("hello.txt") for e in info.entries),
      [e.name for e in info.entries][:5])

import shutil; shutil.rmtree(root, ignore_errors=True)
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
