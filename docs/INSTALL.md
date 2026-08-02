# Installing LinRAR

```bash
git clone https://github.com/suryanarayanrenjith/LinRAR.git
cd LinRAR
./install.sh
linrar
```

Nothing is copied out of this folder: LinRAR runs from where you cloned it, and
the launcher points back at it. Move the folder and re-run `./install.sh`.

**Linux only — it does not run on Windows at all.** LinRAR drives the Linux
builds of `rar`, `unrar`, `7z` and `zip`, stores its settings under the XDG
base directories, and registers itself with a freedesktop.org desktop. The
installer, the uninstaller and the application all check `uname` /
`sys.platform` first and stop with an explanation (exit status 1) anywhere
else; the check in `linrar/__main__.py` runs before PyQt6 is imported, so the
message arrives even where Qt will not load. On Windows use WinRAR or 7-Zip; on
macOS use Keka or The Unarchiver. Under WSL, install inside the Linux
distribution, not on the Windows side.

## Options

| Flag | Effect |
|---|---|
| `--user` | install for the current user only — the default |
| `--system` | install for every user, under `/usr/local` (needs administrator rights) |
| `--no-deps` | do not touch system packages; set the app up only |
| `--keep-venv` | reuse the existing `.venv` instead of rebuilding it |
| `--global-config` | also write `/etc/linrar/linrar.conf`; `--system` always does |
| `--print-global-config` | print that file's template on stdout and stop |
| `--reinstall`, `--force` | install again over an existing install, or repair a broken one |
| `--status` | report whether LinRAR is installed, then stop |
| `-y`, `--yes` | assume yes, ask nothing |
| `-h`, `--help` | usage |

## It installs once

A second `./install.sh` over a working install is **refused**. It prints what
is already there — version, date, mode, project folder, launcher — changes
nothing at all, and exits with status `3`:

```
$ ./install.sh
error: LinRAR is already installed on this system.

    version     2.0.0
    installed   2026-08-02 10:25:06 +0530
    mode        user
    from        /home/you/LinRAR
    launcher    /home/you/.local/bin/linrar
    receipt     /home/you/LinRAR/.install-receipt

    Nothing has been changed.  Pick one:
      ./install.sh --reinstall   install over it again, repairing it
      ./uninstall.sh             remove it first, then install cleanly
      ./install.sh --status      show this again
```

What it goes on is a **receipt**, `.install-receipt`, written beside the
project and copied to `<data dir>/linrar/install-receipt` so that a `--system`
install is still recognised from a fresh clone. If the receipt is there but the
launcher it names is gone, the install is reported as *incomplete* and
`--reinstall` repairs it. An install made by a version older than this one has
no receipt; the launcher itself is then the evidence.

`./uninstall.sh` is the mirror image: run it when LinRAR is not installed and
it refuses with the same exit status rather than sweeping your home directory
on the off chance. `--force` sweeps anyway.

## What it puts where

A user install writes only inside your home directory:

```
~/.local/bin/linrar                                   the launcher
~/.local/share/applications/linrar.desktop            application menu entry
~/.local/share/icons/hicolor/*/apps/linrar.{png,svg}  icon, nine raster sizes
~/.local/share/pixmaps/linrar.png                     legacy icon location
~/.local/share/kio/servicemenus/linrar.desktop        Dolphin right-click menu
~/.local/share/kservices5/ServiceMenus/linrar.desktop   … older Plasma
~/.local/share/nemo/actions/linrar-*.nemo_action      Nemo right-click actions
~/.local/share/{nautilus,nemo,caja}/scripts/LinRAR*   Scripts submenu entries
~/.local/share/linrar/install-receipt                 the install receipt
~/.config/Thunar/uca.xml                              Thunar custom actions (merged)
```

Every path it creates is recorded in `.install-manifest`, which `uninstall.sh`
reads back. A `--system` install uses `/usr/local/bin` and `/usr/local/share`
instead, and adds `/etc/linrar/linrar.conf`.

Your settings live separately, in `~/.config/LinRAR/linrar.conf`, and survive
uninstalling unless you pass `--purge-settings`.

## Settings for every user

`/etc/linrar/linrar.conf` configures LinRAR for everyone on the machine. A
`--system` install writes it; from a `--user` install, add `--global-config`,
or write it yourself:

```bash
sudo ./install.sh --print-global-config > /etc/linrar/linrar.conf
```

The file ships with every setting commented out, so it changes nothing until
you edit it. See [Settings for every user](USAGE.md#settings-for-every-user)
for the format, the read order and how to lock a setting so users cannot change
it. `linrar --config-info` prints exactly what is in force and where each value
came from.

It is never overwritten, not even by `--reinstall`. On uninstall it is removed
only if it is still byte for byte what `install.sh` wrote — a file you have
edited is kept, and named, unless you pass `--purge-settings`.

## Uninstalling

```bash
./uninstall.sh                    # everything, including .venv
./uninstall.sh --keep-venv        # leave the Python environment alone
./uninstall.sh --purge-settings   # also forget your preferences and /etc/linrar
./uninstall.sh --purge-tools      # also remove unrar / rar / 7z / zip
./uninstall.sh --status           # is it installed at all?
./uninstall.sh --force            # clean up even with no receipt
```

The folder containing LinRAR is never deleted — remove it yourself when you are
done with it.

## Distributions

The installer maps its package names for:

| Manager | Distributions |
|---|---|
| APT | Debian, Ubuntu, Pop!\_OS, Mint, elementary, Zorin, Kali, Deepin, MX, Devuan, KDE neon, Raspberry Pi OS |
| DNF / YUM / DNF5 | Fedora, RHEL, Rocky, Alma, Oracle, Nobara, Mageia, OpenMandriva |
| Pacman | Arch, Manjaro, EndeavourOS, Garuda, CachyOS, Artix, ArcoLinux, SteamOS |
| Zypper | openSUSE Leap and Tumbleweed, SLE |
| APK | Alpine, postmarketOS |
| XBPS | Void |
| eopkg | Solus |
| Portage | Gentoo, Funtoo, Calculate |
| swupd | Clear Linux |
| slackpkg | Slackware |
| rpm-ostree | Silverblue, Kinoite, Bazzite, Aurora, uBlue |

**Image-based systems.** `/usr` is read-only, so packages are *layered* with
`rpm-ostree` and a `--system` install falls back to a user install
automatically.

**NixOS.** Packages are declarative, so the installer does not try. It prints
the list to add to your configuration (`python3 unrar rar p7zip zip
squashfs-tools libsecret`) and you re-run with `--no-deps`. PyQt6 from pip needs
`nix-ld` or a Python environment that already includes it.

**`rar` is shareware** and is not in every repository: Ubuntu keeps it in
*multiverse*, Fedora in *RPM Fusion nonfree*, Arch only in the AUR, and Void
not at all. Reading RAR archives only needs `unrar`; without `rar` you cannot
*create* them. Install RARLAB's own build anywhere on the system and point
LinRAR at it in **Settings → Tools and system**.

## The Dependencies manager

Everything below can be done from inside LinRAR, from **Tools → Dependencies**
or the highlighted **Deps** button on the toolbar. The README has the
[walkthrough](../README.md#setting-up-the-tools); this is the reference.

### What it drives

LinRAR builds the command from your distribution's own package manager and
runs it as root, streaming the output into the dialog:

| Manager | Install | Remove |
|---|---|---|
| APT | `apt-get install -y` | `apt-get remove -y` |
| DNF | `dnf install -y` | `dnf remove -y` |
| Pacman | `pacman -S --noconfirm --needed` | `pacman -R --noconfirm` |
| Zypper | `zypper install -y` | `zypper remove -y` |
| APK | `apk add` | `apk del` |
| XBPS | `xbps-install -y` | `xbps-install -y` |
| eopkg | `eopkg install -y` | `eopkg remove -y` |
| Portage | `emerge --noreplace` | `emerge --unmerge` |
| rpm-ostree | `rpm-ostree install --idempotent --apply-live` | `rpm-ostree uninstall` |

Nothing is run behind your back: the exact command appears in the Details pane
before it starts, and if LinRAR cannot obtain administrator rights it shows you
the command to paste into a terminal instead of failing silently.

### Administrator rights

Package changes need root. LinRAR asks once per session, through whichever
tool your system has:

- **pkexec** — your desktop's own authentication dialog. Preferred, because
  LinRAR never sees your password.
- **sudo** / **doas** — LinRAR asks for the password itself and passes it to
  the helper's standard input. It is used once and not stored; `sudo -v` is
  refreshed in the background so the authorisation survives for the session
  (about fifteen minutes past the last use).

If sudo is configured to run without a password, nothing is asked at all.
**Settings → Tools and system** chooses which tool to use if you have several.

### Status and versions

Each component is probed by running it and reading the version out of its
banner, so what you see is the tool that will actually run — not merely a
package the distribution believes is installed. The location column shows the
resolved path, which is how you confirm LinRAR picked up the `rar` you meant
when several are present.

### When a component is not packaged

`rar` is shareware: Ubuntu keeps it in *multiverse*, Fedora in *RPM Fusion
nonfree*, Arch only in the AUR, and Void does not package it at all. The
Details pane says which applies to you. If your distribution has no package:

1. Download RARLAB's Linux build from [rarlab.com](https://www.rarlab.com/download.htm).
2. Unpack it anywhere — `/opt/rar` and `~/.local/bin` are both searched
   automatically.
3. Press **Re-scan** in **Settings → Tools and system**, or point straight at
   the binary there if you put it somewhere unusual. Either way LinRAR picks it
   up without a restart.

Reading RAR archives only ever needs `unrar`, which nearly every distribution
does package.

## Finding the tools

LinRAR looks for each program in this order:

1. the path you set in **Settings → Tools and system** (empty means "search");
2. `PATH`;
3. `/usr/local/bin`, `/usr/bin`, `/opt/bin`, `/opt/rar`, `/opt/local/bin`,
   `/snap/bin`, `/usr/lib/p7zip`, `/usr/libexec/p7zip`, `~/.local/bin`,
   `~/bin`, `~/.nix-profile/bin` and the Flatpak export directories.

It accepts every name these tools ship under: `7z`, `7zz`, `7za`, `7zzs`,
`7zr`, and `unrar`, `unrar-nonfree`, `unrar-free`.

## Troubleshooting

**It does not appear in the application menu.** Some shells cache the
application list. On GNOME/X11 press <kbd>Alt</kbd>+<kbd>F2</kbd>, type `r` and
press Enter; on Wayland log out and back in. `gtk-launch linrar` starts it
directly and prints any error.

**The icon is wrong or missing.** Same cache. The installer writes nine PNG
sizes plus the SVG and refreshes `gtk-update-icon-cache`; `gio info
~/.local/share/applications/linrar.desktop` shows what the desktop actually
sees.

**`linrar: command not found`.** `~/.local/bin` is not on your `PATH`. The
installer says so when that is the case; add it to your shell profile:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

**Qt cannot start: `xcb` plugin, `libGL`, `libxcb-cursor`.** The installer
names the package to install when its final check fails. Usually:

```bash
sudo apt install libxcb-cursor0 libgl1     # Debian/Ubuntu
sudo dnf install xcb-util-cursor mesa-libGL # Fedora
sudo pacman -S xcb-util-cursor              # Arch
```

**Nothing happens when I run `linrar`.** Run it from a terminal — the error
goes to stdout. `linrar --self-test` builds the whole window offscreen and
exits, which separates "Qt cannot start" from "the app is broken".

**Right-click entries do not show.** Nautilus needs its *Scripts* submenu
(the entries are there); Dolphin and Nemo may need a restart of the file
manager (`nautilus -q`, `nemo -q`); Thunar reads `uca.xml` at startup.
