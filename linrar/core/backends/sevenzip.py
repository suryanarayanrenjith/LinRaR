"""Backend wrapping the ``7z`` command line tool.

WinRAR opens far more than RAR and ZIP, so this backend covers the remaining
common formats (7z, tar, gzip, bzip2, xz, iso, cab, ...) whenever p7zip is
installed.  It is optional: if ``7z`` is missing those formats simply are not
offered.
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Optional

from .. import tools
from ..models import (
    ArchiveEntry,
    ArchiveFormat,
    ArchiveInfo,
    CompressOptions,
    CompressionMethod,
    ExtractOptions,
    OperationError,
    OverwriteMode,
    PasswordRequired,
)
from ..process import ProcessRunner, parse_percent
from .base import ArchiveBackend, TaskContext

_PROGRESS_FILE_RE = re.compile(r"\d+%\s*\d*\s*[-+UT]?\s+(.+?)\s*$")


class SevenZipBackend(ArchiveBackend):
    name = "7-Zip"
    formats = (
        ArchiveFormat.SEVENZIP,
        ArchiveFormat.TAR,
        ArchiveFormat.GZIP,
        ArchiveFormat.BZIP2,
        ArchiveFormat.XZ,
        ArchiveFormat.CAB,
        ArchiveFormat.ISO,
        ArchiveFormat.ZSTD,
        ArchiveFormat.LZMA,
        ArchiveFormat.LZIP,
        ArchiveFormat.COMPRESS,
        ArchiveFormat.LZ4,
        ArchiveFormat.ARJ,
        ArchiveFormat.LZH,
        ArchiveFormat.AR,
        ArchiveFormat.DEB,
        ArchiveFormat.RPM,
        ArchiveFormat.CPIO,
        ArchiveFormat.WIM,
        ArchiveFormat.DMG,
        ArchiveFormat.MSI,
        ArchiveFormat.SQUASHFS,
        ArchiveFormat.VHD,
    )
    can_write = True

    def __init__(self, exe: Optional[str] = None) -> None:
        self.exe = tools.locate("sevenzip", exe)

    @property
    def available(self) -> bool:
        return bool(self.exe)

    def _require(self) -> str:
        if not self.exe:
            raise OperationError(
                "The '7z' command is required for this archive format but was "
                "not found.\n\nInstall it, for example:\n"
                "    sudo apt install p7zip-full"
            )
        return self.exe

    # -- command plumbing --------------------------------------------------

    def _run(
        self,
        argv: list[str],
        ctx: Optional[TaskContext],
        allowed: tuple[int, ...] = (0,),
        cwd: Optional[str] = None,
    ) -> ProcessRunner:
        ctx = ctx or TaskContext()
        state = {"last": -1}

        def observe(line: str) -> None:
            # Unlike rar, 7z's percentage is the progress of the *whole*
            # operation, so it drives the overall bar and the per-file figure
            # is worked back out of it.
            match = _PROGRESS_FILE_RE.search(line)
            if match:
                name = match.group(1).strip()
                if name:
                    ctx.start_file(name)
            pct = parse_percent(line)
            if pct is not None and pct != state["last"]:
                state["last"] = pct
                ctx.set_overall(pct)

        def on_line(line: str) -> None:
            observe(line)
            if line.strip():
                ctx.on_message(line.strip())

        runner = ProcessRunner(argv, cwd=cwd, on_line=on_line, on_partial=observe)
        ctx.attach(runner)
        try:
            code = runner.run()
        finally:
            ctx.detach()

        if code in allowed:
            return runner
        output = runner.output
        if "Wrong password" in output or "Data Error in encrypted file" in output:
            raise PasswordRequired("The password is incorrect.", code, output)
        if "Can not open encrypted archive" in output:
            raise PasswordRequired(
                "This archive is encrypted and requires a password.", code, output
            )
        if ctx.cancelled:
            raise OperationError("The operation was cancelled.", code, output)
        detail = "\n".join(
            ln.strip()
            for ln in output.splitlines()
            if ln.strip().startswith(("ERROR", "Error", "Cannot", "Unsupported"))
        )
        raise OperationError(
            f"The operation failed (exit code {code})."
            + (f"\n\n{detail}" if detail else ""),
            code,
            output,
        )

    @staticmethod
    def _password_args(password: Optional[str]) -> list[str]:
        """Build 7z's password switch.

        Unlike rar, p7zip has no reliable way to read a password from a pipe, so
        it must go on the command line.  On a multi-user machine that makes it
        briefly visible in the process list; RAR and ZIP archives use stdin and
        are not affected.  A bare ``-p`` supplies an empty password so 7z fails
        fast on an encrypted archive instead of prompting.
        """
        return [f"-p{password}"] if password else ["-p"]

    def run_raw(
        self,
        argv: list[str],
        ctx: Optional[TaskContext] = None,
        cwd: Optional[str] = None,
    ) -> ProcessRunner:
        """Run an arbitrary pre-built 7z command (used by the ZIP fallback)."""
        return self._run(argv, ctx, allowed=(0, 1), cwd=cwd)

    # -- reading -----------------------------------------------------------

    def read_info(self, path: str, password: Optional[str] = None) -> ArchiveInfo:
        exe = self._require()
        # No -ba here: the suppressed header block is what carries the
        # archive's Type (tar, gzip, iso, ...) for the Info dialog.
        runner = self._run(
            [exe, "l", "-slt", *self._password_args(password), "--", path],
            None,
            allowed=(0, 1),
        )
        return self._parse_listing(runner.output, path)

    # 7z's "Type" field mapped back to our format enum, so the Info dialog does
    # not claim every tar/gz/iso is a "7-Zip" archive.
    _TYPE_FORMATS = {
        "7z": ArchiveFormat.SEVENZIP,
        "zip": ArchiveFormat.ZIP,
        "tar": ArchiveFormat.TAR,
        "gzip": ArchiveFormat.GZIP,
        "bzip2": ArchiveFormat.BZIP2,
        "xz": ArchiveFormat.XZ,
        "zstd": ArchiveFormat.ZSTD,
        "cab": ArchiveFormat.CAB,
        "iso": ArchiveFormat.ISO,
        "udf": ArchiveFormat.ISO,
        "rar": ArchiveFormat.RAR4,
        "rar5": ArchiveFormat.RAR5,
        "lzma": ArchiveFormat.LZMA,
        "lzma86": ArchiveFormat.LZMA,
        "lzip": ArchiveFormat.LZIP,
        "z": ArchiveFormat.COMPRESS,
        "lz4": ArchiveFormat.LZ4,
        "arj": ArchiveFormat.ARJ,
        "lzh": ArchiveFormat.LZH,
        "ar": ArchiveFormat.AR,
        "deb": ArchiveFormat.DEB,
        "rpm": ArchiveFormat.RPM,
        "cpio": ArchiveFormat.CPIO,
        "wim": ArchiveFormat.WIM,
        "dmg": ArchiveFormat.DMG,
        "hfs": ArchiveFormat.DMG,
        "compound": ArchiveFormat.MSI,
        "squashfs": ArchiveFormat.SQUASHFS,
        "vhd": ArchiveFormat.VHD,
        "vhdx": ArchiveFormat.VHD,
    }

    @classmethod
    def _parse_listing(cls, output: str, path: str) -> ArchiveInfo:
        info = ArchiveInfo(path=path, format=ArchiveFormat.UNKNOWN)
        blocks: list[dict[str, str]] = []
        current: dict[str, str] = {}
        in_entries = False

        for line in output.splitlines():
            stripped = line.strip()
            if stripped.startswith("----------"):
                in_entries = True
                if current:
                    blocks.append(current)
                    current = {}
                continue
            if not stripped:
                if current:
                    blocks.append(current)
                    current = {}
                continue
            if " = " in line:
                key, _, value = line.partition(" = ")
                current[key.strip()] = value.strip()
            elif line.rstrip().endswith(" ="):
                current[line.rstrip()[:-2].strip()] = ""
        if current:
            blocks.append(current)

        for block in blocks:
            name = block.get("Path")
            if not name:
                continue
            if not in_entries and name == path:
                info.detail_line = block.get("Type", "")
                info.solid = block.get("Solid", "-") == "+"
                info.format = cls._TYPE_FORMATS.get(
                    block.get("Type", "").lower(), info.format
                )
                continue
            # The archive's own header block repeats its path; skip it.
            if block.get("Type") and "Size" not in block:
                info.detail_line = block.get("Type", "")
                info.solid = block.get("Solid", "-") == "+"
                info.format = cls._TYPE_FORMATS.get(
                    block.get("Type", "").lower(), info.format
                )
                continue

            attributes = block.get("Attributes", "")
            entry = ArchiveEntry(
                name=name.replace("\\", "/").lstrip("/"),
                is_dir=attributes.startswith("D"),
                crc=block.get("CRC", ""),
                attributes=attributes.split(" ", 1)[-1] if " " in attributes else "",
                method=block.get("Method", ""),
                encrypted=block.get("Encrypted", "-") == "+",
            )
            for key, attr in (("Size", "size"), ("Packed Size", "packed_size")):
                raw = block.get(key, "").strip()
                if raw.isdigit():
                    setattr(entry, attr, int(raw))
            raw_time = block.get("Modified", "")
            if raw_time:
                try:
                    entry.mtime = datetime.strptime(
                        raw_time[:19], "%Y-%m-%d %H:%M:%S"
                    )
                except ValueError:
                    entry.mtime = None
            info.entries.append(entry)

        if any(e.encrypted for e in info.entries):
            info.encrypted_headers = False
        return info

    # -- extraction --------------------------------------------------------

    def extract(
        self,
        path: str,
        options: ExtractOptions,
        ctx: Optional[TaskContext] = None,
    ) -> None:
        exe = self._require()
        command = "e" if options.no_paths else "x"
        overwrite = {
            OverwriteMode.OVERWRITE: "-aoa",
            OverwriteMode.SKIP: "-aos",
            OverwriteMode.RENAME: "-aou",
            OverwriteMode.ASK: "-aoa",
        }[options.overwrite_mode]

        destination = options.destination or os.getcwd()
        os.makedirs(destination, exist_ok=True)

        argv = [
            exe, command, "-bsp1", "-bso0", "-y", overwrite,
            f"-o{destination}", *self._password_args(options.password), "--", path,
        ]
        argv.extend(options.members)
        self._run(argv, ctx, allowed=(0, 1))

    def test(
        self,
        path: str,
        password: Optional[str] = None,
        ctx: Optional[TaskContext] = None,
    ) -> None:
        exe = self._require()
        self._run(
            [exe, "t", "-bsp1", "-y", *self._password_args(password), "--", path],
            ctx,
        )

    # -- creation ----------------------------------------------------------

    def create(
        self,
        files: list[str],
        options: CompressOptions,
        ctx: Optional[TaskContext] = None,
    ) -> None:
        exe = self._require()
        if options.format is not ArchiveFormat.SEVENZIP:
            raise OperationError(
                f"Creating {options.format.label} archives is not supported. "
                "Choose RAR, ZIP or 7z."
            )
        # Refuse to "add" into a file that is not actually a 7z archive:
        # 7z would otherwise rebuild a tar/gz in the wrong container.
        if os.path.exists(options.archive_path):
            from ..registry import detect_format

            existing = detect_format(options.archive_path)
            if existing not in (ArchiveFormat.SEVENZIP, ArchiveFormat.UNKNOWN):
                raise OperationError(
                    f"{os.path.basename(options.archive_path)} is a "
                    f"{existing.label} archive; files can only be added to "
                    "7z archives with this format selected."
                )

        level = {
            CompressionMethod.STORE: 0,
            CompressionMethod.FASTEST: 1,
            CompressionMethod.FAST: 3,
            CompressionMethod.NORMAL: 5,
            CompressionMethod.GOOD: 7,
            CompressionMethod.BEST: 9,
        }[options.method]

        argv = [exe, "a", "-bsp1", "-bso0", "-y", f"-mx{level}", "-t7z"]
        if options.solid:
            argv.append("-ms=on")
        else:
            argv.append("-ms=off")
        if options.dictionary_size:
            argv.append(f"-md={options.dictionary_size.lower()}")
        if not options.recurse_subfolders:
            # 7z always recurses into directories it is given, so honour the
            # option by only passing plain files.
            files = [f for f in files if not os.path.isdir(f)]
            if not files:
                raise OperationError(
                    "Only folders were selected but 'Include subfolders' is "
                    "off, so there is nothing to add."
                )
        for pattern in options.exclude_patterns:
            if pattern.strip():
                argv.append(f"-xr!{pattern.strip()}")
        if options.volume_size > 0:
            argv.append(f"-v{options.volume_size}b")
        if options.password:
            argv.append(f"-p{options.password}")
            if options.encrypt_headers:
                argv.append("-mhe=on")
        if options.delete_after:
            argv.append("-sdel")

        # Feed paths relative to the common base so the stored folder
        # structure matches what the user selected, exactly as the RAR
        # backend does.  Absolute paths would be stored flattened.
        base = options.base_folder
        if not base and files:
            base = os.path.dirname(os.path.abspath(files[0]))
        members = []
        for item in files:
            try:
                members.append(os.path.relpath(item, base) if base else item)
            except ValueError:
                members.append(item)
        if not options.store_paths:
            members = [
                os.path.basename(m.rstrip("/")) for m in members
            ]

        argv.extend(["--", os.path.abspath(options.archive_path)])
        argv.extend(members)
        self._run(argv, ctx, allowed=(0, 1), cwd=base or None)

        if options.test_after:
            self.test(options.archive_path, options.password, ctx)

    def rename_member(
        self,
        path: str,
        old_name: str,
        new_name: str,
        password: Optional[str] = None,
        ctx: Optional[TaskContext] = None,
    ) -> None:
        self.rename_members(path, [(old_name, new_name)], password, ctx)

    def rename_members(
        self,
        path: str,
        pairs: list[tuple[str, str]],
        password: Optional[str] = None,
        ctx: Optional[TaskContext] = None,
    ) -> None:
        exe = self._require()
        argv = [exe, "rn", "-y", "-bso0", *self._password_args(password), "--", path]
        for old_name, new_name in pairs:
            argv.extend([old_name, new_name])
        self._run(argv, ctx, allowed=(0, 1))

    def delete_members(
        self,
        path: str,
        members: list[str],
        password: Optional[str] = None,
        ctx: Optional[TaskContext] = None,
    ) -> None:
        exe = self._require()
        argv = [exe, "d", "-y", "-bso0", *self._password_args(password), "--", path]
        argv.extend(members)
        self._run(argv, ctx, allowed=(0, 1))
