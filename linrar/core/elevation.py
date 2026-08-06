"""Gaining administrator rights, for the few things that genuinely need them.

Installing or removing packages, and writing outside the user's own folders,
cannot be done as an ordinary user.  This module finds whichever escalation
tool the system has, authenticates once, and keeps that authorisation alive so
a run of operations only asks the user a single time.

The password is written to the helper's **stdin** and never kept: ``sudo -S -v``
validates it and stamps sudo's own timestamp, after which ``sudo -n`` works
without a password until it expires.  A small keep-alive thread refreshes that
stamp while a session is open.
"""

from __future__ import annotations

import functools
import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Optional

#: How long a session is assumed good for before the UI stops promising it.
SESSION_SECONDS = 15 * 60
_KEEPALIVE_SECONDS = 60


@functools.lru_cache(maxsize=8)
def _which(binary: str) -> Optional[str]:
    """``shutil.which``, remembered.

    Whether pkexec, sudo and doas exist does not change while LinRAR is open,
    and the property that asks is read on nearly every line of the code below.
    """
    return shutil.which(binary)


@dataclass(frozen=True)
class Method:
    """One way of running a command as root."""

    key: str
    binary: str
    label: str
    #: True when the tool prompts on its own (a desktop dialog), so LinRAR
    #: must not ask for a password itself.
    prompts_itself: bool
    #: True when a validated session can be kept alive in the background.
    keeps_session: bool

    @property
    def path(self) -> Optional[str]:
        return _which(self.binary)


METHODS: tuple[Method, ...] = (
    Method("pkexec", "pkexec", "pkexec (desktop authentication)", True, False),
    Method("sudo", "sudo", "sudo (password)", False, True),
    Method("doas", "doas", "doas (password)", False, True),
)


def is_root() -> bool:
    return os.geteuid() == 0


def available() -> list[Method]:
    """Every escalation tool present on this system."""
    return [method for method in METHODS if method.path]


#: How long an answer from :func:`passwordless` is reused for.  It runs
#: ``sudo -n true``, which is a process launch and a line in the audit log,
#: and the UI asks the question several times over while building one dialog:
#: ``preferred``, ``describe``, ``needs_password`` and ``command`` each want
#: it.  A few seconds is far shorter than a sudo timestamp lives and long
#: enough that one user action asks once.
_PROBE_SECONDS = 5.0

#: (method key -> (answered at, answer)).
_probe_cache: dict[str, tuple[float, bool]] = {}
_probe_lock = threading.Lock()


def passwordless(method: Method) -> bool:
    """True when *method* can already run as root without asking."""
    if method.key not in ("sudo", "doas"):
        return False
    binary = method.path
    if not binary:
        return False
    now = time.monotonic()
    with _probe_lock:
        cached = _probe_cache.get(method.key)
        if cached is not None and now - cached[0] < _PROBE_SECONDS:
            return cached[1]
    try:
        proc = subprocess.run(
            [binary, "-n", "true"], capture_output=True, timeout=5
        )
        answer = proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        answer = False
    with _probe_lock:
        _probe_cache[method.key] = (time.monotonic(), answer)
    return answer


class Session:
    """The app's live administrator authorisation, if it has one."""

    def __init__(self) -> None:
        self._method: Optional[Method] = None
        self._until: float = 0.0
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        #: Set when the chosen tool needs no authentication at all.
        self.passwordless = False

    # -- choosing a method -------------------------------------------------

    def preferred(self, requested: str = "auto") -> Optional[Method]:
        """The method to use: the requested one when present, else the best."""
        options = available()
        if not options:
            return None
        if requested and requested != "auto":
            for method in options:
                if method.key == requested:
                    return method
        # A live session wins, then a tool that needs no password, then the
        # desktop's own prompt, then anything at all.
        if self.active and self._method in options:
            return self._method
        for method in options:
            if passwordless(method):
                return method
        for method in options:
            if method.prompts_itself:
                return method
        return options[0]

    # -- state -------------------------------------------------------------

    @property
    def active(self) -> bool:
        with self._lock:
            return self._method is not None and time.monotonic() < self._until

    @property
    def method(self) -> Optional[Method]:
        return self._method

    @property
    def seconds_left(self) -> int:
        with self._lock:
            return max(0, int(self._until - time.monotonic()))

    def describe(self, requested: str = "auto") -> str:
        """A sentence for the UI about what will happen on the next command."""
        if is_root():
            return "Running as root: changes apply immediately."
        method = self.preferred(requested)
        if method is None:
            return (
                "No way to gain administrator rights was found (pkexec, sudo "
                "and doas are all missing). The exact command to run in a "
                "terminal will be shown instead."
            )
        if self.active:
            minutes = max(1, self.seconds_left // 60)
            return (
                f"Administrator access granted via {method.binary}, held for "
                f"about {minutes} more minute(s)."
            )
        if passwordless(method):
            return (
                f"Administrator rights via {method.binary}, which is "
                "configured to run without a password."
            )
        if method.prompts_itself:
            return (
                f"Administrator rights via {method.binary}; your desktop will "
                "ask you to authenticate."
            )
        return (
            f"Administrator rights via {method.binary}; LinRAR will ask for "
            "your password once and hold the authorisation."
        )

    # -- authenticating ----------------------------------------------------

    def authenticate(
        self, password: Optional[str] = None, requested: str = "auto"
    ) -> tuple[bool, str]:
        """Obtain administrator rights.  Returns ``(ok, message)``.

        *password* is used once, for ``sudo``/``doas``, and never stored.
        """
        if is_root():
            return True, "Already running as root."
        method = self.preferred(requested)
        if method is None:
            return False, "No escalation tool (pkexec, sudo or doas) is installed."
        binary = method.path or method.binary

        if passwordless(method):
            self.passwordless = True
            self._begin(method)
            return True, f"{method.binary} needs no password on this system."

        if method.prompts_itself:
            # pkexec cannot hold a session, but polkit may remember the
            # authorisation for a few minutes on its own.
            try:
                proc = subprocess.run(
                    [binary, "true"], capture_output=True, timeout=180
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                return False, f"Could not run {method.binary}: {exc}"
            if proc.returncode != 0:
                return False, "Authentication was cancelled or refused."
            self._begin(method, keep_alive=False)
            return True, "Authenticated."

        if password is None:
            return False, "A password is required."
        try:
            proc = subprocess.run(
                [binary, "-S", "-p", "", "-v"],
                input=(password + "\n").encode("utf-8"),
                capture_output=True,
                timeout=60,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, f"Could not run {method.binary}: {exc}"
        if proc.returncode != 0:
            detail = (proc.stderr or b"").decode("utf-8", "replace").strip()
            return False, detail.splitlines()[-1] if detail else "Wrong password."
        self._begin(method)
        return True, "Administrator access granted."

    def _begin(self, method: Method, keep_alive: bool = True) -> None:
        with self._lock:
            self._method = method
            self._until = time.monotonic() + SESSION_SECONDS
        if keep_alive and method.keeps_session:
            self._start_keepalive(method)

    def _start_keepalive(self, method: Method) -> None:
        self.stop()
        self._stop = threading.Event()

        def loop(stop: threading.Event, binary: str) -> None:
            while not stop.wait(_KEEPALIVE_SECONDS):
                try:
                    proc = subprocess.run(
                        [binary, "-n", "-v"], capture_output=True, timeout=15
                    )
                except (OSError, subprocess.TimeoutExpired):
                    break
                if proc.returncode != 0:
                    break
                with self._lock:
                    self._until = time.monotonic() + SESSION_SECONDS
            with self._lock:
                if not stop.is_set():
                    self._until = 0.0

        self._thread = threading.Thread(
            target=loop,
            args=(self._stop, method.path or method.binary),
            daemon=True,
            name="linrar-sudo-keepalive",
        )
        self._thread.start()

    def stop(self) -> None:
        """Drop the session; sudo's own timestamp is left to expire."""
        self._stop.set()
        thread = self._thread
        self._thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=1)
        with self._lock:
            self._until = 0.0

    # -- running things ----------------------------------------------------

    def command(
        self, argv: list[str], requested: str = "auto"
    ) -> Optional[list[str]]:
        """Prefix *argv* so it runs as root, or ``None`` if that is impossible."""
        if is_root():
            return list(argv)
        method = self.preferred(requested)
        if method is None:
            return None
        binary = method.path or method.binary
        if method.key == "pkexec":
            return [binary, *argv]
        if self.active or passwordless(method):
            return [binary, "-n", "--", *argv]
        # No session yet: sudo/doas would need a terminal to prompt on, so the
        # caller is expected to call authenticate() first.
        return None

    def needs_password(self, requested: str = "auto") -> bool:
        """True when the UI must collect a password before running anything."""
        if is_root() or self.active:
            return False
        method = self.preferred(requested)
        if method is None or method.prompts_itself:
            return False
        return not passwordless(method)

    def run(
        self, argv: list[str], requested: str = "auto", timeout: int = 300
    ) -> tuple[int, str]:
        """Run *argv* as root and return ``(exit code, combined output)``."""
        elevated = self.command(argv, requested)
        if elevated is None:
            return 126, "No administrator rights available."
        try:
            proc = subprocess.run(
                elevated, capture_output=True, timeout=timeout
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return 1, str(exc)
        output = (proc.stdout or b"").decode("utf-8", "replace")
        output += (proc.stderr or b"").decode("utf-8", "replace")
        return proc.returncode, output


#: The single session the application shares.
SESSION = Session()


def manual_instructions(argv: list[str]) -> str:
    """A copy-and-paste command for when we cannot escalate ourselves."""
    return "sudo " + " ".join(argv)
