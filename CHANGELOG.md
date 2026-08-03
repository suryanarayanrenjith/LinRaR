# Changelog

All notable changes to LinRAR, newest first.

## Unreleased

## 2.1.0 — 2026-08-03

### Find reads the files, not just their names

- **The "Text to find" box does something.** It has been on the Find dialog
  all along, and nothing ever read it: the window filtered on the *name* mask
  and the text was thrown away, so typing a word and pressing Find quietly did
  nothing. Find now reads the matching files — through the current folder and
  everything under it, or through the open archive — and lists every line that
  contains the text, grouped by file, with the line numbers. **Go to file**
  takes the window to whichever one you pick.
- A name mask on its own still filters the list in place, as it did; the
  dialog says which of the two pressing Find will do before you press it.
- An archive is unpacked **once** for a search rather than once per member,
  which matters enormously on a solid archive.
- Files are rejected on their raw bytes before anything is decoded, so a
  folder of photographs costs nothing to search; one too large to search says
  so rather than being silently skipped.
- **Fixed: UTF-16 text was treated as binary.** A file written on Windows
  without a byte order mark decodes "successfully" as UTF-8 into
  `h\0e\0l\0l\0o`, so the viewer showed an ordinary README as a hex dump and
  no search could ever find a word in one.

### Checksums

- **Tools → Calculate checksums (Ctrl+K)** works out CRC32, MD5, SHA-1,
  SHA-256 and SHA-512 for the selected files — on disk or inside an archive —
  in a single pass over the bytes, so asking for five costs no more reading
  than asking for one.
- Paste a published checksum (or a whole `sha256sum` line) into the box at the
  bottom and it names the file that matches it and which algorithm it was.
- The result copies or saves either as a table of everything, or in the exact
  `sha256sum` layout, so it can be fed straight to `sha256sum -c`.

### A keyring that is not there no longer swallows passwords

- **Fixed: every password saved could vanish silently.** `secret-tool` being
  installed does not mean anything is listening — a headless server, a minimal
  desktop, a container and a CI runner all routinely have the command and no
  service behind it. It then fails with *"Could not connect"* on stderr while
  still exiting 1, which is also the perfectly ordinary "nothing stored yet".
  LinRAR's check looked for the word *"cannot"*, which that message does not
  contain, so it believed in a keyring that was not there: every password
  written went nowhere and came back empty. The probe is now a `secret-tool
  lookup`, which is silent when it works, and any complaint on stderr counts
  as a refusal.
- **A password the keyring will not take is kept anyway**, in LinRAR's own
  file, and the store stops claiming to use a keyring. Writes are verified by
  reading them back, because a write that reports success and holds nothing is
  a password that has been lost. *Organize passwords* says which storage is
  really in use, and why it changed.
- **The test runner can no longer hang.** Each file now runs under a timeout
  (`LINRAR_TEST_TIMEOUT`, 300s by default) and a file that overruns is killed
  and reported as `TIMED OUT` with everything it managed to print, so the
  check before the hang names itself. This is how the above was found: on
  GitHub's runner the missing keyring left LinRAR with no saved password, the
  archive raised a *modal* prompt, and offscreen it waited for an answer that
  could never come — the job simply stopped after `test_navigation.py` with
  nothing to say. GUI tests now count password prompts instead of showing
  them, so "LinRAR had to ask" is a failed check with a name.
- **A test file that runs no checks is reported as skipped, not as a pass.**
  One that steps aside — no AppImage runtime to build with, say — looked
  exactly like one that verified everything, which is how a file quietly stops
  testing anything without anybody noticing. The reason it gave is shown.

### Saved passwords are finally used

- **Fixed: *Tools → Organize passwords* stored passwords nobody ever read.**
  An archive a saved password would have opened still stopped and asked for
  one. Saved passwords whose mask fits the archive are now tried first, in
  order — a specific mask before a catch-all — and only when they are
  exhausted is the question asked. The status bar says when one was used.
- The password prompt has a **Remember this password** box, so saving one no
  longer means a separate trip to a management dialog.

### Dragging files out

- **Fixed: dragging out of the file list did nothing.** Dragging was switched
  on, but the list published Qt's private mime type, which no file manager
  understands. It now carries real file URLs, with the copy hint both GNOME
  and KDE read.
- Members can be dragged **out of an open archive**: they are unpacked on the
  way, and a selected folder arrives as a folder. Very large selections are
  refused with a pointer to Extract, which has a progress window and a Cancel.
- Dropping *into* LinRAR over the file list works again: the list used to
  swallow the drop before the window could act on it.

### Other fixes

- **Column widths survive a restart.** The saved header state was restored and
  then immediately overwritten by the factory widths, because the first
  listing is built after the state is read.
- **"Reset the interface" now resets the columns too** — widths, order and
  sort indicator. `QHeaderView.reset()` is the model-reset slot and does
  nothing to section sizes.
- **7-Zip archives no longer lose files when "Store full folder structure" is
  off.** 7z has no exclude-paths switch and was handed bare base names, so it
  could not find anything in a subfolder, said so as a *warning*, exited 1 and
  produced an archive quietly missing them. The files are now laid out flat in
  a scratch folder — hard-linked, so it costs nothing — and archived from
  there, using only `7z a`, the one command every build agrees about. (Doing
  it by renaming the members afterwards with `7z rn` worked on p7zip 16.02 and
  died with exit 255 on the 7-Zip release newer distributions ship.) A base
  name already taken keeps its folder rather than overwriting the other file.
- **7-Zip write commands no longer pass a bare `-p`.** What it means is not
  settled between builds — p7zip reads it as an empty password, newer 7-Zip
  as "ask me" — and a command that decides to ask, with nothing on stdin,
  dies rather than doing the work. Same rule the rar backend already follows.
- **A file 7-Zip could not read is reported.** Its scan warnings sit behind an
  exit status that archive creation has to allow, so the words are now read as
  well as the status.
- **ZIP archives the built-in reader will not touch are handed to 7-Zip** — a
  spanned archive, one behind a self-extracting stub, one with a damaged
  central directory. When neither can open it, the message says so in ZIP
  terms rather than passing through `exit code 2`.
- **The default compression profile no longer undoes the remembered
  settings.** The profile LinRAR ships as "Default" holds the factory values
  and was applied over the dialog every time, so changing the method to Best,
  making an archive and opening the dialog again put it back to Normal.
- **A profiles file written by a newer LinRAR is no longer discarded whole**
  because of one unrecognised key.
- The remembered **dictionary size** is restored again; it was saved and never
  read back.
- The **Archive dialog measures the files it actually has.** Files added on
  the Files tab were measured against the folder the dialog opened on, which
  produced `../..` member paths.
- **Properties shows the right icon for a file on disk** instead of a folder.
- An operation that outlives its progress window is now adopted and reported
  when it really finishes, instead of being announced as a success while it
  is still running.
- Toggling hidden files no longer re-reads the open archive — and no longer
  asks for its password again — for a setting that cannot change what is
  shown.
- The Customize picker knows about every toolbar button; Back, Forward,
  Update and Theme were offered without their icons.

### Small additions

- **File → Open recent** keeps the archives you opened lately, kept apart from
  the address bar's folder history.
- The status bar shows **free space** on the filesystem the current folder
  lives on, with the total and the percentage used in its tooltip.

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

### The version number keeps up with the update

- **An update replaces `linrar/version.py` underneath a running process**, so
  from that moment there are two versions on the machine: the one in memory,
  which goes on running until LinRAR is restarted, and the one on disk, which
  is what starts next time. Everything that reports a version now knows which
  of the two it means. `version.installed_version()` reads the file rather than
  the module, so it answers for the copy on disk however often it has been
  replaced.
- **The About box, Settings and the update window say both** while a restart is
  pending — *"2.0.0 — 2.1.0 is installed, restart to use it"* — rather than
  going on showing the old number as though the update had not worked.
- **Fixed: checking again after installing offered the same release twice.**
  The check compared the server's version against the one still in memory, so
  a user who updated without restarting was told the update they had just
  applied was available. It compares against what is installed now, and the
  start-up check does not run at all while a restart is pending.
- The backup folder is named after the version being replaced — the one on
  disk — so a second update in the same session no longer names it after a
  version that was overwritten an hour ago.

### Updating replaces a version rather than piling one on top of another

- **Every release carries a list of its own files**, written into it when it is
  built. An update reads the installed copy's list, so it knows precisely what
  the version it is replacing put on disk — and can delete exactly that.
- **A file the new release no longer ships is deleted.** Previously the update
  copied the new version over the old one, so a module that had been removed
  upstream lived on for ever in every install that had ever been updated.
  Folders the release dropped go with their contents, and directories the
  update empties are removed rather than left standing.
- **Stale compiled bytecode is cleared**, so a module that no longer exists
  cannot go on being importable from a leftover `.pyc`.
- **The backup and the download are removed when the update is over**, once the
  new version has proved it runs. An update used to leave a copy of the old
  version and its tarball in the cache indefinitely; now the cache is emptied,
  and anything a cancelled run left behind is cleared before the next one
  starts.
- **Files the user keeps in the project folder are never touched.** They are on
  no release's list, and the updater only removes what it recognises as its
  own. A version installed before the lists existed falls back to LinRAR's own
  folders and a fixed list of its own files, and leaves everything else alone.
- **The update checks its own work.** After installing, it looks for anything
  of the old version still in the folder; if it finds something it cannot clear,
  the whole update is rolled back rather than declared finished. There is also
  a free-space check before the download, so a full disk stops an update
  instead of interrupting one.

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
