"""Application entry point."""

from __future__ import annotations

import os
import sys

from PyQt6.QtWidgets import QApplication, QMessageBox

from .core import platform
from .core.registry import REGISTRY
from .core.settings import SETTINGS
from .ui import theme
from .ui.main_window import MainWindow


def _check_tools(window: MainWindow) -> None:
    """Offer to install the required tools if none are present."""
    if REGISTRY.rar.available:
        return
    reply = QMessageBox.warning(
        window,
        "LinRAR",
        "Neither 'rar' nor 'unrar' was found on this system.\n\n"
        "LinRAR for Linux drives those command line tools, so archives cannot "
        "be opened until at least one is installed.\n\n"
        "Open the Dependencies manager to install them now?",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.Yes,
    )
    if reply == QMessageBox.StandardButton.Yes:
        window.cmd_dependencies()


USAGE = """LinRAR for Linux — a WinRAR-style archive manager.

Usage:
  linrar [FILE|FOLDER]              open an archive, or browse a folder
  linrar --extract-here FILE...     unpack each archive beside itself
  linrar --extract-to FILE...       unpack, asking where and how
  linrar --add FILE...              add the files to a new archive
  linrar --test FILE...             check each archive for damage
  linrar --config-info              show where every setting comes from
  linrar --version | --help

The action flags are what the file manager's right-click menu uses.

LinRAR runs on Linux only. Settings are read from the system-wide
/etc/linrar/linrar.conf (plus its conf.d drop-ins) and then from
~/.config/LinRAR/linrar.conf, the second overriding the first except where
the administrator locked a key.
"""

#: Command line action -> the window method that carries it out.
_ACTIONS = ("--extract-here", "--extract-to", "--add", "--test")


def _run_action(window: MainWindow, action: str, paths: list[str]) -> None:
    """Carry out a right-click action, then leave the window open."""
    if not paths:
        return
    if action == "--add":
        window.cmd_add(paths)
    elif action == "--extract-here":
        window.extract_paths(paths, ask_options=False)
    elif action == "--extract-to":
        window.extract_paths(paths, ask_options=True)
    elif action == "--test":
        window.test_paths(paths)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)

    # First, before any window: LinRAR is a Linux program.  Reaching this from
    # `python -m linrar` means __main__ already said so, but `main()` is also
    # imported directly, and it must not be the weaker door.
    if not platform.is_supported():
        print(platform.problem(), file=sys.stderr)
        return platform.EXIT_UNSUPPORTED
    note = platform.warning()
    if note:
        print(note, file=sys.stderr)

    if "--help" in argv or "-h" in argv:
        print(USAGE)
        return 0
    if "--version" in argv or "-V" in argv:
        from .ui.dialogs.misc import APP_VERSION

        print(f"LinRAR {APP_VERSION}")
        return 0
    if "--config-info" in argv:
        # For administrators: which files are in play, and what each key
        # actually resolves to once the layers are merged.
        print(SETTINGS.describe())
        return 0
    if "--self-test" in argv:
        # Build the whole window once and exit: what install.sh checks with.
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        app = QApplication(argv)
        theme.apply(app, SETTINGS.get("view/theme"))
        MainWindow()
        return 0

    action = next((a for a in argv[1:] if a in _ACTIONS), "")
    paths = [
        os.path.abspath(a) for a in argv[1:]
        if not a.startswith("-") and os.path.exists(a)
    ]

    QApplication.setApplicationName("LinRAR")
    QApplication.setApplicationDisplayName("LinRAR")
    QApplication.setOrganizationName("LinRAR-Linux")
    QApplication.setDesktopFileName("linrar")

    app = QApplication(argv)
    # apply() also picks the matching icon build and sets the window icon.
    theme.apply(app, SETTINGS.get("view/theme"))

    window = MainWindow()
    if action == "--add" and paths:
        # Adding starts from the folder the files live in.
        window.navigate_to(os.path.dirname(paths[0]))
    window.show()

    if not action and paths:
        # A bare path on the command line opens that archive or folder.
        target = paths[0]
        if os.path.isdir(target):
            window.navigate_to(target)
        elif os.path.isfile(target):
            window.open_archive(target)

    _check_tools(window)
    if action:
        _run_action(window, action, paths)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
