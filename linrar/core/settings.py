"""Persisted application preferences, kept in one readable INI file.

Every choice the user makes — theme, toolbar contents, view mode, layout,
compression and extraction defaults, favourites, history, tool paths — is
written to a single file and read back on the next launch:

    ``$XDG_CONFIG_HOME/LinRAR/linrar.conf``  (usually
    ``~/.config/LinRAR/linrar.conf``)

The path is fixed rather than left to Qt so it is the same on every desktop and
distribution, and so it can be quoted in the UI and in the documentation.
Settings written by earlier versions, which used Qt's own location, are
imported once on first run.
"""

from __future__ import annotations

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
    # -- tools: set these to run a rar/unrar/7z from somewhere unusual --
    "paths/rar": "",
    "paths/unrar": "",
    "paths/sevenzip": "",
    "paths/zip": "",
}


def config_dir() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "LinRAR")


def config_path() -> str:
    return os.path.join(config_dir(), "linrar.conf")


class Settings:
    """Thin typed wrapper so callers never repeat a default value."""

    def __init__(self, path: str = "") -> None:
        self.path = path or config_path()
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
        except OSError:
            pass
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
        """Forget everything; the next read of each key returns its default."""
        self._store.clear()
        self._store.setValue("meta/config_version", CONFIG_VERSION)
        self._store.sync()

    # -- values ------------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        fallback = DEFAULTS.get(key, default)
        value = self._store.value(key, fallback)
        if isinstance(fallback, bool):
            if isinstance(value, str):
                return value.lower() in ("true", "1", "yes")
            return bool(value)
        if isinstance(fallback, int) and not isinstance(fallback, bool):
            try:
                return int(value)
            except (TypeError, ValueError):
                return fallback
        return value

    def string_list(self, key: str) -> list[str]:
        """A list setting, tolerating QSettings collapsing a lone entry."""
        raw = self._store.value(key, DEFAULTS.get(key, []))
        if isinstance(raw, str):
            return [raw] if raw else []
        return [str(item) for item in (raw or [])]

    def set(self, key: str, value: Any) -> None:
        self._store.setValue(key, value)

    def reset(self, *keys: str) -> None:
        """Forget these keys so their defaults apply again."""
        for key in keys:
            self._store.remove(key)

    def sync(self) -> None:
        self._store.sync()

    def keys(self) -> list[str]:
        return list(self._store.allKeys())

    # -- window geometry ---------------------------------------------------

    def save_geometry(self, name: str, data: bytes) -> None:
        self._store.setValue(f"geometry/{name}", data)

    def load_geometry(self, name: str) -> Any:
        return self._store.value(f"geometry/{name}")

    # -- favorites ---------------------------------------------------------

    def favorites(self) -> list[str]:
        return self.string_list("favorites")

    def set_favorites(self, items: list[str]) -> None:
        self._store.setValue("favorites", items)

    # -- history -----------------------------------------------------------

    def history(self) -> list[str]:
        return self.string_list("history")

    def push_history(self, path: str, limit: int = 12) -> None:
        items = [p for p in self.history() if p != path]
        items.insert(0, path)
        self._store.setValue("history", items[:limit])


SETTINGS = Settings()
