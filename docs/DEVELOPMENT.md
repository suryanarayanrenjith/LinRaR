# Working on LinRAR

## Running from source

`install.sh` is not required to develop: it only wires LinRAR into the
desktop. To run it straight from the tree:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
./run.sh                          # or: .venv/bin/python -m linrar
./run.sh ~/Downloads/thing.rar    # open an archive
```

You will also want the tools it drives:

```bash
sudo apt install unrar rar p7zip-full zip squashfs-tools libsecret-tools
sudo apt install libxcb-cursor0 libgl1     # Qt 6.5+ needs these on X11
```

## Tests

Every test file is a standalone script: no framework, nothing to install. Each
prints `N passed, M failed` and exits non-zero on failure.

```bash
python3 tests/run_all.py           # all of them, with a summary
python3 tests/run_all.py theme ui  # only files whose name matches
.venv/bin/python tests/test_theme.py   # one file, full output
```

They run headless (`QT_QPA_PLATFORM=offscreen` is set inside each file), so
they work over SSH and in CI.

| File | Covers |
|---|---|
| `test_backends.py` | rar/unrar/7z/zip: listing, extracting, creating, passwords, formats |
| `test_final.py` | volumes, recovery volumes, reconstruction, AES ZIP delegation |
| `test_sfx_appimage.py` | AppImage building, the runtime stub, `--list`/`--test` |
| `test_ui.py` | archive and extract dialogs: extensions, volumes, saved options |
| `test_dialog.py` | archive-dialog naming and volume parsing in detail |
| `test_mainwindow.py` | navigation, archive browsing, the task runner |
| `test_theme.py` | both themes, painted glyphs, themed icons, live switching |
| `test_customize.py` | toolbar/view/layout customization, elevation, CLI actions |
| `test_persistence.py` | the config file, migration, tool discovery, the installer |
| `test_config.py` | the system-wide config and its locks, the Linux check, the install guards |
| `test_diagnose.py` | format sniffing, volume detection, and the report for every kind of failure |
| `test_cli.py` | the command line: short and long forms, bad lines, `--inspect` |
| `test_navigation.py` | Back/Forward, the cursor and the tree, refusing gracefully, shortcut clashes |

Tests write to temporary directories and, where they touch settings, redirect
`XDG_CONFIG_HOME`, running them does not disturb your own configuration.
`test_config.py` also points `LINRAR_SYSTEM_CONFIG` at a scratch file, so the
real `/etc/linrar` is never read, and it only ever runs the installer script
that is going to *refuse*: whichever of install/uninstall would actually change
this machine is left alone.

## Checking the installer

The installer and uninstaller are exercised for real rather than mocked:

```bash
./install.sh --user --no-deps --keep-venv -y   # fast path, no packages
./uninstall.sh -y
```

`install.sh` finishes by running the launcher it just wrote, from `/`, under
`env -i`; the bare environment a desktop launch gets. If that fails the
install says so and names the missing library. `linrar --self-test` does the
same thing by hand: it builds the entire main window offscreen and exits.

## Where things live

```
linrar/          the application (core/ has no PyQt widget imports)
tests/           standalone test scripts + run_all.py
docs/            this documentation, with images/ for the screenshots
assets/          linrar.svg and a reference copy of the .desktop entry
tools/           release.py (version + CHANGELOG), package.sh (artifacts),
                 screenshots.py (docs/images)
linrar-ui/       the website, and LinRAR's theme generator (see below)
install.sh       everything that touches the desktop
uninstall.sh     reverses it from .install-manifest
run.sh           launch from the source tree
```

`docs/images/*.png` are taken by `tools/screenshots.py`, which drives the real
application offscreen against a demo folder it creates and deletes. Run it after
changing the chrome, the toolbar or a dialog; the images are committed, and that
script is how they are refreshed rather than a screenshot tool and a steady hand.

`themes/` is not in version control and nothing is shipped into it: it is the
folder users drop themes into. **Themes are made on the website**, not here;
`linrar-ui/src/theme-engine/` holds the derivation (a dozen seed colours in,
eighty-two out), the per-style icon renderer and the ten specs, and it serves the
gallery, the previews and the builder from one place. The format the application
reads is [THEMES.md](THEMES.md).

`assets/linrar.svg` is the application icon exported from the icon set, so the
two can never drift apart:

```bash
.venv/bin/python -c "
from PyQt6.QtWidgets import QApplication; QApplication([])
from linrar.ui import icons
open('assets/linrar.svg', 'w').write(icons.svg('app'))"
```

`assets/linrar.desktop` is documentation, not something that gets installed:
`install.sh` generates its own entry with absolute paths filled in.

## Conventions

- Standard library plus PyQt6. No other runtime dependency, so a clone works
  with one `pip install`.
- Comments explain *why*, not *what*. Several of them record a trap that cost
  real time: see [ARCHITECTURE.md](ARCHITECTURE.md#two-traps-that-cost-real-debugging-time).
- Backends raise `OperationError` with a message worth showing to a user; the
  UI never invents its own explanation of a tool's failure.
- Anything that touches the filesystem or a subprocess belongs in `core/`; only
  `ui/` may import PyQt widgets.
- New user-facing preferences need a default in `core/settings.py`, that is
  what makes them typed and persistent, and must not live in a group called
  `general`.

## Releasing

Write the change up under `## Unreleased` in
[CHANGELOG.md](../CHANGELOG.md) as you go, that section *is* the release
notes, and when it is time to publish:

```bash
tools/release.py bump patch          # or minor, major, or an exact 3.0.0
git commit -am "Release $(tools/release.py current)"
git push
```

That is the whole thing. `bump` rewrites `__version__` in
[linrar/version.py](../linrar/version.py) and moves the `## Unreleased` section
under the new number and today's date, so the two can never disagree; pushing a
version that has no tag is what
[.github/workflows/release.yml](../.github/workflows/release.yml) takes as the
instruction to publish. It runs the full suite, builds the tarball, checks that
the tarball unpacks and reports the right version, writes the update manifest,
and creates the tag and the GitHub release together.

A push that does *not* change the version is never mistaken for a release.

```bash
tools/release.py check      # would this tree release cleanly?
tools/release.py notes      # what the notes would say
tools/package.sh            # build the artifacts locally, into dist/
```

**Actions > release > Run workflow** does the bump commit for you, takes a
pre-release label (`rc`), and has a dry-run box that builds and verifies
everything without publishing.

Before a major release it is still worth doing by hand what CI cannot:
`./uninstall.sh -y && ./install.sh -y` on a clean machine or container, and
confirming the app opens from the application menu.

The numbering, the build stamp, the manifest and how an updater should read all
three are set out in [VERSIONING.md](VERSIONING.md).
