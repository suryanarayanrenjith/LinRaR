"""ZIP backend built on the standard library's :mod:`zipfile`.

WinRAR offers ZIP alongside RAR in its format selector, so LinRAR supports it
natively.  Reading, extracting, testing and creating all run in-process; only
password-protected *creation* shells out (to ``zip`` or ``7z``), because
:mod:`zipfile` can read encrypted entries but cannot write them.  Entries that
use AES or exotic compression methods are transparently handed to the 7-Zip
backend when it is installed.

Two things this file is careful about, both of which used to be wrong:

**A password never goes in the command line.**  ``zip -P secret`` would put it
in the process table, where on a stock Linux every other account on the machine
can read ``/proc/<pid>/cmdline`` for as long as the command runs.  ``zip -e``
asks at a terminal instead, so the child is given one of its own and the answer
is typed at it.

**An archive that came out unencrypted is destroyed, not returned.**  Driving a
tool through a prompt is only safe if the result is checked, so
:meth:`ZipBackend._require_encrypted` reads the archive back and refuses to
call it protected unless every file just written really is.
"""

from __future__ import annotations

import fnmatch
import os
import shutil
import stat
import tempfile
import zipfile
from datetime import datetime
from typing import Optional

from .. import tools
from ..process import ProcessRunner, PtyUnavailable
from ..models import (
    ArchiveEntry,
    ArchiveFormat,
    ArchiveInfo,
    CompressOptions,
    CompressionMethod,
    ExtractOptions,
    ExtractUpdateMode,
    OperationError,
    OverwriteMode,
    PasswordRequired,
    UpdateMode,
)
from .base import ArchiveBackend, TaskContext

# WinRAR's six presets mapped onto deflate levels.
_LEVELS = {
    CompressionMethod.STORE: 0,
    CompressionMethod.FASTEST: 1,
    CompressionMethod.FAST: 3,
    CompressionMethod.NORMAL: 6,
    CompressionMethod.GOOD: 8,
    CompressionMethod.BEST: 9,
}


class ZipBackend(ArchiveBackend):
    name = "ZIP"
    formats = (ArchiveFormat.ZIP,)
    can_write = True

    # -- reading -----------------------------------------------------------

    def read_info(self, path: str, password: Optional[str] = None) -> ArchiveInfo:
        info = ArchiveInfo(path=path, format=ArchiveFormat.ZIP)
        try:
            with zipfile.ZipFile(path) as archive:
                raw_comment = archive.comment or b""
                info.comment = raw_comment.decode("utf-8", "replace").strip()
                listing = archive.infolist()
                self.check_entry_count(len(listing), path)
                for item in listing:
                    info.entries.append(self._entry_from_info(item))
        except zipfile.BadZipFile as exc:
            fallback = self._retry_with_sevenzip(
                "read", exc, lambda seven: seven.read_info(path, password)
            )
            fallback.format = ArchiveFormat.ZIP
            return fallback
        except OSError as exc:
            raise OperationError(f"Cannot open the archive.\n\n{exc}") from exc

        if any(e.encrypted for e in info.entries):
            info.encrypted_headers = False
        return info

    @staticmethod
    def _entry_from_info(item: zipfile.ZipInfo) -> ArchiveEntry:
        name = item.filename.replace("\\", "/")
        is_dir = item.is_dir()
        entry = ArchiveEntry(
            name=name.rstrip("/") if is_dir else name,
            is_dir=is_dir,
            size=item.file_size,
            packed_size=item.compress_size,
            crc=f"{item.CRC:08X}" if not is_dir else "",
            encrypted=bool(item.flag_bits & 0x1),
            host_os="Unix" if item.create_system == 3 else "Windows",
            method="Store" if item.compress_type == zipfile.ZIP_STORED else "Deflate",
        )
        try:
            entry.mtime = datetime(*item.date_time)
        except (ValueError, TypeError):
            entry.mtime = None

        mode = item.external_attr >> 16
        if mode:
            entry.attributes = stat.filemode(mode)
            if stat.S_ISLNK(mode):
                entry.link_target = ""
        return entry

    # -- fallback to 7z for AES / exotic compression -----------------------

    @staticmethod
    def _sevenzip_fallback():
        """Return the 7-Zip backend when installed, else ``None``.

        Imported lazily to avoid a cycle with the registry module.
        """
        from ..registry import REGISTRY

        return REGISTRY.sevenzip if REGISTRY.sevenzip.available else None

    @staticmethod
    def _unsupported_member_error(exc: Exception) -> OperationError:
        return OperationError(
            "This ZIP archive uses AES encryption or a compression method the "
            "built-in reader does not support.\n\nInstall 7-Zip to handle it:\n"
            "    sudo apt install p7zip-full\n\n"
            f"({exc})"
        )

    def _retry_with_sevenzip(self, verb: str, exc: Exception, work):
        """Hand a ZIP :mod:`zipfile` will not touch to 7-Zip instead.

        zipfile is stricter than the format is in practice: a spanned archive,
        one with a self-extracting stub in front of it, one whose central
        directory disagrees with its local headers.  7-Zip opens all of them,
        and refusing outright told the user their archive was broken when the
        reader simply was not up to it.

        When 7-Zip cannot open it either, the archive really is damaged, and
        the message says so in ZIP terms rather than passing through a bare
        "exit code 2" from a tool the user never asked for.
        """
        seven = self._sevenzip_fallback()
        if seven is None:
            raise OperationError(
                f"This ZIP archive could not be {verb} by the built-in "
                "reader.\n\nInstall 7-Zip to handle the less common "
                "variants:\n    sudo apt install p7zip-full\n\n"
                f"({exc})"
            ) from exc
        try:
            return work(seven)
        except PasswordRequired:
            raise
        except OperationError as fallback_error:
            raise OperationError(
                f"This ZIP archive could not be {verb}: neither the built-in "
                "reader nor 7-Zip could make sense of it, so it is most "
                "likely damaged or incomplete.\n\n"
                f"({exc})",
                fallback_error.code,
                fallback_error.output,
            ) from exc

    # -- extraction --------------------------------------------------------

    def extract(
        self,
        path: str,
        options: ExtractOptions,
        ctx: Optional[TaskContext] = None,
    ) -> None:
        ctx = ctx or TaskContext()
        destination = os.path.abspath(options.destination or os.getcwd())
        os.makedirs(destination, exist_ok=True)
        dest_real = os.path.realpath(destination)

        try:
            with zipfile.ZipFile(path) as archive:
                if options.password:
                    archive.setpassword(options.password.encode("utf-8"))

                wanted = set(options.members) if options.members else None
                members = [
                    item
                    for item in archive.infolist()
                    if wanted is None or item.filename.rstrip("/") in wanted
                ]
                # The reader knows every member's size up front, so the overall
                # bar can be weighted properly from the first byte.
                ctx.plan({
                    item.filename: item.file_size
                    for item in members if not item.is_dir()
                })

                for item in members:
                    if ctx.cancelled:
                        raise OperationError("The operation was cancelled.")

                    name = item.filename
                    target = self._safe_target(destination, name, options.no_paths)
                    if target is None or not _parent_inside(target, dest_real):
                        ctx.on_message(f"Skipping unsafe path: {name}")
                        continue

                    if item.is_dir():
                        os.makedirs(target, exist_ok=True)
                        continue

                    ctx.start_file(name)
                    if not self._should_write(target, item, options):
                        ctx.advance(100)
                        continue

                    if os.path.lexists(target):
                        if options.overwrite_mode is OverwriteMode.SKIP:
                            ctx.advance(100)
                            continue
                        if options.overwrite_mode is OverwriteMode.RENAME:
                            target = _unique_name(target)

                    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)

                    mode = item.external_attr >> 16
                    if stat.S_ISLNK(mode):
                        # Recreate symlinks instead of writing their target
                        # path into a regular file, but only when the link
                        # stays inside the destination: one that escapes is a
                        # trap left in a folder the user may pass on, and it
                        # would also let a later member be written through it.
                        link_target = archive.read(item).decode("utf-8", "replace")
                        if not _link_stays_inside(target, link_target, dest_real):
                            ctx.on_message(
                                f"Skipping unsafe link: {name} -> {link_target}"
                            )
                            ctx.advance(100)
                            continue
                        _silent_unlink(target)
                        try:
                            os.symlink(link_target, target)
                        except OSError as exc:
                            ctx.on_message(f"Cannot create link {name}: {exc}")
                        ctx.advance(100)
                        continue

                    self._extract_one(archive, item, target, ctx, options)

                    if mode & 0o777:
                        try:
                            os.chmod(target, mode & 0o777)
                        except OSError:
                            pass
                    if item.date_time:
                        try:
                            ts = datetime(*item.date_time).timestamp()
                            os.utime(target, (ts, ts))
                        except (ValueError, OSError):
                            pass
        except NotImplementedError as exc:
            # AES or exotic compression; NotImplementedError subclasses
            # RuntimeError, so this clause must come first.
            seven = self._sevenzip_fallback()
            if seven is not None:
                seven.extract(path, options, ctx)
                return
            raise self._unsupported_member_error(exc) from exc
        except RuntimeError as exc:
            # zipfile signals a bad/missing password with a bare RuntimeError.
            if "password" in str(exc).lower():
                raise PasswordRequired(
                    "The password is incorrect."
                    if options.password
                    else "This archive is encrypted and requires a password."
                ) from exc
            raise OperationError(str(exc)) from exc
        except zipfile.BadZipFile as exc:
            self._retry_with_sevenzip(
                "extracted", exc, lambda seven: seven.extract(path, options, ctx)
            )

    def _extract_one(
        self,
        archive: zipfile.ZipFile,
        item: zipfile.ZipInfo,
        target: str,
        ctx: TaskContext,
        options: ExtractOptions,
    ) -> None:
        """Stream one member to disk, reporting per-file and overall progress."""
        written = 0
        try:
            with archive.open(item) as source, open(target, "wb") as sink:
                while True:
                    if ctx.cancelled:
                        raise OperationError("The operation was cancelled.")
                    chunk = source.read(256 * 1024)
                    if not chunk:
                        break
                    sink.write(chunk)
                    written += len(chunk)
                    if item.file_size:
                        ctx.advance(int(written * 100 / item.file_size))
        except OperationError:
            if not options.keep_broken:
                _silent_unlink(target)
            raise
        except Exception:
            if not options.keep_broken:
                _silent_unlink(target)
            raise
        ctx.advance(100)

    @staticmethod
    def _should_write(
        target: str, item: zipfile.ZipInfo, options: ExtractOptions
    ) -> bool:
        """Apply the dialog's "Update mode" to a single member."""
        exists = os.path.exists(target)
        if options.update_mode is ExtractUpdateMode.EXTRACT_REPLACE:
            return True
        try:
            archived = datetime(*item.date_time).timestamp()
        except (ValueError, TypeError):
            archived = 0.0
        if options.update_mode is ExtractUpdateMode.FRESHEN:
            if not exists:
                return False
            return archived > os.path.getmtime(target)
        # EXTRACT_UPDATE: write when missing or newer in the archive.
        if not exists:
            return True
        return archived > os.path.getmtime(target)

    @staticmethod
    def _safe_target(destination: str, name: str, flatten: bool) -> Optional[str]:
        """Resolve a member path inside *destination*, refusing to escape it.

        Guards against "Zip Slip" entries such as ``../../etc/passwd`` and
        absolute paths, which would otherwise let a crafted archive overwrite
        files anywhere the user can write.
        """
        clean = name.replace("\\", "/")
        if flatten:
            clean = clean.rsplit("/", 1)[-1]
            if not clean:
                return None
        target = os.path.normpath(os.path.join(destination, clean))
        anchor = os.path.join(destination, "")
        # Strictly inside: a member that resolves to the destination folder
        # itself is not a file the archive may write either.
        if target == destination or not target.startswith(anchor):
            return None
        return target

    def test(
        self,
        path: str,
        password: Optional[str] = None,
        ctx: Optional[TaskContext] = None,
    ) -> None:
        ctx = ctx or TaskContext()
        try:
            with zipfile.ZipFile(path) as archive:
                if password:
                    archive.setpassword(password.encode("utf-8"))
                members = [i for i in archive.infolist() if not i.is_dir()]
                ctx.plan({item.filename: item.file_size for item in members})
                for item in members:
                    if ctx.cancelled:
                        raise OperationError("The operation was cancelled.")
                    ctx.start_file(item.filename)
                    read = 0
                    with archive.open(item) as handle:
                        while True:
                            chunk = handle.read(256 * 1024)
                            if not chunk:
                                break
                            read += len(chunk)
                            if item.file_size:
                                ctx.advance(int(read * 100 / item.file_size))
                    ctx.advance(100)
                ctx.finish()
        except NotImplementedError as exc:
            seven = self._sevenzip_fallback()
            if seven is not None:
                seven.test(path, password, ctx)
                return
            raise self._unsupported_member_error(exc) from exc
        except RuntimeError as exc:
            if "password" in str(exc).lower():
                raise PasswordRequired(
                    "The password is incorrect."
                    if password
                    else "This archive is encrypted and requires a password."
                ) from exc
            raise OperationError(str(exc)) from exc
        except zipfile.BadZipFile as exc:
            self._retry_with_sevenzip(
                "tested", exc, lambda seven: seven.test(path, password, ctx)
            )

    # -- creation ----------------------------------------------------------

    def create(
        self,
        files: list[str],
        options: CompressOptions,
        ctx: Optional[TaskContext] = None,
    ) -> None:
        ctx = ctx or TaskContext()
        if options.password:
            self._create_encrypted(files, options, ctx)
            return

        base = options.base_folder
        if not base and files:
            base = os.path.dirname(os.path.abspath(files[0]))

        plan = self._build_plan(files, options, base)
        if not plan and not os.path.exists(options.archive_path):
            raise OperationError("There are no files to add.")

        method = (
            zipfile.ZIP_STORED
            if options.method is CompressionMethod.STORE
            else zipfile.ZIP_DEFLATED
        )
        level = _LEVELS[options.method]

        existing: dict[str, zipfile.ZipInfo] = {}
        existing_comment = b""
        if os.path.exists(options.archive_path):
            try:
                with zipfile.ZipFile(options.archive_path) as current:
                    existing_comment = current.comment or b""
                    for item in current.infolist():
                        existing[item.filename.rstrip("/")] = item
            except zipfile.BadZipFile as exc:
                raise OperationError(
                    "The existing file is not a valid ZIP archive, so it "
                    f"cannot be updated.\n\n{exc}"
                ) from exc

        plan = self._apply_update_mode(plan, existing, options.update_mode)
        replaced = {arc for _s, arc, _z in plan}

        # Which of the current entries survive into the new archive?
        if options.update_mode is UpdateMode.SYNCHRONIZE:
            wanted_dirs = set()
            for _s, arc, _z in plan:
                parts = arc.split("/")
                for depth in range(1, len(parts)):
                    wanted_dirs.add("/".join(parts[:depth]))
            kept = [
                item for key, item in existing.items()
                if key not in replaced
                and (item.is_dir() and key in wanted_dirs)
            ]
        else:
            kept = [
                item for key, item in existing.items() if key not in replaced
            ]

        ctx.plan({arcname: size for _s, arcname, size in plan})

        # Build the result beside the target and swap atomically, so a failure
        # part-way through never corrupts an archive being updated.  mkstemp
        # makes its file private, which an archive is not, so the mode is put
        # back before the swap: either what the archive being updated had, or
        # what an ordinary create would have given it.
        out_dir = os.path.dirname(os.path.abspath(options.archive_path)) or "."
        previous_mode = _mode_of(options.archive_path)
        handle, temp_path = tempfile.mkstemp(dir=out_dir, suffix=".zip")
        os.close(handle)
        try:
            with zipfile.ZipFile(
                temp_path, "w", compression=method, compresslevel=level
            ) as archive:
                # The comment was read with the listing above rather than by
                # opening the archive a second time to fetch one field.
                if options.comment:
                    archive.comment = options.comment.encode("utf-8")
                elif existing_comment:
                    archive.comment = existing_comment

                if kept:
                    with zipfile.ZipFile(options.archive_path) as current:
                        for item in sorted(kept, key=lambda i: i.filename):
                            if ctx.cancelled:
                                raise OperationError(
                                    "The operation was cancelled."
                                )
                            info = zipfile.ZipInfo(item.filename, item.date_time)
                            info.compress_type = item.compress_type
                            info.external_attr = item.external_attr
                            info.internal_attr = item.internal_attr
                            info.comment = item.comment
                            archive.writestr(info, current.read(item))

                for source, arcname, size in plan:
                    if ctx.cancelled:
                        raise OperationError("The operation was cancelled.")
                    if os.path.isdir(source):
                        archive.write(source, arcname.rstrip("/") + "/")
                        continue
                    ctx.start_file(arcname)
                    archive.write(source, arcname)
                    ctx.advance(100)
                ctx.finish()
            _inherit_mode(temp_path, previous_mode)
            os.replace(temp_path, options.archive_path)
        except OSError as exc:
            _silent_unlink(temp_path)
            raise OperationError(f"Cannot create the archive.\n\n{exc}") from exc
        except Exception:
            _silent_unlink(temp_path)
            raise

        if options.test_after:
            self.test(options.archive_path, None, ctx)
        if options.delete_after:
            _delete_sources(files)

    def _build_plan(
        self, files: list[str], options: CompressOptions, base: str
    ) -> list[tuple[str, str, int]]:
        """Expand the selection into unique ``(source, arcname, size)`` rows."""
        collected = _collect_files(files, options.recurse_subfolders)
        plan: list[tuple[str, str, int]] = []
        seen: set[str] = set()
        for source, size in collected:
            arcname = _arcname(source, base, options.store_paths)
            if not arcname or arcname in seen:
                continue
            if _excluded(arcname, options.exclude_patterns):
                continue
            seen.add(arcname)
            plan.append((source, arcname, size))
        return plan

    @staticmethod
    def _apply_update_mode(
        plan: list[tuple[str, str, int]],
        existing: dict[str, zipfile.ZipInfo],
        mode: UpdateMode,
    ) -> list[tuple[str, str, int]]:
        """Filter the add-list according to the dialog's update mode."""
        if not existing or mode in (
            UpdateMode.ADD_REPLACE,
            UpdateMode.ASK,
            UpdateMode.SYNCHRONIZE,
        ):
            return plan

        def newer_than_archived(source: str, item: zipfile.ZipInfo) -> bool:
            try:
                archived = datetime(*item.date_time).timestamp()
                return os.path.getmtime(source) > archived + 1
            except (OSError, ValueError, TypeError):
                return True

        result = []
        for source, arcname, size in plan:
            item = existing.get(arcname.rstrip("/"))
            if mode is UpdateMode.SKIP_EXISTING:
                if item is None:
                    result.append((source, arcname, size))
            elif mode is UpdateMode.FRESHEN:
                if item is not None and newer_than_archived(source, item):
                    result.append((source, arcname, size))
            else:  # ADD_UPDATE
                if item is None or newer_than_archived(source, item):
                    result.append((source, arcname, size))
        return result

    def _create_encrypted(
        self, files: list[str], options: CompressOptions, ctx: TaskContext
    ) -> None:
        """Encrypted ZIP creation via the ``zip`` tool (or 7z as a fallback).

        ``zip -e`` is used rather than ``zip -P secret``: the second puts the
        password in the process table, where on a stock Linux any other account
        on the machine can read it out of ``/proc/<pid>/cmdline`` for as long
        as the command runs.  ``-e`` asks at a terminal instead, so LinRAR
        gives the child one of its own and types the answer (see
        :class:`~linrar.core.process.ProcessRunner`).

        Whatever route it took, the archive is read back before it is handed
        over: :meth:`_require_encrypted` refuses to call an unencrypted archive
        a protected one, which is what makes it safe to drive a tool through a
        prompt at all.
        """
        base = options.base_folder
        if not base and files:
            base = os.path.dirname(os.path.abspath(files[0]))
        relative = [
            os.path.relpath(f, base) if base else f for f in files
        ]
        target = os.path.abspath(options.archive_path)

        zip_exe = tools.locate("zip")
        seven = self._sevenzip_fallback()
        if zip_exe:
            argv = [zip_exe, "-e", f"-{_LEVELS[options.method]}"]
            if options.recurse_subfolders:
                argv.append("-r")
            if not options.store_paths:
                argv.append("-j")
            argv.append(target)
            argv.extend(relative)
            for pattern in options.exclude_patterns:
                argv.extend(["-x", pattern])

            ctx.on_message("Creating encrypted ZIP archive...")
            existed = os.path.exists(target)
            already_plain = self._plain_members(target) if existed else set()
            # zip asks for the password, then asks again to verify it.
            runner = ProcessRunner(
                argv,
                cwd=base or None,
                on_line=lambda line: ctx.on_message(line) if line.strip() else None,
                prompt_answers=[options.password, options.password],
            )
            ctx.attach(runner)
            try:
                code = runner.run()
            except PtyUnavailable as exc:
                raise OperationError(
                    "The encrypted ZIP archive was not created.\n\n"
                    "LinRAR gives the 'zip' command a terminal of its own so "
                    "that the password never appears in the process list, and "
                    f"this system would not provide one.\n\n({exc})\n\n"
                    "Install 7-Zip, or use the RAR format, which encrypts "
                    "natively."
                ) from exc
            finally:
                ctx.detach()
            if code != 0:
                if not existed:
                    _silent_unlink(target)
                raise OperationError(
                    "Failed to create the encrypted ZIP archive.\n\n"
                    + _terminal_tail(runner.output)
                )
            self._require_encrypted(target, already_plain, existed)
        elif seven is not None:
            existed = os.path.exists(target)
            already_plain = self._plain_members(target) if existed else set()
            argv = [
                seven.exe, "a", "-tzip", "-bso0", "-bsp1", "-y",
                f"-mx{_LEVELS[options.method]}",
                # Bare: the secret is typed at the prompt, not put in argv.
                "-p",
            ]
            for pattern in options.exclude_patterns:
                argv.append(f"-xr!{pattern}")
            argv.extend(["--", target])
            argv.extend(relative)
            ctx.on_message("Creating encrypted ZIP archive with 7-Zip...")
            seven.run_raw(
                argv, ctx, cwd=base or None, password=options.password
            )
            self._require_encrypted(target, already_plain, existed)
        else:
            raise OperationError(
                "Creating a password-protected ZIP archive requires either "
                "the 'zip' command or 7-Zip, and neither was found.\n\n"
                "Install one of them, for example:\n"
                "    sudo apt install zip\n\n"
                "Alternatively choose the RAR format, which supports "
                "encryption natively."
            )
        ctx.on_total(100)
        if options.test_after:
            self.test(options.archive_path, options.password, ctx)
        if options.delete_after:
            _delete_sources(files)

    @staticmethod
    def _plain_members(path: str) -> set[str]:
        """The names of the unencrypted files in *path*; empty if unreadable."""
        try:
            with zipfile.ZipFile(path) as archive:
                return {
                    item.filename for item in archive.infolist()
                    if not item.is_dir() and not (item.flag_bits & 0x1)
                }
        except (OSError, zipfile.BadZipFile):
            return set()

    @classmethod
    def _require_encrypted(
        cls, path: str, already_plain: set[str], existed: bool
    ) -> None:
        """Prove the files just written really are encrypted.

        The whole point of the exercise is that the user asked for a password,
        so an archive that came out without one is worse than no archive at
        all: it looks like the protected thing they asked for.  Anything left
        unprotected is reported, and an archive LinRAR itself has just created
        is deleted rather than handed back as a qualified success.

        *already_plain* names the files that were unencrypted before the run
        began.  Adding to an existing plain ZIP does not encrypt what was
        already in it, and complaining about those would refuse a perfectly
        ordinary operation.
        """
        try:
            with zipfile.ZipFile(path) as archive:
                total = sum(1 for item in archive.infolist() if not item.is_dir())
        except (OSError, zipfile.BadZipFile) as exc:
            raise OperationError(
                "The encrypted ZIP archive could not be read back, so LinRAR "
                f"cannot vouch for it.\n\n{exc}"
            ) from exc

        plain = sorted(cls._plain_members(path) - already_plain)
        if not plain:
            return
        if not existed:
            _silent_unlink(path)
            raise OperationError(
                "The archive was written without encryption, so it has been "
                f"discarded.\n\n{len(plain)} of {total} file(s) came out "
                f"unprotected, starting with {plain[0]}.\n\n"
                "Use the RAR format instead, which encrypts natively."
            )
        raise OperationError(
            "These files were added to the archive without encryption:\n  "
            + "\n  ".join(plain[:5])
            + ("\n  ..." if len(plain) > 5 else "")
        )

    # -- modification ------------------------------------------------------

    def delete_members(
        self,
        path: str,
        members: list[str],
        password: Optional[str] = None,
        ctx: Optional[TaskContext] = None,
    ) -> None:
        # ZIP has no in-place delete; rewrite without the unwanted entries.
        self._rewrite(path, drop=set(members), ctx=ctx)

    def rename_member(
        self,
        path: str,
        old_name: str,
        new_name: str,
        password: Optional[str] = None,
        ctx: Optional[TaskContext] = None,
    ) -> None:
        self._rewrite(path, renames=[(old_name, new_name)], ctx=ctx)

    def rename_members(
        self,
        path: str,
        pairs: list[tuple[str, str]],
        password: Optional[str] = None,
        ctx: Optional[TaskContext] = None,
    ) -> None:
        self._rewrite(path, renames=list(pairs), ctx=ctx)

    def _rewrite(
        self,
        path: str,
        drop: Optional[set[str]] = None,
        renames: Optional[list[tuple[str, str]]] = None,
        ctx: Optional[TaskContext] = None,
    ) -> None:
        """Copy the archive to a temp file applying deletions/renames, then swap.

        Renaming a folder renames everything beneath it.  Writing to a sibling
        temp file and replacing atomically means a failure part-way through
        leaves the original archive untouched.
        """
        ctx = ctx or TaskContext()
        drop = drop or set()
        renames = renames or []

        def renamed(key: str) -> Optional[str]:
            for old, new in renames:
                old = old.rstrip("/")
                if key == old:
                    return new
                if key.startswith(old + "/"):
                    return new + key[len(old):]
            return None

        previous_mode = _mode_of(path)
        handle, temp_path = tempfile.mkstemp(
            dir=os.path.dirname(os.path.abspath(path)), suffix=".zip"
        )
        os.close(handle)
        try:
            with zipfile.ZipFile(path) as source, zipfile.ZipFile(
                temp_path, "w"
            ) as target:
                target.comment = source.comment
                items = source.infolist()
                total = len(items) or 1
                for index, item in enumerate(items):
                    if ctx.cancelled:
                        raise OperationError("The operation was cancelled.")
                    key = item.filename.rstrip("/")
                    if key in drop or any(
                        key.startswith(d.rstrip("/") + "/") for d in drop
                    ):
                        continue
                    new_name = item.filename
                    if replacement := renamed(key):
                        new_name = replacement + ("/" if item.is_dir() else "")
                    new_info = zipfile.ZipInfo(new_name, item.date_time)
                    new_info.compress_type = item.compress_type
                    new_info.external_attr = item.external_attr
                    new_info.internal_attr = item.internal_attr
                    new_info.comment = item.comment
                    target.writestr(new_info, source.read(item))
                    ctx.on_total(int((index + 1) * 100 / total))
            _inherit_mode(temp_path, previous_mode)
            os.replace(temp_path, path)
        except Exception as exc:
            _silent_unlink(temp_path)
            if isinstance(exc, OperationError):
                raise
            raise OperationError(f"Failed to update the archive.\n\n{exc}") from exc

    def set_comment(
        self,
        path: str,
        comment: str,
        password: Optional[str] = None,
        ctx: Optional[TaskContext] = None,
    ) -> None:
        try:
            with zipfile.ZipFile(path, "a") as archive:
                archive.comment = comment.encode("utf-8")
        except OSError as exc:
            raise OperationError(f"Cannot write the comment.\n\n{exc}") from exc


def _arcname(source: str, base: str, store_paths: bool) -> str:
    """The name a source file is stored under inside the archive."""
    if not store_paths:
        return "" if os.path.isdir(source) else os.path.basename(source)
    if base:
        try:
            arc = os.path.relpath(source, base)
        except ValueError:
            arc = os.path.basename(source)
    else:
        arc = os.path.basename(source)
    arc = arc.replace(os.sep, "/")
    while arc.startswith("../"):
        arc = arc[3:]
    return "" if arc in ("", ".", "..") else arc


def _excluded(arcname: str, patterns: list[str]) -> bool:
    if not patterns:
        return False
    basename = arcname.rsplit("/", 1)[-1]
    for pattern in patterns:
        pattern = pattern.strip()
        if not pattern:
            continue
        if fnmatch.fnmatch(basename, pattern) or fnmatch.fnmatch(arcname, pattern):
            return True
        # A bare folder name such as "node_modules" excludes that subtree.
        if ("/" + arcname + "/").find("/" + pattern + "/") >= 0:
            return True
    return False


def _parent_inside(target: str, dest_real: str) -> bool:
    """True when the target's directory truly resolves inside the destination.

    Re-checked per file so a symlink extracted earlier cannot redirect later
    writes outside the destination folder.
    """
    parent_real = os.path.realpath(os.path.dirname(target))
    return parent_real == dest_real or parent_real.startswith(dest_real + os.sep)


def _link_stays_inside(target: str, link_target: str, dest_real: str) -> bool:
    """Would a symlink written at *target* point somewhere inside the extraction?

    An archive can carry a link to ``/etc/shadow`` or to ``../../..``, and one
    dropped into a folder the user is about to hand to somebody else is a trap
    laid in their name.  ``unrar`` refuses these by default and so does this.
    An absolute target is refused outright; a relative one is resolved against
    where the link will live.
    """
    if not link_target or os.path.isabs(link_target):
        return False
    resolved = os.path.realpath(
        os.path.join(os.path.dirname(target), link_target)
    )
    return resolved == dest_real or resolved.startswith(dest_real + os.sep)


def _default_file_mode() -> int:
    """0666 less the process umask: what an ordinary ``open()`` would produce.

    An archive built through a temporary file inherits ``mkstemp``'s 0600,
    which silently makes every archive LinRAR writes private to its author.
    That is not what creating a file means, so the mode is put back.
    """
    current = os.umask(0)
    os.umask(current)
    return 0o666 & ~current


def _inherit_mode(target: str, previous: Optional[int]) -> None:
    """Give *target* the mode *previous* had, or the umask default."""
    mode = previous if previous is not None else _default_file_mode()
    try:
        os.chmod(target, mode)
    except OSError:
        pass


def _mode_of(path: str) -> Optional[int]:
    try:
        return stat.S_IMODE(os.stat(path).st_mode)
    except OSError:
        return None


def _collect_files(paths: list[str], recurse: bool) -> list[tuple[str, int]]:
    """Expand the selection into concrete (path, size) pairs."""
    out: list[tuple[str, int]] = []
    for item in paths:
        if os.path.isdir(item):
            out.append((item, 0))
            if not recurse:
                continue
            for root, dirs, names in os.walk(item):
                for directory in dirs:
                    out.append((os.path.join(root, directory), 0))
                for name in names:
                    full = os.path.join(root, name)
                    try:
                        out.append((full, os.path.getsize(full)))
                    except OSError:
                        out.append((full, 0))
        elif os.path.exists(item):
            try:
                out.append((item, os.path.getsize(item)))
            except OSError:
                out.append((item, 0))
    return out


def _delete_sources(paths: list[str]) -> None:
    for item in paths:
        try:
            if os.path.isdir(item) and not os.path.islink(item):
                shutil.rmtree(item)
            else:
                os.unlink(item)
        except OSError:
            pass


def _unique_name(target: str) -> str:
    """Return ``name(1).ext`` style path, matching WinRAR's auto-rename."""
    if not os.path.exists(target):
        return target
    stem, ext = os.path.splitext(target)
    index = 1
    while os.path.exists(f"{stem}({index}){ext}"):
        index += 1
    return f"{stem}({index}){ext}"


def _silent_unlink(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def _terminal_tail(output: str, limit: int = 600) -> str:
    """The last of what a tool printed at its terminal, worth showing.

    A pty echoes back what was typed, so the transcript is filtered for the
    prompt lines before any of it reaches a message box: the password itself
    is never echoed, but the words around it are noise.
    """
    lines = [
        line.rstrip()
        for line in output.splitlines()
        if line.strip() and "password" not in line.lower()
    ]
    return "\n".join(lines)[-limit:].strip()
