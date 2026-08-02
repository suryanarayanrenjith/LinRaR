# Using LinRAR

- [Browsing](#browsing)
- [When something will not open](#when-something-will-not-open)
- [Creating archives](#creating-archives)
- [Extracting](#extracting)
- [Protecting and repairing](#protecting-and-repairing)
- [Self-extracting archives](#self-extracting-archives)
- [Themes and customization](#themes-and-customization)
- [Passwords](#passwords)
- [Right-click menu and command line](#right-click-menu-and-command-line)
- [Keyboard shortcuts](#keyboard-shortcuts)
- [Where your settings live](#where-your-settings-live)

## Browsing

LinRAR opens as a file manager. Double-click an archive to step *inside* it and
the window becomes an archive browser; the `..` row steps back out. The folder
tree on the left follows whichever of the two you are looking at.

**Getting around.** `Alt+←` and `Alt+→` are Back and Forward, over folders and
archives alike, and their tooltips name where they lead. `Backspace` goes up,
`Ctrl+L` puts the cursor in the address bar so you can type a path (`~`, `$HOME`
and relative paths all work), `Ctrl+G` opens a folder chooser, and `F5` re-lists
the folder and clears any find filter.

Three small things that make it feel like a file manager rather than a dialog:
stepping out of a folder leaves the cursor **on** that folder; coming back to a
folder puts the cursor back where it was; and the folder tree keeps every
branch you opened, because it is revealed rather than rebuilt.

Five views, from **Options → File list** or `Ctrl+1`…`Ctrl+5`: Details, List,
Small icons, Large icons, Tiles. Click a column header to sort — the choice is
remembered, as are the column widths and which columns are shown.

## When something will not open

Archives are recognised by their **contents**, not their names, so a file opens
whatever it is called — and a `.rar` that is really an HTML error page is
reported as one rather than as a broken archive.

When a file cannot be opened, LinRAR does not shrug. It shows what it found:

- what the file is — regular file, folder, device, dangling link — its size,
  when it changed, and whether it can be read at all;
- what its contents say it is (plain text, a PDF, an ELF binary, an image…)
  next to what its name claimed;
- which tool is needed to read that format, and whether it is installed;
- whether it is a later part of a split archive, and where the first part is;
- a hex dump of the first bytes, the tool's exit code and its own words, all
  under **Show details** and on **Copy report** for a bug report.

Below that are the things you can do about it, as buttons: *Install tools…*
when a tool is missing, *Open volume 1* for a split set, *View in LinRAR*,
*Open with another application*, *Repair…*, or somewhere else to go when a
folder has vanished. Double-clicking an ordinary file hands it to the desktop;
if nothing takes it, that is explained too rather than silently doing nothing.

The same report is available from the terminal with `linrar -i FILE`.

**Formats.** RAR5, RAR4, ZIP, 7z, TAR, GZip, BZip2, XZ, Zstandard, ISO and CAB,
plus — wherever 7-Zip is installed — `.deb`, `.rpm`, `.cpio`, `.ar`/`.a`,
`.wim`, `.msi`, `.dmg`, `.squashfs`/`.snap`, `.lzma`, `.lz`, `.lz4`, `.arj`,
`.lzh` and `.Z`. Everything past ZIP, RAR and 7z is read-only.

<table>
<tr>
<td width="50%" valign="top"><img src="images/archive-open.png" alt="Browsing inside an archive"></td>
<td width="50%" valign="top"><img src="images/view-large.png" alt="The Large icons view"></td>
</tr>
<tr>
<td align="center"><em>Inside an archive, Details view</em></td>
<td align="center"><em>The same folder, Large icons</em></td>
</tr>
</table>

## Creating archives

Select files and press **Add** (`Alt+A`).

- **Format** — RAR5, RAR4, ZIP or 7z. Options that only apply to one format
  grey out on their own.
- **Compression** — Store, Fastest, Fast, Normal, Good, Best, with the
  dictionary sizes each supports.
- **Split to volumes** — a plain number uses the unit beside it, or write the
  unit in the box (`700 MB`). The classic media sizes are presets.
- **Archiving options** — delete after archiving, self-extracting, solid,
  recovery record, test after, lock.
- **Create SFX archive** — tick the box and pick the kind from the list beside
  it: **AppImage** or **RAR .sfx stub**. **Options…** opens the full SFX
  module. The archive name follows your choice (`.AppImage` or `.sfx`), and
  an AppImage greys out volume splitting because it is a single file. See
  [Self-extracting archives](#self-extracting-archives).
- **Profiles** — save the whole set of choices under a name and reuse it. Six
  come built in.
- **Options tab** — include subfolders, store full paths, exclusion masks.
- **Comment tab** — text stored inside the archive.

Whatever you used last time is what the dialog opens with next time.

## Extracting

**Extract To** (`Alt+E`) opens the full dialog: destination with a folder tree
and history, update mode, overwrite mode, extract to subfolders, keep broken
files, and full-paths / no-paths. **Alt+W** unpacks straight into the current
folder.

With *Ask before overwrite* — the default — conflicts are collected before any
work starts and shown in one prompt with **Yes / Yes to All / No / No to All /
Rename**.

Extracting into a folder you do not own is not refused: LinRAR asks for
administrator rights, unpacks into a private staging folder, and moves the
result into place as root, so the archive tool itself never runs privileged.

## Protecting and repairing

- **Protect** (`Alt+P`) adds a recovery record, with an adjustable redundancy
  percentage, so a damaged archive can be repaired later.
- **Add recovery volumes** creates `.rev` files that can rebuild a *missing*
  part of a volume set; **Reconstruct missing volumes** uses them.
- **Repair** (`Alt+R`) rebuilds a damaged archive.
- **Lock** marks an archive so LinRAR refuses to modify it.
- **Test** (`Alt+T`) verifies without writing anything.

## Self-extracting archives

WinRAR's *Convert to SFX* makes a Windows `.exe`. Linux has two answers, and
LinRAR offers both wherever a self-extracting archive can be made:

| | Best for | Needs |
|---|---|---|
| **AppImage** | giving the archive to somebody with nothing installed | `squashfs-tools`, and a ~1 MB runtime fetched once |
| **RAR `.sfx` stub** | the smallest possible result, on a machine with a shell | nothing |

**Making one while archiving.** In the *Archive name and parameters* dialog,
tick **Create SFX archive** and pick the kind from the list beside it. The
archive name follows the choice, **Options…** opens the SFX module, and one
press of OK compresses *and* wraps — there is no intermediate `.rar` to tidy
up afterwards.

**Converting one that already exists.** **Commands → Convert archive to SFX**
(`Alt+S`) opens the same dialog with the same two choices.

```bash
./MyArchive.AppImage                    # GUI: license → destination → extract
./MyArchive.AppImage --list             # list contents
./MyArchive.AppImage --test             # verify integrity
./MyArchive.AppImage -d ~/here --silent # unattended
```

The SFX dialog mirrors WinRAR's SFX module: default destination, commands to
run before and after, silent mode, overwrite policy, window title and
description, a custom icon, a licence the user must accept, and a `.desktop`
menu entry created after extraction. Encrypted payloads prompt for the password
(via `zenity` or the terminal). Those pages describe the AppImage; the `.sfx`
stub takes no configuration, so choosing it puts them out of the way.

An AppImage is a single file, so *Split to volumes* is greyed out while it is
selected.

## Themes and customization

**Theme** — light or dark, drawn by LinRAR rather than inherited from the
desktop, with a matching build of the icon set. **Options → Theme**, the switch
in the menu bar's corner, or `Ctrl+Shift+T`.

**Options → Customize** (`Ctrl+U`) has three tabs:

- **Toolbar** — pick from 34 commands, drag them into any order, insert
  separators, choose the icon size (16/24/32/48) and whether captions sit under
  the icon, beside it, or not at all.
- **File list** — the five views, row height, row separators, alternating
  shading, and which columns Details shows.
- **Layout** — toolbar at the top or bottom, address bar and status bar on or
  off, folder tree on the left or right, comment pane above or below.

**Options → Layout → Reset the interface** puts all of it back.

## Passwords

Set one for a single operation from the dialog that needs it, or a default for
the session with `Ctrl+P`. **Tools → Organize passwords** stores named
passwords for reuse; they go to your desktop's keyring through `secret-tool`
when it is installed. Without a keyring they are kept in LinRAR's own file,
obfuscated but **not encrypted**, and the dialog says exactly that.

Passwords are handed to `rar`/`unrar` on standard input, never on the command
line, so they never appear in the process list.

## Right-click menu and command line

After installing, archives get LinRAR entries in Dolphin, Nemo, Nautilus, Caja
and Thunar. They all call the same command line, which you can use yourself.
Every action has a short form as well as the long one the desktop files use:

```
Usage:
  linrar [FILE|FOLDER]              open an archive, or browse a folder
  linrar -x, --extract-here FILE... unpack each archive beside itself
  linrar -X, --extract-to   FILE... unpack, asking where and how
  linrar -a, --add          FILE... add the files to a new archive
  linrar -t, --test         FILE... check each archive for damage
  linrar -i, --inspect      FILE... report what a file really is, and print it
  linrar -c, --config-info          show where every setting comes from
  linrar -V, --version | -h, --help
```

```bash
linrar                         # browse your home folder
linrar ~/Downloads             # browse a folder
linrar backup.rar              # open an archive
linrar -x a.rar b.zip          # unpack each one beside itself
linrar -X a.rar                # unpack, asking where and how
linrar -a *.txt                # add the files to a new archive
linrar -t a.rar                # check for damage
linrar -i mystery.rar          # what is this file, really?
linrar -c                      # where every setting comes from
linrar -- -odd-name.rar        # -- ends the options
```

Short options are not bundled: write `-x -t`, never `-xt`. An unknown option is
an error that suggests the one you meant, and an action with nothing to act on
fails before a window opens; both exit **2**. `--inspect` exits **1** for a file
LinRAR cannot open, and **0** for one it can, so it can be used in a script.

LinRAR runs on Linux only; on any other system it prints why and exits without
opening a window, with status **1**.

## Keyboard shortcuts

| | |
|---|---|
| `Alt+A` | add to archive |
| `Alt+E` / `Alt+W` | extract to… / extract here |
| `Alt+T` | test |
| `Alt+V` | view file |
| `Alt+I` | archive information |
| `Alt+R` | repair |
| `Alt+P` | add recovery record |
| `Alt+S` | convert archive to SFX (AppImage or .sfx stub) |
| `Alt+Q` | convert archives |
| `Alt+G` | generate report |
| `Del` / `F2` / `F7` | delete / rename / new folder |
| `Ctrl+O` / `Ctrl+W` | open / close archive |
| `Alt+←` / `Alt+→` | back / forward |
| `Backspace` / `F5` | up one level / refresh and clear the filter |
| `Ctrl+L` / `Ctrl+G` | address bar / go to folder |
| `Ctrl+F` | find |
| `Ctrl+A`, `+`, `-`, `*` | select all, select / deselect / invert by mask |
| `Ctrl+C` `Ctrl+X` `Ctrl+V` | copy, cut, paste |
| `Ctrl+Shift+C` | copy path |
| `Alt+Enter` | properties |
| `Ctrl+1`…`Ctrl+5` | Details, List, Small icons, Large icons, Tiles |
| `Ctrl+T` / `Ctrl+H` | folder tree / hidden files |
| `Ctrl+U` | customize |
| `Ctrl+Shift+T` | switch theme |
| `Ctrl+P` / `Ctrl+S` / `Ctrl+D` | default password / settings / add to favourites |
| `F1` / `Shift+F1` | help / keyboard shortcuts |
| `Ctrl+Q` | quit |

## Where your settings live

One readable file:

```
~/.config/LinRAR/linrar.conf
```

It holds the theme, toolbar contents and style, view mode, row height, sort
order, layout, window and splitter geometry, column widths, the compression
settings of the last archive you made, the extraction options you last used,
the find mask, favourites, folder history, saved profiles and password
metadata. **Settings → Tools and system → Reset all settings** clears it.

## Settings for every user

An administrator can set defaults for everyone on the machine, and lock the
ones that are not up for discussion. LinRAR reads these files in order, each
one overriding the one before:

```
/etc/xdg/LinRAR/linrar.conf      any $XDG_CONFIG_DIRS entry
/etc/linrar/linrar.conf          the machine's own settings
/etc/linrar/conf.d/*.conf        drop-ins, in name order
~/.config/LinRAR/linrar.conf     each user's own choices — last word
```

`./install.sh --system` writes `/etc/linrar/linrar.conf` with every setting
commented out; `--global-config` adds it to a user install, and
`./install.sh --print-global-config` prints it to redirect wherever you like.
It is never overwritten once it exists.

The format is the same INI the user's file uses. **Comments start with a
semicolon** — a `#` is an ordinary character to the parser, so `#theme=light`
would be read as a setting named `#theme` (LinRAR ignores keys like that, but
your setting would silently not apply):

```ini
[view]
theme=dark
show_tree=true

[compression]
method=5

[paths]
rar=/opt/rar/rar

[policy]
locked=view/theme, paths/*
```

Everything outside `[policy]` is a **default**: the user can still change it,
and their choice wins. `locked` makes a key the administrator's: LinRAR keeps
the value set here, ignores whatever is in the user's file, greys the control
out wherever it appears — menu entry, Settings dialog, Customize dialog — with
a tooltip naming the file, and leaves the key alone when the user saves. A key
is its section and name joined by a slash, shell wildcards work, and
`lock_all=true` locks every key the file sets without naming them twice.

Window geometry (`geometry/*`) and the config version stamp (`meta/*`) cannot
be set or locked from a system file. They are not preferences, and freezing
them would break the window rather than manage it.

To see what any of it actually resolves to:

```bash
linrar --config-info
```

It lists the files in play, the locked keys, every effective value, and whether
each came from the user, the system, or the built-in default. **Settings →
Tools and system** shows the same thing in the application, under *Saved
settings*.
