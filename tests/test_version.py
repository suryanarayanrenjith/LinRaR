"""Versioning: the number, the ranking, the bump, and the release manifest.

An updater will make its decision from these rules, so they are pinned here:
the ordering example out of the Semantic Versioning specification, what counts
as an upgrade, and the two files (linrar/version.py and CHANGELOG.md) that a
release is cut from.  Nothing in this file touches the real project's version
or CHANGELOG — the bump is exercised against a copy in a temporary directory.
"""
import json, os, re, shutil, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from linrar import version as V
from linrar.version import Version, compare, is_newer, parse, try_parse

PASS = FAIL = 0
def check(name, cond, extra=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ok  {name}")
    else: FAIL += 1; print(f"FAIL  {name}  {extra}")

RELEASE = os.path.join(ROOT, "tools", "release.py")


def release(*arguments, cwd=ROOT, expect=0):
    """Run tools/release.py and return its stdout."""
    done = subprocess.run(
        [sys.executable, os.path.join(cwd, "tools", "release.py"), *arguments],
        capture_output=True, text=True, cwd=cwd, timeout=120,
    )
    if expect is not None and done.returncode != expect:
        print(f"      (exit {done.returncode}) {(done.stdout + done.stderr).strip()[:300]}")
    return done


print("== parsing")
check("a plain version", parse("2.1.0").release == (2, 1, 0))
check("a git tag parses the same", parse("v2.1.0") == parse("2.1.0"))
check("a pre-release", parse("3.0.0-rc.1").prerelease == ("rc", "1"))
check("build metadata is kept", parse("2.0.0+g1a2b3c").build == "g1a2b3c")
check("surrounding space is tolerated", parse("  2.0.0\n") == parse("2.0.0"))
for bad in ("", "2.0", "2.0.0.0", "v", "2.0.0-", "01.0.0", "two.0.0", "2.0.0+"):
    try:
        parse(bad)
        check(f"{bad!r} is refused", False, "it parsed")
    except ValueError:
        check(f"{bad!r} is refused", True)
check("try_parse says None instead of raising", try_parse("nonsense") is None)
check("try_parse tolerates None", try_parse(None) is None)

print("\n== ranking, straight out of the specification")
# semver.org, item 11: the published ordering, which an updater depends on.
ordered = [
    "1.0.0", "2.0.0", "2.1.0", "2.1.1",
    "3.0.0-alpha", "3.0.0-alpha.1", "3.0.0-alpha.beta", "3.0.0-beta",
    "3.0.0-beta.2", "3.0.0-beta.11", "3.0.0-rc.1", "3.0.0",
]
check("the specification's own example sorts correctly",
      [str(v) for v in sorted(parse(t) for t in ordered)] == ordered,
      [str(v) for v in sorted(parse(t) for t in ordered)])
check("2.10.0 is newer than 2.9.0, though the text is not",
      parse("2.10.0") > parse("2.9.0"))
check("a release outranks its own pre-release",
      parse("3.0.0") > parse("3.0.0-rc.9"))
check("numeric identifiers rank below alphanumeric ones",
      parse("3.0.0-1") < parse("3.0.0-alpha"))
check("more identifiers outrank fewer",
      parse("3.0.0-alpha.1") > parse("3.0.0-alpha"))

print("\n== build metadata is not a version")
check("it is ignored when ranking", parse("2.0.0+build.9") == parse("2.0.0"))
check("compare() agrees", compare("2.0.0+a", "2.0.0+b") == 0)
check("and it never counts as an upgrade", not is_newer("2.0.0+newer", "2.0.0"))
check("two spellings hash alike",
      hash(parse("2.0.0+a")) == hash(parse("2.0.0")))

print("\n== is_newer: the question an updater actually asks")
check("a higher version is an upgrade", is_newer("9.9.9", "2.0.0"))
check("the same version is not", not is_newer("2.0.0", "2.0.0"))
check("a lower version is not", not is_newer("1.0.0", "2.0.0"))
check("a pre-release is refused by default", not is_newer("2.1.0-rc.1", "2.0.0"))
check("unless it is asked for",
      is_newer("2.1.0-rc.1", "2.0.0", allow_prerelease=True))
check("an unreadable version is never an upgrade",
      not is_newer("latest", "2.0.0"))
check("nor is nothing at all", not is_newer("", "2.0.0"))
check("it defaults to this build", is_newer("999.0.0") and not is_newer("0.0.1"))

print("\n== bumping")
check("patch", parse("2.0.0").bump("patch") == parse("2.0.1"))
check("minor resets the patch", parse("2.3.4").bump("minor") == parse("2.4.0"))
check("major resets both", parse("2.3.4").bump("major") == parse("3.0.0"))
check("a pre-release becomes the release it led to",
      parse("2.1.0-rc.2").bump("minor") == parse("2.1.0"))
check("and does not skip a number",
      parse("2.1.0-rc.2").bump("patch") == parse("2.1.0"))
try:
    parse("2.0.0").bump("everything")
    check("an unknown part is refused", False)
except ValueError:
    check("an unknown part is refused", True)

print("\n== this tree")
check("the version parses", isinstance(V.VERSION, Version))
check("VERSION and __version__ agree", str(V.VERSION) == V.__version__)
check("the tag is the version with a v", V.tag() == f"v{V.__version__}")
check("a checkout calls itself source", V.channel() == "source",
      V.channel())
check("a checkout carries no build stamp", V.build_info() == {})
check("describe() starts with the bare version",
      V.describe().split()[0] == V.__version__, V.describe())
check("full_version() is a legal version",
      try_parse(V.full_version()) is not None, V.full_version())

print("\n== one place, and only one")
source = open(os.path.join(ROOT, "linrar", "version.py")).read()
check("version.py declares it on one plain line, as install.sh's sed needs",
      bool(re.search(r'^__version__ = "[^"]+"$', source, re.MULTILINE)))
check("version.py imports no PyQt, so a headless machine can read it",
      re.search(r"^\s*(import|from)\s+PyQt", source, re.MULTILINE) is None)

misc = open(os.path.join(ROOT, "linrar", "ui", "dialogs", "misc.py")).read()
check("the About box no longer keeps its own copy",
      not re.search(r'^APP_VERSION = "', misc, re.MULTILINE))
check("it takes it from version.py", "from ...version import" in misc)

install = open(os.path.join(ROOT, "install.sh")).read()
check("install.sh reads the version out of version.py",
      "linrar/version.py" in install and "__version__" in install)
check("and records which build was installed", "build=%s" in install)
check("the receipt's version is still written", "version=%s" in install)

floor = re.search(r"sys\.version_info >= \((\d+), *(\d+)\)", install)
check("install.sh's Python floor matches REQUIRES_PYTHON",
      bool(floor) and f"{floor.group(1)}.{floor.group(2)}" == V.REQUIRES_PYTHON,
      floor.group(0) if floor else "no floor found")

ignored = open(os.path.join(ROOT, ".gitignore")).read()
check("the build stamp is never committed", "linrar/_build.py" in ignored)

print("\n== the update manifest's addresses")
check("the manifest URL always points at the newest release",
      V.MANIFEST_URL.endswith("/releases/latest/download/latest.json"),
      V.MANIFEST_URL)
check("every URL is built from PROJECT",
      all(V.PROJECT in url for url in
          (V.REPOSITORY_URL, V.RELEASES_URL, V.LATEST_RELEASE_API, V.MANIFEST_URL)))
check("the schema is a whole number", isinstance(V.MANIFEST_SCHEMA, int))

print("\n== tools/release.py, against a copy of the project")
sandbox = tempfile.mkdtemp(prefix="linrar-release-")
os.makedirs(os.path.join(sandbox, "linrar"))
os.makedirs(os.path.join(sandbox, "tools"))
for source_path, target in (
    (os.path.join(ROOT, "linrar", "version.py"), "linrar/version.py"),
    (os.path.join(ROOT, "linrar", "__init__.py"), "linrar/__init__.py"),
    (RELEASE, "tools/release.py"),
):
    shutil.copy(source_path, os.path.join(sandbox, target))

CHANGELOG = os.path.join(sandbox, "CHANGELOG.md")
with open(CHANGELOG, "w") as handle:
    handle.write(
        "# Changelog\n\nAll notable changes, newest first.\n\n"
        "## Unreleased\n\n### A heading\n\n- Something a user would notice.\n\n"
        "## 2.0.0\n\nThe first one.\n"
    )

current = release("current", cwd=sandbox)
check("current prints the version", current.stdout.strip() == V.__version__,
      current.stdout)
check("--tag prints the tag",
      release("current", "--tag", cwd=sandbox).stdout.strip() == V.tag())
check("--json carries the channel",
      json.loads(release("current", "--json", cwd=sandbox).stdout)["channel"]
      == "stable")

# Worked out from whatever this tree's version happens to be, never written
# down: releasing LinRAR must not mean editing its tests, and a hard-coded
# "2.0.1" here would fail the day the version moved -- which is the one day
# these checks most need to be passing.
NEXT_PATCH = str(V.VERSION.bump("patch"))
NEXT_MINOR = str(V.VERSION.bump("minor"))

dry = release("bump", "patch", "--dry-run", cwd=sandbox)
check("a dry run says what it would do", NEXT_PATCH in dry.stdout, dry.stdout)
check("and writes nothing",
      V.__version__ in open(os.path.join(sandbox, "linrar/version.py")).read())

check("a version that does not go up is refused",
      release("bump", "1.0.0", cwd=sandbox, expect=1).returncode == 1)
check("the same version again is refused",
      release("bump", V.__version__, cwd=sandbox, expect=1).returncode == 1)
check("nonsense is refused",
      release("bump", "soon", cwd=sandbox, expect=1).returncode == 1)
check("build metadata may not be written into the source",
      release("bump", "9.9.9+g1a2b3c", cwd=sandbox, expect=1).returncode == 1)

bumped = release("bump", "minor", "--date", "2026-01-01", cwd=sandbox)
check("a real bump reports the move", NEXT_MINOR in bumped.stdout, bumped.stdout)
check("version.py was rewritten",
      f'__version__ = "{NEXT_MINOR}"' in
      open(os.path.join(sandbox, "linrar/version.py")).read())

changelog = open(CHANGELOG).read()
check("the CHANGELOG gained a dated heading for it",
      f"## {NEXT_MINOR} — 2026-01-01" in changelog, changelog[:200])
check("an empty Unreleased section was opened above it",
      changelog.index("## Unreleased") < changelog.index(f"## {NEXT_MINOR}"))
check("the notes moved under the new number, none of them lost",
      "- Something a user would notice." in
      changelog[changelog.index(f"## {NEXT_MINOR}"):changelog.index("## 2.0.0")])
check("the older release is untouched", "## 2.0.0" in changelog)

check("bumping again refuses, because Unreleased is empty now",
      release("bump", "patch", cwd=sandbox, expect=1).returncode == 1)
check("--allow-empty is the way to say you meant it",
      release("bump", "patch", "--allow-empty", "--dry-run",
              cwd=sandbox).returncode == 0)

notes = release("notes", cwd=sandbox)
check("notes prints the new section",
      "Something a user would notice" in notes.stdout, notes.stdout[:120])
check("notes for an older version still work",
      "The first one." in release("notes", "2.0.0", cwd=sandbox).stdout)
check("notes for a version nobody documented fails",
      release("notes", "9.9.9", cwd=sandbox, expect=1).returncode == 1)

checked = release("check", cwd=sandbox)
check("check passes on a consistent tree", checked.returncode == 0,
      checked.stdout[-300:])
check("check notices there is no git checkout to ask about tags",
      "not a git checkout" in checked.stdout)

print("\n== the manifest an updater reads")
dist = os.path.join(sandbox, "dist")
os.makedirs(dist)
with open(os.path.join(dist, f"linrar-{NEXT_MINOR}.tar.gz"), "wb") as handle:
    handle.write(b"not really a tarball, but it hashes just the same")
with open(os.path.join(dist, "SHA256SUMS"), "w") as handle:
    handle.write(f"0  linrar-{NEXT_MINOR}.tar.gz\n")

made = release("manifest", "--dir", dist, "--commit", "a" * 40,
               "--date", "2026-01-01T00:00:00Z", cwd=sandbox)
check("manifest writes latest.json", made.returncode == 0, made.stderr[-200:])
manifest = json.load(open(os.path.join(dist, "latest.json")))

check("it declares its schema", manifest["schema"] == V.MANIFEST_SCHEMA)
check("it names the version", manifest["version"] == NEXT_MINOR)
check("and the tag", manifest["tag"] == f"v{NEXT_MINOR}")
check("and the commit", manifest["commit"] == "a" * 40)
check("and the channel", manifest["channel"] == "stable")
check("it says what it needs to run",
      manifest["requires"] == {"os": "linux", "python": V.REQUIRES_PYTHON})
check("it carries the release notes",
      "Something a user would notice" in manifest["notes"])
check("it lists both artifacts", len(manifest["artifacts"]) == 2,
      manifest["artifacts"])
check("but never itself",
      all(a["name"] != "latest.json" for a in manifest["artifacts"]))

import hashlib
for artifact in manifest["artifacts"]:
    body = open(os.path.join(dist, artifact["name"]), "rb").read()
    check(f"{artifact['name']}: the checksum is right",
          artifact["sha256"] == hashlib.sha256(body).hexdigest())
    check(f"{artifact['name']}: the size is right",
          artifact["size"] == len(body))
    check(f"{artifact['name']}: the URL points at this release",
          artifact["url"].endswith(f"/download/v{NEXT_MINOR}/{artifact['name']}"),
          artifact["url"])
check("the tarball is recognised as source",
      [a["kind"] for a in manifest["artifacts"] if a["name"].endswith(".tar.gz")]
      == ["source"])
check("and the checksums as checksums",
      [a["kind"] for a in manifest["artifacts"] if a["name"] == "SHA256SUMS"]
      == ["checksums"])

check("a version that is newer than this tree's is an upgrade",
      is_newer(manifest["version"], V.__version__))

print("\n== a prerelease travels as one")
# The sandbox is on NEXT_MINOR by now, so an rc series starts from the one
# after that -- again worked out rather than written down.
RC_BASE = str(V.parse(NEXT_MINOR).bump("minor"))
release("bump", "minor", "--pre", "rc", "--allow-empty", cwd=sandbox)
check("the version gained the label",
      f'__version__ = "{RC_BASE}-rc.1"' in
      open(os.path.join(sandbox, "linrar/version.py")).read())
state = json.loads(release("current", "--json", cwd=sandbox).stdout)
check("and is reported as a prerelease", state["prerelease"] is True, state)
check("with the channel to match", state["channel"] == "prerelease")
release("bump", "minor", "--pre", "rc", "--allow-empty", cwd=sandbox)
check("a second rc continues the series rather than starting one",
      f'__version__ = "{RC_BASE}-rc.2"' in
      open(os.path.join(sandbox, "linrar/version.py")).read())
check("a bad label is refused",
      release("bump", "patch", "--pre", "1", "--allow-empty",
              cwd=sandbox, expect=1).returncode == 1)

shutil.rmtree(sandbox, ignore_errors=True)

print("\n== the pipeline is wired to all of this")
workflow = open(os.path.join(ROOT, ".github/workflows/release.yml")).read()
check("release.yml runs on a push to main", "branches: [main]" in workflow)
check("it can also be started by hand", "workflow_dispatch:" in workflow)
check("it publishes nothing without the suite",
      "uses: ./.github/workflows/tests.yml" in workflow)
check("the publish job waits for that verification",
      "needs: [plan, verify]" in workflow)
check("it runs the releasable check", "tools/release.py check" in workflow)
check("it builds with the packager", "tools/package.sh" in workflow)
check("it attaches the update manifest", "release.py manifest" in workflow)
check("the tag is created with the release, not before",
      "--target" in workflow)
check("one release at a time", "concurrency:" in workflow)
check("and an interrupted one is never cancelled",
      "cancel-in-progress: false" in workflow)

suite = open(os.path.join(ROOT, ".github/workflows/tests.yml")).read()
check("tests.yml can be called by release.yml", "workflow_call:" in suite)

packager = open(os.path.join(ROOT, "tools", "package.sh")).read()
check("the packager ships tracked files only", "git ls-files" in packager)
check("it stamps the build", "_build.py" in packager)
check("it pins every timestamp", "SOURCE_DATE_EPOCH" in packager)
check("it proves the artifact before anybody is offered it",
      "import linrar" in packager and "does not unpack" in packager)
check("it writes checksums", "SHA256SUMS" in packager)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
