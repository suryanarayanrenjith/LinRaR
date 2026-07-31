<div align="center">

<img src="assets/linrar.svg" width="96" alt="LinRAR">

# LinRAR

**A native WinRAR for Linux.**

Clone it, run one script, and you have the classic WinRAR interface — the same
dialogs, the same keyboard shortcuts, the same right-click menu — running
natively on your desktop.

</div>

<div align="center">

<img src="docs/images/main-light.png" width="49%" alt="LinRAR, light theme">
<img src="docs/images/main-dark.png" width="49%" alt="LinRAR, dark theme">

</div>

RARLAB ships only command line binaries for Linux; there has never been a
native WinRAR GUI. LinRAR is that GUI, built with PyQt6 on top of `rar`,
`unrar` and `7z`.

---

## Install

```bash
git clone https://github.com/suryanarayanrenjith/LinRAR.git
cd LinRAR
./install.sh
```

That is the whole setup. The installer creates the virtual environment,
installs the command line tools LinRAR drives (asking for your password once),
puts a `linrar` launcher on your `PATH`, installs the icon at nine sizes, adds
LinRAR to the application menu, registers it for archive files, wires **Extract
here / Extract to… / Add to archive…** into your file manager's right-click
menu, and finishes by starting the app once to prove it works.

```bash
linrar                       # or find LinRAR in your application menu
```

| | |
|---|---|
| `./install.sh --system` | install for every user, in `/usr/local` |
| `./install.sh --no-deps` | skip the rar/unrar/7z packages |
| `./install.sh -y` | never ask anything |
| `./uninstall.sh` | remove all of it, including `.venv` |

`uninstall.sh` reverses every file the installer wrote — launcher, desktop
entry, icons, MIME defaults, right-click entries and the virtual environment —
from a manifest, and leaves the project folder itself for you to delete.

**Distributions.** APT, DNF/YUM, Pacman, Zypper, APK, XBPS, eopkg, Portage,
swupd, slackpkg, `rpm-ostree` (Silverblue, Kinoite, Bazzite) and NixOS are all
recognised, with fallbacks when a PyQt6 wheel will not build, when `venv` or
`pip` is missing, and when a Wayland session has no Qt Wayland plugin. See
[docs/INSTALL.md](docs/INSTALL.md) for the details and for troubleshooting.

## What it does

**Browsing** — browse the filesystem, step *into* an archive and keep browsing.
Folder tree, address bar, sortable columns, five view modes, column chooser,
comment pane, favourites, find, drag and drop.

**Archiving** — the full *Archive name and parameters* dialog: RAR5 / RAR4 /
ZIP / 7z, six compression presets, dictionary sizes, volumes, solid archives,
recovery records, SFX, locking, every update mode, encryption including
encrypted file names, exclusion masks, comments and saved profiles.

**Extraction** — the full *Extraction path and options* dialog, with WinRAR's
*Confirm file replace* prompt. Extracting into a folder you do not own asks for
administrator rights and stages the files rather than running the archive tool
as root.

**Commands** — Test, View, Save as, Delete, Rename, Find, Info, Properties,
Comment, Protect (recovery record), recovery volumes and reconstruction,
Repair, Lock, Convert to AppImage, batch Convert, reports.

**Themes and customization** — a light and a dark theme drawn by LinRAR itself,
a toolbar you choose the contents and order of, five file-list views, and a
layout you can rearrange. Everything is remembered between launches.

<div align="center">

<img src="docs/images/archive-dialog.png" width="43%" alt="Archive name and parameters">
<img src="docs/images/customize.png" width="52%" alt="Customize">

</div>

Full tour, keyboard shortcuts and the command line: [docs/USAGE.md](docs/USAGE.md).

## Requirements

| Component | Purpose | Required |
|---|---|---|
| Python 3.9+ and PyQt6 | the application itself | Yes (installer handles it) |
| `unrar` | read, extract and test RAR archives | Yes |
| `rar` | create and modify RAR archives | for writing RAR |
| `7z` | 7z, TAR, GZip, BZip2, XZ, ISO, CAB | optional |
| `zip` | password-protected ZIP creation | optional |
| `squashfs-tools` | building self-extracting AppImages | for SFX |
| `secret-tool` | keyring storage for saved passwords | recommended |

You do not need to install any of these by hand: `install.sh` does it, and so
does the highlighted **Dependencies** button on the toolbar, which drives your
distribution's package manager and asks for administrator rights once per
session. Plain ZIP reading and writing needs nothing at all — it is handled
in-process by Python.

## Documentation

| | |
|---|---|
| [docs/INSTALL.md](docs/INSTALL.md) | installing, distributions, file-manager integration, troubleshooting |
| [docs/USAGE.md](docs/USAGE.md) | everything the app does, shortcuts, customization, command line |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | how it works inside, and the traps worth knowing about |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | running from source, the test suite, project layout |
| [CHANGELOG.md](CHANGELOG.md) | what changed |

## Credits

UI built by **Surya** — [surya.is-a.dev](https://surya.is-a.dev/)

LinRAR's own code is MIT licensed ([LICENSE](LICENSE)). It contains no RAR
code: RAR and UnRAR are Copyright © Alexander Roshal, LinRAR simply drives
them, and it is not affiliated with win.rar GmbH.
