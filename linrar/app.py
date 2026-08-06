"""Application entry point and command line.

The command line is small but it is a real interface: the file manager's
right-click menu is built out of it, and so is every shell script anybody
writes around LinRAR.  So it is parsed properly rather than sniffed: an
unknown option is an error with a suggestion, a missing file is named, and an
action with nothing to act on fails before a window is ever created.  Every
action has a one-letter short form as well as the long one the desktop files
use.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field

from PyQt6.QtWidgets import QApplication, QMessageBox

from .core import platform
from .core.registry import REGISTRY
from .core.settings import SETTINGS
from .ui import theme
from .ui.main_window import MainWindow

#: Returned when the command line itself is wrong, as distinct from the work
#: failing.  Matches the convention of the shell tools LinRAR drives.
EXIT_USAGE = 2

#: Returned when the requested work could not be done at all.
EXIT_FAILED = 1


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


USAGE = """LinRAR for Linux: a WinRAR-style archive manager.

Usage:
  linrar [FILE|FOLDER]              open an archive, or browse a folder
  linrar -x, --extract-here FILE... unpack each archive beside itself
  linrar -X, --extract-to   FILE... unpack, asking where and how
  linrar -a, --add          FILE... add the files to a new archive
  linrar -t, --test         FILE... check each archive for damage
  linrar -i, --inspect      FILE... report what a file really is, and print it
  linrar -c, --config-info          show where every setting comes from
  linrar -V, --version | -h, --help

Each action has the short form shown above; the long forms are what the file
manager's right-click menu uses. Use -- to end the options when a file name
begins with a dash.

LinRAR runs on Linux only. It does not run on Windows or macOS: it drives the
Linux builds of rar, unrar, 7z and zip, stores its settings in the XDG
directories, and integrates with a freedesktop.org desktop. On Windows use
WinRAR or 7-Zip; under WSL, install LinRAR inside the Linux distribution.

Settings are read from the system-wide /etc/linrar/linrar.conf (plus its conf.d
drop-ins) and then from ~/.config/LinRAR/linrar.conf, the second overriding the
first except where the administrator locked a key.
"""

#: Long option -> short option, for every action the command line offers.
#: Both spellings of each are accepted everywhere; this is also what the error
#: message uses to suggest the option somebody meant.
ACTION_FLAGS: dict[str, str] = {
    "--extract-here": "-x",
    "--extract-to": "-X",
    "--add": "-a",
    "--test": "-t",
}

#: Options that print something and exit, without opening a window.
QUERY_FLAGS: dict[str, str] = {
    "--help": "-h",
    "--version": "-V",
    "--config-info": "-c",
    "--inspect": "-i",
}

#: Not advertised: install.sh uses it to prove the application really starts.
_INTERNAL_FLAGS = ("--self-test",)

#: Every spelling LinRAR accepts, short -> long, so the parser has one table.
_ALIASES: dict[str, str] = {
    short: long
    for long, short in list(ACTION_FLAGS.items()) + list(QUERY_FLAGS.items())
}


@dataclass
class Invocation:
    """What a command line asked for, once it has been understood."""

    action: str = ""                              # a long --action, or ""
    query: str = ""                               # a long --query, or ""
    paths: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    #: Every non-option argument in the order it was written, so anything that
    #: reports per file reports them the way the user listed them.
    arguments: list[str] = field(default_factory=list)
    self_test: bool = False
    error: str = ""                               # set when the line is wrong

    @property
    def valid(self) -> bool:
        return not self.error


def parse_args(argv: list[str]) -> Invocation:
    """Turn a command line into an :class:`Invocation`.

    Never touches the screen and never exits, so the whole surface can be
    tested; the caller decides what a bad line is worth.
    """
    result = Invocation()
    rest = list(argv[1:])
    literal = False
    seen_action = ""

    while rest:
        argument = rest.pop(0)

        if literal or argument == "-":
            _add_path(result, argument)
            continue
        if argument == "--":
            literal = True
            continue

        if argument.startswith("-") and len(argument) > 1:
            option = _ALIASES.get(argument, argument)
            if option in _INTERNAL_FLAGS:
                result.self_test = True
                continue
            if option in QUERY_FLAGS:
                # First query wins; --help beats everything, as people expect.
                if not result.query or option == "--help":
                    result.query = option
                continue
            if option in ACTION_FLAGS:
                if seen_action and seen_action != option:
                    result.error = (
                        f"{_spelling(seen_action)} and {_spelling(option)} "
                        "cannot both be used: choose one action."
                    )
                    return result
                seen_action = option
                result.action = option
                continue
            result.error = _unknown(argument)
            return result

        _add_path(result, argument)

    if result.query or result.self_test:
        return result
    if result.action and not result.paths:
        if result.missing:
            result.error = (
                f"{_spelling(result.action)}: "
                + _list_missing(result.missing)
            )
        else:
            result.error = (
                f"{_spelling(result.action)} needs at least one file. "
                f"For example:  linrar {ACTION_FLAGS[result.action]} archive.rar"
            )
    return result


def _add_path(result: Invocation, argument: str) -> None:
    path = os.path.abspath(os.path.expanduser(argument))
    result.arguments.append(path)
    (result.paths if os.path.exists(path) else result.missing).append(path)


def _spelling(long: str) -> str:
    """"--add (-a)", so an error names the option however it was typed."""
    short = ACTION_FLAGS.get(long) or QUERY_FLAGS.get(long)
    return f"{long} ({short})" if short else long


def _list_missing(paths: list[str]) -> str:
    if len(paths) == 1:
        return f"there is no file at {paths[0]}"
    listed = "\n  ".join(paths)
    return f"none of these files exist:\n  {listed}"


def _unknown(argument: str) -> str:
    """"unknown option" plus the closest thing LinRAR does understand."""
    known = list(ACTION_FLAGS) + list(QUERY_FLAGS)
    bare = argument.lstrip("-").lower()
    close = [
        option for option in known
        if bare and (bare in option.lstrip("-") or option.lstrip("-").startswith(bare))
    ]
    message = f"unknown option: {argument}"
    if close:
        message += "\n\nDid you mean:  " + ", ".join(
            f"{option} ({ACTION_FLAGS.get(option) or QUERY_FLAGS.get(option)})"
            for option in close
        )
    if not argument.startswith("--") and len(argument) > 2:
        message += (
            "\n\nShort options are not combined: write  -x -t  rather than -xt."
        )
    message += "\n\nRun  linrar --help  for the full list."
    return message


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


def _inspect(targets: list[str]) -> int:
    """``--inspect``: say exactly what each file is, without a window.

    The same report the interface shows when something will not open, printed
    where a script or a bug report can get at it.  Exits 0 only when every
    file named is one LinRAR can actually open.
    """
    from .core import diagnose

    if not targets:
        print(
            "--inspect (-i) needs at least one file.\n"
            "For example:  linrar -i download.rar",
            file=sys.stderr,
        )
        return EXIT_USAGE

    failed = 0
    for index, path in enumerate(targets):
        if index:
            print()
        facts = diagnose.inspect_path(path)
        # Only a format proven by the contents earns the short answer; a name
        # that merely looks like an archive gets the full report instead.
        if facts.exists and facts.kind == "file" and facts.confirmed:
            print(f"{path}\n  {facts.format.label} archive, "
                  f"{facts.size:,} bytes".replace(",", " "))
            for name, value in facts.rows()[2:]:
                print(f"  {name:<12} {value}")
        else:
            failed += 1
            print(diagnose.summarise(path), end="")
    return 0 if not failed else EXIT_FAILED


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

    request = parse_args(argv)
    if not request.valid:
        print(f"linrar: {request.error}", file=sys.stderr)
        return EXIT_USAGE

    if request.query == "--help":
        print(USAGE)
        return 0
    if request.query == "--version":
        # "LinRAR <version>" first, always, so a script can cut the second
        # field; anything known about the build follows in brackets.
        from .version import describe

        print(f"LinRAR {describe()}")
        return 0
    if request.query == "--config-info":
        # For administrators: which files are in play, and what each key
        # actually resolves to once the layers are merged.
        print(SETTINGS.describe())
        return 0
    if request.query == "--inspect":
        return _inspect(request.arguments)
    if request.self_test:
        # Build the whole window once and exit: what install.sh checks with.
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        app = QApplication(argv)
        theme.apply(app, SETTINGS.get("view/theme"))
        MainWindow()
        return 0

    action, paths = request.action, request.paths
    # A file that is not there is worth saying out loud, even though the window
    # still opens: the right-click menu is a common way to reach a stale path.
    for path in request.missing:
        print(f"linrar: no such file or folder: {path}", file=sys.stderr)

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
        else:
            window.open_archive(target)
    elif not action and request.missing:
        # Nothing to open, but the user named something: show them why, in the
        # window, with everything LinRAR could work out about the path.
        window.report_path(request.missing[0])

    _check_tools(window)
    # Only when the user asked for it in Settings, and only on a timer once the
    # window is up: opening LinRAR must never wait on the network.
    window.start_update_check()
    if action:
        _run_action(window, action, paths)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
