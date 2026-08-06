#!/usr/bin/env python3
"""Take the screenshots the README and docs/USAGE.md show.

    tools/screenshots.py                    # write them into docs/images
    tools/screenshots.py --out DIR          # somewhere else
    tools/screenshots.py --list             # say what it would write

Every image is grabbed from the real application, driven through its own API,
no mock-ups, no editing afterwards, so a screenshot cannot show a window
LinRAR does not build.  It runs offscreen, so it needs no display, and it works
on a demo folder it creates and deletes, so nothing in it is anybody's real
files.

Run it after changing the chrome, the toolbar or a dialog.  The images are
committed; this script is how they are refreshed.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

#: The folder the demo files are made in, and the sizes windows are grabbed at.
WINDOW = (1180, 700)

#: Files the demo folder holds: one of every icon family the list can draw, with
#: plausible names and sizes, because a screenshot of an empty folder shows
#: nothing and a screenshot of somebody's home directory shows too much.
DEMO_FILES = [
    ("Quarterly report.docx", 18035),
    ("presentation.pptx", 546808),
    ("Budget.xlsx", 24160),
    ("Screenshot.png", 264192),
    ("holiday.jpg", 842104),
    ("soundtrack.mp3", 4210688),
    ("interview.mkv", 18874368),
    ("manual.pdf", 1258291),
    ("notes.txt", 3072),
    ("build.py", 11264),
    ("styles.css", 6144),
    ("contacts.sqlite", 40960),
    ("id_rsa.pem", 1704),
]
DEMO_DIRS = ["Contracts", "Invoices", "Photos"]

#: The demo folder's *neighbours*.  The folder tree in these images is the real
#: one, and it lists the siblings of every ancestor -- so without a synthetic
#: home to sit in, a screenshot of the tree is a screenshot of whatever else
#: happens to be on the machine that took it.  These are what fills the frame
#: instead.


def _write_demo(folder: str) -> None:
    for name in DEMO_DIRS:
        os.makedirs(os.path.join(folder, name), exist_ok=True)
    for name, size in DEMO_FILES:
        with open(os.path.join(folder, name), "wb") as handle:
            handle.write(b"\0" * size)


def _make_archive(folder: str) -> str:
    """A real archive to open, made with whatever tool is installed."""
    from linrar.core import tools

    target = os.path.join(folder, "Documents.rar")
    rar = tools.find("rar")
    if rar:
        subprocess.run(
            [rar, "a", "-ep1", "-idq", target, "Contracts", "notes.txt",
             "Quarterly report.docx", "build.py", "Screenshot.png"],
            cwd=folder, capture_output=True,
        )
        if os.path.isfile(target):
            return target
    # No rar: a zip opens in exactly the same window.
    import zipfile

    target = os.path.join(folder, "Documents.zip")
    with zipfile.ZipFile(target, "w") as archive:
        for name, _size in DEMO_FILES[:6]:
            archive.write(os.path.join(folder, name), name)
        archive.writestr("Contracts/agreement.docx", b"\0" * 9000)
    return target


def _grab(widget, path: str) -> None:
    # Any transient status message ("Light theme applied") is cleared first: it
    # is true for two and a half seconds and misleading in a committed image.
    bar = getattr(widget, "statusBar", None)
    if callable(bar):
        bar().clearMessage()
    widget.grab().save(path)
    print(f"  {os.path.basename(path):<26} {os.path.getsize(path) // 1024} KB")


def _settle(app, times: int = 4) -> None:
    for _ in range(times):
        app.processEvents()


def _hide_tree(window, app) -> None:
    """Turn the folder tree off before anything is grabbed.

    The tree is real: it walks the actual filesystem and lists the siblings of
    every ancestor. Wherever a demo folder is put, the frame therefore fills with
    whatever else is on the machine that took the picture: somebody's other
    projects, a client name, a scratch directory. Several attempts at framing
    around that (a synthetic home, scrolling the open folder to the top, filling
    the viewport with made-up siblings) all leaked at the edges, because the tree
    lazily expands and the row count is not something a screenshot can pin down.

    So it is simply switched off. What is left, the menu bar, the toolbar, the
    address bar, the file list with a row per icon family, the status bar, is
    the substance of the window, and the tree is described in the docs in words.
    """
    window.toggle_tree(False)
    _settle(app, 2)


SHOTS = [
    "main-light.png", "main-dark.png", "main-themed.png",
    "themes.png", "themes-fixing.png",
    "archive-open.png", "view-large.png",
    "archive-dialog.png", "customize.png",
    "dependencies.png", "toolbar.png", "tools-settings.png",
]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=os.path.join(ROOT, "docs", "images"))
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args(argv[1:])

    if args.list:
        for name in SHOTS:
            print(name)
        return 0

    os.makedirs(args.out, exist_ok=True)

    from PyQt6.QtWidgets import QApplication

    app = QApplication([])
    from linrar.core.settings import SETTINGS
    from linrar.ui import filelist, theme

    # A screenshot must not depend on, or disturb, the settings of whoever runs
    # this: every appearance key is reset first and restored at the end.
    keys = ("view/theme", "toolbar/items", "toolbar/icon_size", "toolbar/style",
            "view/mode", "view/show_tree", "view/show_hidden")
    saved = {key: SETTINGS.get(key) for key in keys}
    SETTINGS.reset(*keys)
    SETTINGS.sync()

    theme.apply(app, "light")
    from linrar.ui.main_window import MainWindow
    from linrar.ui.dialogs.themes import ThemeManagerDialog

    try:
        return _shoot(app, args, saved, MainWindow, ThemeManagerDialog,
                      filelist, SETTINGS)
    finally:
        shutil.rmtree(os.path.join(ROOT, "screenshot-demo"), ignore_errors=True)
        for key, value in saved.items():
            SETTINGS.set(key, value)
        SETTINGS.sync()


def _shoot(app, args, saved, MainWindow, ThemeManagerDialog, filelist,
           SETTINGS) -> int:
    from PyQt6.QtCore import QRect

    # Inside the project rather than /tmp so the path in the address bar is
    # short and readable, and removed again in the `finally` below.
    work = os.path.join(ROOT, "screenshot-demo")
    shutil.rmtree(work, ignore_errors=True)
    demo = os.path.join(work, "Documents")
    os.makedirs(demo)
    _write_demo(demo)
    archive = _make_archive(demo)

    window = MainWindow()
    window.resize(*WINDOW)
    window.navigate_to(demo)
    window.show()
    _settle(app)
    _hide_tree(window, app)

    print("the main window")
    for name, wanted in (("main-light.png", "light"),
                         ("main-dark.png", "dark"),
                         ("main-themed.png", "midnight-neon")):
        window.set_theme(wanted)
        _settle(app)
        _grab(window, os.path.join(args.out, name))

    print("the toolbar, on its own")
    window.set_theme("light")
    _settle(app)
    bar = window.toolbar
    top = bar.mapTo(window, bar.rect().topLeft())
    shot = window.grab().copy(
        QRect(top.x(), top.y(), bar.width(), bar.height())
    )
    shot.save(os.path.join(args.out, "toolbar.png"))
    print(f"  {'toolbar.png':<26} "
          f"{os.path.getsize(os.path.join(args.out, 'toolbar.png')) // 1024} KB")

    print("the Themes window")
    # One deliberately broken theme, so the shot shows what a mistake looks like
    # rather than only the happy path.  Removed again below.
    from linrar.core import themes as packs

    broken = os.path.join(packs.ensure_writable_dir() or work, "zz-example.json")
    try:
        with open(broken, "w", encoding="utf-8") as handle:
            handle.write('{"name": "Half Written", "colors": {"window": "#223344",}}')
    except OSError:
        broken = ""
    packs.reload()

    manager = ThemeManagerDialog(window)
    manager.resize(1000, 660)
    manager.show()
    manager._select("midnight-neon")
    _settle(app)
    _grab(manager, os.path.join(args.out, "themes.png"))
    if broken:
        manager._select(broken)
        _settle(app)
        _grab(manager, os.path.join(args.out, "themes-fixing.png"))
    manager.close()
    if broken and os.path.isfile(broken):
        os.remove(broken)
        packs.reload()

    print("inside an archive, and the other views")
    window.open_archive(archive)
    _settle(app, 8)
    _grab(window, os.path.join(args.out, "archive-open.png"))

    window.cmd_close() if hasattr(window, "cmd_close") else None
    window.navigate_to(demo)
    window.set_view_mode(filelist.LARGE_ICONS)
    _settle(app)
    _grab(window, os.path.join(args.out, "view-large.png"))
    window.set_view_mode(filelist.DETAILS)
    _settle(app)

    print("the dialogs")
    from linrar.ui.dialogs.archive import ArchiveDialog
    from linrar.ui.dialogs.customize import CustomizeDialog
    from linrar.ui.dialogs.dependencies import DependenciesDialog
    from linrar.ui.dialogs.misc import SettingsDialog

    sources = [os.path.join(demo, name) for name, _size in DEMO_FILES[:5]]
    add = ArchiveDialog(window, sources, demo)
    add.resize(560, 620)
    add.show()
    _settle(app)
    _grab(add, os.path.join(args.out, "archive-dialog.png"))
    add.close()

    custom = CustomizeDialog(window)
    custom.resize(640, 600)
    custom.show()
    _settle(app)
    _grab(custom, os.path.join(args.out, "customize.png"))
    custom.close()

    deps = DependenciesDialog(window)
    deps.resize(860, 560)
    deps.show()
    _settle(app, 8)
    _grab(deps, os.path.join(args.out, "dependencies.png"))
    deps.close()

    settings = SettingsDialog(window)
    settings.resize(600, 600)
    settings.tabs.setCurrentIndex(1)
    settings.show()
    _settle(app)
    _grab(settings, os.path.join(args.out, "tools-settings.png"))
    settings.close()

    window.close()

    written = [name for name in SHOTS
               if os.path.isfile(os.path.join(args.out, name))]
    print(f"\n{len(written)} screenshots written to {args.out}")
    missing = [name for name in SHOTS if name not in written]
    if missing:
        print(f"not written: {', '.join(missing)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
