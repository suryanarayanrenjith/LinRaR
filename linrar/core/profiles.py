"""Compression profiles: WinRAR's saved sets of archiving parameters."""

from __future__ import annotations

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

    def to_options(self, archive_path: str = "", base_folder: str = "") -> CompressOptions:
        return CompressOptions(
            archive_path=archive_path,
            format=_format_from_value(self.format),
            method=CompressionMethod(self.method),
            dictionary_size=self.dictionary_size,
            volume_size=self.volume_size,
            update_mode=_update_from_value(self.update_mode),
            solid=self.solid,
            recovery_record=self.recovery_record,
            recovery_percent=self.recovery_percent,
            create_sfx=self.create_sfx,
            sfx_format=self.sfx_format,
            delete_after=self.delete_after,
            test_after=self.test_after,
            lock=self.lock,
            recurse_subfolders=self.recurse_subfolders,
            store_paths=self.store_paths,
            encrypt_headers=self.encrypt_headers,
            exclude_patterns=list(self.exclude_patterns),
            comment=self.comment,
            base_folder=base_folder,
        )

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


def _update_from_value(value: str) -> UpdateMode:
    for mode in UpdateMode:
        if mode.value == value:
            return mode
    return UpdateMode.ADD_REPLACE


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
            return [Profile(**asdict(p)) for p in DEFAULT_PROFILES]
        try:
            data = json.loads(raw)
            profiles = [Profile(**item) for item in data]
        except (ValueError, TypeError):
            return [Profile(**asdict(p)) for p in DEFAULT_PROFILES]
        return profiles or [Profile(**asdict(p)) for p in DEFAULT_PROFILES]

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
