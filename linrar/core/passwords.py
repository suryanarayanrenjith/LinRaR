"""Stored passwords: WinRAR's "Organize passwords".

Where the desktop provides a secret service (GNOME Keyring, KWallet via
libsecret), passwords are stored there and never touch our own configuration.
Only when no keyring is reachable do we fall back to local storage, and that
fallback is *obfuscated, not encrypted*: the UI says so plainly rather than
implying a guarantee we cannot make.
"""

from __future__ import annotations

import base64
import fnmatch
import json
import os
import shutil
import subprocess
from dataclasses import dataclass, replace
from typing import Optional


from .settings import SETTINGS

_SCHEMA = "org.linrar.ArchivePassword"

#: An entry name nothing is ever stored under, used only to ask the secret
#: service whether it is there at all.  The dialog requires a label, and a
#: leading space is not one anybody can type, so this can never collide with a
#: real entry.
_PROBE = " linrar service probe "


@dataclass
class PasswordEntry:
    """A saved password and the archives it applies to."""

    label: str
    mask: str = "*"          # filename mask this password is tried for
    password: str = ""
    note: str = ""

    def matches(self, filename: str) -> bool:
        base = os.path.basename(filename)
        return fnmatch.fnmatch(base.lower(), (self.mask or "*").lower())


def keyring_available() -> bool:
    """True when secret-tool is installed **and** a secret service answers.

    Installing ``libsecret-tools`` does not mean anything is listening: a
    headless server, a minimal window manager, a container or a CI runner all
    routinely have the command and no daemon behind it.  ``secret-tool`` then
    fails on stderr ("Could not connect: No such file or directory") while
    still exiting 1, which is also the perfectly ordinary "nothing stored yet".

    So the status is not enough on its own.  This used to look for the word
    "cannot" in stderr, which that message does not contain, so LinRAR
    believed in a keyring that was not there: every password saved went
    nowhere and came back empty.

    ``lookup`` is the probe rather than ``search`` because it is silent when
    it works: ``search`` prints the matching attributes *to stderr*, so
    "stderr means trouble" would be wrong for the very case it is meant to
    accept.  Looking up a name nothing will ever be stored under exits 1 with
    nothing on stderr when a service answered, and exits 1 with the connection
    error when none did.
    """
    if not shutil.which("secret-tool"):
        return False
    try:
        proc = subprocess.run(
            ["secret-tool", "lookup", "schema", _SCHEMA, "entry", _PROBE],
            capture_output=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    # Exit 1 simply means "nothing stored under that name", which still proves
    # the service is reachable; a missing daemon complains on stderr.
    if proc.returncode not in (0, 1):
        return False
    return not proc.stderr.strip()


class PasswordStore:
    """Reads and writes saved passwords, preferring the system keyring.

    The keyring is reached by running ``secret-tool``, once per stored entry.
    Opening any archive asks this store for the passwords whose mask fits it,
    so a user with a dozen saved passwords was paying a dozen process launches
    for every archive they opened, whether or not it was even encrypted.  The
    entries are therefore read once and kept, and dropped again the moment
    anything writes to the store.
    """

    KEY = "passwords/list"

    def __init__(self) -> None:
        self._use_keyring = keyring_available()
        #: Set when the keyring turned out not to work after all, so the UI
        #: can say what happened rather than quietly changing its mind.
        self.failure = ""
        #: The last result of :meth:`load`, or ``None`` when it must be read
        #: again.  Only ever holds what this process has already been told.
        self._cache: Optional[list[PasswordEntry]] = None

    @property
    def backend_name(self) -> str:
        return "System keyring" if self._use_keyring else "Local file (obfuscated)"

    @property
    def secure(self) -> bool:
        return self._use_keyring

    # -- metadata (always local; only the secret itself goes to the keyring)

    def _load_meta(self) -> list[dict]:
        raw = SETTINGS.get(self.KEY, "")
        if not raw:
            return []
        try:
            return list(json.loads(raw))
        except (ValueError, TypeError):
            return []

    def _save_meta(self, items: list[dict]) -> None:
        SETTINGS.set(self.KEY, json.dumps(items))
        SETTINGS.sync()

    # -- public API --------------------------------------------------------

    def invalidate(self) -> None:
        """Forget what was read, so the next :meth:`load` asks again."""
        self._cache = None

    def load(self) -> list[PasswordEntry]:
        """Every saved password, read from the keyring at most once."""
        if self._cache is not None:
            return [replace(entry) for entry in self._cache]
        entries: list[PasswordEntry] = []
        for item in self._load_meta():
            entry = PasswordEntry(
                label=item.get("label", ""),
                mask=item.get("mask", "*"),
                note=item.get("note", ""),
            )
            if self._use_keyring:
                entry.password = self._keyring_get(entry.label) or ""
            # A record that carries its own secret wins whenever the keyring
            # had nothing to say.  That covers both the ordinary local store
            # and the entries written before a keyring appeared on the
            # machine, which would otherwise come back blank.
            if not entry.password:
                entry.password = _deobfuscate(item.get("secret", ""))
            entries.append(entry)
        self._cache = entries
        return [replace(entry) for entry in entries]

    def save(self, entries: list[PasswordEntry]) -> None:
        """Store *entries*, keeping them somewhere even if the keyring refuses.

        A password that cannot be written to the keyring is written to
        LinRAR's own file instead, and the store stops claiming to be using a
        keyring.  Losing what the user typed, which is what silently
        swallowing the failure amounted to, is far worse than falling back to
        the weaker storage and saying so.
        """
        self.invalidate()
        existing = {item.get("label") for item in self._load_meta()}
        kept = {entry.label for entry in entries}
        if self._use_keyring:
            for label in existing - kept:
                self._keyring_delete(label)

        refused = False
        if self._use_keyring:
            for entry in entries:
                if not self._keyring_set(entry.label, entry.password):
                    refused = True
                    break
        if refused:
            self._use_keyring = False
            self.failure = (
                "The system keyring would not accept the passwords, so they "
                "were kept in LinRAR's own file instead."
            )

        items = []
        for entry in entries:
            record = {"label": entry.label, "mask": entry.mask, "note": entry.note}
            if not self._use_keyring:
                record["secret"] = _obfuscate(entry.password)
            items.append(record)
        self._save_meta(items)

    def candidates_for(self, filename: str) -> list[str]:
        """Passwords whose mask matches *filename*, best match first."""
        entries = self.load()
        exact = [e.password for e in entries if e.mask not in ("*", "") and e.matches(filename)]
        generic = [e.password for e in entries if e.mask in ("*", "")]
        seen: set[str] = set()
        result = []
        for password in exact + generic:
            if password and password not in seen:
                seen.add(password)
                result.append(password)
        return result

    # -- keyring helpers ---------------------------------------------------

    def _keyring_set(self, label: str, password: str) -> bool:
        """Write one secret.  ``False`` means the keyring would not take it."""
        if not password:
            return True
        try:
            proc = subprocess.run(
                [
                    "secret-tool", "store", "--label", f"LinRAR: {label}",
                    "schema", _SCHEMA, "entry", label,
                ],
                input=password.encode("utf-8"),
                capture_output=True,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        if proc.returncode != 0 or proc.stderr.strip():
            return False
        # Trust nothing: prove it can be read back before reporting success.
        # `secret-tool store` has been known to exit 0 against a service that
        # then holds nothing, and a password that cannot be read back is a
        # password that has been lost.
        return self._keyring_get(label) == password

    def _keyring_get(self, label: str) -> Optional[str]:
        try:
            proc = subprocess.run(
                ["secret-tool", "lookup", "schema", _SCHEMA, "entry", label],
                capture_output=True,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if proc.returncode != 0:
            return None
        return proc.stdout.decode("utf-8", "replace").strip("\n")

    def _keyring_delete(self, label: str) -> None:
        try:
            subprocess.run(
                ["secret-tool", "clear", "schema", _SCHEMA, "entry", label],
                capture_output=True,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass


def _obfuscate(value: str) -> str:
    if not value:
        return ""
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


def _deobfuscate(value: str) -> str:
    if not value:
        return ""
    try:
        return base64.b64decode(value.encode("ascii")).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return ""


PASSWORDS = PasswordStore()
