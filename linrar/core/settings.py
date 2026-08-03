"""Persisted application preferences, kept in readable INI files.

Every choice the user makes (theme, toolbar contents, view mode, layout,
compression and extraction defaults, favourites, history, tool paths) is
written to a single file and read back on the next launch:

    ``$XDG_CONFIG_HOME/LinRAR/linrar.conf``  (usually
    ``~/.config/LinRAR/linrar.conf``)

The path is fixed rather than left to Qt so it is the same on every desktop and
distribution, and so it can be quoted in the UI and in the documentation.
Settings written by earlier versions, which used Qt's own location, are
imported once on first run.

A value is looked up through three layers, each one overriding the one before:

1. the built-in :data:`DEFAULTS`;
2. the **system-wide configuration**, which an administrator installs once for
   every user of the machine (``/etc/linrar/linrar.conf``, its ``conf.d``
   drop-ins, and ``$XDG_CONFIG_DIRS/LinRAR/linrar.conf``);
3. the user's own file above, written whenever a preference is changed.

The system layer may also *lock* keys, through a ``[policy]`` section:

.. code-block:: ini

    [view]
    theme=dark

    [policy]
    locked=view/theme, paths/*

A locked key keeps the value the administrator chose, is never written back to
the user's file, and shows up disabled (with the reason) everywhere it can be
edited in the interface.  Window geometry and the file's own bookkeeping
(``geometry/*``, ``meta/*``) are deliberately outside the administrator's
reach: locking them would freeze the window layout rather than a preference.
"""

from __future__ import annotations

import fnmatch
import glob
import os
from typing import Any

from PyQt6.QtCore import QSettings

#: The organisation/application pair earlier versions handed to QSettings.
LEGACY_ORG = "LinRAR-Linux"
LEGACY_APP = "LinRAR"

#: Bumped when a release needs to convert or drop stored keys.
CONFIG_VERSION = 2

#: Keys that changed name, old -> new.
#:
#: "general/..." had to go: Qt writes a group with that name as "[%General]"
#: and reads it back as "General/...", so anything stored under it was quietly
#: lost on the next launch.  Any group name but that one round-trips.
RENAMED: dict[str, str] = {
    "general/last_folder": "places/last_folder",
    "General/last_folder": "places/last_folder",
    "general/extract_folder": "places/extract_folder",
    "General/extract_folder": "places/extract_folder",
    "general/elevation": "admin/method",
    "General/elevation": "admin/method",
    # Dropped outright: superseded, or unreadable where they were stored.
    "general/config_version": "",
    "General/config_version": "",
    "view/toolbar_text": "",
    "view/large_icons": "",
    "view/details": "",
}

#: Toolbar buttons as they ship, "|" being a separator.  The Customize dialog
#: writes its own version of this list to "toolbar/items".
DEFAULT_TOOLBAR = [
    "add", "extract_to", "test", "view", "delete", "|",
    "find", "wizard", "info", "repair", "|",
    "comment", "protect", "sfx", "|",
    "dependencies",
]

DEFAULTS: dict[str, Any] = {
    "view/theme": "light",
    "view/show_tree": True,
    "view/show_comment": False,
    "view/show_hidden": False,
    # -- customization --
    "view/mode": "details",
    "view/tree_side": "left",
    "view/comment_side": "bottom",
    "view/show_toolbar": True,
    "view/show_address": True,
    "view/show_status": True,
    "view/toolbar_area": "top",
    "view/row_height": "normal",
    "view/grid_lines": False,
    "view/alternate_rows": False,
    "view/sort_column": 0,
    "view/sort_descending": False,
    "toolbar/items": DEFAULT_TOOLBAR,
    "toolbar/icon_size": 32,
    "toolbar/style": "under",
    # -- places --
    "places/last_folder": os.path.expanduser("~"),
    "places/extract_folder": os.path.expanduser("~"),
    "admin/method": "auto",
    # -- compression defaults, remembered from the last archive created --
    "compression/method": 3,
    "compression/format": "RAR",
    "compression/dictionary": "",
    "compression/profile": "Default",
    "compression/update_mode": "add_replace",
    "compression/solid": False,
    "compression/recovery": False,
    "compression/recovery_percent": 3,
    "compression/test_after": False,
    "compression/delete_after": False,
    "compression/store_paths": True,
    "compression/recurse": True,
    "compression/volume_unit": "MB",
    # "appimage" or "rar": which kind of self-extracting archive the SFX box
    # on the archive dialog produces.
    "compression/sfx_format": "appimage",
    "compression/exclude": "",
    # -- extraction defaults --
    "extract/overwrite": "ask",
    "extract/update": "replace",
    "extract/no_paths": False,
    "extract/keep_broken": False,
    "extract/subfolders": False,
    "extract/open_when_done": False,
    # -- find --
    "find/mask": "*.*",
    "find/case_sensitive": False,
    # -- updates: all off until the user asks, because checking for one is a
    # network request they did not make.  An administrator can lock the group
    # to settle the question for a whole machine.
    "update/check_on_start": False,
    "update/automatic": False,
    "update/prereleases": False,
    #: When the last check happened (ISO 8601), so a start-up check can be
    #: rate limited rather than run on every launch.
    "update/last_check": "",
    #: A version the user pressed "Skip" on; never offered again.
    "update/skipped": "",
    # -- tools: set these to run a rar/unrar/7z from somewhere unusual --
    "paths/rar": "",
    "paths/unrar": "",
    "paths/sevenzip": "",
    "paths/zip": "",
}


#: The file name both layers use, so one example serves for both.
CONFIG_NAME = "linrar.conf"

#: Where an administrator puts settings meant for every user of the machine.
#: ``linrar.conf`` is read first, then ``conf.d/*.conf`` in name order, so a
#: packaged default can be overridden by a drop-in without editing it.
SYSTEM_CONFIG_DIR = "/etc/linrar"
DROPIN_DIR = "conf.d"

#: Overrides the search above: a colon-separated list of files, lowest
#: precedence first.  Set it to the empty string for no system layer at all.
#: Meant for packagers, for a sandboxed run, and for the test suite.
SYSTEM_CONFIG_ENV = "LINRAR_SYSTEM_CONFIG"

#: Groups the system layer may neither set nor lock.  ``geometry/*`` is where
#: the window puts itself back together and ``meta/*`` is this file's own
#: version stamp: neither is a preference, and freezing either one breaks the
#: interface rather than configuring it.
SYSTEM_EXCLUDED_GROUPS = ("meta/", "geometry/")

#: Keys inside a system file that steer the policy instead of being settings.
POLICY_LOCKED = "policy/locked"      #: list of key patterns the user may not change
POLICY_LOCK_ALL = "policy/lock_all"  #: lock every key the system file sets
POLICY_KEYS = (POLICY_LOCKED, POLICY_LOCK_ALL)


def config_dir() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "LinRAR")


def config_path() -> str:
    return os.path.join(config_dir(), CONFIG_NAME)


def system_config_paths() -> list[str]:
    """Every system-wide file that exists, lowest precedence first."""
    override = os.environ.get(SYSTEM_CONFIG_ENV)
    if override is not None:
        candidates = override.split(os.pathsep)
    else:
        candidates = []
        # XDG lists these most-important first, so they are read in reverse.
        search = os.environ.get("XDG_CONFIG_DIRS") or "/etc/xdg"
        for directory in reversed([d for d in search.split(os.pathsep) if d]):
            candidates.append(os.path.join(directory, "LinRAR", CONFIG_NAME))
        # LinRAR's own directory outranks the shared XDG search path.
        candidates.append(os.path.join(SYSTEM_CONFIG_DIR, CONFIG_NAME))
        candidates.extend(
            sorted(glob.glob(os.path.join(SYSTEM_CONFIG_DIR, DROPIN_DIR, "*.conf")))
        )
    return [path for path in candidates if path and os.path.isfile(path)]


def _as_list(raw: Any) -> list[str]:
    """A setting written either as ``a, b`` or as a single value."""
    if raw is None:
        return []
    if isinstance(raw, str):
        return [item.strip() for item in raw.split(",") if item.strip()]
    return [str(item).strip() for item in raw if str(item).strip()]


def _as_bool(raw: Any) -> bool:
    if isinstance(raw, str):
        return raw.strip().lower() in ("true", "1", "yes", "on")
    return bool(raw)


class SystemConfig:
    """The read-only layer an administrator installs for every user.

    Construct it with an explicit list of files, with ``[]`` for none at all,
    or with ``None`` to use :func:`system_config_paths`.
    """

    def __init__(self, paths: list[str] | None = None) -> None:
        #: What was asked for, so a reload can repeat the same question.
        self.requested: list[str] | None = None if paths is None else list(paths)
        candidates = system_config_paths() if paths is None else list(paths)
        #: What is actually there.  Only real files, so anything shown to the
        #: user names a file they can go and open.
        self.files: list[str] = [
            path for path in candidates if path and os.path.isfile(path)
        ]
        #: key -> value, later files winning.
        self.values: dict[str, Any] = {}
        #: key -> the file that last set it, for "who did this?" in the UI.
        self.origin: dict[str, str] = {}
        #: Locked key patterns, ``fnmatch`` style, so ``paths/*`` works.
        self.patterns: list[str] = []
        self.lock_all = False
        #: Files that could not be read or parsed, reported rather than hidden.
        self.problems: list[str] = []
        self._read()

    # -- loading -----------------------------------------------------------

    def _read(self) -> None:
        for path in self.files:
            try:
                store = QSettings(path, QSettings.Format.IniFormat)
                keys = store.allKeys()
                status = store.status()
            except Exception:  # pragma: no cover - defensive
                self.problems.append(f"{path}: could not be read")
                continue
            if status == QSettings.Status.AccessError:
                self.problems.append(f"{path}: permission denied")
                continue
            if status != QSettings.Status.NoError:
                # Usually one stray line.  Keep whatever did parse: dropping
                # the file whole would silently ignore an administrator, but
                # say so, loudly, in --config-info and in the Settings dialog.
                self.problems.append(
                    f"{path}: not valid INI in places; only comments starting "
                    "with ';' and 'key=value' lines under a [section] are read"
                )
            for key in keys:
                # Qt's INI parser treats '#' as an ordinary character, so a
                # file commented the shell way turns into keys called
                # "#theme".  Never act on one, whatever it says.
                if key.rsplit("/", 1)[-1].lstrip().startswith(("#", ";")):
                    continue
                value = store.value(key)
                if key == POLICY_LOCKED:
                    self.patterns.extend(_as_list(value))
                    continue
                if key == POLICY_LOCK_ALL:
                    self.lock_all = _as_bool(value)
                    continue
                target = RENAMED.get(key, key)
                if not target or target.startswith(SYSTEM_EXCLUDED_GROUPS):
                    continue
                self.values[target] = value
                self.origin[target] = path

    # -- questions the rest of the program asks -----------------------------

    @property
    def active(self) -> bool:
        """Is there anything at all coming from the system layer?"""
        return bool(self.values or self.patterns or self.lock_all)

    def is_locked(self, key: str) -> bool:
        if not key or key.startswith(SYSTEM_EXCLUDED_GROUPS):
            return False
        if self.lock_all and key in self.values:
            return True
        return any(fnmatch.fnmatchcase(key, pattern) for pattern in self.patterns)

    def locked_keys(self) -> list[str]:
        """Known keys the policy locks: patterns resolved against DEFAULTS."""
        known = set(DEFAULTS) | set(self.values)
        return sorted(key for key in known if self.is_locked(key))

    def source_file(self, key: str) -> str:
        """The file a key's value came from, or the first policy file."""
        if key in self.origin:
            return self.origin[key]
        return self.files[-1] if self.files else ""

    def reason(self, key: str) -> str:
        """One line for a tooltip on a control the user may not touch."""
        if not self.is_locked(key):
            return ""
        where = self.source_file(key)
        return (
            "Set for every user by the system administrator"
            + (f"\n{where}" if where else "")
        )


class Settings:
    """Thin typed wrapper so callers never repeat a default value."""

    def __init__(
        self,
        path: str = "",
        system: SystemConfig | list[str] | None = None,
    ) -> None:
        self.path = path or config_path()
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
        except OSError:
            pass
        self.system = (
            system if isinstance(system, SystemConfig) else SystemConfig(system)
        )
        self._store = QSettings(self.path, QSettings.Format.IniFormat)
        self._migrate()

    # -- lifecycle ---------------------------------------------------------

    def _migrate(self) -> None:
        """Import the settings of a version that used Qt's own location."""
        # INI hands back strings, so "0" would be truthy: compare as a number.
        try:
            stored = int(self._store.value("meta/config_version", 0) or 0)
        except (TypeError, ValueError):
            stored = 0
        if stored >= CONFIG_VERSION:
            return
        try:
            legacy = QSettings(LEGACY_ORG, LEGACY_APP)
            if legacy.fileName() != self.path:
                for key in legacy.allKeys():
                    target = RENAMED.get(key, key)
                    if target and not self._store.contains(target):
                        self._store.setValue(target, legacy.value(key))
        except Exception:  # pragma: no cover - a broken old file is not fatal
            pass
        # Keys already in this file that used a retired name.
        for old, new in RENAMED.items():
            if new and self._store.contains(old) and not self._store.contains(new):
                self._store.setValue(new, self._store.value(old))
            self._store.remove(old)
        self._store.setValue("meta/config_version", CONFIG_VERSION)
        # Rewrite the file from the merged map so the imported keys and the new
        # ones land in one tidy set of groups rather than two.
        values = {key: self._store.value(key) for key in self._store.allKeys()}
        self._store.clear()
        for key, value in values.items():
            self._store.setValue(key, value)
        self._store.sync()

    def reset_all(self) -> None:
        """Forget everything the user chose.

        The system-wide layer is untouched (it is not this user's to clear),
        so the next read of each key returns the administrator's value, or the
        built-in default where there is none.
        """
        self._store.clear()
        self._store.setValue("meta/config_version", CONFIG_VERSION)
        self._store.sync()

    def reload_system(self) -> None:
        """Re-read the system-wide files, after an administrator edits them."""
        self.system = SystemConfig(self.system.requested)

    # -- values ------------------------------------------------------------

    @staticmethod
    def _coerce(value: Any, fallback: Any) -> Any:
        """INI files hand back strings; give the caller the type it expects."""
        if isinstance(fallback, bool):
            if isinstance(value, str):
                return value.strip().lower() in ("true", "1", "yes", "on")
            return bool(value)
        if isinstance(fallback, int) and not isinstance(fallback, bool):
            try:
                return int(value)
            except (TypeError, ValueError):
                return fallback
        return value

    def get(self, key: str, default: Any = None) -> Any:
        fallback = DEFAULTS.get(key, default)
        if self.system.is_locked(key):
            # Locked: the user's file is ignored even when it holds a value.
            if key in self.system.values:
                return self._coerce(self.system.values[key], fallback)
            return fallback
        if self._store.contains(key):
            return self._coerce(self._store.value(key, fallback), fallback)
        if key in self.system.values:
            return self._coerce(self.system.values[key], fallback)
        return fallback

    def _raw(self, key: str, fallback: Any) -> Any:
        """The winning value for *key*, before any type coercion."""
        if self.system.is_locked(key):
            return self.system.values.get(key, fallback)
        if self._store.contains(key):
            return self._store.value(key, fallback)
        return self.system.values.get(key, fallback)

    def string_list(self, key: str) -> list[str]:
        """A list setting, tolerating QSettings collapsing a lone entry."""
        raw = self._raw(key, DEFAULTS.get(key, []))
        if isinstance(raw, str):
            # A hand-written system file may well use one comma-separated line.
            return _as_list(raw) if "," in raw else ([raw] if raw else [])
        return [str(item) for item in (raw or [])]

    def set(self, key: str, value: Any) -> bool:
        """Store *value*, unless an administrator locked *key*.

        Returns whether the write happened, so a caller that cares can say so;
        the many callers that just mirror a widget can ignore it safely.
        """
        if self.system.is_locked(key):
            return False
        self._store.setValue(key, value)
        return True

    def reset(self, *keys: str) -> None:
        """Forget these keys so their defaults apply again."""
        for key in keys:
            self._store.remove(key)

    # -- the system-wide layer ---------------------------------------------

    def is_locked(self, key: str) -> bool:
        """May the user still change *key*?"""
        return self.system.is_locked(key)

    def lock_reason(self, key: str) -> str:
        return self.system.reason(key)

    def source(self, key: str) -> str:
        """Which layer a value comes from: locked/user/system/default/unset."""
        if self.system.is_locked(key):
            return "locked"
        if self._store.contains(key):
            return "user"
        if key in self.system.values:
            return "system"
        return "default" if key in DEFAULTS else "unset"

    def effective(self) -> list[tuple[str, Any, str]]:
        """Every key that has a value, as (key, value, source), sorted."""
        known = set(DEFAULTS) | set(self.system.values) | set(self._store.allKeys())
        return [
            (key, self.get(key), self.source(key))
            for key in sorted(known)
            if not key.startswith("geometry/")
        ]

    def describe(self) -> str:
        """The whole picture, for ``linrar --config-info`` and bug reports."""
        lines = ["LinRAR configuration", ""]
        exists = "" if os.path.isfile(self.path) else "   (not created yet)"
        lines.append(f"  user file    {self.path}{exists}")
        if self.system.files:
            for index, path in enumerate(self.system.files):
                label = "  system       " if index == 0 else "               "
                count = list(self.system.origin.values()).count(path)
                plural = "" if count == 1 else "s"
                lines.append(f"{label}{path}   ({count} key{plural})")
        else:
            lines.append("  system       none installed")
        locked = self.system.locked_keys()
        if self.system.patterns or self.system.lock_all:
            patterns = ", ".join(self.system.patterns) or "-"
            lines.append(f"  locked       {patterns}"
                         + ("  + every key the system file sets"
                            if self.system.lock_all else ""))
            lines.append(f"               {len(locked)} keys in all")
        for problem in self.system.problems:
            lines.append(f"  PROBLEM      {problem}")
        lines.append("")
        lines.append("  key                            value                source")
        for key, value, origin in self.effective():
            shown = ", ".join(str(v) for v in value) if isinstance(value, list) \
                else str(value)
            if len(shown) > 20:
                shown = shown[:19] + "…"
            lines.append(f"  {key:<30} {shown:<20} {origin}")
        return "\n".join(lines)

    def sync(self) -> None:
        self._store.sync()

    def keys(self) -> list[str]:
        return list(self._store.allKeys())

    # -- window geometry ---------------------------------------------------
    # Never part of the system layer, so these go straight to the user's file.

    def save_geometry(self, name: str, data: bytes) -> None:
        self._store.setValue(f"geometry/{name}", data)

    def load_geometry(self, name: str) -> Any:
        return self._store.value(f"geometry/{name}")

    # -- favorites ---------------------------------------------------------

    def favorites(self) -> list[str]:
        return self.string_list("favorites")

    def set_favorites(self, items: list[str]) -> bool:
        return self.set("favorites", items)

    # -- history -----------------------------------------------------------

    def history(self) -> list[str]:
        return self.string_list("history")

    def push_history(self, path: str, limit: int = 12) -> None:
        items = [p for p in self.history() if p != path]
        items.insert(0, path)
        self.set("history", items[:limit])


SETTINGS = Settings()
