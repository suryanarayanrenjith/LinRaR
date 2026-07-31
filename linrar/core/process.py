"""Subprocess plumbing for the rar/unrar command line tools.

``rar`` and ``unrar`` report progress by rewriting the current terminal line
with backspaces (``\\b\\b\\b\\b 42%``) rather than emitting newlines.  A naive
``readline()`` loop therefore blocks until a file finishes.  :class:`LineAssembler`
replays those control characters so we can observe the line exactly as a
terminal would render it, and :class:`ProcessRunner` streams the result.
"""

from __future__ import annotations

import os
import re
import selectors
import signal
import subprocess
import threading
from typing import Callable, Iterable, Optional

# " 42%" / "100%" as rendered after the backspaces have been applied.
PERCENT_RE = re.compile(r"(\d{1,3})%")

# "Adding    foo.txt", "Extracting  bar/baz.txt", "Testing     qux"
FILE_LINE_RE = re.compile(
    r"^\s*(Adding|Updating|Extracting|Testing|Creating|Deleting|Packing|"
    r"Skipping|Replacing)\s+(.+?)(?:\s{2,}.*)?$"
)


class LineAssembler:
    """Replays ``\\b``, ``\\r`` and ``\\n`` to reconstruct terminal output.

    Feed it raw decoded text; it yields ``(line, final)`` tuples where *final*
    is ``True`` for lines terminated by a newline and ``False`` for the
    still-being-rewritten current line.
    """

    def __init__(self) -> None:
        self._buf: list[str] = []

    def feed(self, text: str) -> list[tuple[str, bool]]:
        out: list[tuple[str, bool]] = []
        for ch in text:
            if ch == "\n":
                out.append(("".join(self._buf), True))
                self._buf = []
            elif ch == "\r":
                # Carriage return without newline restarts the line.
                self._buf = []
            elif ch == "\b":
                if self._buf:
                    self._buf.pop()
            else:
                self._buf.append(ch)
        if self._buf:
            out.append(("".join(self._buf), False))
        return out

    def flush(self) -> Optional[str]:
        if self._buf:
            line = "".join(self._buf)
            self._buf = []
            return line
        return None


class ProcessRunner:
    """Runs a command, streaming reconstructed output lines to callbacks.

    Passwords are written to the child's stdin rather than passed on the command
    line so they never appear in ``/proc/<pid>/cmdline`` for other users to read.
    """

    def __init__(
        self,
        argv: list[str],
        cwd: Optional[str] = None,
        stdin_text: Optional[str] = None,
        on_line: Optional[Callable[[str], None]] = None,
        on_partial: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.argv = argv
        self.cwd = cwd
        self.stdin_text = stdin_text
        self.on_line = on_line
        self.on_partial = on_partial

        self._proc: Optional[subprocess.Popen] = None
        self._cancelled = threading.Event()
        self.output_lines: list[str] = []
        self.returncode: int = -1

    # -- lifecycle ---------------------------------------------------------

    def cancel(self) -> None:
        """Ask the child to stop; escalate to SIGKILL if it ignores us."""
        self._cancelled.set()
        proc = self._proc
        if proc is None or proc.poll() is not None:
            return
        try:
            proc.terminate()
        except (ProcessLookupError, OSError):
            return
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except (ProcessLookupError, OSError):
                pass

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    def run(self) -> int:
        """Execute the command and block until it exits."""
        env = dict(os.environ)
        # Keep rar's own messages parseable regardless of the user's locale.
        env["LC_ALL"] = "C.UTF-8"
        env.setdefault("LANG", "C.UTF-8")

        try:
            self._proc = subprocess.Popen(
                self.argv,
                cwd=self.cwd or None,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
                bufsize=0,
                start_new_session=True,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(f"Command not found: {self.argv[0]}") from exc

        proc = self._proc
        assert proc.stdin is not None and proc.stdout is not None

        # Hand over the password (and close stdin) on a helper thread so a
        # child that never reads stdin cannot deadlock us on a full pipe.
        def _write_stdin() -> None:
            try:
                if self.stdin_text:
                    proc.stdin.write(self.stdin_text.encode("utf-8"))
                    proc.stdin.flush()
            except (BrokenPipeError, OSError, ValueError):
                pass
            finally:
                try:
                    proc.stdin.close()
                except (BrokenPipeError, OSError, ValueError):
                    pass

        writer = threading.Thread(target=_write_stdin, daemon=True)
        writer.start()

        assembler = LineAssembler()
        decoder_buf = b""

        sel = selectors.DefaultSelector()
        sel.register(proc.stdout, selectors.EVENT_READ)
        try:
            while True:
                for _key, _mask in sel.select(timeout=0.1):
                    try:
                        chunk = os.read(proc.stdout.fileno(), 8192)
                    except OSError:
                        chunk = b""
                    if not chunk:
                        raise _StreamClosed
                    decoder_buf += chunk
                    # Decode only whole UTF-8 sequences; keep any tail for later.
                    text, decoder_buf = _decode_partial(decoder_buf)
                    if text:
                        self._dispatch(assembler.feed(text))
                if proc.poll() is not None:
                    # Drain whatever is still buffered in the pipe.
                    try:
                        while True:
                            chunk = os.read(proc.stdout.fileno(), 8192)
                            if not chunk:
                                break
                            decoder_buf += chunk
                            text, decoder_buf = _decode_partial(decoder_buf)
                            if text:
                                self._dispatch(assembler.feed(text))
                    except OSError:
                        pass
                    break
        except _StreamClosed:
            pass
        finally:
            sel.close()

        if decoder_buf:
            self._dispatch(assembler.feed(decoder_buf.decode("utf-8", "replace")))
        tail = assembler.flush()
        if tail:
            self.output_lines.append(tail)
            if self.on_line:
                self.on_line(tail)

        proc.wait()
        writer.join(timeout=1)
        self.returncode = proc.returncode
        return self.returncode

    # -- internals ---------------------------------------------------------

    def _dispatch(self, events: Iterable[tuple[str, bool]]) -> None:
        for line, final in events:
            if final:
                self.output_lines.append(line)
                if self.on_line:
                    self.on_line(line)
            elif self.on_partial:
                self.on_partial(line)

    @property
    def output(self) -> str:
        return "\n".join(self.output_lines)


class _StreamClosed(Exception):
    """Internal sentinel signalling EOF on the child's stdout."""


def _decode_partial(data: bytes) -> tuple[str, bytes]:
    """Decode as much UTF-8 as possible, returning the undecodable tail.

    Prevents a multi-byte character split across two reads from being mangled
    into replacement characters.
    """
    if not data:
        return "", b""
    for cut in range(len(data), max(len(data) - 4, 0) - 1, -1):
        try:
            return data[:cut].decode("utf-8"), data[cut:]
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "replace"), b""


def parse_percent(line: str) -> Optional[int]:
    """Return the last percentage rendered on *line*, if any."""
    matches = PERCENT_RE.findall(line)
    if not matches:
        return None
    try:
        value = int(matches[-1])
    except ValueError:
        return None
    return value if 0 <= value <= 100 else None


def parse_file_line(line: str) -> Optional[tuple[str, str]]:
    """Return ``(verb, filename)`` for rar's per-file status lines."""
    match = FILE_LINE_RE.match(line)
    if not match:
        return None
    return match.group(1), match.group(2).strip()
