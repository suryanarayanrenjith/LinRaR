#!/usr/bin/env python3
"""Run every LinRAR test file and summarise the result.

    ./tests/run_all.py              # all of them
    ./tests/run_all.py theme ui     # only the ones whose name contains these

Each test file is a standalone script that prints "N passed, M failed" and
exits non-zero on failure, so this is deliberately a thin driver: no framework,
nothing to install.  It uses the project's own virtual environment when there
is one, so `python3 tests/run_all.py` works even outside it.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

#: Slowest last: the backend suites shell out to rar/unrar many times.
ORDER = [
    "test_parsing.py",
    "test_theme.py",
    "test_customize.py",
    "test_persistence.py",
    "test_config.py",
    "test_ui.py",
    "test_dialog.py",
    "test_mainwindow.py",
    "test_backends.py",
    "test_sfx_appimage.py",
    "test_final.py",
]

#: Files that cannot run without a particular tool.  `rar` is shareware and is
#: missing on plenty of machines (and on CI runners), so those files are
#: skipped with a note rather than reported as failures.
REQUIRES = {
    "test_backends.py": ["rar", "unrar"],
    "test_final.py": ["rar", "unrar"],
    "test_sfx_appimage.py": ["rar", "unrar", "mksquashfs"],
    "test_mainwindow.py": ["rar"],
    "test_dialog.py": ["rar"],
}

BOLD, GREEN, RED, DIM, OFF = (
    ("\033[1m", "\033[32m", "\033[31m", "\033[2m", "\033[0m")
    if sys.stdout.isatty() and not os.environ.get("NO_COLOR")
    else ("", "", "", "", "")
)


def interpreter() -> str:
    venv = os.path.join(ROOT, ".venv", "bin", "python")
    return venv if os.path.exists(venv) else sys.executable


def available(tool: str) -> bool:
    """Is *tool* usable — asked the same way the application asks it.

    LinRAR looks past PATH into the places distributions and manual installs
    use, so the tests must agree with it or they would skip work that would
    actually have run.
    """
    try:
        sys.path.insert(0, ROOT)
        from linrar.core import tools as tool_finder

        kind = {"7z": "sevenzip", "mksquashfs": "squashfs"}.get(tool, tool)
        if kind in tool_finder.CANDIDATES:
            return bool(tool_finder.find(kind))
    except Exception:
        pass
    return bool(shutil.which(tool))


def files(patterns: list[str]) -> list[str]:
    known = [name for name in ORDER if os.path.exists(os.path.join(HERE, name))]
    extra = sorted(
        name for name in os.listdir(HERE)
        if name.startswith("test_") and name.endswith(".py") and name not in known
    )
    names = known + extra
    if not patterns:
        return names
    return [n for n in names if any(p.strip("/") in n for p in patterns)]


def main(argv: list[str]) -> int:
    selected = files(argv[1:])
    if not selected:
        print("no test files matched")
        return 1

    python = interpreter()
    print(f"{BOLD}LinRAR test suite{OFF}  {DIM}({python}){OFF}\n")

    passed = failed = 0
    broken: list[str] = []
    skipped: list[str] = []
    started = time.monotonic()
    for name in selected:
        print(f"  {name:<24}", end="", flush=True)
        missing = [
            tool for tool in REQUIRES.get(name, []) if not available(tool)
        ]
        if missing:
            skipped.append(name)
            print(f"{DIM}skipped  needs {', '.join(missing)}{OFF}")
            continue
        began = time.monotonic()
        result = subprocess.run(
            [python, os.path.join(HERE, name)],
            capture_output=True, text=True, cwd=ROOT,
        )
        seconds = time.monotonic() - began
        summary = ""
        for line in reversed(result.stdout.splitlines()):
            if "passed," in line:
                summary = line.strip()
                break
        counts = summary.replace(" passed,", "").replace(" failed", "").split()
        if len(counts) == 2 and counts[0].isdigit() and counts[1].isdigit():
            passed += int(counts[0])
            failed += int(counts[1])
        if result.returncode == 0:
            print(f"{GREEN}ok{OFF}    {summary or 'no summary'}  {DIM}{seconds:.1f}s{OFF}")
        else:
            broken.append(name)
            print(f"{RED}FAIL{OFF}  {summary or 'crashed'}  {DIM}{seconds:.1f}s{OFF}")
            output = (result.stdout + result.stderr).strip()
            # The failed checks first — a tail alone hides them when the file
            # keeps going, which is exactly when you need to see them.
            failures = [
                line for line in output.splitlines() if line.startswith("FAIL")
            ]
            for line in failures:
                print(f"        {RED}{line}{OFF}")
            tail = output.splitlines()[-25:]
            if tail and (not failures or tail[-1] != failures[-1]):
                print(f"        {DIM}--- last {len(tail)} lines ---{OFF}")
                for line in tail:
                    print(f"        {DIM}{line}{OFF}")

    elapsed = time.monotonic() - started
    print()
    colour = RED if broken else GREEN
    ran = len(selected) - len(skipped)
    print(f"{colour}{BOLD}{passed} checks passed, {failed} failed{OFF}"
          f"  {DIM}across {ran} files in {elapsed:.1f}s{OFF}")
    if skipped:
        print(f"{DIM}skipped (tools not installed): {', '.join(skipped)}{OFF}")
    if broken:
        print(f"{RED}failing files: {', '.join(broken)}{OFF}")
    return 1 if broken else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
