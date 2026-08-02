# Changelog

All notable changes to LinRAR, newest first.

## Unreleased

### Settings for every user

- **System-wide configuration.** `/etc/linrar/linrar.conf`, its
  `conf.d/*.conf` drop-ins and any `$XDG_CONFIG_DIRS/LinRAR/linrar.conf` are
  read before the user's own file, so a machine can be set up once for
  everybody. Each layer overrides the one before; the user still has the last
  word unless the administrator says otherwise.
- **Locking.** A `[policy]` section names keys the user may not change —
  `locked=view/theme, paths/*`, with shell wildcards, or `lock_all=true` for
  every key the file sets. A locked setting keeps the administrator's value,
  ignores anything already in the user's file, and is never written back to it.
- **The interface says so.** Every menu entry, checkbox, combo and path box
  bound to a locked key is greyed out with a tooltip naming the file that
  decided it; the Settings and Customize dialogs carry a banner counting them;
  **Settings → Tools and system** lists the system files in force and how many
  settings each contributes. Nothing is clickable that would not be saved.
- **`linrar --config-info`** prints the files in play, the locked keys, and
  every effective value with the layer it came from.
- `install.sh --system` writes the file (fully commented out, so it changes
  nothing until edited); `--global-config` adds it to a user install and
  `--print-global-config` writes the template to stdout. It is never
  overwritten, and `uninstall.sh` removes it only when it is still byte for
  byte what was installed.
- Window geometry (`geometry/*`) and the config version stamp (`meta/*`) are
  deliberately outside the administrator's reach.

### Linux only, and it says so

- The application, `install.sh`, `uninstall.sh` and `run.sh` all check the
  platform first and stop with an explanation — and a suggestion of what to use
  instead — on anything but Linux. The check in `linrar/__main__.py` runs
  *before* PyQt6 is imported, so the message arrives even where Qt will not
  load. `LINRAR_ALLOW_ANY_OS=1` overrides it, loudly, for porting work.

### The installers run once

- Running `./install.sh` over a working install is refused: it prints the
  version, date, mode, project folder and launcher of what is already there,
  changes nothing, and exits `3`. `--reinstall` (or `--force`) goes ahead, and
  also repairs an install whose launcher has gone missing.
- Running `./uninstall.sh` with nothing installed is refused the same way,
  rather than sweeping the standard locations on the off chance; `--force`
  sweeps anyway.
- Both learned `--status`, which reports the state and stops.
- Both are driven by a new `.install-receipt`, written beside the project and
  copied into the data directory so a `--system` install is recognised from a
  fresh clone. An install made before receipts existed is still detected, from
  the launcher.

### Fixed

- `Settings.string_list()` now reads through the system layer like every other
  getter, and accepts the single comma-separated line a hand-written file uses.
- A `#`-commented system config can no longer set anything: Qt's INI parser
  treats `#` as an ordinary character, so those lines arrived as keys named
  `#theme`. They are dropped, and the shipped template warns about it.

## 2.0.0

The release this repository starts from: a complete WinRAR-style archive
manager, a one-command installer, and a light and dark theme of its own.

### Interface

- **Light and dark themes**, drawn by LinRAR rather than inherited from the
  desktop, with a matching build of the icon set for each. Switch from
  **Options → Theme**, the corner of the menu bar, or `Ctrl+Shift+T`.
- **Customize** (`Ctrl+U`): choose and reorder the toolbar buttons from a
  catalogue of 34 commands, set icon size and caption style; five file-list
  views (Details, List, Small icons, Large icons, Tiles) with row height, row
  separators and alternating shading; layout control over the toolbar, address
  bar, status bar, folder tree side and comment pane side.
- Every preference is remembered in `~/.config/LinRAR/linrar.conf`, including
  window geometry, splitter positions, column widths, sort order, and the
  compression and extraction options last used.
- Painted chrome glyphs (combo arrows, check boxes, radios, tree twisties,
  scrollbar arrows) so no control loses its indicator to Qt's stylesheet rules.
- Help is a real dialog with three pages; About credits the UI author.

### Archiving

- RAR5 / RAR4 / ZIP / 7z creation with six compression presets, dictionary
  sizes, volumes, solid archives, recovery records, SFX, locking, all update
  modes, encryption including encrypted file names, exclusion masks and
  comments.
- Extraction with update and overwrite modes and a *Confirm file replace*
  prompt; extraction into a folder you do not own asks for administrator
  rights and stages the files rather than running the archive tool as root.
- Convert to a self-extracting **AppImage**, built directly with `mksquashfs`.
- Recovery volumes, volume reconstruction, repair, test, batch conversion and
  TXT/CSV/HTML reports.

### System

- `install.sh` / `uninstall.sh`: virtual environment, system packages, a
  `linrar` launcher, icons at nine sizes, desktop entry, MIME associations and
  right-click entries for Dolphin, Nemo, Nautilus, Caja and Thunar. The
  uninstaller reverses all of it from a manifest and leaves the project folder.
- Twelve package managers, image-based systems (`rpm-ostree`) and NixOS are
  handled; the installer verifies the app actually starts before finishing.
- Administrator rights through `pkexec`, `sudo` or `doas`, authenticated once
  and held for the session; the password is never stored.
- Tools are located through your own setting, `PATH`, and the places distros
  and manual installs use, under every name they ship with.
- Command line: `--extract-here`, `--extract-to`, `--add`, `--test`.

### Fixed along the way

- Combo boxes, spin boxes and scrollbars lost their arrows once the chrome was
  styled: Qt stops drawing a sub-control's own glyph as soon as it is styled.
- Settings stored under a group named `general` were silently discarded on the
  next launch — Qt writes `[%General]` and reads it back as `General/…`.
- A launcher that renamed `argv[0]` broke the virtual environment: CPython
  resolves its prefix from `argv[0]`, so it fell back to the system Python and
  lost PyQt6.
- `rar a -p-` does not mean "no password" — it encrypts with the literal
  password `-`. Read commands get `-p-`; write commands get no `-p` at all.
- The Dependencies manager located tools with `PATH` alone while the rest of
  the app searched further, so a `rar` in `/opt/rar` or a Nix profile was
  reported "Missing" while LinRAR was quite happily running it.
- unrar 7 prints an `Archive comment:` heading above the comment where unrar 6
  printed it bare, so on newer distributions every archive comment gained that
  line — and gained another one each time it was edited. The heading is now
  stripped, and the listing parsers are covered by tests that feed them both
  versions' output, so a tool upgrade cannot silently change what LinRAR reads.
