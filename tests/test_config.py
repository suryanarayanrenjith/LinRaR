"""The system-wide configuration layer, the Linux check, and the install guards.

Three things that all have to hold at once:

  * a machine-wide config file sets defaults for every user, the user's own
    file still wins, and a key the administrator locks wins over both;
  * LinRAR refuses to start anywhere but Linux;
  * install.sh and uninstall.sh each run once, and say so the second time.
"""
import os, subprocess, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# Everything below runs against scratch files: the real config, the real
# /etc/linrar and the real install are never read or written.
SCRATCH = tempfile.mkdtemp(prefix="linrar-policy-")
os.environ["XDG_CONFIG_HOME"] = os.path.join(SCRATCH, "config")

SYSTEM_DIR = os.path.join(SCRATCH, "etc")
os.makedirs(SYSTEM_DIR, exist_ok=True)


def write(name, text):
    path = os.path.join(SYSTEM_DIR, name)
    with open(path, "w") as handle:
        handle.write(text)
    return path


# The file the singleton SETTINGS is built from, so the dialogs further down
# see a machine with a policy on it.
SINGLETON_CONF = write("singleton.conf", """
[view]
theme=dark
show_hidden=true
mode=list

[toolbar]
style=icon

[policy]
locked=view/theme, view/show_hidden, view/mode, toolbar/style, paths/*
""")
os.environ["LINRAR_SYSTEM_CONFIG"] = SINGLETON_CONF

from PyQt6.QtWidgets import QApplication
app = QApplication([])

from linrar.core import platform as platform_check
from linrar.core import settings as settings_module
from linrar.core.settings import (
    DEFAULTS,
    SETTINGS,
    Settings,
    SystemConfig,
    system_config_paths,
)

PASS = FAIL = 0
def check(name, cond, extra=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ok  {name}")
    else: FAIL += 1; print(f"FAIL  {name}  {extra}")


def store(*files, name="user.conf"):
    """A Settings on a fresh user file, layered over *files*."""
    path = os.path.join(SCRATCH, name)
    if os.path.exists(path):
        os.remove(path)
    return Settings(path, system=list(files))


print("== the layers stack in the right order")
system = write("base.conf", """
[view]
theme=dark
show_tree=false

[compression]
method=5
""")
layered = store(system)
check("a system value beats the built-in default",
      layered.get("view/theme") == "dark", layered.get("view/theme"))
check("and is reported as coming from the system",
      layered.source("view/theme") == "system", layered.source("view/theme"))
check("an untouched key still falls back to its default",
      layered.get("view/tree_side") == "left")
check("its source is the default", layered.source("view/tree_side") == "default")
check("types survive the INI: bool",
      layered.get("view/show_tree") is False, layered.get("view/show_tree"))
check("types survive the INI: int",
      layered.get("compression/method") == 5
      and isinstance(layered.get("compression/method"), int))

layered.set("view/theme", "light")
check("the user's own choice beats the system default",
      layered.get("view/theme") == "light")
check("and is reported as the user's", layered.source("view/theme") == "user")
layered.reset("view/theme")
check("dropping it falls back to the system value, not the default",
      layered.get("view/theme") == "dark")

print("== reading it back in a second process")
layered.set("view/theme", "light")
layered.sync()
reopened = Settings(layered.path, system=[system])
check("the user file still wins after a restart",
      reopened.get("view/theme") == "light")
check("a system-only key is still there too",
      reopened.get("compression/method") == 5)

print("== several files, later ones winning")
dropin = write("50-dropin.conf", "[view]\ntheme=light\n[toolbar]\nicon_size=48\n")
merged = store(system, dropin, name="merged.conf")
check("the last file to set a key wins", merged.get("view/theme") == "light")
check("keys only the first file sets survive",
      merged.get("view/show_tree") is False)
check("and keys only the last one sets", merged.get("toolbar/icon_size") == 48)
check("each key remembers which file it came from",
      merged.system.origin["view/theme"] == dropin
      and merged.system.origin["view/show_tree"] == system)

print("== locking")
locked_file = write("locked.conf", """
[view]
theme=dark

[paths]
rar=/opt/rar/rar

[policy]
locked=view/theme, paths/*, view/row_height
""")
managed = store(locked_file, name="managed.conf")
check("a locked key reads the administrator's value",
      managed.get("view/theme") == "dark")
check("and says so", managed.source("view/theme") == "locked")
check("is_locked agrees", managed.is_locked("view/theme"))
check("set() refuses and says it refused",
      managed.set("view/theme", "light") is False)
check("the value did not move", managed.get("view/theme") == "dark")
managed.sync()
check("nothing was written to the user's file either",
      "theme" not in open(managed.path).read())

check("a wildcard covers every key under it",
      managed.is_locked("paths/rar") and managed.is_locked("paths/sevenzip"))
check("a locked key with no value locks to the built-in default",
      managed.is_locked("view/row_height")
      and managed.get("view/row_height") == DEFAULTS["view/row_height"])
check("an unlisted key is still the user's",
      not managed.is_locked("view/show_tree")
      and managed.set("view/show_tree", False) is True)
check("a user value set before the lock is ignored, not obeyed",
      Settings(managed.path, system=[locked_file]).get("view/theme") == "dark")
check("locked_keys() lists what is actually locked",
      set(managed.system.locked_keys()) >=
      {"view/theme", "paths/rar", "paths/unrar", "view/row_height"},
      managed.system.locked_keys())
check("the reason names the file",
      locked_file in managed.lock_reason("view/theme"),
      managed.lock_reason("view/theme"))

print("== lock_all")
lock_all = write("all.conf", """
[view]
theme=dark
show_tree=false

[policy]
lock_all=true
""")
everything = store(lock_all, name="all-user.conf")
check("every key the file sets is locked",
      everything.is_locked("view/theme") and everything.is_locked("view/show_tree"))
check("but not the keys it does not set",
      not everything.is_locked("view/tree_side"))

print("== what the administrator may not touch")
overreach = write("overreach.conf", """
[geometry]
main=nonsense

[meta]
config_version=99

[policy]
locked=geometry/*, meta/*, view/theme
""")
guarded = store(overreach, name="guarded.conf")
check("window geometry cannot be set from a system file",
      "geometry/main" not in guarded.system.values)
check("nor the config version stamp",
      "meta/config_version" not in guarded.system.values)
check("geometry cannot be locked", not guarded.is_locked("geometry/main"))
check("meta cannot be locked", not guarded.is_locked("meta/config_version"))
guarded.save_geometry("main", b"\x01\x02")
check("so the window can still save where it is",
      bytes(guarded.load_geometry("main")) == b"\x01\x02")

print("== policy keys are policy, not settings")
check("policy/locked is not offered as a setting",
      "policy/locked" not in managed.system.values
      and managed.get("policy/locked") is None)
check("policy/lock_all is not either",
      "policy/lock_all" not in everything.system.values)

print("== a file commented the wrong way cannot set anything")
# Qt's INI parser treats ';' as a comment and '#' as an ordinary character,
# so a hash-commented file would otherwise arrive as keys called "#theme".
hashed = write("hashed.conf", """
[view]
#theme=dark
#show_tree=false
""")
ignored = store(hashed, name="hashed-user.conf")
check("hash-commented lines are dropped, not obeyed",
      ignored.system.values == {}, ignored.system.values)
check("so the defaults still apply", ignored.get("view/theme") == "light")

print("== an unreadable or missing file")
check("a file that is not there is simply not read",
      SystemConfig([os.path.join(SYSTEM_DIR, "nope.conf")]).files == [])
check("no system files at all is the normal case",
      not SystemConfig([]).active)
broken = write("broken.conf", "this is not an INI file at all\n[view]\ntheme=dark\n")
damaged = SystemConfig([broken])
check("a malformed file is reported rather than hidden", damaged.problems,
      damaged.problems)
check("and whatever parsed is still used",
      damaged.values.get("view/theme") == "dark", damaged.values)

print("== where the system files are looked for")
saved_env = os.environ.pop("LINRAR_SYSTEM_CONFIG")
os.environ["XDG_CONFIG_DIRS"] = "/etc/xdg-first:/etc/xdg-second"
# The ordering is what matters here, and it cannot be observed from the return
# value on a machine where none of those files exist, so read it from both
# ends: the constants the search uses, and the shape of the search itself.
source = open(os.path.join(ROOT, "linrar/core/settings.py")).read()
check("XDG_CONFIG_DIRS is honoured", "XDG_CONFIG_DIRS" in source)
check("and read in reverse, since XDG lists the most important first",
      "reversed(" in source)
check("/etc/linrar is LinRAR's own directory",
      settings_module.SYSTEM_CONFIG_DIR == "/etc/linrar")
check("with conf.d drop-ins after it",
      settings_module.DROPIN_DIR == "conf.d" and "conf.d" in source)
check("the search returns a list of real files",
      all(os.path.isfile(p) for p in system_config_paths()))
os.environ["LINRAR_SYSTEM_CONFIG"] = os.path.join(SYSTEM_DIR, "nope.conf")
check("the override replaces the search entirely", system_config_paths() == [])
os.environ["LINRAR_SYSTEM_CONFIG"] = f"{system}{os.pathsep}{dropin}"
check("and takes a list, lowest precedence first",
      system_config_paths() == [system, dropin], system_config_paths())
os.environ["LINRAR_SYSTEM_CONFIG"] = ""
check("empty means no system layer at all", system_config_paths() == [])
os.environ["LINRAR_SYSTEM_CONFIG"] = saved_env

print("== resetting is the user's business, not the machine's")
managed.set("view/show_tree", False)
managed.reset_all()
check("the user's own keys go", managed.get("view/show_tree") is True)
check("the administrator's stay", managed.get("view/theme") == "dark")
check("and stay locked", managed.is_locked("view/theme"))

print("== describing the whole picture")
report = managed.describe()
check("--config-info names the user file", managed.path in report)
check("and the system file", locked_file in report)
check("and what is locked", "locked" in report)
check("and lists effective values", "view/theme" in report)
check("but not window geometry",
      not [line for line in report.splitlines() if line.startswith("  geometry/")])
effective = dict((key, source_) for key, _value, source_ in managed.effective())
check("every default appears in the effective list",
      set(DEFAULTS) <= set(effective))

print("== the running application uses the layers")
check("the singleton picked up the system file",
      SETTINGS.system.files == [SINGLETON_CONF], SETTINGS.system.files)
check("its locked keys are in force", SETTINGS.get("view/theme") == "dark")
check("and refuse to be written", SETTINGS.set("view/theme", "light") is False)

print("== the interface shows what it cannot change")
from linrar.ui import policy, theme
from linrar.ui.main_window import MainWindow
from linrar.ui.dialogs.misc import SettingsDialog
from linrar.ui.dialogs.customize import CustomizeDialog

theme.apply(app, SETTINGS.get("view/theme"))
check("the locked theme is the one actually applied", theme.mode() == "dark")

window = MainWindow()
check("the Themes entry is disabled", not window.act_themes.isEnabled())
check("so are the view modes",
      not any(a.isEnabled() for a in window.view_mode_actions.values()))
check("and Show hidden files", not window.act_show_hidden.isEnabled())
check("and the toolbar text toggle", not window.act_toolbar_text.isEnabled())
check("and the button in the menu bar's corner with it",
      not window.themes_button.isEnabled())
check("while an unlocked entry is untouched", window.act_show_tree.isEnabled())
check("the window knows which settings those were",
      set(window.locked_settings) ==
      {"view/theme", "view/mode", "view/show_hidden", "toolbar/style"},
      window.locked_settings)
check("a disabled entry explains itself",
      "administrator" in window.act_themes.toolTip())

dialog = SettingsDialog(window)
check("Settings disables the theme box", not dialog.theme_combo.isEnabled())
check("and every tool path box",
      not any(e.isEnabled() for e in dialog.path_edits.values()))
check("and the hidden-files box", not dialog.hidden_check.isEnabled())
check("while the compression method stays editable",
      dialog.method_combo.isEnabled())
check("it carries a banner naming the file", dialog.lock_banner is not None)
check("and lists what is locked",
      set(dialog.locked) >= {"view/theme", "paths/rar", "view/show_hidden"},
      dialog.locked)
check("the Tools tab says where the system settings come from",
      SINGLETON_CONF in dialog._system_summary())
check("saving leaves the locked values alone", dialog._save() is None
      and SETTINGS.get("view/theme") == "dark")

customize = CustomizeDialog(window)
check("Customize disables the locked caption style",
      not customize.style_combo.isEnabled())
check("and the locked view modes",
      not any(b.isEnabled() for b in customize.mode_buttons.values()))
check("while the icon size is still free",
      customize.icon_size_combo.isEnabled())
check("and it has a banner too", customize.lock_banner is not None)
customize.close()
dialog.close()
window.close()

check("no banner when nothing is locked",
      policy.banner([], None) is None)

print("== LinRAR is a Linux program")
check("this machine is Linux", platform_check.is_linux())
check("and is therefore supported", platform_check.is_supported())
check("with nothing to complain about", platform_check.problem() == "")
check("and no override warning", platform_check.warning() == "")

real = sys.platform
try:
    for fake, expected in (("darwin", "macOS"), ("win32", "Windows"),
                           ("freebsd14", "FreeBSD")):
        sys.platform = fake
        check(f"{fake} is named {expected}",
              platform_check.system_name() == expected,
              platform_check.system_name())
        check(f"{fake} is refused", not platform_check.is_supported())
        message = platform_check.problem()
        check(f"{fake} is told why", expected in message and len(message) > 100)
    sys.platform = "win32"
    check("and pointed somewhere useful",
          "WinRAR" in platform_check.problem())
    os.environ["LINRAR_ALLOW_ANY_OS"] = "1"
    check("the override is the only way past it",
          platform_check.is_supported())
    check("and it warns every time",
          "unsupported" in platform_check.warning())
    del os.environ["LINRAR_ALLOW_ANY_OS"]
finally:
    sys.platform = real

check("the exit code is a failure", platform_check.EXIT_UNSUPPORTED != 0)
main_module = open(os.path.join(ROOT, "linrar/__main__.py")).read()
check("__main__ checks before importing anything graphical",
      main_module.index("ensure_supported()") < main_module.index("from .app"))
app_module = open(os.path.join(ROOT, "linrar/app.py")).read()
check("main() checks before opening a window",
      app_module.index("platform.is_supported()") < app_module.index("QApplication("))

result = subprocess.run(
    [sys.executable, "-c",
     "import sys; sys.platform = 'darwin';"
     "from linrar.app import main; sys.exit(main(['linrar', '--version']))"],
    capture_output=True, text=True, cwd=ROOT, timeout=120,
)
check("a non-Linux run really does stop", result.returncode != 0, result.returncode)
check("with an explanation on stderr", "does not run on" in result.stderr,
      result.stderr[:120])
check("and no version banner on stdout", "LinRAR 2" not in result.stdout)

print("== --config-info")
info = subprocess.run(
    [sys.executable, "-m", "linrar", "--config-info"],
    capture_output=True, text=True, cwd=ROOT, timeout=120,
    env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
)
check("it runs without a display", info.returncode == 0, info.stderr[-200:])
check("and reports the system file", SINGLETON_CONF in info.stdout)
check("and that keys are locked", "locked" in info.stdout)
check("--help mentions it", "--config-info" in
      subprocess.run([sys.executable, "-m", "linrar", "--help"],
                     capture_output=True, text=True, cwd=ROOT,
                     timeout=120).stdout)

print("== install.sh runs once")
install = open(os.path.join(ROOT, "install.sh")).read()
uninstall = open(os.path.join(ROOT, "uninstall.sh")).read()
for needle in ("--reinstall", "--status", "EXIT_REFUSED=3", "detect_install",
               "receipt_locations", "already installed", "uname -s",
               "--print-global-config", "--global-config"):
    check(f"install.sh knows {needle}", needle in install)
for needle in ("--force", "--status", "EXIT_REFUSED=3", "detect_install",
               "is not installed", "uname -s", "GLOBAL_CONFIG_FILE"):
    check(f"uninstall.sh knows {needle}", needle in uninstall)
check("the manifest is only truncated once the guard has passed",
      install.index("exit \"$EXIT_REFUSED\"") < install.index(': > "${MANIFEST}.tmp"'))
check("uninstall keeps an edited global config",
      "has been edited since it was installed" in uninstall)
check("and knows the checksum recorded at install time",
      "global_config_sha256" in install and "global_config_sha256" in uninstall)


def script(name, *args):
    return subprocess.run(
        [os.path.join(ROOT, name), *args],
        capture_output=True, text=True, cwd=ROOT, timeout=120,
        env={**os.environ, "NO_COLOR": "1"},
    )


helped = script("install.sh", "--help")
check("install.sh --help works", helped.returncode == 0)
check("and documents the refusal", "--reinstall" in helped.stdout)
check("uninstall.sh --help works too",
      script("uninstall.sh", "--help").returncode == 0)

status = script("install.sh", "--status")
INSTALLED = status.returncode == 0
check("install.sh --status answers one way or the other",
      status.returncode in (0, 1), status.returncode)
check("and says which", ("is installed" in status.stdout
                         or "is not installed" in status.stdout))
removal_status = script("uninstall.sh", "--status")
check("uninstall.sh --status agrees with it",
      (removal_status.returncode == 0) == INSTALLED,
      f"{removal_status.returncode} vs installed={INSTALLED}")

# Only ever run the script that is going to *refuse*: the other one would do
# the real thing to this machine.
if INSTALLED:
    before = sorted(os.listdir(ROOT))
    refused = script("install.sh", "--no-deps", "-y")
    check("a second install is refused", refused.returncode == 3,
          f"{refused.returncode}: {refused.stdout[-200:]}")
    check("and says it is already installed",
          "already installed" in refused.stderr + refused.stdout)
    check("and points at the way out",
          "--reinstall" in refused.stdout and "uninstall.sh" in refused.stdout)
    check("and changed nothing", sorted(os.listdir(ROOT)) == before)
    check("not even a stray manifest",
          not os.path.exists(os.path.join(ROOT, ".install-manifest.tmp")))
else:
    refused = script("uninstall.sh", "-y")
    check("uninstalling what was never installed is refused",
          refused.returncode == 3,
          f"{refused.returncode}: {refused.stdout[-200:]}")
    check("and says so", "not installed" in refused.stderr + refused.stdout)
    check("and points at the way out", "--force" in refused.stdout)

print("== the global config template it installs")
template = script("install.sh", "--print-global-config")
check("install.sh can print it", template.returncode == 0)
check("it is commented with semicolons, which is what Qt reads",
      template.stdout.startswith("; "))
check("it says so, because '#' is the tempting mistake",
      "'#' is NOT a comment" in template.stdout)
check("it documents the read order",
      "/etc/linrar/conf.d" in template.stdout
      and "~/.config/LinRAR/linrar.conf" in template.stdout)
check("and the policy section", "[policy]" in template.stdout
      and "locked=" in template.stdout)
check("and how to check the result", "--config-info" in template.stdout)

shipped = write("shipped.conf", template.stdout)
inert = SystemConfig([shipped])
check("as it ships it sets nothing", inert.values == {}, inert.values)
check("locks nothing", not inert.patterns and not inert.lock_all)
check("parses without complaint", not inert.problems, inert.problems)
check("and so changes nothing at all", not inert.active)

# Every key the template offers has to be one LinRAR actually reads.
offered = set()
section = ""
for line in template.stdout.splitlines():
    stripped = line.strip()
    if stripped.startswith("[") and stripped.endswith("]"):
        section = stripped[1:-1]
    elif stripped.startswith(";") and "=" in stripped and section:
        key = stripped[1:].split("=", 1)[0].strip()
        if key and " " not in key:
            offered.add(f"{section}/{key}")
unknown = sorted(
    key for key in offered
    if key not in DEFAULTS and not key.startswith("policy/")
)
check("every key it suggests is one LinRAR reads", not unknown, unknown)
check("and it covers the settings worth managing",
      {"view/theme", "compression/method", "paths/rar", "admin/method"} <= offered,
      sorted(offered))

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
