# How LinRAR works

LinRAR is a front end. It never implements compression itself: it drives `rar`,
`unrar` and `7z` as child processes, parses what they print, and puts a WinRAR
interface on top. ZIP is the exception, reading and writing plain ZIP is done
in-process with Python's `zipfile`.

## Layout

```
linrar/               the application
├── app.py            entry point, command line actions
├── core/
│   ├── process.py    terminal emulation for rar's \b-based progress output
│   ├── backends/
│   │   ├── rar.py    rar + unrar (the primary backend)
│   │   ├── zip.py    in-process ZIP via zipfile
│   │   └── sevenzip.py  7z for every other format
│   ├── registry.py   content sniffing, format to backend, volume naming
│   ├── diagnose.py   why a file would not open, in words worth reading
│   ├── tools.py      finding rar/unrar/7z/zip wherever a distro puts them
│   ├── elevation.py  pkexec / sudo / doas, with a held authorisation
│   ├── packages.py   distribution and package-manager detection
│   ├── settings.py   layered INI: built-in < /etc/linrar < the user's file
│   ├── platform.py   the Linux-only check, made before Qt is imported
│   ├── sfx.py        AppImage builder (runtime, AppRun, squashfs, concat)
│   ├── convert.py    batch format conversion
│   ├── profiles.py   saved compression profiles
│   ├── passwords.py  keyring-backed password store
│   ├── search.py     finding text inside files and archive members
│   ├── hashes.py     CRC32/MD5/SHA digests in one pass
│   ├── report.py     TXT / CSV / HTML listings
│   ├── themes.py     finding, validating and installing theme packs
│   ├── tasks.py      QThread workers with progress signals
│   └── models.py     entries, options, errors
└── ui/
    ├── theme.py      the chrome as a Qt style sheet: two built-ins + packs
    ├── icons.py      gradient 3D SVG icon set, one build per theme
    ├── filelist.py   one model, five views, one selection
    ├── foldertree.py the folder pane
    ├── policy.py     greying out what an administrator has locked
    ├── main_window.py
    └── dialogs/      archive, extract, sfx, themes, customize, tools, ...

assets/               linrar.svg (the app icon) and a reference .desktop entry
themes/               the user's theme folder: generated into, never tracked
linrar-ui/            the website: a Vite/React landing page and /themes gallery
tools/                screenshots.py, package.sh, release.py
tests/                the suite plus run_all.py
docs/                 this documentation
install.sh            desktop wiring; uninstall.sh reverses it
run.sh                run from the source tree without installing
```

## Things worth knowing

**One place computes progress.** `TaskContext` (in `core/backends/base.py`)
owns the arithmetic behind the two bars: give it a `plan()` of member sizes,
then call `start_file()` and `advance()`, and it emits the per-file percentage,
the byte-weighted overall percentage (clamped so it can never retreat when rar
makes a second pass) and the counters. A tool that reports the *whole* job
instead of the current file, 7-Zip, calls `set_overall()` and gets the
per-file figure derived from the plan. Nothing but this class does the sums, so
every backend's bars agree.

**rar rewrites one terminal line per member.** It prints `Extracting  name`,
pads to a column, then backspaces over the tail to show ` 42%` and finally
`  OK`. So the name is on the *live* line as well as the finished one, and
reading it only from the finished one names each file as it ends. It also
prints `Extracting from archive.rar` as a header, one space, not two, which
is what `FILE_LINE_RE` uses to tell prose from a member, and when a name is
long enough to reach the status column the percentage arrives glued to it.

**Extraction never touches the browser.** `read_archive()` is the half of
opening an archive that reads it; `open_archive()` adds the half that changes
what is on screen. Extracting and testing use only the first, so the window
stays where the user left it.

**A failure is a report, not a sentence.** `core/diagnose.py` inspects the path
itself: kind, size, permissions, leading bytes, what the name claimed, the
volume it belongs to, the tool the format needs, and returns a `Problem` with
a headline, an explanation, a fact table, suggestions, technical detail and a
list of *action keys*. `ui/dialogs/problem.py` renders it and offers only the
actions the caller can carry out, so one table of handlers in `MainWindow`
serves every call site. Nothing in `diagnose.py` imports Qt, which is what lets
`linrar --inspect` print the same report from a terminal.

**Exit status is not the same as success.** `unrar lt` says "...is not RAR
archive" on stdout and exits 0; `x` and `t` say it and exit 1, which is
`EXIT_WARNING`. All three used to count as success, so a text file named `.rar`
opened an empty archive window and extracting it produced nothing at all. The
rar backend now reads the answer as well as the status.

**Names are a hint; contents are the answer.** `detect_format_source()` reports
*how* a format was decided, `content`, `sfx` or `name`, and only the first
two are treated as proof. Everything still *tries* a file that merely looks
like an archive (some old tar variants carry no signature at all), but nothing
tells the user a renamed text file is a RAR archive.

**Settings are three layers, not one file.** `DEFAULTS` in `settings.py`, then
whatever `/etc/linrar/linrar.conf` and its `conf.d` drop-ins say, then the
user's `~/.config/LinRAR/linrar.conf`: each overriding the last. A `[policy]`
section in the system layer can *lock* keys (`fnmatch` patterns, so `paths/*`
works); `Settings.set()` then returns `False` and writes nothing. That return
value is not enough on its own: a control the user can still click but that
refuses to save reads as a bug, so `ui/policy.py` disables every widget and
menu action bound to a locked key and explains why in its tooltip. `geometry/*`
and `meta/*` are outside the system layer entirely; they are state, not
preferences, and locking them would freeze the window rather than manage it.

**Qt's INI parser treats `;` as a comment and `#` as an ordinary character.**
A system config commented the shell way arrives as keys called `#theme`, so
`SystemConfig` drops any key beginning with `#` or `;` rather than acting on
it, and the shipped template says so at the top. A file that fails to parse
cleanly keeps whatever *did* parse and records the problem, which surfaces in
`linrar --config-info` and in the Settings dialog: silently ignoring an
administrator is worse than partly obeying one and saying so.

**The platform check happens before PyQt6 is imported.** `linrar/__main__.py`
calls `ensure_supported()` in its module body, above `from .app import main`.
A system LinRAR does not support is also one where the Qt wheels may not
install, and `ModuleNotFoundError: PyQt6` is a far worse explanation than the
real one. `app.main()` repeats the check, because it is imported directly too.

**Progress parsing.** `rar` reports progress by rewriting the current terminal
line with backspaces (`\b\b\b\b 42%`) and emits no newline until a file
finishes, so a `readline()` loop looks frozen. `process.py` replays `\b`, `\r`
and `\n` to reconstruct the line exactly as a terminal would render it. Because
rar makes several passes over some files its raw percentage jumps backwards, so
overall progress is derived from members completed and clamped monotonic.

**Passwords** go to the child's **stdin**, never `-p<password>` on the command
line, so they never appear in `/proc/<pid>/cmdline`. When no password is
supplied, *read* commands get `-p-` so an encrypted archive fails fast instead
of blocking on an invisible console prompt. *Write* commands must get no
password switch at all: for `rar a`, `-p-` does not mean "no password": it
silently encrypts the archive with the literal password `-`. (p7zip and
encrypted-ZIP creation are exceptions; those tools cannot read a password from
a pipe, and the code says so.)

**Overwrite prompts.** Rather than driving unrar's interactive console prompt,
conflicts are detected up front and resolved in the GUI; the decision becomes a
concrete `-o+` / `-o-` / `-or` flag plus a filtered member list.

**Zip Slip.** ZIP members are resolved against the destination and refused if
they escape it, so a crafted archive cannot write outside the target folder.

**Find has two answers, and they want different windows.** A name mask filters
the listing in place; the file list is already the right shape for that. Text
produces something the listing cannot show at all: several hits inside one
file, each with its line. So `core/search.py` returns matches and
`ui/dialogs/search.py` groups them by file. A file is rejected on its *bytes*
before it is ever decoded (the needle is encoded in a handful of likely
encodings and looked for raw), which is what keeps a folder of photographs
from costing anything; and an archive is unpacked **once**, for every member
whose name passes the mask, because there is no "read member *n*" in any of
the tools LinRAR drives.

**Saved passwords are tried before the user is asked.** `PasswordStore`
has always been able to hold a password; `_StoredPasswords` in the main window
is what makes holding one worth anything. Each candidate whose mask fits the
archive is offered once, specific masks before catch-alls, and only when they
run out does a prompt appear. Reading the store is never fatal; a keyring
that will not answer must not stop an archive from opening.

**The file list drags out, and never drops in.** `FileListModel.mimeData()`
publishes real `text/uri-list` URLs; for an archive it calls back into the
window, which unpacks the selection to a scratch folder first. Dropping is the
*window's* job, it decides between browsing a folder, opening an archive and
adding files to one, so the views are `DragOnly`. A view that accepted drops
itself would swallow them and the window would never see them.

**Administrator rights.** `elevation.py` finds pkexec, sudo or doas,
authenticates **once**, the password goes to the helper's stdin and is never
stored, and a keep-alive thread refreshes sudo's own timestamp so the rest of
the session runs without asking again. Extracting into a protected folder
unpacks to a staging folder and then moves the result into place as root, so
the archive tool never runs privileged.

**AppImage SFX.** A type 2 AppImage is a small ELF *runtime* with a SquashFS
image concatenated onto it; the runtime FUSE-mounts that filesystem and runs
`AppRun` inside. LinRAR builds one directly with `mksquashfs` plus a
concatenation: no `appimagetool` needed. It obtains the runtime stub from, in
order: its own cache, `appimagetool` if installed, any AppImage already on the
machine (the runtime size is computed from the ELF section headers, so nothing
is executed), or a one-time ~1 MB download you are asked to approve.

**Themed chrome.** Qt stops drawing a sub-control's built-in glyph as soon as
that sub-control is styled at all, which is why a styled combo box loses its
drop-down arrow. `theme.py` therefore paints the small monochrome parts
(arrows, check boxes, radios, tree twisties, scrollbar arrows) into PNGs in the
cache directory, tinted for the active theme, and hands them back to the style
sheet. If that cache cannot be written the rules are dropped and the Fusion
style keeps drawing its own.

**Icons** are inline SVG rendered on demand, so they stay sharp at any size
without shipping binary assets, and each theme gets its own build with paper
whites, steel and shadows re-tuned.

**Theme packs.** Because the chrome is built from one `Colors` record and the
icons from one `Ink` record, a theme is *data*: two colour maps, three corner
radii, a font, and optionally raw SVG for individual glyphs and a block of
style sheet. `core/themes.py` finds and validates those files and hands over
plain dictionaries; `ui/theme.py` folds one onto its declared base palette with
`dataclasses.replace` and `ui/icons.py` registers a matching icon build under
the same id. Three consequences fall out of that shape:

- **A partial theme is safe.** Anything a manifest does not mention keeps the
  built-in value, so the worst a three-line theme can do is look like the
  built-in it started from; there is no way to get black text on a black list.
- **A broken theme is not fatal, and never silent.** Every mistake becomes a
  `Problem`: four fields, not a sentence, because the four questions somebody
  has are *where*, *what did I write*, *what belongs there* and *what do I write
  instead*, and the last one carries JSON to paste. Misspelled names get a
  "did you mean" from `difflib`. A theme that cannot load at all becomes a
  `BrokenTheme`, which the manager **lists**: a theme somebody just dropped in
  and cannot find anywhere is the one failure they have no way to look into.
  The loader owns the shapes and the UI layer owns the *names*, which is why
  "no such colour: windo" is raised in `ui/theme.py` and `ui/icons.py`, where
  the field lists live, rather than in the loader, which must stay importable
  without Qt.
- **Anything that could be a theme is one.** A folder, a folder one level deeper
  (what a zip tool leaves), a folder holding one JSON file of any name, a bare
  manifest, or a zip; read *in place*, since a file already sitting in the
  themes folder should not need installing. Being clever about only one of those
  would just mean a dropped theme silently not appearing.
- **Nothing in a theme executes.** A pack is downloaded from a stranger, so
  installing a zip refuses absolute paths, `..`, symlinks and oversized members
  outright rather than partially unpacking, and only ever writes inside
  `$XDG_DATA_HOME/LinRAR/themes`; the one directory `remove` will delete from.

**Icons change with the theme in two ways.** `Ink` re-tunes what they are drawn
*with*; `icon_style` changes how they are drawn: `gloss`, `flat`, `neon` or
`soft`. That second one is deliberately not per-glyph: a flat folder beside a
glossy 3D wrench reads as a bug rather than as a theme, so the style is applied
in the primitives every glyph is built from (`_lin` collapses gradients to a
single stop, `_shadow` becomes a pass-through filter or a glow, `_gl` scales the
white highlights, `_edge` adds the hard outline a flat icon needs). All
thirty-nine move together for four small changes. The file-type bands are mixed
out of the theme's own palette for the same reason, with a fixed table of brand
colours, a themed application had a file list stuck in the built-in blues.
On top of that a theme may carry real SVG for individual glyphs, which is how the
ten on the website get their own artwork for the dozen you look at most.

`theme.mode()` and `theme.active()` answer different questions and both are
needed: a theme called `midnight-neon` is the one in force *and* is a dark theme,
and the icon build follows the first while the built-in palette it derives from
follows the second. `theme.resolve()` maps anything at all, including the id of a
theme that has since been uninstalled, onto a theme that exists.

**One button, not three.**  Changing the theme used to be reachable from a
light/dark switch, a submenu listing every theme, and the manager: three
controls for one setting, two of which could only offer two of the twelve themes
and neither of which could show you what it was about to do.  There is now a
single `act_themes`, in the menu bar's corner where the switch used to be.  That
is why `theme_actions` and `toggle_theme` are gone: a checkable entry per theme is
a menu that grows without limit and duplicates a window that already exists.

**Themes are made on the website, and `themes/` belongs to the user.** Nothing
is shipped into that folder: LinRAR has the light and dark themes drawn into it,
and every other theme is one somebody put there. The derivation that produces
them, a dozen seed colours in, eighty-two out, lives in
`linrar-ui/src/theme-engine/`, which also draws the per-style icon artwork and
holds the ten specs. One implementation serves the gallery, the previews, the
downloads and the builder at <https://linrar.vercel.app/create>, so a theme
cannot be advertised in colours its file does not have.

It used to be a Python script in `tools/`, and the port is exact: the colour maths
rounds half to even the way Python's `round()` does, which was checked field by
field across all ten themes and all their artwork before the script was deleted.
What did not survive the move is the test-suite gate that held every shipped theme
to the contrast the built-ins manage; there is nothing shipped to hold any more.
The builder does that job now, live, while somebody is still choosing.

**A tool's warning can hide a missing file.** 7-Zip reports a source it could
not read as a *scan warning*, prints it, carries on with the rest and exits 1
a status archive creation has to allow, for the ordinary "one file was
locked" case. So `_reject_missing_sources` reads the words too, and the
archive that came out short is reported rather than handed back as a success.
This is the same lesson as unrar's exit status, one tool along.

**7-Zip has no "exclude paths" switch**, and both obvious ways of faking one
are wrong. Handing it bare base names, which LinRAR used to do, leaves it
unable to find anything in a subfolder, and it reports that as a warning and
quietly builds an archive without them. Renaming the members afterwards with
`7z rn` works, but only on some builds: it is a fifteen-year-old command whose
argument handling differs between p7zip 16.02 and the modern 7-Zip releases,
and on a distribution shipping the latter it failed outright with exit 255.
So `_stage_flat` builds the layout **on disk** instead, each file hard-linked
into a scratch folder beside the archive, falling back to a copy across
devices, and only `7z a` is used, which every build agrees about. A base name
already claimed keeps its folder: losing one of two files to a silent
overwrite is worse than storing one of them under its path, and the message
says which.

**The same lesson twice: a switch whose meaning depends on the build.** A bare
`-p` is an empty password to p7zip and a request to prompt to newer 7-Zip, so
7z *write* commands are given no password switch at all when there is none:
exactly the rule the rar backend follows for `-p-`. Nothing that modifies an
archive should be able to decide to ask a question when there is nobody there
to answer it.

## Two traps that cost real debugging time

**Never name a settings group `general`.** Qt writes `general/last_folder` as
`[%General] last_folder` and a *fresh process* reads it back as
`General/last_folder`, so `value("general/last_folder")` returns nothing. It
looks fine within one process because Qt serves a cached map. LinRAR uses
`places/`, `admin/` and `meta/` instead, and `settings.py` carries the old
names forward. Test persistence across two processes, never one.

**Never give a virtual environment's Python a fake `argv[0]`.** A launcher
doing `exec -a linrar .venv/bin/python -m linrar` breaks the environment:
CPython resolves its prefix from `argv[0]`, finds no `pyvenv.cfg` beside the
launcher script, and falls back to the system interpreter without PyQt6. Set
`RESOURCE_NAME` for the X11 window class instead. The installer's final check
now runs the *launcher* from `/` under `env -i`, which is what a desktop
launch actually looks like.
