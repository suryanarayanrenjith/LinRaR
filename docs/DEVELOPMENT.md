# Working on LinRAR

## Running from source

`install.sh` is not required to develop — it only wires LinRAR into the
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

Tests write to temporary directories and, where they touch settings, redirect
`XDG_CONFIG_HOME` — running them does not disturb your own configuration.

## Checking the installer

The installer and uninstaller are exercised for real rather than mocked:

```bash
./install.sh --user --no-deps --keep-venv -y   # fast path, no packages
./uninstall.sh -y
```

`install.sh` finishes by running the launcher it just wrote, from `/`, under
`env -i` — the bare environment a desktop launch gets. If that fails the
install says so and names the missing library. `linrar --self-test` does the
same thing by hand: it builds the entire main window offscreen and exits.

## Where things live

```
linrar/          the application (core/ has no PyQt widget imports)
tests/           standalone test scripts + run_all.py
docs/            this documentation, with images/ for the screenshots
assets/          linrar.svg and a reference copy of the .desktop entry
install.sh       everything that touches the desktop
uninstall.sh     reverses it from .install-manifest
run.sh           launch from the source tree
```

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
  real time — see [ARCHITECTURE.md](ARCHITECTURE.md#two-traps-that-cost-real-debugging-time).
- Backends raise `OperationError` with a message worth showing to a user; the
  UI never invents its own explanation of a tool's failure.
- Anything that touches the filesystem or a subprocess belongs in `core/`; only
  `ui/` may import PyQt widgets.
- New user-facing preferences need a default in `core/settings.py` — that is
  what makes them typed and persistent — and must not live in a group called
  `general`.

## Releasing

1. Update [CHANGELOG.md](../CHANGELOG.md) and `APP_VERSION` in
   `linrar/ui/dialogs/misc.py`.
2. `python3 tests/run_all.py` — everything green.
3. `./uninstall.sh -y && ./install.sh -y` on a clean machine or container, and
   confirm the app opens from the application menu.
4. Tag the commit.
