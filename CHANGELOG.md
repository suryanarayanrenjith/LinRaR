# Changelog

All notable changes to LinRAR, newest first.

## Unreleased

## 2.5.0 - 2026-08-06

### Themes you can install, like WinRAR's

- **Options > Themes... (`Ctrl+Shift+M`)** is a theme manager. It lists the two
  built-in themes, **ten new ones that ship with LinRAR**, and anything you
  install yourself.
- **The preview is real.** Selecting a theme shows a working miniature of the
  main window, toolbar, list pane, column headers, group box, buttons, progress
  bar, status bar, wearing that theme, beside a window still wearing the old
  one. It is not a drawing of the theme: the same style sheet that would restyle
  the window is set on the preview subtree, so what you see is what Apply does.
  **Apply** repaints the application and leaves the dialog open, **Cancel** puts
  back the theme that was in force when it opened.
- **A theme changes everything the built-ins do.** Every surface, edge,
  gradient, selection and hover colour; the corner radii, so *Classic Silver*
  is hard-square and *Sakura Blossom* is round; the font; and **the icon set**,
  which is *redrawn* in the theme's colours rather than tinted, because the
  icons are SVG built from a palette record. A theme can also replace individual
  icons outright with SVG of its own and append style sheet rules that override
  everything else.
- **The ten:** *Midnight Neon*, *Nord Frost*, *Dracula Purple*, *Graphite
  Steel* and *Crimson Noir* (dark); *Solarized Sand*, *Forest Canopy*, *Sakura
  Blossom*, *Classic Silver*, the beige and navy of Windows 95, which is what
  WinRAR looked like when it was new, and *Arctic Paper* (light). Five of
  each.
- **Installing one** is **Install theme file...**, or dropping it on the window:
  a `.linrar-theme` file, a zip of a theme folder, or a bare `theme.json`. It
  lands in the themes folder **Open themes folder** opens, which is the only
  place **Remove** will ever delete from. A copy there shadows a system-wide one
  of the same name.
- **Nothing in a theme is executed**; it is two colour maps and some numbers.
  A zip that holds an absolute path, a `..`, a symbolic link or an absurdly
  large member is refused outright rather than partly unpacked, and a theme is
  loaded back from where it landed before the install is reported as having
  worked.
- **A theme with mistakes in it still works.** `base` says which built-in to
  start from and everything a manifest leaves out keeps that theme's value, so
  a ten-line theme is a perfectly good theme and there is no way to end up with
  black text on a black list. A bad colour, a gradient triple written as one
  value, a radius of 99: each is skipped, named, and shown under the preview;
  one typo costs one value rather than the theme.
- The theme is still one setting (`view/theme`), so an administrator can name a
  pack for every user of a machine and lock it, and every way of changing it,
  the Themes button, the Settings combo, the manager itself, greys out
  together. A theme the settings file names but nobody installed falls back to
  the light theme instead of failing to start.
- **Settings > General** lists every theme with a preview of its icons, and has
  a **Themes...** button through to the manager. **Themes** is also available as
  a toolbar button from Customize.
- `themes/` is **not** in version control: it is data you install, edit and
  delete, and nothing is shipped into it. The ten are downloaded from the site,
  see *The theme generator now lives on the website*, below, and
  [docs/THEMES.md](docs/THEMES.md) documents the format.
- All ten were held to the contrast the built-in themes themselves manage,
  capped at WCAG AA: that is how four genuinely unreadable spots were found and
  fixed before any of them shipped, among them a progress bar whose percentage
  vanished into the bar. The theme builder now runs the same check live.

### Themes, part two: dropping one in, and being told what is wrong with it

- **Drag a theme onto the Themes window to install it.** A folder or a file,
  however many at once. The window carries a card saying so and naming the
  folder they are kept in, because a drop target nobody knows about is not a
  feature; dropping into that folder in a file manager works just as well.
- **Anything in a themes folder that could be a theme is now treated as one:**
  a folder, a folder one level deeper (which is what a zip tool leaves behind),
  a folder holding a single JSON file of any name, a bare manifest, or a zip,
  and a zip is read **in place**, because a file already sitting in the themes
  folder should not have to be installed. `.linrar-theme`, `.theme`, `.zip` and
  `.json` are all recognised.
- **`themes/` beside the application is now the folder themes go into**, when it
  is writable, and it is searched *last*, so a theme you dropped in beats one
  installed for the whole machine. On a system-wide install, where that folder
  belongs to root, it falls back to `~/.local/share/LinRAR/themes` and nothing
  anywhere assumes which of the two it is.
- **A theme that will not load is now listed rather than ignored.** It appears
  under *needs fixing* with the whole diagnosis: bad JSON says which line and
  column and names the four things that usually cause it; a folder with no
  manifest says where to put one; a theme calling itself "dark" says to rename
  it. **Copy report** and **Delete this file** are right there, and **Rescan**
  picks up the fix. A theme nobody can find is the one failure that cannot be
  debugged, so silence was the worst possible answer.
- **Every mistake now says how to fix it.** Four fields rather than a sentence,
  where it is, what you wrote, what belongs there, and a line of JSON to paste
  instead, with a *did you mean* for a misspelled name (`"windo"` becomes `window`),
  a worked `[light, mid, dark]` triple built from the colour you actually wrote,
  and a note that colour *names* are refused because they differ between
  systems. A radius written among the colours is told to move to `metrics`
  rather than reported as an unknown colour.
- **The manager is now hard to miss:** the palette button in the menu bar's
  corner, `Ctrl+Shift+M`, a button in Settings, and **Options > Themes...**.
- **Every icon follows the theme, not just some.** A theme picks an
  `icon_style`: `gloss` (the built-in 3D look), `flat` (no gradients or
  shadows at all, with a hard outline), `neon` (lit from inside) or `soft`, and
  it applies to **all thirty-nine** glyphs at once, because a flat folder next
  to a glossy 3D wrench reads as a bug rather than as a theme. Each of the ten
  themes also carries real SVG artwork of its own for the fourteen glyphs you
  look at most, drawn from one geometry description and four style renderers.
- **Fixed: the file-type icons never really changed with the theme.** Their
  coloured bands came from a fixed table of brand colours, so however far a
  theme moved, the file list stayed in the built-in blues and greens. They are
  now mixed out of the theme's own palette, with the shades pushed apart so
  fifteen kinds of file are still told apart by six inks.
- The two built-in themes are untouched by all of this, and `assets/linrar.svg`
  was re-exported from the icon set so the shipped application icon still
  matches it exactly.

### One button for how LinRAR looks

- **The light/dark switch is gone, and so is the Theme submenu.** There were
  three ways to change one setting and two of them only ever offered two of the
  twelve themes. What is left is a single **Themes** button, in the menu bar's
  corner where the switch used to be, plus **Options > Themes...** and
  `Ctrl+Shift+M`, which are the same command. It opens the manager, where every
  theme is listed and each one is previewed before it is applied.
  `Ctrl+Shift+T` no longer does anything.
- **Not on the toolbar either**, as it ships: the corner button is already
  there, and a second button for the same command beside *Dependencies* was one
  too many. Customize can still put it on the toolbar for anybody who wants it.
- The button's tooltip names the theme in use, so the thing the switch used to
  tell you at a glance is still there to read.
- Light and Dark are of course still themes; they are the first two rows of the
  manager, as they always were.

### themes/ belongs to you

- **Nothing is shipped into `themes/` any more, not even a README.** It is the
  folder you drop themes into, and a file of documentation sitting among them was
  never anybody's idea of tidy. The format is documented in
  **[docs/THEMES.md](docs/THEMES.md)** instead, and `.gitignore` excludes the
  folder and everything in it explicitly.
- The ten themes are **downloaded from the site** rather than written into it.

### The theme generator now lives on the website

- **`tools/make_themes.py` is gone.** The whole of it, the colour maths, the
  eighty-two-colour derivation, the four-style icon renderer, the ten theme specs
  and the manifest writer, is now `linrar-ui/src/theme-engine/`, in TypeScript,
  and it runs in the browser.
- **The port is exact.** Every field of all ten themes, their icon palettes and
  all their generated artwork was compared against the Python output before the
  script was deleted, and the only differences were rounding: `Math.round` rounds
  a half up, Python's `round()` rounds half to even. The TypeScript now does the
  same, so a theme built in the browser is the same file the command line would
  have produced.
- **New `/create` route: a theme builder.** Thirteen colours in, a whole theme
  out. Pick the surfaces, the accents and the icon inks; choose light or dark, one
  of four icon styles and three corner radii; watch a miniature of the window
  repaint as you go, and download the `.linrar-theme` when it looks right. Any of
  the twelve existing themes can be loaded as a starting point.
- **It checks legibility while you choose.** The same seventeen colour pairs the
  application's test suite used to hold the shipped themes to are checked live, so
  a progress bar whose percentage vanishes into it is caught before anybody
  downloads the theme rather than after.
- The download is a single JSON file named `.linrar-theme`, with the icon artwork
  inside it under `icon_svg`; LinRAR reads that as a theme directly, so there is
  no archive to build in the browser and nothing to unpack at the other end.
- Nothing on the site is pre-generated any more: `src/themes.generated.ts` and the
  ten packed downloads are gone, and the gallery, the previews, the downloads and
  the builder all call one `build()`. A theme cannot be shown in colours its file
  does not have. `install.sh` no longer generates anything into `themes/` either;
  that folder starts empty, and themes come from the site.
- **What was lost, stated plainly:** the test-suite gate that held every shipped
  theme to the contrast the built-ins manage. There is nothing shipped to hold any
  more, so `tests/test_themes.py` now checks the loader against themes it writes
  itself, and the legibility job moved to the builder.

### linrar-ui: a themes page, and a shorter front page

- **New `/themes` route** listing all ten themes with a working miniature of the
  window in each one: painted from the theme's real palette and radii, with the
  real icons the application's own engine drew for it. Filter by light or dark,
  and download any of them as a `.linrar-theme` file.
- Everything on that page comes from one call: the same `build()` that produces
  the download produces the preview, so a preview cannot advertise colours the
  file does not have.
- **The landing page went from twelve sections to six**; what it is, what it
  does, what it opens, themes, how to get it, get it. The problem statement, the
  dependency table, the file-manager list, the terminal reference, the distro
  grid, the tech-stack strip and the FAQ were all true and all documentation,
  which is what the README and `docs/` are for.
- Routing is about ninety lines rather than a dependency: two routes, real
  anchors that stay middle-clickable, and a `vercel.json` rewrite so `/themes`
  survives a hard refresh.
- **The window in the hero is painted from real theme data.** It used to carry
  two hand-sampled colour blocks and a sun/moon switch: a control the
  application no longer has. The palette now arrives from
  `themes.generated.ts`, including the two built-ins, so the mock cannot show a
  shade LinRAR has stopped using; and the button in its menu bar is the palette,
  which steps the window through five of the real themes. What the mock still
  draws in the site's own line-art is the *icons*: thirty-nine real SVGs twelve
  times over is most of a megabyte for one hero image, and the /themes page is
  where the genuine icons are.

### The site, tidied

- **One Themes button in the app means one in its picture too:** the window in the
  hero no longer has a light/dark switch. The palette in its menu bar steps
  through five real themes instead, and its chrome is painted from real theme
  data.
- The two sub-pages shared a masthead written twice; it is one set of global
  classes now, so they cannot drift apart. Route changes fade rather than snap,
  links to another *page* are pills where links to a *section* are underlines, and
  the scrollbar belongs to the page rather than to the browser.

### Every screenshot is taken by a script

- `tools/screenshots.py` drives the real application offscreen against a demo
  folder it creates and deletes, and writes all twelve images in `docs/images`.
  No mock-ups, no editing afterwards, and no way for a screenshot to show a
  window LinRAR does not build. `docs/DEVELOPMENT.md` says to run it after
  changing the chrome, the toolbar or a dialog.
- **Every screenshot has been retaken** for the new chrome, and the old ones are
  gone. Two are new: the Themes window previewing a theme, and a theme that
  will not load showing what to fix.
- It shoots with the folder tree switched off, and that is deliberate: the tree
  is real, it lists the siblings of every ancestor, and no amount of framing
  stopped it filling with whatever else was on the machine that took the
  picture. A committed image is not the place for somebody's other project
  names.

### Passwords stay out of the process table

- **An archive password is no longer visible to other accounts.** Creating an
  encrypted ZIP ran `zip -P <your password>`, and creating an encrypted 7z ran
  `7z -p<your password>`. On a stock Linux any other account on the machine can
  read `/proc/<pid>/cmdline`, so for as long as the command ran the password
  was there for the taking. Both tools will instead *ask* for it if they have a
  terminal, so LinRAR now gives the child one of its own and types the answer.
- **An archive that came out unencrypted is destroyed rather than handed back.**
  Driving a tool through a prompt is only worth doing if the result is checked,
  so a newly encrypted archive is read back and every file in it has to really
  be encrypted. One that is not is deleted, and the message says to use RAR.
- Reading an existing encrypted 7z archive still passes the password in the
  command line, because 7-Zip offers no other way in: a bare `-p` means "ask
  me" to `7z a` and "the empty password" to `7z x`, with no prompt at all. RAR
  takes its password on standard input for every command, which is why the
  format selector recommends it.
- **`~/.config/LinRAR/linrar.conf` is now created 0600, in a 0700 folder.** It
  records the folders you have been in, the archives you opened, and, on a
  machine with no keyring, your saved archive passwords. Qt wrote it with the
  process umask, which on most distributions left it readable by everyone.

### Archives from strangers are treated as such

- **A symbolic link that points out of the extraction folder is refused.** A
  ZIP could carry a link to `/etc` or to `../..`; it was recreated as-is, which
  left a trap in a folder you might pass on, and could route a later member's
  contents through it. `unrar` has always refused these and now so does LinRAR.
- **An archive claiming millions of files is turned away with a sentence**
  rather than filling memory while the window is still opening.
- **A member whose name begins with a dash can no longer become a rar switch.**
  `rar` has no `--` to end its options, and renaming inside an archive is the
  one command that passes member names on the command line.
- **The updater will not be walked down to plain HTTP.** It refused an
  `http://` address in the manifest, but followed a redirect to one without a
  word. Downloads are also capped, the download name has to be a plain file
  name, and the checksum has to be hexadecimal.
- **Release notes are no longer trusted with a link.** They arrive over the
  network and were rendered with every link armed; only `http` and `https` are
  followed now, and the release URL is escaped before it goes into the pane.
- An `install.sh` that produced no output during an update could be waited on
  for ever. The timeout is now enforced whether or not the script says anything.

### Faster

- **Starting up no longer repaints the whole theme.** Every one of the
  thirty-eight small glyphs Qt needs (arrows, check boxes, radios, tree
  twisties) was redrawn and rewritten to disk on every launch, on every theme
  change, and once per step through the Theme Manager's list. They are painted
  once per theme and kept.
- **The toolbar no longer runs every archive tool to draw itself.** Deciding
  whether to put a warning on the Dependencies button ran `rar`, `unrar`, `7z`
  and the rest to ask their versions, up to eighteen process launches, every
  time the toolbar was rebuilt. It now only looks for them.
- **A folder of ten thousand files scrolls without re-deciding what everything
  is.** A row's type and icon were worked out afresh every time Qt painted it,
  and again for every comparison when sorting by Type.
- Opening an archive asked the keyring for every saved password, once per
  saved password, whether or not the archive was even encrypted.
- Selecting files, expanding a folder selection, identifying a file's format,
  and finding where a member was unpacked to were all doing work proportional
  to the square of what they were given. They are all one pass now.

### Fixed

- **Forward, then Back, out of an archive landed in the folder it lives in
  rather than back inside it.** Back and Forward were written separately and
  only one of them knew an entry could be an archive; they are one method now.
- A ZIP archive created or edited by LinRAR came out mode 0600, private to
  whoever made it, because it was built through a temporary file. It now gets
  the mode an ordinary file would, or the one the archive it replaced had.
- The glyph cache fell back to a fixed name under `/tmp` when no cache
  directory was available, which anybody on the machine could create first.

### Code nothing was running

Everything below was found by cross-referencing every definition in the package
against every mention of it in the package, the tests, the tools, the installer
and the documentation, then reading each hit in place.

- **Gone: nine functions and methods nothing called.** `ArchiveBackend.build_tree`
  (44 lines, and it had dead code of its own inside it), `Profile.to_options`
  and the `_update_from_value` helper only it used, `Settings.reload_system`,
  `PasswordStore.recheck`, `platform.describe_machine`, `themes.ids`,
  `search.relative_display`, and `main_window._find_under`, which this release
  had already replaced with the index beside it.
- **Gone: seven names nothing read.** The `METHOD_BY_KEY` lookup table, the
  `POLICY_KEYS` tuple, the `_ACTIONS` copy of the command line table (whose own
  comment admitted it was vestigial), the `ensure_user_dir` and `APP_VERSION`
  aliases, and the `contextRequested` signal that was never emitted or
  connected.
- **Gone: six attributes written and never looked at**, in the convert,
  problem, progress and update windows. The progress window was keeping three
  counters up to date that nothing displayed.
- **Gone: `Ink.gloss`.** A colour every theme could set and nothing ever painted
  with. A theme that sets it now gets told it does nothing, instead of silence.
- **Gone: the `compression/profile` setting.** Profiles have lived under
  `profiles/list` for some time; this was left behind. It is retired through
  the same migration that retired the others, so it is cleared out of existing
  configuration files rather than sitting in them for ever.
- **`ArchiveFormat.read_only` is now used** instead of the hand-written list of
  the four writable formats that had been copied into the main window. Which
  formats can be written is one question with one answer.

### Writing

- Every em dash in the source, the documentation and the changelog has been
  replaced with ordinary punctuation, along with the curly quotes, ellipsis
  characters, arrows and bullet glyphs that had crept in. The text says the
  same things; it just says them in ASCII.

## 2.1.0 - 2026-08-03

### Find reads the files, not just their names

- **The "Text to find" box does something.** It has been on the Find dialog
  all along, and nothing ever read it: the window filtered on the *name* mask
  and the text was thrown away, so typing a word and pressing Find quietly did
  nothing. Find now reads the matching files, through the current folder and
  everything under it, or through the open archive, and lists every line that
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

- **Tools > Calculate checksums (Ctrl+K)** works out CRC32, MD5, SHA-1,
  SHA-256 and SHA-512 for the selected files, on disk or inside an archive,
  in a single pass over the bytes, so asking for five costs no more reading
  than asking for one.
- Paste a published checksum (or a whole `sha256sum` line) into the box at the
  bottom and it names the file that matches it and which algorithm it was.
- The result copies or saves either as a table of everything, or in the exact
  `sha256sum` layout, so it can be fed straight to `sha256sum -c`.

### A keyring that is not there no longer swallows passwords

- **Fixed: every password saved could vanish silently.** `secret-tool` being
  installed does not mean anything is listening: a headless server, a minimal
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
  could never come: the job simply stopped after `test_navigation.py` with
  nothing to say. GUI tests now count password prompts instead of showing
  them, so "LinRAR had to ask" is a failed check with a name.
- **A test file that runs no checks is reported as skipped, not as a pass.**
  One that steps aside, no AppImage runtime to build with, say, looked
  exactly like one that verified everything, which is how a file quietly stops
  testing anything without anybody noticing. The reason it gave is shown.

### Saved passwords are finally used

- **Fixed: *Tools > Organize passwords* stored passwords nobody ever read.**
  An archive a saved password would have opened still stopped and asked for
  one. Saved passwords whose mask fits the archive are now tried first, in
  order, a specific mask before a catch-all, and only when they are
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
- **"Reset the interface" now resets the columns too**: widths, order and
  sort indicator. `QHeaderView.reset()` is the model-reset slot and does
  nothing to section sizes.
- **7-Zip archives no longer lose files when "Store full folder structure" is
  off.** 7z has no exclude-paths switch and was handed bare base names, so it
  could not find anything in a subfolder, said so as a *warning*, exited 1 and
  produced an archive quietly missing them. The files are now laid out flat in
  a scratch folder, hard-linked, so it costs nothing, and archived from
  there, using only `7z a`, the one command every build agrees about. (Doing
  it by renaming the members afterwards with `7z rn` worked on p7zip 16.02 and
  died with exit 255 on the 7-Zip release newer distributions ship.) A base
  name already taken keeps its folder rather than overwriting the other file.
- **7-Zip write commands no longer pass a bare `-p`.** What it means is not
  settled between builds, p7zip reads it as an empty password, newer 7-Zip
  as "ask me", and a command that decides to ask, with nothing on stdin,
  dies rather than doing the work. Same rule the rar backend already follows.
- **A file 7-Zip could not read is reported.** Its scan warnings sit behind an
  exit status that archive creation has to allow, so the words are now read as
  well as the status.
- **ZIP archives the built-in reader will not touch are handed to 7-Zip**: a
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
- Toggling hidden files no longer re-reads the open archive, and no longer
  asks for its password again, for a setting that cannot change what is
  shown.
- The Customize picker knows about every toolbar button; Back, Forward,
  Update and Theme were offered without their icons.

### Small additions

- **File > Open recent** keeps the archives you opened lately, kept apart from
  the address bar's folder history.
- The status bar shows **free space** on the filesystem the current folder
  lives on, with the total and the percentage used in its tooltip.

### Extracting behaves the way WinRAR's does

- **Extracting no longer opens the archive in the background.** Unpacking from
  the file list, the right-click menu or the command line used to step the
  browser into the archive first, leaving the user somewhere they had not
  asked to be. The window now stays exactly where it is, same folder, same
  title, same Back history, and the listing refreshes when the files arrive.
  Testing an archive from outside behaves the same way.
- Extracting several selected archives runs them one after another and reports
  how many succeeded, instead of leaving the browser inside the last one.

### The progress window

- **The two bars finally mean two different things.** The lower bar is now
  weighted by **bytes**, as WinRAR's is: thirty small files followed by one
  large one no longer reads as "almost finished" after the small ones. It was
  previously derived from the file count, and fell back to *copying the
  per-file percentage outright* whenever the count was unknown, which is why
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
  beside it: **AppImage** or **RAR .sfx stub**, with an **Options...** button
  for the full SFX module. One press of OK compresses *and* wraps, leaving no
  intermediate `.rar` behind. Previously an AppImage could only be reached by
  creating a `.rar`, opening it, and finding a separate command.
- **One SFX command instead of two.** *Convert to AppImage (SFX)* and *Convert
  to RAR .sfx stub* are now a single **Commands > Convert archive to SFX**
  (`Alt+S`); the dialog asks which of the two you want and explains the
  difference. The stub's pages are simply put away, since it takes no options.
- The archive name follows the choice (`.AppImage` / `.sfx` / `.rar`), volume
  splitting greys out while an AppImage is selected, it is one file, and the
  choice is remembered and saved into compression profiles.

### The interface, tidied

- **Every command appears in exactly one menu.** *Repair archive* was in both
  Commands and Tools; *Compression profiles* was in both Tools and Options.
  Repair now lives under Tools and profiles under Options, as in WinRAR.
- The *Protect and repair* submenu is gone: **Protect**, **Lock** and **Convert
  archive to SFX** sit directly in Commands where WinRAR puts them, with the
  two volume commands under a **Volumes** submenu.
- Removed a dead *Convert archive* action that only forwarded to *Convert
  archives...*.
- **Help > About** now links to the website and the source repository, next to
  the author's page.

### Opening files: it now explains itself

- **Every failure is diagnosed** (`linrar/core/diagnose.py`). Before anything
  is reported, the file is inspected: what it is (regular file, folder, device,
  dangling link), its size, whether it can be read, what its leading bytes
  really are, what its name claimed, whether it is a later part of a split set,
  which tool would open it and whether that tool is installed. The result is a
  headline, an explanation, a table of findings, concrete suggestions, and a
  block of technical detail with the hex dump, the exit code and the tool's own
  words, which **Copy report** puts on the clipboard for a bug report.
- **The fix is a button.** *Install tools...* when a tool is missing, *Open
  volume 1* for a part of a split archive, *View in LinRAR*, *Open with another
  application*, *Repair...*, or the nearest folder that still exists.
- **Fixed: a file that is not an archive opened an empty window.** `unrar lt`
  answers "...is not RAR archive" and still exits 0, and `x`/`t` exit 1, all of
  which counted as success, so a text file named `.rar` "opened" and showed
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

- **Back and Forward**, `Alt+Left` / `Alt+Right`, over folders and archives alike,
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
  with nothing to act on fails before a window opens, all with status **2**,
  and `--` ends the options. Files that do not exist are named on stderr
  instead of being silently dropped.

### Settings for every user

- **System-wide configuration.** `/etc/linrar/linrar.conf`, its
  `conf.d/*.conf` drop-ins and any `$XDG_CONFIG_DIRS/LinRAR/linrar.conf` are
  read before the user's own file, so a machine can be set up once for
  everybody. Each layer overrides the one before; the user still has the last
  word unless the administrator says otherwise.
- **Locking.** A `[policy]` section names keys the user may not change:
  `locked=view/theme, paths/*`, with shell wildcards, or `lock_all=true` for
  every key the file sets. A locked setting keeps the administrator's value,
  ignores anything already in the user's file, and is never written back to it.
- **The interface says so.** Every menu entry, checkbox, combo and path box
  bound to a locked key is greyed out with a tooltip naming the file that
  decided it; the Settings and Customize dialogs carry a banner counting them;
  **Settings > Tools and system** lists the system files in force and how many
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
  platform first and stop with an explanation, and a suggestion of what to use
  instead, on anything but Linux. The check in `linrar/__main__.py` runs
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
  not an archive the same blank page. Fifteen new icons: Word, Excel,
  PowerPoint, PDF, OpenDocument and EPUB, images, audio, video, source code,
  fonts, programs, databases, disc images and keys: drawn in the same style as
  the rest of the set, as a sheet with a coloured band across its foot, because
  at sixteen pixels the colour is what the eye reads.
- **Every file is identified now.** A file with no extension at all, a
  compiled program, a `README` with no suffix, used to read as "File"; its
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
- *Commands > Convert archive to SFX* asks which kind first, in a small window
  that explains the difference, and the `.sfx` stub, which takes no options at
  all, goes straight to the converter instead of through a window with nothing
  to fill in.
- On the Add dialog the kind is already a box beside the button, so pressing
  **Options...** goes straight to the AppImage settings.

### Files it does not archive, handled properly

- **The viewer shows the file, not its bytes.** It was answering anything it
  did not recognise with a hex dump; it now asks what the file is and shows
  the most useful thing it can; text in whatever encoding it turns out to be,
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
  `.apk`, `.deb`, `.rpm`, `.epub` and the office formats; all of which it can
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
  ten extensions to over fifty: written once now, and reshaped for whichever
  punctuation each file manager wants.
- **146 distributions** are recognised, up from about forty, across **18
  package managers**: ALT Linux's apt-rpm, Mageia's urpmi, GNU Guix, OpenWrt's
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
  pending; *"2.0.0; 2.1.0 is installed, restart to use it"*, rather than
  going on showing the old number as though the update had not worked.
- **Fixed: checking again after installing offered the same release twice.**
  The check compared the server's version against the one still in memory, so
  a user who updated without restarting was told the update they had just
  applied was available. It compares against what is installed now, and the
  start-up check does not run at all while a restart is pending.
- The backup folder is named after the version being replaced, the one on
  disk, so a second update in the same session no longer names it after a
  version that was overwritten an hour ago.

### Updating replaces a version rather than piling one on top of another

- **Every release carries a list of its own files**, written into it when it is
  built. An update reads the installed copy's list, so it knows precisely what
  the version it is replacing put on disk, and can delete exactly that.
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

- **Help > Check for updates.** LinRAR reads the manifest its own release
  pipeline publishes, tells you what is available and what changed in it, and
  installs it if you say so: the tarball, the launcher, the desktop entry and
  the icons, in one press.
- **It shows its working.** Seven stages, listed before the first one starts
  and ticked off as they pass; a download with a byte count, a live speed and a
  time remaining; a weighted overall bar beside the per-stage one; and a
  details pane holding every line the updater logged, with **Copy log** for
  putting it in a bug report.
- **Nothing that arrives over the network is trusted.** The download must be
  the size the release declared and must hash to the SHA-256 it published:
  verified by re-reading the file from disk rather than by trusting the bytes
  that streamed past. The archive may hold only ordinary files under its own
  folder: anything with `..` in it, an absolute path or a symlink is refused
  outright rather than sanitised.
- **A failed update leaves the version that was working.** The current install
  is copied aside before anything is replaced, and every failure, a bad
  download, a refused installer, a cancel, puts it back. The last step starts
  the newly installed copy in a fresh process and asks its version; a wrong
  answer is rolled back too, even though every individual step succeeded.
- **Automatic updates, off until asked for** (*Settings > General > Updates*):
  check at start-up, install without asking, and include pre-releases. A
  start-up check reaches the network at most once an hour however often LinRAR
  is opened, says nothing when there is nothing to say, and never turns a
  failed check into something the user has to dismiss. **Skip this version**
  puts one release aside without switching anything off.
- **It refuses what is not its to replace**, a git checkout, a folder it
  cannot write to, a system-wide install with no administrator rights, and
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
  downloaded 2.1.0 from a working tree that calls itself 2.1.0, and an updater
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
  is created by the same call that creates the release, so a run that fails
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
  **Options > Theme**, the corner of the menu bar, or `Ctrl+Shift+T`.
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
  next launch; Qt writes `[%General]` and reads it back as `General/<key>`.
- A launcher that renamed `argv[0]` broke the virtual environment: CPython
  resolves its prefix from `argv[0]`, so it fell back to the system Python and
  lost PyQt6.
- `rar a -p-` does not mean "no password": it encrypts with the literal
  password `-`. Read commands get `-p-`; write commands get no `-p` at all.
- The Dependencies manager located tools with `PATH` alone while the rest of
  the app searched further, so a `rar` in `/opt/rar` or a Nix profile was
  reported "Missing" while LinRAR was quite happily running it.
- unrar 7 prints an `Archive comment:` heading above the comment where unrar 6
  printed it bare, so on newer distributions every archive comment gained that
  line, and gained another one each time it was edited. The heading is now
  stripped, and the listing parsers are covered by tests that feed them both
  versions' output, so a tool upgrade cannot silently change what LinRAR reads.
