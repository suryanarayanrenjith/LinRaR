"""Stored passwords: WinRAR's "Organize passwords".

Where the desktop provides a secret service (GNOME Keyring, KWallet via
libsecret), passwords are stored there and never touch our own configuration.
Only when no keyring is reachable do we fall back to local storage, and that
fallback is *obfuscated, not encrypted*: the UI says so plainly rather than
implying a guarantee we cannot make.
"""

from __future__ import annotations

import base64
import json
import shutil
import subprocess
from dataclasses import dataclass
from typing import Optional


from .settings import SETTINGS

_SCHEMA = "org.linrar.ArchivePassword"


@dataclass
class PasswordEntry:
    """A saved password and the archives it applies to."""

    label: str
    mask: str = "*"          # filename mask this password is tried for
    password: str = ""
    note: str = ""

    def matches(self, filename: str) -> bool:
        import fnmatch
        import os

        base = os.path.basename(filename)
        return fnmatch.fnmatch(base.lower(), (self.mask or "*").lower())


def keyring_available() -> bool:
    """True when secret-tool is installed and a secret service answers."""
    if not shutil.which("secret-tool"):
        return False
    try:
        proc = subprocess.run(
            ["secret-tool", "search", "--all", "schema", _SCHEMA],
            capture_output=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    # Exit 1 simply means "nothing stored yet", which still proves the
    # service is reachable; a missing daemon reports an error on stderr.
    if proc.returncode not in (0, 1):
        return False
    return b"cannot" not in proc.stderr.lower()


class PasswordStore:
    """Reads and writes saved passwords, preferring the system keyring."""

    KEY = "passwords/list"

    def __init__(self) -> None:
        self._use_keyring = keyring_available()

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

    def load(self) -> list[PasswordEntry]:
        entries: list[PasswordEntry] = []
        for item in self._load_meta():
            entry = PasswordEntry(
                label=item.get("label", ""),
                mask=item.get("mask", "*"),
                note=item.get("note", ""),
            )
            if self._use_keyring:
                entry.password = self._keyring_get(entry.label) or ""
            else:
                entry.password = _deobfuscate(item.get("secret", ""))
            entries.append(entry)
        return entries

    def save(self, entries: list[PasswordEntry]) -> None:
        existing = {item.get("label") for item in self._load_meta()}
        kept = {entry.label for entry in entries}
        if self._use_keyring:
            for label in existing - kept:
                self._keyring_delete(label)

        items = []
        for entry in entries:
            record = {"label": entry.label, "mask": entry.mask, "note": entry.note}
            if self._use_keyring:
                self._keyring_set(entry.label, entry.password)
            else:
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

    def _keyring_set(self, label: str, password: str) -> None:
        if not password:
            return
        try:
            subprocess.run(
                [
                    "secret-tool", "store", "--label", f"LinRAR: {label}",
                    "schema", _SCHEMA, "entry", label,
                ],
                input=password.encode("utf-8"),
                capture_output=True,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass

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
