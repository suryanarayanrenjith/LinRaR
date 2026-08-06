"""Subprocess plumbing for the rar/unrar command line tools.

``rar`` and ``unrar`` report progress by rewriting the current terminal line
with backspaces (``\\b\\b\\b\\b 42%``) rather than emitting newlines.  A naive
``readline()`` loop therefore blocks until a file finishes.  :class:`LineAssembler`
replays those control characters so we can observe the line exactly as a
terminal would render it, and :class:`ProcessRunner` streams the result.
"""

from __future__ import annotations

import errno
import fcntl
import os
import pty
import re
import selectors
import subprocess
import termios
import threading
from typing import Callable, Iterable, Optional

# " 42%" / "100%" as rendered after the backspaces have been applied.
PERCENT_RE = re.compile(r"(\d{1,3})%")

# "Adding    foo.txt", "Extracting  bar/baz.txt", "Testing     qux"
#
# Two or more spaces, never one: rar pads the verb out to a fixed column for a
# member, and writes ordinary prose with single spaces.  That is what tells
# "Extracting  photos/a.jpg" (a member) from "Extracting from backup.rar"
# (the header line rar prints once per archive), which was otherwise read as a
# member called "from backup.rar".
FILE_LINE_RE = re.compile(
    r"^\s*(Adding|Updating|Extracting|Testing|Creating|Deleting|Packing|"
    r"Skipping|Replacing)\s{2,}(.+?)(?:\s{2,}.*)?$"
)

# rar pads the name out to a status column and then backspaces over the tail to
# write " 42%", "  OK" or "  Failed".  When the name is long enough to reach
# that column there is only one space left between the two, so the status ends
# up glued to the name and has to be taken off it explicitly.
_STATUS_TAIL_RE = re.compile(r"(?:\s+(?:\d{1,3}%|OK|Failed))+\s*$")


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


class PtyUnavailable(RuntimeError):
    """No pseudo-terminal could be set up for a tool that insists on one."""


def _become_session_leader() -> None:
    """Between fork and exec: adopt the pty as the controlling terminal.

    ``zip -e`` and ``7z -p`` do not read a password from standard input.  They
    open ``/dev/tty``, which resolves through the *controlling* terminal, and a
    process started from a desktop has none at all: without this the tools
    refuse outright ("stderr is not a tty"), and a process that merely
    inherited the user's own terminal would prompt on it, where nobody is
    looking.  ``setsid`` puts the child in a session of its own and the ioctl
    makes its new standard input that session's terminal.

    Runs in the forked child, before exec, so it does nothing but two system
    calls: no allocation, no imports, nothing that could want a lock another
    thread holds.
    """
    os.setsid()
    fcntl.ioctl(0, termios.TIOCSCTTY, 0)


class ProcessRunner:
    """Runs a command, streaming reconstructed output lines to callbacks.

    Passwords are written to the child's stdin rather than passed on the command
    line so they never appear in ``/proc/<pid>/cmdline`` for other users to read.

    *prompt_answers* covers the tools that will not take a password on stdin
    at all.  The child is then given a pseudo-terminal of its own, and each
    answer is typed at it the first time the tool falls silent, which is what
    a tool waiting at a prompt looks like.  They are typed rather than
    pre-loaded because these tools flush pending terminal input before asking,
    exactly so that a password cannot be fed to them ahead of the question.
    """

    def __init__(
        self,
        argv: list[str],
        cwd: Optional[str] = None,
        stdin_text: Optional[str] = None,
        on_line: Optional[Callable[[str], None]] = None,
        on_partial: Optional[Callable[[str], None]] = None,
        prompt_answers: Optional[list[str]] = None,
    ) -> None:
        self.argv = argv
        self.cwd = cwd
        self.stdin_text = stdin_text
        self.on_line = on_line
        self.on_partial = on_partial
        self.prompt_answers = list(prompt_answers or [])

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

    def _start_on_pty(self, env: dict) -> int:
        """Launch the child with a terminal of its own.  Returns the master fd."""
        try:
            master, slave = pty.openpty()
        except OSError as exc:
            raise PtyUnavailable(str(exc)) from exc
        try:
            attributes = termios.tcgetattr(slave)
            # Output processing off.  A terminal turns every "\n" the child
            # writes into "\r\n", and LineAssembler reads a carriage return as
            # "start this line again" because that is what rar means by one:
            # left on, every line of output arrives as an empty one.
            attributes[1] &= ~termios.ONLCR
            # Echo off before the child starts, so a password typed at the
            # prompt is never reflected back into the output LinRAR keeps and
            # shows in a progress log.  The tools turn echo off themselves,
            # but only once they have reached the prompt.
            attributes[3] &= ~termios.ECHO
            termios.tcsetattr(slave, termios.TCSANOW, attributes)
        except termios.error:
            pass
        try:
            self._proc = subprocess.Popen(
                self.argv,
                cwd=self.cwd or None,
                stdin=slave,
                stdout=slave,
                stderr=slave,
                env=env,
                close_fds=True,
                preexec_fn=_become_session_leader,
            )
        except FileNotFoundError as exc:
            os.close(master)
            os.close(slave)
            raise RuntimeError(f"Command not found: {self.argv[0]}") from exc
        except OSError as exc:
            os.close(master)
            os.close(slave)
            raise PtyUnavailable(str(exc)) from exc
        # The child holds its own end now; ours has to go or the master never
        # reports end of file.
        os.close(slave)
        return master

    def run(self) -> int:
        """Execute the command and block until it exits."""
        env = dict(os.environ)
        # Keep rar's own messages parseable regardless of the user's locale.
        env["LC_ALL"] = "C.UTF-8"
        env.setdefault("LANG", "C.UTF-8")

        on_pty = bool(self.prompt_answers)
        master = -1
        if on_pty:
            master = self._start_on_pty(env)
            read_fd = master
            writer = None
        else:
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
            read_fd = proc.stdout.fileno()

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

        proc = self._proc
        assert proc is not None
        pending = list(self.prompt_answers)
        assembler = LineAssembler()
        decoder_buf = b""

        def drain() -> bytes:
            """Read what is there, treating a closed pty as end of file."""
            try:
                return os.read(read_fd, 8192)
            except OSError as exc:
                # A pty whose child has gone reports EIO rather than EOF.
                if on_pty and exc.errno not in (errno.EIO, errno.EBADF):
                    raise
                return b""

        sel = selectors.DefaultSelector()
        sel.register(read_fd, selectors.EVENT_READ)
        try:
            while True:
                ready = sel.select(timeout=0.1)
                for _key, _mask in ready:
                    chunk = drain()
                    if not chunk:
                        raise _StreamClosed
                    decoder_buf += chunk
                    # Decode only whole UTF-8 sequences; keep any tail for later.
                    text, decoder_buf = _decode_partial(decoder_buf)
                    if text:
                        self._dispatch(assembler.feed(text))
                if not ready and pending and proc.poll() is None:
                    # Silence with the child still running is what a prompt
                    # looks like from out here.
                    try:
                        os.write(read_fd, (pending.pop(0) + "\n").encode("utf-8"))
                    except OSError:
                        pending.clear()
                    continue
                if proc.poll() is not None:
                    # Drain whatever is still buffered.
                    while True:
                        chunk = drain()
                        if not chunk:
                            break
                        decoder_buf += chunk
                        text, decoder_buf = _decode_partial(decoder_buf)
                        if text:
                            self._dispatch(assembler.feed(text))
                    break
        except _StreamClosed:
            pass
        finally:
            sel.close()
            if on_pty and master >= 0:
                try:
                    os.close(master)
                except OSError:
                    pass

        if decoder_buf:
            self._dispatch(assembler.feed(decoder_buf.decode("utf-8", "replace")))
        tail = assembler.flush()
        if tail:
            self.output_lines.append(tail)
            if self.on_line:
                self.on_line(tail)

        proc.wait()
        if writer is not None:
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
    name = _STATUS_TAIL_RE.sub("", match.group(2)).strip()
    return (match.group(1), name) if name else None
