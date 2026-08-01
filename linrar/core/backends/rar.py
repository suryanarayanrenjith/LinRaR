"""Backend driving the ``rar`` and ``unrar`` command line tools.

``unrar`` handles every read-only operation; ``rar`` (which is not always
installed, since it is shareware) is required for anything that modifies an
archive.  The class degrades gracefully when only ``unrar`` is present.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
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
    ExtractUpdateMode,
    OperationError,
    OverwriteMode,
    PasswordRequired,
    UpdateMode,
)
from ..process import ProcessRunner, parse_file_line, parse_percent
from .base import ArchiveBackend, TaskContext

# unrar/rar exit statuses (see the shipped manual).
EXIT_SUCCESS = 0
EXIT_WARNING = 1
EXIT_FATAL = 2
EXIT_CRC = 3
EXIT_LOCKED = 4
EXIT_WRITE = 5
EXIT_OPEN = 6
EXIT_USER = 7
EXIT_MEMORY = 8
EXIT_CREATE = 9
EXIT_NO_FILES = 10
EXIT_BAD_PASSWORD = 11
EXIT_USER_BREAK = 255

_EXIT_MESSAGES = {
    EXIT_WARNING: "Completed with warnings.",
    EXIT_FATAL: "A fatal error occurred.",
    EXIT_CRC: "Checksum error: the archive is damaged or the password is wrong.",
    EXIT_LOCKED: "The archive is locked and cannot be modified.",
    EXIT_WRITE: "Write error. The destination may be full or read-only.",
    EXIT_OPEN: "Cannot open the archive or one of the files.",
    EXIT_USER: "Invalid command line options.",
    EXIT_MEMORY: "Not enough memory.",
    EXIT_CREATE: "Cannot create the destination file.",
    EXIT_NO_FILES: "No files matched the specified mask.",
    EXIT_BAD_PASSWORD: "The password is incorrect.",
    EXIT_USER_BREAK: "The operation was cancelled.",
}

_DETAIL_MTIME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")


class RarBackend(ArchiveBackend):
    name = "RAR"
    formats = (ArchiveFormat.RAR5, ArchiveFormat.RAR4)
    can_write = True

    def __init__(
        self, rar_path: Optional[str] = None, unrar_path: Optional[str] = None
    ) -> None:
        self.rar = tools.locate("rar", rar_path)
        self.unrar = tools.locate("unrar", unrar_path)
        # "unrar" resolving to rar itself is fine; rar does everything unrar
        # does, and this is what a rar-only install looks like.

    # -- availability ------------------------------------------------------

    @property
    def available(self) -> bool:
        return bool(self.unrar or self.rar)

    def _require_unrar(self) -> str:
        if self.unrar:
            return self.unrar
        if self.rar:
            return self.rar  # rar can do everything unrar can
        raise OperationError(
            "Neither 'unrar' nor 'rar' was found on this system.\n\n"
            "Install one of them, for example:\n"
            "    sudo apt install unrar"
        )

    def _require_rar(self) -> str:
        if not self.rar:
            raise OperationError(
                "The 'rar' command is required to modify archives but was not "
                "found on this system.\n\n"
                "Install it, for example:\n"
                "    sudo apt install rar"
            )
        return self.rar

    # -- command plumbing --------------------------------------------------

    def _run(
        self,
        argv: list[str],
        password: Optional[str],
        ctx: Optional[TaskContext],
        cwd: Optional[str] = None,
        password_repeat: int = 1,
        allowed: tuple[int, ...] = (EXIT_SUCCESS,),
        write_command: bool = False,
    ) -> ProcessRunner:
        """Run a rar/unrar command, streaming progress into *ctx*.

        The password is delivered on stdin (never argv) so it stays out of the
        process table.  When no password is supplied, read commands get ``-p-``
        so the tool fails fast on an encrypted archive instead of blocking on a
        prompt.  Write commands must NOT receive ``-p-``: for ``rar a`` and
        friends that switch does not mean "no password" — it silently encrypts
        the archive with the literal password ``-``.  (This was the bug that
        made freshly created SFX archives demand a password.)  Since stdin is
        closed immediately, a write command that does decide to prompt simply
        reads EOF and fails instead of hanging.
        """
        ctx = ctx or TaskContext()
        stdin_text = None
        if password is not None:
            argv = argv[:1] + ["-p"] + argv[1:]
            stdin_text = (password + "\n") * max(1, password_repeat)
        elif not write_command:
            argv = argv[:1] + ["-p-"] + argv[1:]

        handle_line, handle_partial = _make_progress_handlers(ctx)

        runner = ProcessRunner(
            argv,
            cwd=cwd,
            stdin_text=stdin_text,
            on_line=handle_line,
            on_partial=handle_partial,
        )
        ctx.attach(runner)
        try:
            code = runner.run()
        finally:
            ctx.detach()

        if code in allowed:
            return runner
        if ctx.cancelled or code == EXIT_USER_BREAK:
            raise OperationError("The operation was cancelled.", code, runner.output)
        if code == EXIT_BAD_PASSWORD:
            raise PasswordRequired(
                "The password is incorrect." if password else
                "This archive is encrypted and requires a password.",
                code,
                runner.output,
            )
        raise OperationError(
            self._error_message(code, runner.output), code, runner.output
        )

    @staticmethod
    def _error_message(code: int, output: str) -> str:
        base = _EXIT_MESSAGES.get(code, f"The operation failed (exit code {code}).")
        # Surface the most informative line rar produced, if there is one.
        interesting = [
            ln.strip()
            for ln in output.splitlines()
            if ln.strip()
            and not ln.startswith(("Extracting", "Testing", "Adding", "Creating"))
            and any(
                k in ln
                for k in (
                    "Cannot", "cannot", "error", "Error", "failed", "Failed",
                    "No files", "not found", "corrupt", "Corrupt", "Unexpected",
                    "checksum", "Checksum", "wrong", "damaged",
                )
            )
        ]
        if interesting:
            detail = "\n".join(dict.fromkeys(interesting[-4:]))
            return f"{base}\n\n{detail}"
        return base

    @staticmethod
    def _write_list_file(names: list[str]) -> str:
        """Write member names to a temp file for rar's ``@listfile`` syntax.

        Avoids both ARG_MAX limits and any quoting ambiguity around names that
        contain spaces or non-ASCII characters.
        """
        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".lst", delete=False, encoding="utf-8"
        )
        try:
            # rar reads these lines verbatim, so names must not be escaped:
            # a backslash is an ordinary filename character on Linux.
            for name in names:
                handle.write(name + "\n")
        finally:
            handle.close()
        return handle.name

    # -- reading -----------------------------------------------------------

    def read_info(self, path: str, password: Optional[str] = None) -> ArchiveInfo:
        exe = self._require_unrar()
        argv = [exe, "-idc", "lt", path]
        runner = self._run(
            argv, password, None, allowed=(EXIT_SUCCESS, EXIT_WARNING)
        )
        info = self._parse_listing(runner.output, path)
        return info

    @staticmethod
    def _parse_listing(output: str, path: str) -> ArchiveInfo:
        info = ArchiveInfo(path=path)
        lines = output.splitlines()

        # Locate the "Archive:" header whose next meaningful line is "Details:".
        header_idx = -1
        for i, line in enumerate(lines):
            if line.startswith("Archive: "):
                for follow in lines[i + 1 : i + 3]:
                    if follow.strip():
                        if follow.startswith("Details: "):
                            header_idx = i
                        break
                if header_idx >= 0:
                    break
        if header_idx < 0:
            for i, line in enumerate(lines):
                if line.startswith("Archive: "):
                    header_idx = i
                    break

        if header_idx > 0:
            info.comment = _clean_comment("\n".join(lines[:header_idx]))
        body_start = header_idx + 1 if header_idx >= 0 else 0

        for i in range(body_start, min(body_start + 3, len(lines))):
            if lines[i].startswith("Details: "):
                info.detail_line = lines[i][len("Details: ") :].strip()
                body_start = i + 1
                break

        details = info.detail_line.lower()
        info.format = ArchiveFormat.RAR4 if "rar 4" in details else ArchiveFormat.RAR5
        info.encrypted_headers = "encrypted headers" in details
        info.solid = "solid" in details
        info.locked = "lock" in details
        info.recovery_record = "recovery record" in details
        info.sfx = "sfx" in details
        if "volume" in details:
            info.volume = True
            match = re.search(r"volume\s+(\d+)", details)
            if match:
                info.volume_number = int(match.group(1))

        # Entries arrive as blank-line separated "  Key: value" blocks.
        block: dict[str, str] = {}
        for line in lines[body_start:]:
            if not line.strip():
                if block:
                    entry = RarBackend._entry_from_block(block)
                    if entry:
                        info.entries.append(entry)
                    block = {}
                continue
            if ":" not in line:
                continue
            key, _, value = line.partition(":")
            key = key.strip()
            if key:
                block[key] = value.strip()
        if block:
            entry = RarBackend._entry_from_block(block)
            if entry:
                info.entries.append(entry)

        return info

    @staticmethod
    def _entry_from_block(block: dict[str, str]) -> Optional[ArchiveEntry]:
        name = block.get("Name")
        if not name:
            return None

        kind = block.get("Type", "File").lower()
        entry = ArchiveEntry(
            name=name.replace("\\", "/").lstrip("/"),
            is_dir=kind.startswith("dir"),
            attributes=block.get("Attributes", ""),
            host_os=block.get("Host OS", ""),
            method=block.get("Compression", ""),
            crc=block.get("CRC32") or block.get("CRC32 MAC") or block.get("BLAKE2sp", ""),
        )
        if kind.startswith("link") or block.get("Target"):
            entry.link_target = block.get("Target", "")

        for key, attr in (("Size", "size"), ("Packed size", "packed_size")):
            raw = block.get(key, "")
            if raw:
                digits = re.sub(r"[^\d]", "", raw)
                if digits:
                    setattr(entry, attr, int(digits))

        flags = block.get("Flags", "").lower()
        entry.encrypted = "encrypted" in flags

        raw_time = block.get("mtime") or block.get("Modified") or ""
        match = _DETAIL_MTIME_RE.match(raw_time)
        if match:
            try:
                entry.mtime = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S")
            except ValueError:
                entry.mtime = None

        return entry

    # -- extraction --------------------------------------------------------

    def extract(
        self,
        path: str,
        options: ExtractOptions,
        ctx: Optional[TaskContext] = None,
    ) -> None:
        exe = self._require_unrar()
        command = "e" if options.no_paths else "x"
        argv = [exe, "-idc", command, "-y"]

        if options.update_mode is ExtractUpdateMode.EXTRACT_UPDATE:
            argv.append("-u")
        elif options.update_mode is ExtractUpdateMode.FRESHEN:
            argv.append("-f")

        # ASK is resolved by the UI before we get here, so it never reaches rar.
        argv.append(
            {
                OverwriteMode.OVERWRITE: "-o+",
                OverwriteMode.SKIP: "-o-",
                OverwriteMode.RENAME: "-or",
                OverwriteMode.ASK: "-o+",
            }[options.overwrite_mode]
        )
        if options.keep_broken:
            argv.append("-kb")

        argv.append(path)

        list_file = None
        if options.members:
            list_file = self._write_list_file(options.members)
            argv.append(f"@{list_file}")

        destination = options.destination or os.getcwd()
        os.makedirs(destination, exist_ok=True)
        argv.append(destination.rstrip("/") + "/")

        try:
            self._run(
                argv,
                options.password,
                ctx,
                allowed=(EXIT_SUCCESS, EXIT_WARNING),
            )
        finally:
            if list_file:
                _silent_unlink(list_file)

    def test(
        self,
        path: str,
        password: Optional[str] = None,
        ctx: Optional[TaskContext] = None,
    ) -> None:
        exe = self._require_unrar()
        self._run([exe, "-idc", "t", "-y", path], password, ctx)

    # -- creation ----------------------------------------------------------

    def create(
        self,
        files: list[str],
        options: CompressOptions,
        ctx: Optional[TaskContext] = None,
    ) -> None:
        exe = self._require_rar()

        command = {
            UpdateMode.ADD_REPLACE: "a",
            UpdateMode.ADD_UPDATE: "u",
            UpdateMode.FRESHEN: "f",
            UpdateMode.ASK: "a",
            UpdateMode.SKIP_EXISTING: "a",
            UpdateMode.SYNCHRONIZE: "a",
        }[options.update_mode]

        argv = [exe, "-idc", command, "-y"]

        if options.update_mode is UpdateMode.SKIP_EXISTING:
            argv.append("-o-")
        elif options.update_mode is UpdateMode.SYNCHRONIZE:
            argv.append("-as")

        argv.append(f"-m{int(options.method)}")
        if options.format is ArchiveFormat.RAR4:
            argv.append("-ma4")
        else:
            argv.append("-ma5")
        if options.dictionary_size:
            argv.append(f"-md{options.dictionary_size}")
        # -r0 recurses into listed folders but, unlike -r, does not go hunting
        # through every subdirectory for other files that happen to share a
        # listed file's name (which used to sweep unrelated files into the
        # archive).  -r- disables recursion entirely.
        argv.append("-r0" if options.recurse_subfolders else "-r-")
        if options.solid:
            argv.append("-s")
        if options.volume_size > 0:
            argv.append(f"-v{options.volume_size}b")
        if options.recovery_record:
            argv.append(f"-rr{options.recovery_percent}p")
        if options.create_sfx:
            argv.append("-sfx")
        if options.delete_after:
            argv.append("-df")
        if options.test_after:
            argv.append("-t")
        if not options.store_paths:
            # -ep drops the path entirely; -ep1 (used previously) only trims
            # the base folder and still stored intermediate directories.
            argv.append("-ep")

        comment_file = None
        if options.comment:
            handle = tempfile.NamedTemporaryFile(
                "w", suffix=".txt", delete=False, encoding="utf-8"
            )
            handle.write(options.comment)
            handle.close()
            comment_file = handle.name
            argv.append(f"-z{comment_file}")

        exclude_file = None
        if options.exclude_patterns:
            exclude_file = self._write_list_file(options.exclude_patterns)
            argv.append(f"-x@{exclude_file}")

        password = options.password
        if password:
            # -hp encrypts the file names too; plain -p encrypts contents only.
            argv.insert(1, "-hp" if options.encrypt_headers else "-p")

        # rar silently renames the output to <stem>.sfx when -sfx is used, so
        # normalise the name up front and let callers see the real path.
        if options.create_sfx and not options.archive_path.lower().endswith(".sfx"):
            options.archive_path = (
                os.path.splitext(options.archive_path)[0] + ".sfx"
            )
        argv.append(options.archive_path)

        # Feed the member list relative to a common base so stored paths match
        # what the user selected in the browser.
        base = options.base_folder
        if not base and files:
            base = os.path.dirname(os.path.abspath(files[0]))
        relative = []
        for item in files:
            try:
                relative.append(os.path.relpath(item, base) if base else item)
            except ValueError:
                relative.append(item)

        list_file = self._write_list_file(relative)
        argv.append(f"@{list_file}")

        # Freshen/update runs legitimately end with "no files matched" when
        # everything is already up to date; that is not a failure.
        allowed: tuple[int, ...] = (EXIT_SUCCESS, EXIT_WARNING)
        if options.update_mode in (
            UpdateMode.FRESHEN,
            UpdateMode.ADD_UPDATE,
            UpdateMode.SKIP_EXISTING,
        ):
            allowed = allowed + (EXIT_NO_FILES,)

        try:
            self._run_create(argv, password, ctx, cwd=base or None, allowed=allowed)
        finally:
            _silent_unlink(list_file)
            if comment_file:
                _silent_unlink(comment_file)
            if exclude_file:
                _silent_unlink(exclude_file)

        if options.lock:
            self.lock(options.archive_path, ctx)

    def _run_create(
        self,
        argv: list[str],
        password: Optional[str],
        ctx: Optional[TaskContext],
        cwd: Optional[str],
        allowed: tuple[int, ...] = (EXIT_SUCCESS, EXIT_WARNING),
    ) -> None:
        """Like :meth:`_run` but rar asks for a new password twice.

        With no password, no ``-p`` switch of any kind is passed: ``rar a``
        never prompts unless asked to, and ``-p-`` here would encrypt the
        archive with the literal password ``-``.
        """
        ctx = ctx or TaskContext()
        stdin_text = None
        if password is not None:
            stdin_text = (password + "\n") * 2

        handle_line, handle_partial = _make_progress_handlers(ctx)

        runner = ProcessRunner(
            argv,
            cwd=cwd,
            stdin_text=stdin_text,
            on_line=handle_line,
            on_partial=handle_partial,
        )
        ctx.attach(runner)
        try:
            code = runner.run()
        finally:
            ctx.detach()

        if code in allowed:
            if code == EXIT_NO_FILES:
                ctx.on_message("Nothing to do: the archive is already up to date.")
            return
        if ctx.cancelled or code == EXIT_USER_BREAK:
            raise OperationError("The operation was cancelled.", code, runner.output)
        if code == EXIT_BAD_PASSWORD:
            raise PasswordRequired("The password is incorrect.", code, runner.output)
        raise OperationError(
            self._error_message(code, runner.output), code, runner.output
        )

    # -- modification ------------------------------------------------------

    def delete_members(
        self,
        path: str,
        members: list[str],
        password: Optional[str] = None,
        ctx: Optional[TaskContext] = None,
    ) -> None:
        exe = self._require_rar()
        list_file = self._write_list_file(members)
        try:
            self._run(
                [exe, "-idc", "d", "-y", path, f"@{list_file}"],
                password,
                ctx,
                allowed=(EXIT_SUCCESS, EXIT_WARNING),
                write_command=True,
            )
        finally:
            _silent_unlink(list_file)

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
        """Rename several members in one pass.

        ``rar rn`` only renames the exact entries named, so renaming a folder
        requires renaming every child too; callers pass the full pair list and
        it is applied in a single invocation.
        """
        exe = self._require_rar()
        argv = [exe, "-idc", "rn", "-y", path]
        for old_name, new_name in pairs:
            argv.extend([old_name, new_name])
        self._run(
            argv,
            password,
            ctx,
            allowed=(EXIT_SUCCESS, EXIT_WARNING),
            write_command=True,
        )

    def set_comment(
        self,
        path: str,
        comment: str,
        password: Optional[str] = None,
        ctx: Optional[TaskContext] = None,
    ) -> None:
        exe = self._require_rar()
        # An empty comment file clears the existing comment.
        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".txt", delete=False, encoding="utf-8"
        )
        handle.write(comment)
        handle.close()
        try:
            self._run(
                [exe, "-idc", "c", "-y", f"-z{handle.name}", path],
                password,
                ctx,
                allowed=(EXIT_SUCCESS, EXIT_WARNING),
                write_command=True,
            )
        finally:
            _silent_unlink(handle.name)

    def lock(self, path: str, ctx: Optional[TaskContext] = None) -> None:
        exe = self._require_rar()
        self._run(
            [exe, "-idc", "k", "-y", path],
            None,
            ctx,
            allowed=(EXIT_SUCCESS, EXIT_WARNING),
            write_command=True,
        )

    def add_recovery_record(
        self, path: str, percent: int = 3, ctx: Optional[TaskContext] = None
    ) -> None:
        exe = self._require_rar()
        self._run(
            [exe, "-idc", f"rr{percent}p", "-y", path],
            None,
            ctx,
            allowed=(EXIT_SUCCESS, EXIT_WARNING),
            write_command=True,
        )

    def add_recovery_volumes(
        self,
        path: str,
        amount: str = "3%",
        ctx: Optional[TaskContext] = None,
    ) -> None:
        """Create ``.rev`` recovery volumes beside a multi-volume archive.

        Recovery volumes can rebuild whole missing parts of a volume set, which
        a recovery *record* cannot do.  rar only accepts this for volumes.
        """
        exe = self._require_rar()
        self._run(
            [exe, "-idc", f"rv{amount}", "-y", path],
            None,
            ctx,
            allowed=(EXIT_SUCCESS, EXIT_WARNING),
            write_command=True,
        )

    def reconstruct_volumes(
        self, path: str, ctx: Optional[TaskContext] = None
    ) -> None:
        """Rebuild missing volumes of a set from its ``.rev`` files."""
        exe = self._require_rar()
        self._run(
            [exe, "-idc", "rc", "-y", path],
            None,
            ctx,
            allowed=(EXIT_SUCCESS, EXIT_WARNING),
            write_command=True,
        )

    def convert_to_sfx(
        self, path: str, ctx: Optional[TaskContext] = None
    ) -> str:
        """Convert an archive in place to rar's own ``.sfx`` stub format."""
        exe = self._require_rar()
        self._run(
            [exe, "-idc", "s", "-y", path],
            None,
            ctx,
            allowed=(EXIT_SUCCESS, EXIT_WARNING),
            write_command=True,
        )
        return os.path.splitext(path)[0] + ".sfx"

    def repair(
        self, path: str, output_dir: str, ctx: Optional[TaskContext] = None
    ) -> Optional[str]:
        exe = self._require_rar()
        path = os.path.abspath(path)  # we run with cwd=output_dir
        before = set(os.listdir(output_dir)) if os.path.isdir(output_dir) else set()
        self._run(
            [exe, "-idc", "r", "-y", path],
            None,
            ctx,
            cwd=output_dir,
            allowed=(EXIT_SUCCESS, EXIT_WARNING, EXIT_CRC),
            write_command=True,
        )
        after = set(os.listdir(output_dir)) if os.path.isdir(output_dir) else set()
        # rar writes "fixed.<name>" or "rebuilt.<name>" next to the original.
        for created in sorted(after - before):
            if created.startswith(("fixed.", "rebuilt.")):
                return os.path.join(output_dir, created)
        return None


#: The heading unrar 7 puts above the comment block; unrar 6 printed the
#: comment bare.  It is not part of the comment and must not survive into the
#: UI, nor into the next comment written back — that would grow a header line
#: on every edit.  Matched exactly: a user comment whose own first line reads
#: "Comment:" stays untouched, because losing a line of someone's text is
#: worse than showing one stray heading.
_COMMENT_LABELS = ("archive comment:",)


def _clean_comment(block: str) -> str:
    """The comment itself, without unrar's heading or surrounding blank lines."""
    lines = block.strip("\n").splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines and lines[0].strip().lower() in _COMMENT_LABELS:
        lines.pop(0)
    return "\n".join(lines).strip()


def _make_progress_handlers(ctx: TaskContext):
    """Build the stdout handlers that translate rar's output into progress.

    rar only ever prints a percentage for the file it is currently processing,
    and it makes more than one pass over some files (an analysis pass before the
    compression pass) so that number jumps backwards.  The overall figure is
    therefore derived from how many members have been started, and is clamped so
    it can never regress.
    """
    state = {"current": "", "last_pct": -1, "index": 0, "overall": 0}

    def emit_overall(pct: int) -> None:
        total = ctx.total_items
        if total > 0:
            done = max(state["index"] - 1, 0) + pct / 100.0
            value = int(min(100.0, done * 100.0 / total))
        else:
            value = pct
        if value > state["overall"]:
            state["overall"] = value
            ctx.on_total(value)

    def observe(line: str) -> None:
        pct = parse_percent(line)
        if pct is not None and pct != state["last_pct"]:
            state["last_pct"] = pct
            ctx.on_percent(pct)
            emit_overall(pct)

    def handle_partial(line: str) -> None:
        observe(line)

    def handle_line(line: str) -> None:
        parsed = parse_file_line(line)
        if parsed:
            verb, filename = parsed
            if filename != state["current"]:
                state["current"] = filename
                state["last_pct"] = -1
                # "Creating" marks a folder being made (or the archive itself),
                # which is not one of the members we are counting towards.
                if verb != "Creating":
                    state["index"] += 1
                ctx.on_file(filename)
                emit_overall(0)
        observe(line)
        stripped = line.strip()
        if stripped:
            ctx.on_message(stripped)

    return handle_line, handle_partial


def _silent_unlink(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def dictionary_sizes(fmt: ArchiveFormat) -> list[str]:
    """Dictionary sizes offered for a format, matching WinRAR's combo box."""
    if fmt is ArchiveFormat.RAR4:
        return ["64K", "128K", "256K", "512K", "1024K", "2048K", "4096K"]
    if fmt is ArchiveFormat.ZIP:
        return ["32K"]
    return [
        "128K", "256K", "512K", "1M", "2M", "4M", "8M", "16M",
        "32M", "64M", "128M", "256M", "512M", "1G",
    ]


def default_dictionary(fmt: ArchiveFormat, method: CompressionMethod) -> str:
    """The dictionary size rar itself would pick, so the combo shows the truth."""
    if fmt is ArchiveFormat.ZIP:
        return "32K"
    if fmt is ArchiveFormat.RAR4:
        return "4096K"
    if method is CompressionMethod.STORE:
        return "128K"
    return "32M"
