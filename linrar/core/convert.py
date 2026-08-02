"""Archive format conversion: WinRAR's Tools > Convert archives.

Conversion is unpack-then-repack: there is no format-to-format transcoder, so
each archive is extracted to a private temporary folder and rebuilt in the
target format.  The original is only replaced once the new archive has been
written successfully.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass, field
from typing import Optional

from .backends.base import TaskContext
from .models import (
    ArchiveFormat,
    CompressOptions,
    ExtractOptions,
    OperationError,
    OverwriteMode,
    PasswordRequired,
)
from .registry import REGISTRY


@dataclass
class ConvertOptions:
    """Settings for a batch conversion run."""

    target_format: ArchiveFormat = ArchiveFormat.RAR5
    output_folder: str = ""       # blank keeps each archive beside the original
    delete_original: bool = False
    keep_going: bool = True       # carry on when one archive fails
    compress: Optional[CompressOptions] = None
    passwords: list[str] = field(default_factory=list)


@dataclass
class ConvertResult:
    source: str
    output: str = ""
    ok: bool = False
    message: str = ""


def _extension_for(fmt: ArchiveFormat) -> str:
    return {
        ArchiveFormat.RAR5: ".rar",
        ArchiveFormat.RAR4: ".rar",
        ArchiveFormat.ZIP: ".zip",
        ArchiveFormat.SEVENZIP: ".7z",
    }.get(fmt, ".rar")


def convert_archive(
    source: str,
    options: ConvertOptions,
    ctx: Optional[TaskContext] = None,
) -> ConvertResult:
    """Convert a single archive, returning what happened."""
    ctx = ctx or TaskContext()
    result = ConvertResult(source=source)

    try:
        backend, _fmt = REGISTRY.for_path(source)
    except OperationError as exc:
        result.message = exc.message
        return result

    # Find a password that opens it, if any were supplied.
    password: Optional[str] = None
    try:
        info = backend.read_info(source)
    except PasswordRequired:
        info = None
        for candidate in options.passwords:
            try:
                info = backend.read_info(source, candidate)
                password = candidate
                break
            except (PasswordRequired, OperationError):
                continue
        if info is None:
            result.message = "The archive is encrypted and no password matched."
            return result
    except OperationError as exc:
        result.message = exc.message
        return result

    folder = options.output_folder or os.path.dirname(os.path.abspath(source))
    stem = os.path.splitext(os.path.basename(source))[0]
    target = os.path.join(folder, stem + _extension_for(options.target_format))
    if os.path.abspath(target) == os.path.abspath(source):
        target = os.path.join(
            folder, f"{stem}_converted{_extension_for(options.target_format)}"
        )

    workdir = tempfile.mkdtemp(prefix="linrar-convert-")
    try:
        ctx.on_message(f"Unpacking {os.path.basename(source)}...")
        backend.extract(
            source,
            ExtractOptions(
                destination=workdir,
                overwrite_mode=OverwriteMode.OVERWRITE,
                password=password,
            ),
            ctx,
        )

        members = [
            os.path.join(workdir, name) for name in sorted(os.listdir(workdir))
        ]
        if not members:
            result.message = "The archive is empty; nothing to convert."
            return result

        compress = options.compress or CompressOptions()
        compress = CompressOptions(
            **{
                **compress.__dict__,
                "archive_path": target,
                "format": options.target_format,
                "base_folder": workdir,
                "comment": info.comment or compress.comment,
            }
        )

        ctx.on_message(f"Repacking as {os.path.basename(target)}...")
        target_backend = REGISTRY.for_format(options.target_format)
        if os.path.exists(target):
            os.unlink(target)
        target_backend.create(members, compress, ctx)

        result.output = target
        result.ok = True
        result.message = "Converted."

        if options.delete_original and os.path.abspath(target) != os.path.abspath(
            source
        ):
            try:
                os.unlink(source)
                result.message = "Converted; original deleted."
            except OSError as exc:
                result.message = f"Converted, but the original could not be deleted: {exc}"
    except OperationError as exc:
        result.message = exc.message
    except Exception as exc:  # noqa: BLE001 - report anything unexpected per file
        result.message = str(exc)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    return result


def convert_many(
    sources: list[str],
    options: ConvertOptions,
    ctx: Optional[TaskContext] = None,
) -> list[ConvertResult]:
    """Convert several archives, reporting overall progress as it goes."""
    ctx = ctx or TaskContext()
    results: list[ConvertResult] = []
    total = len(sources) or 1

    for index, source in enumerate(sources):
        if ctx.cancelled:
            break
        ctx.on_file(os.path.basename(source))
        result = convert_archive(source, options, ctx)
        results.append(result)
        ctx.on_total(int((index + 1) * 100 / total))
        if not result.ok and not options.keep_going:
            break

    return results
