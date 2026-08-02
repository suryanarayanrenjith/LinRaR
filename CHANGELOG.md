# Changelog

All notable changes to LinRAR, newest first.

## Unreleased

### Self-extracting archives, in one step

- **The Add dialog makes AppImages.** *Create SFX archive* now has the kind
  beside it: **AppImage** or **RAR .sfx stub**, with an **Options…** button
  for the full SFX module. One press of OK compresses *and* wraps, leaving no
  intermediate `.rar` behind. Previously an AppImage could only be reached by
  creating a `.rar`, opening it, and finding a separate command.
- **One SFX command instead of two.** *Convert to AppImage (SFX)* and *Convert
  to RAR .sfx stub* are now a single **Commands → Convert archive to SFX**
  (`Alt+S`); the dialog asks which of the two you want and explains the
  difference. The stub's pages are simply put away, since it takes no options.
- The archive name follows the choice (`.AppImage` / `.sfx` / `.rar`), volume
  splitting greys out while an AppImage is selected — it is one file — and the
  choice is remembered and saved into compression profiles.

### The interface, tidied

- **Every command appears in exactly one menu.** *Repair archive* was in both
  Commands and Tools; *Compression profiles* was in both Tools and Options.
  Repair now lives under Tools and profiles under Options, as in WinRAR.
- The *Protect and repair* submenu is gone: **Protect**, **Lock** and **Convert
  archive to SFX** sit directly in Commands where WinRAR puts them, with the
  two volume commands under a **Volumes** submenu.
- Removed a dead *Convert archive* action that only forwarded to *Convert
  archives…*.
- **Help → About** now links to the website and the source repository, next to
  the author's page.

### Opening files: it now explains itself

- **Every failure is diagnosed** (`linrar/core/diagnose.py`). Before anything
  is reported, the file is inspected: what it is (regular file, folder, device,
  dangling link), its size, whether it can be read, what its leading bytes
  really are, what its name claimed, whether it is a later part of a split set,
  which tool would open it and whether that tool is installed. The result is a
  headline, an explanation, a table of findings, concrete suggestions, and a
  block of technical detail with the hex dump, the exit code and the tool's own
  words — which **Copy report** puts on the clipboard for a bug report.
- **The fix is a button.** *Install tools…* when a tool is missing, *Open
  volume 1* for a part of a split archive, *View in LinRAR*, *Open with another
  application*, *Repair…*, or the nearest folder that still exists.
- **Fixed: a file that is not an archive opened an empty window.** `unrar lt`
  answers "…is not RAR archive" and still exits 0, and `x`/`t` exit 1, all of
  which counted as success — so a text file named `.rar` "opened" and showed
  nothing, and extracting it silently produced no files. All three now read the
  answer rather than the exit status.
- **Contents beat names.** A `.rar` that is really an HTML error page is
  reported as one instead of being blamed on a broken archive; the report says
  which of the two the format came from.
- **Fixed: nothing happened for a file the desktop cannot open.** Double-click
  now says so when no application is registered, and offers LinRAR's viewer.
- **A later volume opens the first one.** `archive.part03.rar` and
  `archive.r02` are recognised, and open the volume that carries the index.
- **More formats.** Anything 7-Zip can read is now offered rather than refused:
  `.deb`, `.rpm`, `.cpio`, `.ar`/`.a`, `.wim`, `.msi`, `.dmg`,
  `.squashfs`/`.snap`, `.lzma`, `.lz`, `.lz4`, `.arj`, `.lzh` and `.Z`.
  Signatures shared with things that are not archives (an OLE compound file is
  an `.msi` *and* every legacy Word document) only count when the name agrees.

### Browsing

- **Back and Forward**, `Alt+←` / `Alt+→`, over folders and archives alike,
  with tooltips naming where they lead and available as toolbar buttons.
- **The cursor follows the eye.** Stepping out of a folder leaves it selected
  in its parent; returning to a folder restores the row that was current there.
- **The folder tree is revealed, not rebuilt**, so the branches you opened stay
  open; it follows *Show hidden files*, and reloads one branch when a folder is
  created, renamed, deleted or pasted.
- **`Ctrl+L`** puts a path in the address bar (`~`, `$HOME` and relative paths
  all work), **`Ctrl+G`** opens the folder chooser.
- **Fixed: `Ctrl+D` did nothing.** It was bound to both *Add to favorites* and
  *Change folder*, so Qt fired neither. Favourites keeps it.
- **Fixed: F5 did not clear the find filter**, though the status bar and the
  help both said it did.
- Folder history now reaches the address bar's drop-down, which previously only
  ever listed extraction folders.
- *Extract* on the folder listing handles several selected archives at once,
  and explains a single selected file that is not one.

### Command line

- **A short form for every action**: `-x` `--extract-here`, `-X`
  `--extract-to`, `-a` `--add`, `-t` `--test`, `-c` `--config-info`, `-V`
  `--version`, `-h` `--help`. The long forms the desktop files use are
  unchanged.
- **`-i` / `--inspect`** prints the full diagnostic report for each file
  without opening a window, exiting 0 only for a file LinRAR can really open.
- **The line is parsed rather than sniffed.** Unknown options are refused with
  a suggestion of the one you meant, two actions at once are refused, an action
  with nothing to act on fails before a window opens — all with status **2** —
  and `--` ends the options. Files that do not exist are named on stderr
  instead of being silently dropped.

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
