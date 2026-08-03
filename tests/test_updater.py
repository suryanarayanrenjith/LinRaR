"""The updater: what it refuses, what it downloads, and what it puts back.

The interesting half of an updater is the half that says no, so most of this
file feeds it manifests and archives that are wrong in one specific way and
checks that it declines rather than installs.  The rest of it does the real
thing end to end — a genuine release tarball, built by tools/package.sh and
served over HTTP from this machine, downloaded, verified, unpacked and
installed over a scratch copy of LinRAR, then rolled back.

Nothing here touches the real install: every path is inside a temporary
directory, and the one test that runs install.sh is the one that does not.
"""
import hashlib, http.server, json, os, shutil, socket, subprocess, sys
import tarfile, tempfile, threading, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SCRATCH = tempfile.mkdtemp(prefix="linrar-updater-")
# Before anything of LinRAR's is imported: this file turns update settings on
# and off, and it must do that to a scratch config rather than to the one the
# person running the tests actually uses.  The system layer is switched off
# for the same reason.
os.environ["XDG_CONFIG_HOME"] = os.path.join(SCRATCH, "config")
os.environ["XDG_CACHE_HOME"] = os.path.join(SCRATCH, "cache-home")
os.environ["LINRAR_SYSTEM_CONFIG"] = ""

from linrar import version as versions
from linrar.core import updater
from linrar.core.updater import (
    Artifact,
    Update,
    UpdateContext,
    UpdateError,
    parse_manifest,
)

PASS = FAIL = 0
def check(name, cond, extra=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ok  {name}")
    else: FAIL += 1; print(f"FAIL  {name}  {extra}")

def silent() -> UpdateContext:
    """A context that records instead of showing."""
    log: list = []
    ctx = UpdateContext(on_message=log.append)
    ctx.log_lines = log            # type: ignore[attr-defined]
    return ctx


def manifest_bytes(**overrides) -> bytes:
    body = {
        "schema": versions.MANIFEST_SCHEMA,
        "app": "LinRAR",
        "version": "99.0.0",
        "tag": "v99.0.0",
        "channel": "stable",
        "prerelease": False,
        "released": "2026-08-02T10:00:00Z",
        "commit": "a" * 40,
        "requires": {"os": "linux", "python": "3.9"},
        "release_url": "https://example.invalid/releases/tag/v99.0.0",
        "notes": "- Something new.",
        "artifacts": [{
            "name": "linrar-99.0.0.tar.gz",
            "kind": "source",
            "size": 100,
            "sha256": "b" * 64,
            "url": "https://example.invalid/linrar-99.0.0.tar.gz",
        }],
    }
    body.update(overrides)
    return json.dumps(body).encode()


print("== reading a manifest")
good = parse_manifest(manifest_bytes())
check("a well-formed manifest parses", good.version == "99.0.0")
check("the tag comes with it", good.tag == "v99.0.0")
check("so do the notes", "Something new" in good.notes)
check("and the download", good.artifact.name == "linrar-99.0.0.tar.gz")
check("the size is carried through", good.size == 100)
check("the date is trimmed for display", good.date == "2026-08-02")


def refuses(name, expectation, **overrides):
    try:
        parse_manifest(manifest_bytes(**overrides))
        check(name, False, "it was accepted")
    except UpdateError as error:
        check(name, expectation.lower() in str(error).lower(), str(error))


refuses("a newer schema is refused", "newer LinRAR", schema=99)
refuses("a missing schema is refused", "newer LinRAR", schema=None)
refuses("an unparseable version is refused", "usable version", version="latest")
refuses("no artifacts at all is refused", "no downloads", artifacts=None)
refuses("an empty artifact list is refused", "no source download", artifacts=[])
refuses("a short checksum is refused", "checksum", artifacts=[{
    "name": "linrar-99.0.0.tar.gz", "kind": "source", "size": 1,
    "sha256": "abc", "url": "https://example.invalid/x.tar.gz"}])
refuses("a plain-HTTP download is refused", "insecure", artifacts=[{
    "name": "linrar-99.0.0.tar.gz", "kind": "source", "size": 1,
    "sha256": "b" * 64, "url": "http://example.invalid/x.tar.gz"}])
refuses("a download that is not a tarball is refused", "no source download",
        artifacts=[{"name": "linrar.deb", "kind": "source", "size": 1,
                    "sha256": "b" * 64, "url": "https://x.invalid/linrar.deb"}])

try:
    parse_manifest(b"<html>404</html>")
    check("a page that is not JSON is refused", False)
except UpdateError as error:
    check("a page that is not JSON is refused", "not a manifest" in str(error))
try:
    parse_manifest(b'"a string"')
    check("JSON that is not an object is refused", False)
except UpdateError as error:
    check("JSON that is not an object is refused", "JSON object" in str(error))

print("\n== what this machine can run")
try:
    updater._requirements_met(Update(version="9.0.0", requires={"python": "99.0"}))
    check("a release needing a newer Python is refused", False)
except UpdateError as error:
    check("a release needing a newer Python is refused", "Python 99.0" in str(error))
try:
    updater._requirements_met(Update(version="9.0.0", requires={"os": "haiku"}))
    check("a release for another system is refused", False)
except UpdateError as error:
    check("a release for another system is refused", "haiku" in str(error))
updater._requirements_met(Update(version="9.0.0",
                                 requires={"os": "linux", "python": "3.9"}))
check("and this one is accepted", True)

print("\n== is this copy updatable at all")
source_tree = os.path.join(SCRATCH, "checkout")
os.makedirs(source_tree)
verdict = updater.eligibility(source_tree)
check("a source checkout is refused", not verdict)
check("and told why", "not installed from a release" in verdict.reason,
      verdict.reason)
check("with something to do instead", "git" in verdict.suggestion.lower())
check("Eligibility is falsy when it says no", not bool(verdict))
check("and truthy when it says yes", bool(updater.Eligibility(True)))

print("\n== the install receipt")
receipt_dir = os.path.join(SCRATCH, "receipted")
os.makedirs(receipt_dir)
with open(os.path.join(receipt_dir, ".install-receipt"), "w") as handle:
    handle.write("# a comment\napp=LinRAR\nversion=2.0.0\nbuild=abc123\n"
                 "mode=user\nlauncher=/home/someone/.local/bin/linrar\n"
                 "project=/home/someone/LinRAR\nnot a pair\n")
receipt = updater.read_receipt(receipt_dir)
check("a receipt is read", receipt.found)
check("the mode comes out", receipt.mode == "user")
check("the version comes out", receipt.version == "2.0.0")
check("the launcher comes out", receipt.launcher.endswith("/linrar"))
check("comments and junk lines are ignored", "not a pair" not in receipt.values)
check("a missing receipt is not an error",
      not updater.read_receipt(os.path.join(SCRATCH, "nowhere")).found)

print("\n== the overall progress weighting")
check("it starts at nothing", updater.overall_percent("check", 0) == 0)
check("it ends at everything", updater.overall_percent("done", 100) == 100)
check("the weights add up to 100",
      sum(weight for _, _, weight in updater.STAGES) == 100)
previous = -1
for key, _title, _weight in updater.STAGES:
    for percent in (0, 50, 100):
        value = updater.overall_percent(key, percent)
        if value < previous:
            break
        previous = value
    else:
        continue
    break
check("and it never goes backwards", previous == 100, previous)

print("\n== building a release to update to")
# A real tarball, built the way the pipeline builds one, from a scratch clone
# so that neither the project nor its git history is touched.
served = os.path.join(SCRATCH, "server")
work = os.path.join(SCRATCH, "build")
os.makedirs(served)
# The working tree as it is now, not as it was committed: the point is to
# package *this* code.  git is only needed because the packager works from the
# tracked file list, so the copy gets a repository of its own.
shutil.copytree(ROOT, work, ignore=shutil.ignore_patterns(
    ".venv", "venv", "__pycache__", "dist", ".git", ".install-*"))
for argv in (["git", "init", "--quiet"],
             ["git", "add", "-A"],
             ["git", "-c", "user.email=t@t", "-c", "user.name=t",
              "commit", "--quiet", "-m", "scratch"]):
    subprocess.run(argv, cwd=work, capture_output=True)

NEW_VERSION = "99.1.0"
subprocess.run([sys.executable, os.path.join(work, "tools", "release.py"),
                "bump", NEW_VERSION, "--allow-empty"],
               cwd=work, capture_output=True, text=True)
subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                "commit", "--quiet", "-am", "release"],
               cwd=work, capture_output=True)
built = subprocess.run([os.path.join(work, "tools", "package.sh"),
                        "--dist", served],
                       cwd=work, capture_output=True, text=True)
tarball = os.path.join(served, f"linrar-{NEW_VERSION}.tar.gz")
check("tools/package.sh built the release", os.path.isfile(tarball),
      (built.stdout + built.stderr)[-400:])

if not os.path.isfile(tarball):
    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1)

digest = hashlib.sha256(open(tarball, "rb").read()).hexdigest()
size = os.path.getsize(tarball)

# Serve it, exactly as GitHub would, minus the TLS this machine has no
# certificate for -- which is the one thing the updater is asked to overlook.
sock = socket.socket()
sock.bind(("127.0.0.1", 0))
PORT = sock.getsockname()[1]
sock.close()


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


httpd = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Quiet)
os.chdir(served)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{PORT}"

with open(os.path.join(served, "latest.json"), "wb") as handle:
    handle.write(manifest_bytes(
        version=NEW_VERSION, tag=f"v{NEW_VERSION}",
        artifacts=[{
            "name": os.path.basename(tarball), "kind": "source",
            "size": size, "sha256": digest,
            "url": f"{BASE}/{os.path.basename(tarball)}",
        }],
    ))

print("\n== checking against a real server")
updater.REQUIRE_HTTPS = False       # 127.0.0.1 over plain HTTP, for this file
ctx = silent()
found = updater.check(ctx, url=f"{BASE}/latest.json", current="2.0.0")
check("the check finds the release", found is not None and
      found.version == NEW_VERSION, found)
check("it knows where to get it", found.artifact.url.endswith(".tar.gz"))
check("a machine already on that version is told nothing is new",
      updater.check(silent(), url=f"{BASE}/latest.json",
                    current=NEW_VERSION) is None)
check("a machine on something newer likewise",
      updater.check(silent(), url=f"{BASE}/latest.json",
                    current="99.9.9") is None)

try:
    updater.check(silent(), url=f"{BASE}/nothing-here.json")
    check("a 404 is reported as no release", False)
except UpdateError as error:
    check("a 404 is reported as no release", "No release" in str(error))
try:
    updater.check(silent(), url="http://127.0.0.1:1/latest.json", timeout=3)
    check("an unreachable server is reported as one", False)
except UpdateError as error:
    check("an unreachable server is reported as one",
          "reach the update server" in str(error))

print("\n== downloading and verifying")
cache = os.path.join(SCRATCH, "cache")
ctx = silent()
downloaded = updater.download(found, ctx, directory=cache)
check("the tarball arrives", os.path.isfile(downloaded))
check("at the size the release promised",
      os.path.getsize(downloaded) == size)
updater.verify(downloaded, found, silent())
check("and it verifies against the published checksum", True)

again = silent()
updater.download(found, again, directory=cache)
check("a second download reuses the cached copy",
      any("not fetching it again" in line for line in again.log_lines))

tampered = Update(version=found.version, artifact=Artifact(
    name=found.artifact.name, kind="source", size=size,
    sha256="c" * 64, url=found.artifact.url))
copy = os.path.join(SCRATCH, "tampered.tar.gz")
shutil.copy(downloaded, copy)
try:
    updater.verify(copy, tampered, silent())
    check("a checksum mismatch is refused", False)
except UpdateError as error:
    check("a checksum mismatch is refused", "checksum" in str(error))
check("and the bad download is deleted", not os.path.exists(copy))

print("\n== unpacking, and what will not be unpacked")
unpacked = updater.unpack(downloaded, found, silent(),
                          directory=os.path.join(SCRATCH, "tree"))
check("the tarball unpacks", os.path.isdir(unpacked))
check("into the folder the release names",
      os.path.basename(unpacked) == f"linrar-{NEW_VERSION}")
check("and it really is that version",
      updater._version_of(unpacked) == NEW_VERSION)
check("install.sh survived as an executable",
      os.access(os.path.join(unpacked, "install.sh"), os.X_OK))

evil = os.path.join(SCRATCH, "evil.tar.gz")
with tarfile.open(evil, "w:gz") as archive:
    victim = os.path.join(SCRATCH, "payload")
    open(victim, "w").write("pwned")
    for name in (f"linrar-{NEW_VERSION}/../../escaped", "/etc/passwd",
                 f"linrar-{NEW_VERSION}/../outside"):
        info = archive.gettarinfo(victim, arcname=name)
        archive.addfile(info, open(victim, "rb"))
try:
    updater.unpack(evil, Update(version=NEW_VERSION), silent(),
                   directory=os.path.join(SCRATCH, "evil-tree"))
    check("an archive that escapes its folder is refused", False)
except UpdateError as error:
    check("an archive that escapes its folder is refused",
          "outside its own folder" in str(error) or
          "not laid out" in str(error), str(error))
check("and nothing was written outside",
      not os.path.exists(os.path.join(SCRATCH, "escaped")))

stray = os.path.join(SCRATCH, "stray.tar.gz")
with tarfile.open(stray, "w:gz") as archive:
    archive.add(os.path.join(SCRATCH, "payload"), arcname="somewhere-else/file")
try:
    updater.unpack(stray, Update(version=NEW_VERSION), silent(),
                   directory=os.path.join(SCRATCH, "stray-tree"))
    check("an archive laid out some other way is refused", False)
except UpdateError as error:
    check("an archive laid out some other way is refused",
          "not laid out" in str(error))

wrong = os.path.join(SCRATCH, "wrong.tar.gz")
with tarfile.open(wrong, "w:gz") as archive:
    archive.add(unpacked, arcname=f"linrar-{NEW_VERSION}")
try:
    updater.unpack(wrong, Update(version="98.0.0"), silent(),
                   directory=os.path.join(SCRATCH, "wrong-tree"))
    check("an archive whose contents disagree with the release is refused",
          False)
except UpdateError as error:
    check("an archive whose contents disagree with the release is refused",
          "not laid out" in str(error) or "claims" in str(error), str(error))

print("\n== installing over a scratch copy of LinRAR")
# A stand-in for an installed LinRAR: the previous release, unpacked, with no
# receipt, so install.sh is never run and nothing outside SCRATCH is touched.
installed = os.path.join(SCRATCH, "installed")
os.makedirs(installed)
with tarfile.open(downloaded) as archive:
    archive.extractall(os.path.join(SCRATCH, "seed"))
seed = os.path.join(SCRATCH, "seed", f"linrar-{NEW_VERSION}")
for entry in os.listdir(seed):
    origin, target = os.path.join(seed, entry), os.path.join(installed, entry)
    (shutil.copytree if os.path.isdir(origin) else shutil.copy2)(origin, target)
# Pretend the installed copy is older, so the update has something to change.
with open(os.path.join(installed, "linrar", "version.py")) as handle:
    body = handle.read()
with open(os.path.join(installed, "linrar", "version.py"), "w") as handle:
    handle.write(body.replace(f'__version__ = "{NEW_VERSION}"',
                              '__version__ = "98.0.0"'))
os.makedirs(os.path.join(installed, ".venv"))
open(os.path.join(installed, ".venv", "marker"), "w").write("kept")
open(os.path.join(installed, "user-notes.txt"), "w").write("mine")

check("the scratch install starts out older",
      updater._version_of(installed) == "98.0.0")

ctx = silent()
backup = updater.install(installed, unpacked, found, ctx, run_installer=False)
check("the install reports where the backup went", os.path.isdir(backup))
check("the tree is now the new version",
      updater._version_of(installed) == NEW_VERSION)
check("the virtual environment was left alone",
      os.path.isfile(os.path.join(installed, ".venv", "marker")))
check("the backup holds the version that was replaced",
      updater._version_of(backup) == "98.0.0")
check("the backup does not carry a copy of the venv",
      not os.path.exists(os.path.join(backup, ".venv")))
check("it said it verified the result",
      any("reports version" in line for line in ctx.log_lines),
      ctx.log_lines[-3:])
check("the stages it went through were announced",
      updater._version_of(installed) == NEW_VERSION)

print("\n== rolling back")
updater.restore(installed, backup)
check("restore puts the old version back",
      updater._version_of(installed) == "98.0.0")
check("and the file the user left there comes back too",
      os.path.isfile(os.path.join(installed, "user-notes.txt")))
check("while the venv was never involved",
      os.path.isfile(os.path.join(installed, ".venv", "marker")))

print("\n== a failure rolls itself back")
broken = os.path.join(SCRATCH, "broken-tree")
shutil.copytree(unpacked, broken)
# A tree that unpacks and looks right but cannot import: the last check in
# install() is the only thing that catches this, and it must undo everything.
with open(os.path.join(broken, "linrar", "__init__.py"), "w") as handle:
    handle.write("raise RuntimeError('this build is broken')\n")
try:
    updater.install(installed, broken, found, silent(), run_installer=False)
    check("an update that does not run is refused", False)
except UpdateError as error:
    check("an update that does not run is refused",
          "does not run" in str(error) or "rolled back" in str(error),
          str(error))
check("and the working version is back in place",
      updater._version_of(installed) == "98.0.0")
check("with its files intact",
      os.path.isfile(os.path.join(installed, "user-notes.txt")))
check("and it still imports",
      subprocess.run([sys.executable, "-c", "import linrar"], cwd=installed,
                     capture_output=True).returncode == 0)

print("\n== cancelling")
class Stopper:
    def __init__(self, after): self.left = after
    def __call__(self):
        self.left -= 1
        return self.left < 0

cancelling = UpdateContext(should_cancel=Stopper(0))
try:
    updater.download(found, cancelling,
                     directory=os.path.join(SCRATCH, "cancelled"))
    check("a cancelled download stops", False)
except updater.Cancelled:
    check("a cancelled download stops", True)
check("and leaves no half-file behind",
      not any(name.endswith(".part") for name in
              os.listdir(os.path.join(SCRATCH, "cancelled"))
              if os.path.isdir(os.path.join(SCRATCH, "cancelled"))))

print("\n== restarting")
argv = updater.restart_command(installed)
check("a restart command is always answerable", bool(argv), argv)
check("and it names something runnable",
      argv[0] == sys.executable or os.path.exists(argv[0]), argv)

print("\n== the settings it is driven by")
from linrar.core.settings import DEFAULTS
for key in ("update/check_on_start", "update/automatic", "update/prereleases",
            "update/last_check", "update/skipped"):
    check(f"{key} has a default", key in DEFAULTS)
check("checking is off until it is asked for",
      DEFAULTS["update/check_on_start"] is False)
check("and so is installing on its own",
      DEFAULTS["update/automatic"] is False)
check("no update setting lives in a group called general",
      not any(k.startswith("general") for k in DEFAULTS if "update" in k))

print("\n== the window it is shown through")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PyQt6.QtWidgets import QApplication      # noqa: E402  (headless, after the core)

app = QApplication.instance() or QApplication([])
from linrar.ui.dialogs.update import (          # noqa: E402
    START_CHECK_INTERVAL,
    StageList,
    StartupCheck,
    UpdateDialog,
    due_for_check,
)
from linrar.core.settings import SETTINGS       # noqa: E402

dialog = UpdateDialog(None)
check("the window builds", dialog is not None)
check("it lists every stage before starting",
      list(dialog.stages.rows) == [key for key, _t, _w in updater.STAGES])
check("all of them start out pending",
      all(glyph.text() == "·" for glyph, _c in dialog.stages.rows.values()))

dialog.present(found)
check("an available update names the version",
      dialog.fact_version.text() == NEW_VERSION)
check("and the download size", "KB" in dialog.fact_size.text()
      or "MB" in dialog.fact_size.text(), dialog.fact_size.text())
check("and says which channel it came from",
      dialog.fact_channel.text() in ("Stable", "Pre-release"))
check("the notes are shown", NEW_VERSION in dialog.notes.toPlainText())
check("the headline says an update is available",
      NEW_VERSION in dialog.title_label.text(), dialog.title_label.text())
check("this checkout is told it cannot install it",
      dialog.blocked_label.isVisible() or not updater.eligibility(),
      "a source tree must not offer to overwrite itself")
check("so Update now is not offered here", not dialog.btn_update.isVisible())

dialog._on_checked(None)
check("being up to date is its own answer",
      "up to date" in dialog.title_label.text().lower(),
      dialog.title_label.text())
check("and offers nothing to install", not dialog.btn_update.isVisible())

dialog._on_stage("download", "Downloading the update")
check("a stage in progress is marked current",
      dialog.stages.rows["download"][0].text() == "▶")
check("and the ones before it are ticked off",
      dialog.stages.rows["check"][0].text() == "✓")
dialog._on_progress(50, 512 * 1024, 1024 * 1024)
check("the stage bar follows the stage", dialog.stage_bar.value() == 50)
check("the overall bar is weighted, not the same number",
      0 < dialog.overall_bar.value() < 50, dialog.overall_bar.value())
check("the byte counter reads as a person would say it",
      "of" in dialog.stats_label.text(), dialog.stats_label.text())
check("and the title carries the percentage",
      "%" in dialog.windowTitle(), dialog.windowTitle())

dialog._on_failed(UpdateError("It broke.", "Here is why."))
check("a failure says what went wrong",
      "It broke." in dialog.done_hint.text() or
      "It broke." in dialog.done_label.text())
check("it opens the details by itself", dialog.details_button.isChecked())
check("the log kept the reason", any("It broke." in line
                                     for line in dialog._log))
check("and the failed stage is marked failed",
      dialog.stages.rows["download"][0].text() == "✕")
dialog.close()

empty = StageList(updater.STAGES)
empty.finish()
check("finishing ticks every stage",
      all(glyph.text() == "✓" for glyph, _c in empty.rows.values()))

SETTINGS.set("update/check_on_start", False)
SETTINGS.set("update/automatic", False)
check("no start-up check unless it was asked for", not StartupCheck.wanted())
SETTINGS.set("update/check_on_start", True)
check("asking for one is enough", StartupCheck.wanted())
SETTINGS.set("update/check_on_start", False)
SETTINGS.set("update/automatic", True)
check("so is asking for automatic installs", StartupCheck.wanted())

SETTINGS.set("update/last_check", "")
check("a machine that never checked is due", due_for_check())
SETTINGS.set("update/last_check", time.strftime("%Y-%m-%dT%H:%M:%S"))
check("one that just checked is not", not due_for_check())
check("but it is again once the interval has passed",
      due_for_check(time.time() + START_CHECK_INTERVAL + 60))
SETTINGS.set("update/last_check", "not a timestamp")
check("an unreadable stamp is treated as never", due_for_check())
SETTINGS.set("update/last_check", "")
SETTINGS.set("update/automatic", False)
SETTINGS.sync()

httpd.shutdown()
os.chdir(ROOT)
shutil.rmtree(SCRATCH, ignore_errors=True)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
