"""The command line: short forms, long forms, and refusing a bad line."""
import os, subprocess, sys, tempfile, shutil
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from linrar.app import (
    ACTION_FLAGS,
    EXIT_USAGE,
    QUERY_FLAGS,
    USAGE,
    Invocation,
    parse_args,
)

PASS = FAIL = 0
def check(name, cond, extra=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ok  {name}")
    else: FAIL += 1; print(f"FAIL  {name}  {extra}")

root = tempfile.mkdtemp(prefix="linrar-cli-")
here = os.path.join(root, "here.txt")
with open(here, "w") as handle:
    handle.write("payload\n")
folder = os.path.join(root, "folder")
os.makedirs(folder)
gone = os.path.join(root, "gone.rar")

print("== the flag table")
check("four actions", set(ACTION_FLAGS) ==
      {"--extract-here", "--extract-to", "--add", "--test"}, ACTION_FLAGS)
check("every action has a short form",
      all(len(s) == 2 and s.startswith("-") for s in ACTION_FLAGS.values()),
      ACTION_FLAGS)
check("every query has a short form",
      all(len(s) == 2 and s.startswith("-") for s in QUERY_FLAGS.values()),
      QUERY_FLAGS)
check("short forms are unique",
      len(set(ACTION_FLAGS.values()) | set(QUERY_FLAGS.values())) ==
      len(ACTION_FLAGS) + len(QUERY_FLAGS))
for long, short in list(ACTION_FLAGS.items()) + list(QUERY_FLAGS.items()):
    check(f"USAGE documents {short}/{long}",
          short in USAGE and long in USAGE)
check("USAGE says Linux only", "Linux only" in USAGE and "Windows" in USAGE)

print("== short and long forms agree")
for long, short in ACTION_FLAGS.items():
    by_long = parse_args(["linrar", long, here])
    by_short = parse_args(["linrar", short, here])
    check(f"{short} == {long}",
          by_long.action == by_short.action == long and
          by_long.paths == by_short.paths == [here],
          (by_long, by_short))
for long, short in QUERY_FLAGS.items():
    argv = ["linrar", short] + ([here] if long == "--inspect" else [])
    check(f"{short} selects {long}", parse_args(argv).query == long)

print("== paths")
one = parse_args(["linrar", here, folder, gone])
check("existing paths kept", one.paths == [here, folder], one.paths)
check("missing path recorded", one.missing == [gone], one.missing)
check("argument order preserved", one.arguments == [here, folder, gone],
      one.arguments)
check("no action means no error", one.valid and not one.action)
check("relative paths become absolute",
      os.path.isabs(parse_args(["linrar", "tests"]).arguments[0]))
check("~ is expanded",
      parse_args(["linrar", "~"]).arguments[0] == os.path.expanduser("~"))

print("== -- ends the options")
literal = parse_args(["linrar", "--", "-x"])
check("after -- a dash is a name", not literal.action and
      literal.arguments and literal.arguments[0].endswith("-x"), literal)
check("a lone - is a name", parse_args(["linrar", "-"]).valid)

print("== bad command lines")
bad = parse_args(["linrar", "--extract"])
check("unknown option refused", not bad.valid and "unknown option" in bad.error)
check("unknown option suggests the real ones",
      "--extract-here" in bad.error and "--extract-to" in bad.error, bad.error)
bundled = parse_args(["linrar", "-xt"])
check("bundled short options refused", not bundled.valid, bundled.error)
check("bundling explained", "not combined" in bundled.error, bundled.error)
clash = parse_args(["linrar", "-x", "-a", here])
check("two actions refused", not clash.valid and "cannot both" in clash.error,
      clash.error)
empty = parse_args(["linrar", "--test"])
check("action with no files refused", not empty.valid, empty.error)
check("refusal names the option and an example",
      "--test (-t)" in empty.error and "linrar -t" in empty.error, empty.error)
absent = parse_args(["linrar", "-t", gone])
check("action with only missing files refused", not absent.valid, absent.error)
check("refusal names the file", gone in absent.error, absent.error)
check("action with one good file accepted",
      parse_args(["linrar", "-t", here, gone]).valid)
check("--help beats everything else",
      parse_args(["linrar", "-c", "--help"]).query == "--help")
check("--self-test still recognised", parse_args(["linrar", "--self-test"]).self_test)
check("Invocation defaults are empty",
      Invocation().valid and not Invocation().paths)

print("== running it for real")
PY = os.path.join(ROOT, ".venv", "bin", "python")
if not os.path.exists(PY):
    PY = sys.executable
env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONPATH=ROOT)

def run(*args):
    return subprocess.run(
        [PY, "-c", "import sys; from linrar.app import main; sys.exit(main(['linrar'] + sys.argv[1:]))",
         *args],
        capture_output=True, text=True, env=env, cwd=ROOT, timeout=120,
    )

result = run("--help")
check("--help exits 0", result.returncode == 0, result.returncode)
check("--help prints the usage", "Usage:" in result.stdout)
check("-h matches --help", run("-h").stdout == result.stdout)
version = run("-V")
check("-V prints a version", version.returncode == 0 and
      version.stdout.startswith("LinRAR "), version.stdout)
check("--version matches -V", run("--version").stdout == version.stdout)
config = run("-c")
check("-c prints the configuration", config.returncode == 0 and
      "LinRAR configuration" in config.stdout, config.stdout[:80])

broken = run("--nonsense")
check("a bad option exits 2", broken.returncode == EXIT_USAGE, broken.returncode)
check("a bad option says so on stderr", "unknown option" in broken.stderr,
      broken.stderr)
check("a bad option prints nothing on stdout", broken.stdout == "",
      broken.stdout)
check("an action with no files exits 2",
      run("--add").returncode == EXIT_USAGE)

print("== --inspect")
report = run("-i", here)
check("-i on a plain file exits 1", report.returncode == 1, report.returncode)
check("-i explains it is not an archive",
      "not an archive" in report.stdout, report.stdout[:120])
check("-i shows the bytes it read", "00000000" in report.stdout)
missing = run("-i", gone)
check("-i on a missing file exits 1", missing.returncode == 1)
check("-i names the missing file", "gone.rar" in missing.stdout, missing.stdout[:80])
check("-i with no files exits 2", run("-i").returncode == EXIT_USAGE)
check("--inspect matches -i", run("--inspect", gone).stdout == missing.stdout)

if shutil.which("rar"):
    archive = os.path.join(root, "good.rar")
    subprocess.run(["rar", "a", "-idq", archive, here], check=True,
                   capture_output=True)
    good = run("-i", archive)
    check("-i on a real archive exits 0", good.returncode == 0, good.stdout[:200])
    check("-i names the format", "RAR5 archive" in good.stdout, good.stdout[:120])
    check("-i says the contents proved it",
          "by its contents" in good.stdout, good.stdout[:200])
    mislabelled = os.path.join(root, "text.rar")
    shutil.copy(here, mislabelled)
    fake = run("-i", mislabelled)
    check("-i is not fooled by a .rar name",
          fake.returncode == 1 and "not an archive" in fake.stdout,
          fake.stdout[:160])
else:
    print("  --  rar not installed, skipping the real-archive checks")

print("== the desktop files still call it correctly")
desktop = open(os.path.join(ROOT, "assets", "linrar.desktop")).read()
installer = open(os.path.join(ROOT, "install.sh")).read()
for long in ACTION_FLAGS:
    check(f"linrar.desktop uses {long}", long in desktop)
    check(f"install.sh uses {long}", long in installer)

shutil.rmtree(root, ignore_errors=True)
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
