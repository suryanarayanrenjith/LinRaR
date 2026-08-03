# Versions, releases and updates

This is the contract. LinRAR promises to number its releases the way described
here, and to publish each one with a machine-readable description of itself, so
that a program — an updater, a packaging script, a distribution's robot — can
work out on its own whether the copy on this machine is out of date, and what
to fetch if it is.

- [The number](#the-number)
- [Where the version lives](#where-the-version-lives)
- [Which build, as opposed to which version](#which-build-as-opposed-to-which-version)
- [Cutting a release](#cutting-a-release)
- [The update manifest](#the-update-manifest)
- [The updater](#the-updater)

---

## The number

[Semantic Versioning 2.0.0](https://semver.org/), and it means something:

| Part | Changes when | Upgrading is |
|---|---|---|
| **MAJOR** `3`.0.0 | something a user relied on changed or went away — a command line flag, a settings key no longer read, a dropped format | a decision |
| **MINOR** 2.`1`.0 | new behaviour, nothing taken away | always safe |
| **PATCH** 2.0.`1` | fixes only | always safe |

A **pre-release** carries a label — `2.1.0-rc.1`, `2.1.0-beta.2` — and always
ranks *below* the release it leads to. `2.1.0-rc.9` is older than `2.1.0`.

Versions are never compared as text. `"2.10.0" < "2.9.0"` is true for strings
and false for software, which is why [`linrar/version.py`](../linrar/version.py)
exists and every comparison goes through it:

```python
from linrar.version import is_newer, compare, parse

is_newer("2.10.0", "2.9.0")                       # True
is_newer("2.1.0-rc.1", "2.0.0")                   # False — pre-releases are opt-in
is_newer("2.1.0-rc.1", "2.0.0", allow_prerelease=True)  # True
is_newer("whatever they served us", "2.0.0")      # False — refuses what it cannot read
compare("2.0.0+g1a2b3c", "2.0.0")                 # 0 — build metadata is not a version
```

## Where the version lives

In exactly one place:

```python
# linrar/version.py
__version__ = "2.0.0"
```

Everything else derives from it — the About box, `linrar --version`, the git
tag, the tarball's name, the installer's receipt and the update manifest. There
is no second copy to fall out of step, and `tests/test_version.py` fails if one
appears. `install.sh` reads the line with `sed`, so it stays on one plain line
with no computation on it.

```bash
python3 -c "import linrar; print(linrar.__version__)"   # 2.0.0
linrar --version                                        # LinRAR 2.0.0
tools/release.py current --json                         # every field, as JSON
```

## Which build, as opposed to which version

Two copies can both say `2.1.0`: the one published on the releases page, and a
working tree that has been edited since. They are told apart by a **build
stamp** — `linrar/_build.py`, written by `tools/package.sh` into the release
artifact and never committed:

```python
from linrar import version

version.channel()        # "stable", "prerelease", or "source" for a checkout
version.is_release_build()
version.build_info()     # {"commit": ..., "date": ..., "tag": ..., "version": ...}
version.full_version()   # 2.1.0+g1a2b3c  — build metadata, ignored when ranking
```

An updater should leave `source` alone: nobody published it, and replacing
somebody's working tree with a tarball would lose their work.

`install.sh` records the same thing in `.install-receipt` as `build=`, so it is
answerable without starting the application.

## Cutting a release

Releases are triggered by the version number itself. Change it, and the push
that carries the change is published; leave it alone, and nothing happens.

```bash
tools/release.py bump patch          # or minor, major, or an exact 3.0.0
git commit -am "Release $(tools/release.py current)"
git push
```

`bump` does two things at once, which is the point — the number and the notes
can never disagree:

1. rewrites `__version__` in `linrar/version.py`;
2. renames the CHANGELOG's `## Unreleased` heading to `## 2.0.1 — 2026-08-02`
   and opens a fresh empty `## Unreleased` above it.

It refuses to bump when `## Unreleased` is empty (`--allow-empty` overrides),
and refuses any number that does not come *after* the current one.

Then [`.github/workflows/release.yml`](../.github/workflows/release.yml) takes
over, and everything below happens without anybody watching:

| Stage | What it does | What stops it |
|---|---|---|
| **Plan** | reads the version, looks for its tag | the tag exists → nothing to release, and the run says so |
| | `tools/release.py check` | the CHANGELOG has no section for it, or an import disagrees with the file |
| **Verify** | the entire suite, `tests.yml` | any failing test |
| **Publish** | `tools/package.sh` builds the tarball | a tarball that will not unpack or cannot report its own version |
| | writes `latest.json`, then re-reads it and re-hashes every artifact | a checksum that does not match |
| | `gh release create --target <commit>` | — |

The tag is created *by* the call that creates the release, so a run that fails
part way through leaves no tag behind and can simply be run again.

To release by hand — including doing the bump commit for you — use **Actions →
release → Run workflow**, which takes a `bump` of `patch`/`minor`/`major`, an
optional pre-release label such as `rc`, and a **dry run** box that builds and
verifies everything and publishes nothing.

> The dispatch path pushes the bump commit to `main`. If `main` is protected
> against pushes, do the bump locally instead — the result is identical.

## The update manifest

Every release carries `latest.json`, and GitHub keeps a permanent address for
the newest one:

```
https://github.com/suryanarayanrenjith/LinRAR/releases/latest/download/latest.json
```

That URL never changes and always resolves to the newest release's copy. It is
a static download rather than an API call, so it is not rate limited the way
`api.github.com` is, and it is already in the code as
`linrar.version.MANIFEST_URL`.

```json
{
  "schema": 1,
  "app": "LinRAR",
  "version": "2.1.0",
  "tag": "v2.1.0",
  "channel": "stable",
  "prerelease": false,
  "released": "2026-08-02T10:11:12Z",
  "commit": "1a2b3c4d…",
  "requires": { "os": "linux", "python": "3.9" },
  "release_url": "https://github.com/suryanarayanrenjith/LinRAR/releases/tag/v2.1.0",
  "notes": "### What changed\n\n- …",
  "artifacts": [
    {
      "name": "linrar-2.1.0.tar.gz",
      "kind": "source",
      "size": 828092,
      "sha256": "04afb3d0…",
      "url": "https://github.com/…/releases/download/v2.1.0/linrar-2.1.0.tar.gz"
    }
  ]
}
```

| Field | Meaning |
|---|---|
| `schema` | the shape of this document. **Refuse a schema you do not know** rather than guessing — it only goes up, and only when a field changes meaning |
| `version` | the version being offered; compare it with `is_newer`, never with `==` on strings |
| `channel` | `stable` or `prerelease`; skip `prerelease` unless the user asked for them |
| `requires` | what the machine needs. Do not offer a release the interpreter cannot run |
| `notes` | the CHANGELOG section, as Markdown — enough to show "what's new" without a second request |
| `artifacts[].sha256` | verify after downloading, before unpacking. `SHA256SUMS` is published beside it and says the same thing |

The whole answer is in one file on purpose: one request tells an updater
whether there is anything newer, what changed, what to download, and how to
know the download is intact.

## The updater

[`linrar/core/updater.py`](../linrar/core/updater.py) is the consumer of
everything above, and [`linrar/ui/dialogs/update.py`](../linrar/ui/dialogs/update.py)
is the window it is shown through. What a user sees is described in
[USAGE.md](USAGE.md#keeping-linrar-up-to-date); this is what it does and why.

```python
from linrar.core import updater

updater.eligibility()       # may this copy be replaced at all?
updater.check(ctx)          # an Update, or None for "already newest"
updater.run_update(found, ctx)   # download, verify, unpack, back up, install
```

`core/updater.py` imports no PyQt and needs no display: the work runs on a
`QThread` (`core.tasks.UpdateTask`) and reports through an `UpdateContext`
shaped like the one the archive backends use — a stage, a percentage, a byte
count, a log line, and a cancellation flag checked between steps.

**Everything that arrives over the network is treated as hostile.** The
manifest's schema must be one this version knows; the version in it must parse
and must really be newer; the download must be `https`, must be the size the
manifest declared, and must hash to the SHA-256 it published — checked by
re-reading the file from disk, not by trusting the bytes that streamed past.
The tarball may contain only ordinary files and directories, all of them under
its own `linrar-<version>/` folder: a member with `..` in it, an absolute path,
a symlink or a device node is refused outright rather than sanitised, because a
member that needs sanitising has no business in a LinRAR release.

**Every step after the backup is reversible.** The current tree is copied aside
before anything is replaced, and any failure — a bad file, a refused
`install.sh`, an interrupted run, a cancel — puts it back before reporting.
The last step of an update is to start the newly installed copy in a fresh
process and ask what version it is; if that answer is wrong the update is
rolled back even though every individual step succeeded.

**It refuses what is not its to replace**, and says which: a source checkout
(`channel() == "source"`, or a `.git` folder), a project folder it cannot write
to, or a `--system` install with no way to become an administrator.
`.install-receipt` is what tells it which of those it is looking at.

### For a different updater

If you are building your own — a packaging robot, a distribution hook — the
manifest is the contract and the rules that matter are these:

- **Verify before trusting.** Check `sha256` against the downloaded file,
  before unpacking, not after.
- **Respect how LinRAR was installed.** `.install-receipt` records `mode=user`
  or `mode=system`, the project folder, and `build=` — the commit the running
  copy was cut from.
- **Never downgrade**, and never act on a version that will not parse. Both are
  already refused by `is_newer`, which is why it is the only comparison worth
  using.
- **Refuse a `schema` you do not know** instead of guessing at the fields.
