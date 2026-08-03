# Changelog

All notable changes to LinRAR, newest first.

## Unreleased

### Extracting behaves the way WinRAR's does

- **Extracting no longer opens the archive in the background.** Unpacking from
  the file list, the right-click menu or the command line used to step the
  browser into the archive first, leaving the user somewhere they had not
  asked to be. The window now stays exactly where it is — same folder, same
  title, same Back history — and the listing refreshes when the files arrive.
  Testing an archive from outside behaves the same way.
- Extracting several selected archives runs them one after another and reports
  how many succeeded, instead of leaving the browser inside the last one.

### The progress window

- **The two bars finally mean two different things.** The lower bar is now
  weighted by **bytes**, as WinRAR's is: thirty small files followed by one
  large one no longer reads as "almost finished" after the small ones. It was
  previously derived from the file count, and fell back to *copying the
  per-file percentage outright* whenever the count was unknown — which is why
  both bars moved in lock step.
- **More detail, WinRAR's set:** elapsed time, time left, bytes processed of
  the total, the file count (`14 of 38`), current speed, and the live
  compression figure while an archive is being written. The bars are captioned
  *Current file* and *Total*, and the percentage is in the window title so the
  taskbar carries it.
- **Fixed: the file being worked on was named one file late.** rar rewrites a
  single terminal line per member, so the name was only read from the finished
  line; the live line is now parsed too, and the counters advance when a file
  starts rather than when it ends.
- **Fixed: `Extracting from backup.rar` was counted as a member** called "from
  backup.rar", and a percentage or `OK` printed tight against a long file name
  was read as part of the name. Both threw the file count and the byte
  accounting off.
- Building a self-extracting AppImage restarts the bars for the wrapping
  phase, rather than leaving them at 100% while work continues.

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

### An icon for every kind of file

- **The file list draws what a file is**, instead of giving everything that is
  not an archive the same blank page. Fifteen new icons — Word, Excel,
  PowerPoint, PDF, OpenDocument and EPUB, images, audio, video, source code,
  fonts, programs, databases, disc images and keys — drawn in the same style as
  the rest of the set, as a sheet with a coloured band across its foot, because
  at sixteen pixels the colour is what the eye reads.
- **Every file is identified now.** A file with no extension at all — a
  compiled program, a `README` with no suffix — used to read as "File"; its
  first bytes are read instead, so it reports what it actually is. Only files
  with nothing in the name to go on are read, the answer is remembered until
  the file changes, and a member of an archive is never read at all.
- The icon and the *Type* column come from one table, so they can never
  disagree, and selecting a single file now names it in the status bar rather
  than counting to one.

### The self-extracting dialogs, split in two

- **The AppImage options window only configures AppImages.** It used to open
  with a choice of format at the top and every page below it greyed out if you
  picked the other one. The format is gone from it: all six pages describe an
  AppImage, so that is what the window is now called and all it asks about.
- *Commands → Convert archive to SFX* asks which kind first, in a small window
  that explains the difference — and the `.sfx` stub, which takes no options at
  all, goes straight to the converter instead of through a window with nothing
  to fill in.
- On the Add dialog the kind is already a box beside the button, so pressing
  **Options…** goes straight to the AppImage settings.

### Files it does not archive, handled properly

- **The viewer shows the file, not its bytes.** It was answering anything it
  did not recognise with a hex dump; it now asks what the file is and shows
  the most useful thing it can — text in whatever encoding it turns out to be,
  images as images, and **Word, PowerPoint, Excel, OpenDocument and EPUB as
  their text**, lifted out of the XML inside them with nothing but the standard
  library. **View as hex** is still one click away, because sometimes the hex
  is what you came for.
- **What cannot be shown is at least named.** A binary now arrives as
  "Linux program or library" with its bytes below it and **Open with...** next
  to it, instead of an unexplained wall of hex.
- **A `.docx` is a ZIP archive and a document at once, and LinRAR now holds
  both ideas.** Double-clicking one opens the word processor; **Open as
  archive** in the right-click menu opens it as the ZIP it is. Previously the
  file's contents won and Word documents opened as a listing of
  `word/document.xml`. The same goes for `.xlsx`, `.pptx`, `.odt`, `.ods`,
  `.odp`, `.epub` and twenty more.
- **LinRAR no longer takes over what is not its.** Installing it made it the
  default application for everything in its MIME list; that list now has two
  halves. It claims archive formats, and it merely *offers* itself for `.jar`,
  `.apk`, `.deb`, `.rpm`, `.epub` and the office formats — all of which it can
  open, none of which it should own.
- **The Type column knows several hundred file types** instead of sixty, and
  reads them from the same table the viewer does, so the two can never
  disagree about what a file is.

### More machines, more distributions, more desktops

- **Right-click menus for four more file managers**: PCManFM, PCManFM-Qt and
  SpaceFM through the freedesktop action spec; **Pantheon Files** through
  Contractor; **Deepin**'s file manager through its menu extensions; and
  **Krusader** through its user actions, merged into the existing file with a
  backup the way Thunar's already was. With Dolphin, Konqueror, Nemo,
  Nautilus, Caja and Thunar that is ten.
- The menus offer **Test archive** as well, and their file-type lists went from
  ten extensions to over fifty — written once now, and reshaped for whichever
  punctuation each file manager wants.
- **146 distributions** are recognised, up from about forty, across **18
  package managers** — ALT Linux's apt-rpm, Mageia's urpmi, GNU Guix, OpenWrt's
  opkg, CRUX, NuTyX, SliTaz, Slackware and Clear Linux join the existing
  twelve, with package names for each.
- **Architecture is no longer assumed.** LinRAR runs wherever Python and Qt do;
  what does not is `rar`, which RARLAB publishes for four architectures, and
  the AppImage runtime, published for four others. On POWER, RISC-V, s390x or
  LoongArch the Dependencies window now says **"Not available here"** with the
  reason, rather than offering an Install button that cannot succeed, and
  building an AppImage refuses with an explanation instead of downloading a
  404. The installer names the machine, and records it in the receipt.

### LinRAR updates itself

- **Help → Check for updates.** LinRAR reads the manifest its own release
  pipeline publishes, tells you what is available and what changed in it, and
  installs it if you say so — the tarball, the launcher, the desktop entry and
  the icons, in one press.
- **It shows its working.** Seven stages, listed before the first one starts
  and ticked off as they pass; a download with a byte count, a live speed and a
  time remaining; a weighted overall bar beside the per-stage one; and a
  details pane holding every line the updater logged, with **Copy log** for
  putting it in a bug report.
- **Nothing that arrives over the network is trusted.** The download must be
  the size the release declared and must hash to the SHA-256 it published —
  verified by re-reading the file from disk rather than by trusting the bytes
  that streamed past. The archive may hold only ordinary files under its own
  folder: anything with `..` in it, an absolute path or a symlink is refused
  outright rather than sanitised.
- **A failed update leaves the version that was working.** The current install
  is copied aside before anything is replaced, and every failure — a bad
  download, a refused installer, a cancel — puts it back. The last step starts
  the newly installed copy in a fresh process and asks its version; a wrong
  answer is rolled back too, even though every individual step succeeded.
- **Automatic updates, off until asked for** (*Settings → General → Updates*):
  check at start-up, install without asking, and include pre-releases. A
  start-up check reaches the network at most once an hour however often LinRAR
  is opened, says nothing when there is nothing to say, and never turns a
  failed check into something the user has to dismiss. **Skip this version**
  puts one release aside without switching anything off.
- **It refuses what is not its to replace** — a git checkout, a folder it
  cannot write to, a system-wide install with no administrator rights — and
  says which, with the command to run instead. An administrator can lock the
  `update/` settings to decide it for a whole machine.

### Versions that a program can tell apart

- **One version, in one place.** `linrar/version.py` is now the only place a
  version number is written down; the About box, `linrar --version`, the git
  tag, the tarball's name and the installer's receipt all derive from it. It
  was previously an `APP_VERSION` constant in the middle of a dialog module,
  which `install.sh` scraped with `sed`.
- **The numbering is a promise, not decoration.** Semantic Versioning, with the
  comparison written down rather than left to whoever needs it:
  `version.is_newer()` knows that 2.10.0 is newer than 2.9.0 though the text
  says otherwise, that a pre-release ranks below the release it leads to, and
  that a version it cannot parse is never an upgrade.
- **A published release knows it is one.** Release artifacts carry a build
  stamp naming the commit they were cut from, so `version.channel()` tells a
  downloaded 2.1.0 from a working tree that calls itself 2.1.0 — and an updater
  can leave the second one alone. `install.sh` records it in the receipt too.
- **Every release publishes a description of itself.** `latest.json`, at a
  permanent address, giving the version, what changed, what it needs to run,
  and every download with its SHA-256. One request answers "is there anything
  newer, and what do I fetch": [docs/VERSIONING.md](docs/VERSIONING.md) is the
  contract, down to the updater sketch.

### Releasing, done by the pipeline

- **A release is one commit.** `tools/release.py bump patch` raises the version
  *and* moves this file's "Unreleased" section under the new number and date,
  so the two can never disagree; pushing a version that has no tag is what
  tells `.github/workflows/release.yml` to publish it. A push that does not
  change the version is never mistaken for a release.
- Nothing is published that has not passed the whole suite first, and the tag
  is created by the same call that creates the release — so a run that fails
  half way leaves no half-release behind, and can simply be run again.
- `tools/package.sh` builds the tarball reproducibly (same commit in,
  byte-identical tarball out), from tracked files only, and then **unpacks what
  it just built and asks it its version** before anybody can be offered it.
- The whole thing can also be run by hand, with the bump and an `rc` label as
  inputs, and a dry run that builds and verifies everything and publishes
  nothing.

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
