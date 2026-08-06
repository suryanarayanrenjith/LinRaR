"""Config file persistence, tool discovery, icon export and desktop install."""
import os, subprocess, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# A scratch config so the real one is never touched by the test run.
SCRATCH = tempfile.mkdtemp(prefix="linrar-conf-")
os.environ["XDG_CONFIG_HOME"] = SCRATCH

from PyQt6.QtWidgets import QApplication
app = QApplication([])

from linrar.core import settings as settings_module
from linrar.core import tools
from linrar.core.settings import DEFAULTS, SETTINGS, Settings, config_path
from linrar.ui import icons, theme

PASS = FAIL = 0
def check(name, cond, extra=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ok  {name}")
    else: FAIL += 1; print(f"FAIL  {name}  {extra}")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

print("== the config file")
check("path follows XDG_CONFIG_HOME",
      config_path() == os.path.join(SCRATCH, "LinRAR", "linrar.conf"),
      config_path())
store = Settings(os.path.join(SCRATCH, "probe.conf"))
check("file created on construction", os.path.isfile(store.path), store.path)
store.set("view/theme", "dark")
store.set("toolbar/icon_size", 24)
store.set("view/grid_lines", True)
store.set("toolbar/items", ["add", "|", "find"])
store.sync()
check("written to disk", "theme=dark" in open(store.path).read())

reopened = Settings(store.path)
check("string survives a restart", reopened.get("view/theme") == "dark")
check("int survives a restart", reopened.get("toolbar/icon_size") == 24)
check("bool survives a restart", reopened.get("view/grid_lines") is True)
check("list survives a restart",
      reopened.string_list("toolbar/items") == ["add", "|", "find"])
check("defaults fill the gaps", reopened.get("view/tree_side") == "left")
check("unknown key -> None", reopened.get("nothing/here") is None)

reopened.set("geometry/probe", b"\x01\x02\x03")
reopened.sync()
check("binary values round-trip",
      bytes(Settings(store.path).load_geometry("probe")) == b"\x01\x02\x03")

reopened.reset("view/theme")
check("reset restores the default", reopened.get("view/theme") == "light")
reopened.set("view/theme", "dark")
reopened.reset_all()
check("reset_all clears everything", reopened.get("view/theme") == "light")
check("but keeps the version stamp",
      reopened.get("meta/config_version") == settings_module.CONFIG_VERSION)

print("== migration from the old location")
legacy_dir = os.path.join(SCRATCH, "LinRAR-Linux")
os.makedirs(legacy_dir, exist_ok=True)
with open(os.path.join(legacy_dir, "LinRAR.conf"), "w") as handle:
    # Qt escapes a group literally named "general" to "%General", which is how
    # the old file really looked on disk.
    handle.write("[view]\ntheme=dark\n\n[%General]\nlast_folder=/tmp\n")
migrated = Settings(os.path.join(SCRATCH, "LinRAR", "migrated.conf"))
check("old settings imported", migrated.get("view/theme") == "dark")
check("old paths imported under their new name",
      migrated.get("places/last_folder") == "/tmp",
      migrated.get("places/last_folder"))
check("only imported once",
      Settings(migrated.path).get("meta/config_version") ==
      settings_module.CONFIG_VERSION)

print("== the retired 'general' group")
# with the legacy file gone, the only source is the stale key in this file
import shutil
shutil.rmtree(legacy_dir, ignore_errors=True)
renamed = Settings(os.path.join(SCRATCH, "renamed.conf"))
renamed.set("General/last_folder", "/old")
renamed.reset("meta/config_version")
renamed.sync()
fixed = Settings(renamed.path)
check("a stale general/ key is carried over",
      fixed.get("places/last_folder") == "/old", fixed.get("places/last_folder"))
check("and the old one is dropped",
      "General/last_folder" not in fixed.keys(), fixed.keys())
check("no setting uses the general group",
      not [k for k in DEFAULTS if k.startswith(("general/", "General/"))])

print("== everything the user changes has a home")
for key in ("view/mode", "view/tree_side", "view/comment_side",
            "view/sort_column", "view/sort_descending", "view/row_height",
            "toolbar/items", "toolbar/style", "toolbar/icon_size",
            "compression/format", "compression/method", "compression/solid",
            "compression/update_mode", "extract/overwrite", "extract/update",
            "extract/no_paths", "extract/subfolders", "find/mask",
            "admin/method", "paths/rar", "paths/unrar", "paths/sevenzip"):
    check(f"default for {key}", key in DEFAULTS)

print("== finding the tools")
check("rar found", tools.find("rar").endswith("rar"), tools.find("rar"))
check("7z found under one of its names",
      os.path.basename(tools.find("sevenzip")) in
      ("7z", "7zz", "7za", "7zzs", "7zr", "p7zip"), tools.find("sevenzip"))
check("nonsense tool -> empty", tools.find("definitely-not-a-tool") == "")
check("an explicit path wins", tools.find("rar", "/bin/sh") == "/bin/sh")
import shutil
if shutil.which("sh"):
    check("a bare name resolves through PATH",
          tools.find("rar", "sh").endswith("sh"))
check("a bad override falls back to the search",
      tools.find("rar", "/nope/rar").endswith("rar"))
check("extra directories are searched",
      "/usr/local/bin" in tools.EXTRA_DIRS and "/opt/rar" in tools.EXTRA_DIRS)
check("7-Zip alternatives known",
      {"7z", "7zz", "7za"} <= set(tools.CANDIDATES["sevenzip"]))
check("unrar alternatives known",
      "unrar-free" in tools.CANDIDATES["unrar"])

from linrar.core.backends.rar import RarBackend
from linrar.core.backends.sevenzip import SevenZipBackend
check("rar backend uses the resolver", RarBackend().rar == tools.find("rar"))
check("7z backend uses the resolver",
      SevenZipBackend().exe == tools.find("sevenzip"))

print("== icon export")
theme.apply(app, "light")
out = os.path.join(SCRATCH, "icon.png")
check("export writes a file", icons.export_png("app", 48, out))
from PyQt6.QtGui import QImage
image = QImage(out)
check("at exactly the size asked for",
      image.width() == 48 and image.height() == 48,
      f"{image.width()}x{image.height()}")
check("and it is not blank", image.pixelColor(24, 24).alpha() > 0)
check("svg() returns markup", icons.svg("app").startswith("<svg"))

print("== repository layout")
for path in ("assets/linrar.svg", "assets/linrar.desktop", "install.sh",
             "uninstall.sh", "run.sh", "requirements.txt", "README.md",
             "LICENSE", "CHANGELOG.md", ".gitignore", "tests/run_all.py",
             "docs/INSTALL.md", "docs/USAGE.md", "docs/ARCHITECTURE.md",
             "docs/DEVELOPMENT.md"):
    check(f"{path} is where it belongs", os.path.exists(os.path.join(ROOT, path)))
strays = [
    name for name in os.listdir(ROOT)
    if not name.startswith(".")
    and os.path.isfile(os.path.join(ROOT, name))
    and name not in {"install.sh", "uninstall.sh", "run.sh", "requirements.txt",
                     "README.md", "LICENSE", "CHANGELOG.md"}
]
check("no loose files in the root", not strays, strays)
check("the shipped icon is the icon set's own",
      open(os.path.join(ROOT, "assets/linrar.svg")).read().strip()
      == icons.svg("app").strip())
gitignore = open(os.path.join(ROOT, ".gitignore")).read()
for pattern in (".venv/", ".install-manifest", "__pycache__/"):
    check(f".gitignore covers {pattern}", pattern in gitignore)

print("== the tools tab")
from linrar.ui.main_window import MainWindow
from linrar.ui.dialogs.misc import SettingsDialog

theme.apply(app, "light")
window = MainWindow()
tools_tab = SettingsDialog(window)
tools_tab.tabs.setCurrentIndex(1)
check("a path box for every tool",
      set(tools_tab.path_edits) == {"rar", "unrar", "sevenzip", "zip"},
      sorted(tools_tab.path_edits))
check("the boxes are wide enough for a path",
      all(e.minimumWidth() >= 260 for e in tools_tab.path_edits.values()),
      {k: e.minimumWidth() for k, e in tools_tab.path_edits.items()})
check("each box shows where the tool was found",
      all(e.placeholderText() for e in tools_tab.path_edits.values()))
tools_tab.path_edits["rar"].setText("/nonexistent/rar")
tools_tab._rescan_tools()
check("Re-scan falls back to the search when a path is wrong",
      tools_tab.path_edits["rar"].placeholderText().endswith("rar"),
      tools_tab.path_edits["rar"].placeholderText())
tools_tab.path_edits["rar"].setText("")
tools_tab._rescan_tools()
check("clearing a box clears the setting", SETTINGS.get("paths/rar") == "")
tools_tab.close()
window.close()

print("== the installer's desktop wiring")
install = open(os.path.join(ROOT, "install.sh")).read()
for needle in ("assets/linrar.svg", "hicolor/${size}x${size}/apps", "pixmaps",
               "index.theme",
               "gtk-update-icon-cache", "StartupWMClass",
               "rpm-ostree", "emerge", "nix", "dnf5", "ensurepip",
               "system-site-packages", "Checking that it actually runs"):
    check(f"install.sh handles {needle}", needle in install)
removal = open(os.path.join(ROOT, "uninstall.sh")).read()
check("uninstall removes the raster icons",
      "icons/hicolor/${size}x${size}/apps/${APP_ID}.png" in removal)
check("uninstall knows the new config path", "config}/LinRAR\"" in removal
      or "/LinRAR" in removal)

print("== the launcher")
check("no fake argv[0]", "exec -a" not in install,
      "python resolves its venv from argv[0]; renaming it breaks PyQt6")
check("WM_CLASS set the safe way", "RESOURCE_NAME" in install)
check("the check runs the launcher, not the interpreter",
      '"$LAUNCHER" --version' in install and '"$LAUNCHER" --self-test' in install)
check("and from a bare environment", "env -i HOME=" in install)

launcher = os.path.expanduser("~/.local/bin/linrar")
if os.path.exists(launcher):
    result = subprocess.run(
        [launcher, "--version"],
        cwd="/",
        env={"HOME": os.path.expanduser("~"), "PATH": "/usr/bin:/bin",
             "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True, text=True, timeout=90,
    )
    check("the installed launcher runs from a clean environment",
          result.returncode == 0 and "LinRAR" in result.stdout,
          (result.stdout + result.stderr).strip()[-200:])
    check("and finds PyQt6 in the virtual environment",
          "ModuleNotFoundError" not in result.stderr)
else:
    print("  --  launcher not installed, skipping the live check")

check("uninstall removes the venv by default",
      'rm -rf "${APP_DIR}/.venv"' in removal
      and 'KEEP_VENV" = "1"' in removal)
check("and --keep-venv still opts out", "--keep-venv" in removal)

print("== desktop integration is gone from the app")
main_window = open(os.path.join(ROOT, "linrar/ui/main_window.py")).read()
check("no command left", "cmd_desktop_integration" not in main_window)
check("no action left", "act_desktop_integration" not in main_window)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
