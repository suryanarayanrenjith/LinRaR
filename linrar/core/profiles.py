"""Compression profiles: WinRAR's saved sets of archiving parameters."""

from __future__ import annotations

import dataclasses
import json
from dataclasses import asdict, dataclass, field
from typing import Optional


from .models import ArchiveFormat, CompressOptions, CompressionMethod, UpdateMode
from .settings import SETTINGS


@dataclass
class Profile:
    """A named set of archive parameters."""

    name: str
    format: str = ArchiveFormat.RAR5.value
    method: int = int(CompressionMethod.NORMAL)
    dictionary_size: str = ""
    volume_size: int = 0
    update_mode: str = UpdateMode.ADD_REPLACE.value
    solid: bool = False
    recovery_record: bool = False
    recovery_percent: int = 3
    create_sfx: bool = False
    sfx_format: str = ""
    delete_after: bool = False
    test_after: bool = False
    lock: bool = False
    recurse_subfolders: bool = True
    store_paths: bool = True
    encrypt_headers: bool = False
    exclude_patterns: list[str] = field(default_factory=list)
    comment: str = ""
    is_default: bool = False

    # -- conversion --------------------------------------------------------

    @classmethod
    def from_options(cls, name: str, options: CompressOptions) -> "Profile":
        return cls(
            name=name,
            format=options.format.value,
            method=int(options.method),
            dictionary_size=options.dictionary_size,
            volume_size=options.volume_size,
            update_mode=options.update_mode.value,
            solid=options.solid,
            recovery_record=options.recovery_record,
            recovery_percent=options.recovery_percent,
            create_sfx=options.create_sfx,
            sfx_format=options.sfx_format,
            delete_after=options.delete_after,
            test_after=options.test_after,
            lock=options.lock,
            recurse_subfolders=options.recurse_subfolders,
            store_paths=options.store_paths,
            encrypt_headers=options.encrypt_headers,
            exclude_patterns=list(options.exclude_patterns),
            comment=options.comment,
        )

    def summary(self) -> str:
        """One-line description shown next to the profile name."""
        parts = [
            _format_from_value(self.format).label,
            CompressionMethod(self.method).label,
        ]
        if self.solid:
            parts.append("solid")
        if self.recovery_record:
            parts.append(f"RR {self.recovery_percent}%")
        if self.volume_size:
            parts.append("split")
        if self.sfx_format == "appimage":
            parts.append("AppImage")
        elif self.create_sfx or self.sfx_format == "rar":
            parts.append("SFX")
        return ", ".join(parts)


def _format_from_value(value: str) -> ArchiveFormat:
    for fmt in ArchiveFormat:
        if fmt.value == value:
            return fmt
    return ArchiveFormat.RAR5


DEFAULT_PROFILES = [
    Profile(name="Default", is_default=True),
    Profile(
        name="Best compression",
        method=int(CompressionMethod.BEST),
        solid=True,
        dictionary_size="128M",
    ),
    Profile(
        name="Fastest",
        method=int(CompressionMethod.FASTEST),
    ),
    Profile(
        name="Store only",
        method=int(CompressionMethod.STORE),
    ),
    Profile(
        name="Backup with recovery record",
        method=int(CompressionMethod.GOOD),
        recovery_record=True,
        recovery_percent=5,
        test_after=True,
    ),
    Profile(
        name="ZIP for sharing",
        format=ArchiveFormat.ZIP.value,
        method=int(CompressionMethod.NORMAL),
    ),
]


class ProfileStore:
    """Persists profiles as JSON in the shared settings file."""

    KEY = "profiles/list"

    def load(self) -> list[Profile]:
        raw = SETTINGS.get(self.KEY, "")
        if not raw:
            return self.builtin()
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return self.builtin()
        if not isinstance(data, list):
            return self.builtin()
        # A key this version does not know about is not a reason to throw away
        # every profile the user saved: a file written by a newer LinRAR is
        # read for the fields both versions share.
        fields = {f.name for f in dataclasses.fields(Profile)}
        profiles = []
        for item in data:
            if not isinstance(item, dict) or not item.get("name"):
                continue
            try:
                profiles.append(
                    Profile(**{k: v for k, v in item.items() if k in fields})
                )
            except (TypeError, ValueError):
                continue
        return profiles or self.builtin()

    @staticmethod
    def builtin() -> list[Profile]:
        """Fresh copies of the profiles LinRAR ships with."""
        return [Profile(**asdict(p)) for p in DEFAULT_PROFILES]

    def save(self, profiles: list[Profile]) -> None:
        SETTINGS.set(self.KEY, json.dumps([asdict(p) for p in profiles], indent=None))
        SETTINGS.sync()

    def get(self, name: str) -> Optional[Profile]:
        for profile in self.load():
            if profile.name == name:
                return profile
        return None

    def default(self) -> Profile:
        profiles = self.load()
        for profile in profiles:
            if profile.is_default:
                return profile
        return profiles[0]

    def chosen_default(self) -> Optional[Profile]:
        """The default profile, unless it is the untouched built-in one.

        The Archive dialog starts from the settings the last archive used, and
        then applies whichever profile is marked as the default.  The profile
        LinRAR ships as "Default" holds nothing but the factory values, so
        applying it wiped those remembered settings on every single launch:
        change the method to Best, make an archive, and the next one was back
        to Normal.  ``None`` here means "nobody has chosen a default; leave the
        remembered settings alone".
        """
        profile = self.default()
        pristine = Profile(**asdict(DEFAULT_PROFILES[0]))
        pristine.name = profile.name
        pristine.is_default = profile.is_default
        return None if asdict(profile) == asdict(pristine) else profile

    def upsert(self, profile: Profile) -> None:
        profiles = [p for p in self.load() if p.name != profile.name]
        profiles.append(profile)
        self.save(profiles)

    def remove(self, name: str) -> None:
        self.save([p for p in self.load() if p.name != name])

    def set_default(self, name: str) -> None:
        profiles = self.load()
        for profile in profiles:
            profile.is_default = profile.name == name
        self.save(profiles)


PROFILES = ProfileStore()
