"""Self-extracting archives built as Linux AppImages.

WinRAR's "Convert to SFX" wraps an archive in a Windows ``.exe`` that unpacks
itself when double-clicked.  The Linux equivalent of a single-file, double
clickable executable is the AppImage, so that is what LinRAR produces.

A type 2 AppImage is simply a small ELF *runtime* with a SquashFS image
concatenated onto the end.  The runtime mounts that filesystem with FUSE and
executes ``AppRun`` inside it.  Building one therefore needs no special tooling
beyond ``mksquashfs``::

    mksquashfs AppDir payload.squashfs -root-owned -noappend
    cat runtime payload.squashfs > Out.AppImage
    chmod +x Out.AppImage

The only awkward ingredient is the runtime binary itself, which this module
obtains from (in order): a local cache, ``appimagetool`` if installed, an
AppImage already present on the machine, or a download.
"""

from __future__ import annotations

import os
import platform
import shutil
import struct
import tempfile
from dataclasses import dataclass
from typing import Callable, Optional

from .backends.base import TaskContext
from . import tools
from .models import OperationError
from .process import ProcessRunner

#: The two shapes a self-extracting archive takes on Linux.  They are stored
#: in settings and in saved profiles, so they live here rather than in the
#: dialog that offers them.
APPIMAGE = "appimage"
RAR_STUB = "rar"

RUNTIME_URL = (
    "https://github.com/AppImage/type2-runtime/releases/download/continuous/"
    "runtime-{arch}"
)

# Directories scanned when harvesting a runtime from an existing AppImage.
_APPIMAGE_DIRS = (
    "~/Applications", "~/AppImages", "~/.local/bin", "~/Downloads",
    "~/Desktop", "/opt", "/usr/local/bin",
)


def cache_dir() -> str:
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    path = os.path.join(base, "linrar")
    os.makedirs(path, exist_ok=True)
    return path


def runtime_arch() -> str:
    """Map the running machine to AppImage's runtime naming."""
    machine = platform.machine().lower()
    return {
        "x86_64": "x86_64", "amd64": "x86_64",
        "aarch64": "aarch64", "arm64": "aarch64",
        "armv7l": "armhf", "armv7": "armhf",
        "i686": "i686", "i386": "i686",
    }.get(machine, machine)


def cached_runtime_path() -> str:
    return os.path.join(cache_dir(), f"appimage-runtime-{runtime_arch()}")


# ---------------------------------------------------------------- options


@dataclass
class SfxOptions:
    """Mirrors WinRAR's SFX module configuration."""

    # General
    default_path: str = ""
    ask_destination: bool = True

    # Setup
    run_after: str = ""
    run_before: str = ""

    # Modes
    silent: bool = False
    overwrite: str = "ask"  # ask | overwrite | skip | rename

    # Text and icon
    title: str = "Self-extracting archive"
    description: str = ""
    icon_png: Optional[bytes] = None

    # License
    license_title: str = ""
    license_text: str = ""

    # Advanced (Linux equivalents of WinRAR's shortcut/registry options)
    create_desktop_entry: bool = False
    desktop_entry_name: str = ""
    desktop_entry_exec: str = ""

    def validate(self) -> None:
        if self.create_desktop_entry and not self.desktop_entry_exec:
            raise OperationError(
                "A desktop entry was requested but no command was given for it."
            )


# ---------------------------------------------------------------- runtime


def _elf_payload_offset(path: str) -> Optional[int]:
    """Return the size of the ELF part of an AppImage, i.e. the runtime.

    The SquashFS image begins immediately after the ELF section headers, so
    ``e_shoff + e_shentsize * e_shnum`` gives exactly what
    ``--appimage-offset`` reports -- without having to execute the file.
    """
    try:
        with open(path, "rb") as handle:
            head = handle.read(64)
    except OSError:
        return None
    if len(head) < 64 or head[:4] != b"\x7fELF":
        return None
    if head[4] != 2:  # 64-bit only
        return None
    # Bytes 8..10 carry AppImage's "AI\x02" type 2 marker.
    if head[8:11] != b"AI\x02":
        return None
    shoff = struct.unpack_from("<Q", head, 0x28)[0]
    shentsize = struct.unpack_from("<H", head, 0x3A)[0]
    shnum = struct.unpack_from("<H", head, 0x3C)[0]
    size = shoff + shentsize * shnum
    file_size = os.path.getsize(path)
    if 0 < size < file_size:
        return size
    return None


def find_donor_appimage() -> Optional[str]:
    """Locate any type 2 AppImage on this machine we can copy a runtime from."""
    for folder in _APPIMAGE_DIRS:
        expanded = os.path.expanduser(folder)
        if not os.path.isdir(expanded):
            continue
        try:
            entries = sorted(os.scandir(expanded), key=lambda e: e.name.lower())
        except OSError:
            continue
        for entry in entries:
            if not entry.is_file():
                continue
            if not entry.name.lower().endswith(".appimage"):
                continue
            if _elf_payload_offset(entry.path):
                return entry.path
    return None


def harvest_runtime(donor: str, destination: str) -> bool:
    """Copy the runtime stub out of an existing AppImage."""
    size = _elf_payload_offset(donor)
    if not size:
        return False
    try:
        with open(donor, "rb") as src, open(destination, "wb") as dst:
            dst.write(src.read(size))
        os.chmod(destination, 0o755)
    except OSError:
        return False
    return True


def download_runtime(destination: str, timeout: int = 60) -> None:
    """Fetch the official AppImage runtime for this architecture."""
    import urllib.error
    import urllib.request

    url = RUNTIME_URL.format(arch=runtime_arch())
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "LinRAR"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read()
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise OperationError(
            "Could not download the AppImage runtime.\n\n"
            f"{url}\n\n{exc}\n\n"
            "Check your internet connection, or install 'appimagetool'."
        ) from exc
    if len(data) < 10000 or data[:4] != b"\x7fELF":
        raise OperationError(
            "The downloaded AppImage runtime is not a valid executable."
        )
    with open(destination, "wb") as handle:
        handle.write(data)
    os.chmod(destination, 0o755)


class RuntimeSource:
    """Describes where a runtime came from, for reporting back to the user."""

    def __init__(self, path: str, origin: str) -> None:
        self.path = path
        self.origin = origin


def acquire_runtime(
    allow_download: bool = True,
    confirm_download: Optional[Callable[[str], bool]] = None,
    ctx: Optional[TaskContext] = None,
) -> RuntimeSource:
    """Obtain an AppImage runtime, trying every offline option first."""
    ctx = ctx or TaskContext()
    cached = cached_runtime_path()
    if os.path.isfile(cached) and os.path.getsize(cached) > 10000:
        return RuntimeSource(cached, "cache")

    donor = find_donor_appimage()
    if donor and harvest_runtime(donor, cached):
        ctx.on_message(f"Using the AppImage runtime from {donor}")
        return RuntimeSource(cached, f"copied from {os.path.basename(donor)}")

    if not allow_download:
        raise OperationError(_no_runtime_message())

    url = RUNTIME_URL.format(arch=runtime_arch())
    if confirm_download is not None and not confirm_download(url):
        raise OperationError("Cancelled: no AppImage runtime is available.")

    ctx.on_message(f"Downloading the AppImage runtime from {url}")
    download_runtime(cached)
    return RuntimeSource(cached, "downloaded")


def _no_runtime_message() -> str:
    return (
        "No AppImage runtime is available.\n\n"
        "LinRAR needs the small AppImage runtime stub to build a "
        "self-extracting archive. It can be obtained by:\n\n"
        "  • installing 'appimagetool', or\n"
        "  • keeping any .AppImage file in ~/Applications or ~/Downloads, or\n"
        "  • allowing LinRAR to download it once (about 1 MB)."
    )


# ---------------------------------------------------------------- AppRun

# Static launcher.  Everything configurable lives in sfx.conf beside it, so the
# script itself never needs escaping or templating.
APPRUN = r"""#!/bin/sh
# LinRAR self-extracting archive.
set -u
HERE="$(dirname "$(readlink -f "$0")")"
DATA="$HERE/usr/share/linrar-sfx"
. "$DATA/sfx.conf"

PAYLOAD="$DATA/$SFX_PAYLOAD"
SELF="$(readlink -f "$0")"

# --- extractor -------------------------------------------------------------
UNRAR=""
for candidate in "$HERE/usr/bin/unrar" "$(command -v unrar 2>/dev/null)" \
                 "$(command -v rar 2>/dev/null)"; do
    if [ -n "$candidate" ] && [ -x "$candidate" ]; then UNRAR="$candidate"; break; fi
done

have_gui() {
    [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ] && command -v zenity >/dev/null 2>&1
}

msg_info() {
    if have_gui; then zenity --info --no-wrap --title="$SFX_TITLE" --text="$1" 2>/dev/null
    else printf '%s\n' "$1"; fi
}
msg_error() {
    if have_gui; then zenity --error --no-wrap --title="$SFX_TITLE" --text="$1" 2>/dev/null
    else printf '%s\n' "$1" >&2; fi
}

usage() {
    cat <<USAGE
$SFX_TITLE

Usage: $(basename "$SELF") [options]

  -d DIR, --dest DIR   Extract into DIR
  -y, --yes            Overwrite existing files without asking
  -s, --silent         Extract without any prompts
  -l, --list           List the contents and exit
  -t, --test           Test archive integrity and exit
  -x, --extract-only   Extract but do not run the setup command
      --gui            Force the graphical interface
      --no-gui         Force the terminal interface
  -h, --help           Show this help

This is a self-extracting archive created with LinRAR.
USAGE
}

# --- arguments -------------------------------------------------------------
DEST=""
FORCE_YES=0
SILENT="$SFX_SILENT"
ACTION="extract"
RUN_SETUP=1
GUI_MODE="auto"

while [ $# -gt 0 ]; do
    case "$1" in
        -d|--dest) DEST="${2:-}"; shift 2 ;;
        -d*) DEST="${1#-d}"; shift ;;
        -y|--yes) FORCE_YES=1; shift ;;
        -s|--silent) SILENT=1; shift ;;
        -l|--list) ACTION="list"; shift ;;
        -t|--test) ACTION="test"; shift ;;
        -x|--extract-only) RUN_SETUP=0; shift ;;
        --gui) GUI_MODE="yes"; shift ;;
        --no-gui) GUI_MODE="no"; shift ;;
        -h|--help) usage; exit 0 ;;
        *) printf 'Unknown option: %s\n' "$1" >&2; usage; exit 2 ;;
    esac
done

case "$GUI_MODE" in
    yes) have_gui() { command -v zenity >/dev/null 2>&1; } ;;
    no)  have_gui() { return 1; } ;;
esac

if [ -z "$UNRAR" ]; then
    msg_error "No RAR extractor was found.
Install 'unrar' and run this archive again."
    exit 1
fi

# --- list / test -----------------------------------------------------------
if [ "$ACTION" = "list" ]; then
    "$UNRAR" l -- "$PAYLOAD"
    exit $?
fi
if [ "$ACTION" = "test" ]; then
    "$UNRAR" t -- "$PAYLOAD"
    exit $?
fi

# --- licence ---------------------------------------------------------------
if [ -f "$DATA/license.txt" ] && [ "$SILENT" -eq 0 ]; then
    if have_gui; then
        if ! zenity --text-info --title="${SFX_LICENSE_TITLE:-License Agreement}" \
                    --filename="$DATA/license.txt" --checkbox="I accept the terms" \
                    --width=640 --height=480 2>/dev/null; then
            exit 1
        fi
    else
        printf '\n--- %s ---\n' "${SFX_LICENSE_TITLE:-License Agreement}"
        cat "$DATA/license.txt"
        printf '\nDo you accept these terms? [y/N] '
        read -r reply
        case "$reply" in [Yy]*) ;; *) exit 1 ;; esac
    fi
fi

# --- destination -----------------------------------------------------------
expand_home() {
    case "$1" in
        "~") printf '%s' "$HOME" ;;
        "~/"*) printf '%s/%s' "$HOME" "${1#\~/}" ;;
        *) printf '%s' "$1" ;;
    esac
}

if [ -z "$DEST" ]; then
    DEST="$(expand_home "$SFX_DEFAULT_PATH")"
fi
[ -z "$DEST" ] && DEST="$PWD"

if [ "$SILENT" -eq 0 ] && [ "$SFX_ASK_DEST" -eq 1 ]; then
    if have_gui; then
        intro="$SFX_DESCRIPTION"
        [ -n "$intro" ] && zenity --info --no-wrap --title="$SFX_TITLE" \
            --text="$intro" 2>/dev/null
        chosen="$(zenity --file-selection --directory --title="Extract to" \
                  --filename="$DEST/" 2>/dev/null)" || exit 1
        [ -n "$chosen" ] && DEST="$chosen"
    else
        [ -n "$SFX_DESCRIPTION" ] && printf '%s\n\n' "$SFX_DESCRIPTION"
        printf 'Extract to [%s]: ' "$DEST"
        read -r reply
        [ -n "$reply" ] && DEST="$(expand_home "$reply")"
    fi
fi

if ! mkdir -p "$DEST" 2>/dev/null; then
    msg_error "Cannot create the destination folder:
$DEST"
    exit 1
fi

# --- overwrite policy ------------------------------------------------------
if [ "$FORCE_YES" -eq 1 ] || [ "$SILENT" -eq 1 ]; then
    OW="-o+"
else
    case "$SFX_OVERWRITE" in
        overwrite) OW="-o+" ;;
        skip) OW="-o-" ;;
        rename) OW="-or" ;;
        *) OW="-o+" ;;
    esac
fi

# --- run before ------------------------------------------------------------
if [ -n "$SFX_RUN_BEFORE" ] && [ "$RUN_SETUP" -eq 1 ]; then
    ( cd "$DEST" && sh -c "$SFX_RUN_BEFORE" )
fi

# --- extract ---------------------------------------------------------------
PW=""
do_extract() {
    if [ -n "$PW" ]; then
        printf '%s\n' "$PW" | "$UNRAR" x -y "$OW" -p -- "$PAYLOAD" "$DEST/"
    else
        "$UNRAR" x -y "$OW" -p- -- "$PAYLOAD" "$DEST/"
    fi
}

# rar reports progress with backspaces rather than newlines, so a line-based
# progress bar would never advance; a pulsing one is honest about that.
run_extract() {
    if have_gui && [ "$SILENT" -eq 0 ]; then
        statusfile="$(mktemp 2>/dev/null || echo /tmp/linrar-sfx.$$)"
        ( do_extract >/dev/null 2>&1; echo $? > "$statusfile" ) &
        worker=$!
        (
            while kill -0 "$worker" 2>/dev/null; do
                printf '#Extracting files...\n'
                sleep 0.3
            done
        ) | zenity --progress --pulsate --auto-close --no-cancel \
                   --title="$SFX_TITLE" --text="Extracting files..." \
                   --width=420 2>/dev/null
        wait "$worker" 2>/dev/null
        status="$(cat "$statusfile" 2>/dev/null || echo 1)"
        rm -f "$statusfile"
    else
        do_extract
        status=$?
    fi
}

ask_password() {
    if have_gui; then
        PW="$(zenity --password --title="$SFX_TITLE" 2>/dev/null)" || return 1
    else
        printf 'Password: '
        stty -echo 2>/dev/null
        read -r PW
        stty echo 2>/dev/null
        printf '\n'
    fi
    [ -n "$PW" ]
}

run_extract
# 11 is rar's "bad password"; give the user up to three attempts.
attempts=0
while [ "${status:-0}" -eq 11 ] && [ "$attempts" -lt 3 ]; do
    attempts=$((attempts + 1))
    ask_password || break
    run_extract
done

if [ "${status:-0}" -ne 0 ] && [ "${status:-0}" -ne 1 ]; then
    msg_error "Extraction failed (code ${status})."
    exit "${status}"
fi

# --- desktop entry ---------------------------------------------------------
if [ "$SFX_DESKTOP_ENTRY" -eq 1 ] && [ -n "$SFX_DESKTOP_EXEC" ]; then
    apps="$HOME/.local/share/applications"
    mkdir -p "$apps"
    entry="$apps/linrar-sfx-$(printf '%s' "$SFX_DESKTOP_NAME" | tr -c 'A-Za-z0-9' '-').desktop"
    # Exec is quoted so destinations containing spaces still launch.
    cat > "$entry" <<DESKTOP
[Desktop Entry]
Type=Application
Name=$SFX_DESKTOP_NAME
Exec="$DEST/$SFX_DESKTOP_EXEC"
Path=$DEST
Terminal=false
Categories=Utility;
DESKTOP
    chmod +x "$entry" 2>/dev/null
    command -v update-desktop-database >/dev/null 2>&1 &&
        update-desktop-database "$apps" >/dev/null 2>&1
fi

# --- run after -------------------------------------------------------------
if [ -n "$SFX_RUN_AFTER" ] && [ "$RUN_SETUP" -eq 1 ]; then
    ( cd "$DEST" && sh -c "$SFX_RUN_AFTER" )
    exit $?
fi

if [ "$SILENT" -eq 0 ]; then
    msg_info "Extraction complete.

Files were extracted to:
$DEST"
fi
exit 0
"""


def _shell_quote(value: str) -> str:
    """Single-quote a value for safe inclusion in a POSIX shell config."""
    return "'" + str(value).replace("'", "'\\''") + "'"


def _write_config(path: str, options: SfxOptions, payload_name: str) -> None:
    lines = [
        "# Generated by LinRAR. Values are shell-quoted.",
        f"SFX_TITLE={_shell_quote(options.title or 'Self-extracting archive')}",
        f"SFX_DESCRIPTION={_shell_quote(options.description)}",
        f"SFX_DEFAULT_PATH={_shell_quote(options.default_path)}",
        f"SFX_ASK_DEST={_shell_quote('1' if options.ask_destination else '0')}",
        f"SFX_SILENT={_shell_quote('1' if options.silent else '0')}",
        f"SFX_OVERWRITE={_shell_quote(options.overwrite)}",
        f"SFX_RUN_AFTER={_shell_quote(options.run_after)}",
        f"SFX_RUN_BEFORE={_shell_quote(options.run_before)}",
        f"SFX_PAYLOAD={_shell_quote(payload_name)}",
        f"SFX_LICENSE_TITLE={_shell_quote(options.license_title)}",
        f"SFX_DESKTOP_ENTRY="
        f"{_shell_quote('1' if options.create_desktop_entry else '0')}",
        f"SFX_DESKTOP_NAME={_shell_quote(options.desktop_entry_name)}",
        f"SFX_DESKTOP_EXEC={_shell_quote(options.desktop_entry_exec)}",
        "",
    ]
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))


# Minimal 1x1 transparent PNG, used when no icon is supplied.
_FALLBACK_PNG = bytes.fromhex(
    "89504e470d0a1a0a"                                  # signature
    "0000000d49484452000000010000000108060000001f15c489"  # IHDR
    "0000000a49444154789c63000100000500010d0a2db4"        # IDAT
    "0000000049454e44ae426082"                            # IEND
)


# ---------------------------------------------------------------- builder


def build_sfx_appimage(
    archive_path: str,
    output_path: str,
    options: Optional[SfxOptions] = None,
    ctx: Optional[TaskContext] = None,
    allow_download: bool = True,
    confirm_download: Optional[Callable[[str], bool]] = None,
) -> str:
    """Wrap *archive_path* into a self-extracting ``.AppImage``.

    Returns the path actually written.
    """
    options = options or SfxOptions()
    options.validate()
    ctx = ctx or TaskContext()

    if not os.path.isfile(archive_path):
        raise OperationError(f"The archive does not exist:\n{archive_path}")
    mksquashfs = tools.find("squashfs")
    if not mksquashfs:
        raise OperationError(
            "'mksquashfs' is required to build an AppImage but was not "
            "found.\n\nInstall it, for example:\n"
            "    sudo apt install squashfs-tools"
        )

    ctx.on_message("Preparing the AppImage runtime...")
    runtime = acquire_runtime(allow_download, confirm_download, ctx)
    ctx.on_total(10)

    workdir = tempfile.mkdtemp(prefix="linrar-sfx-")
    appdir = os.path.join(workdir, "AppDir")
    data_dir = os.path.join(appdir, "usr", "share", "linrar-sfx")
    bin_dir = os.path.join(appdir, "usr", "bin")
    os.makedirs(data_dir)
    os.makedirs(bin_dir)

    try:
        # -- payload --
        ctx.on_message("Adding the archive payload...")
        payload_name = os.path.basename(archive_path)
        shutil.copy2(archive_path, os.path.join(data_dir, payload_name))
        ctx.on_total(35)

        # -- bundled extractor, so the recipient needs nothing installed --
        unrar = tools.find("unrar")
        if unrar:
            try:
                shutil.copy2(unrar, os.path.join(bin_dir, "unrar"))
                os.chmod(os.path.join(bin_dir, "unrar"), 0o755)
                ctx.on_message("Bundled the unrar extractor.")
            except OSError:
                ctx.on_message("Could not bundle unrar; the recipient will need it.")

        # -- launcher and configuration --
        apprun = os.path.join(appdir, "AppRun")
        with open(apprun, "w", encoding="utf-8") as handle:
            handle.write(APPRUN)
        os.chmod(apprun, 0o755)
        _write_config(os.path.join(data_dir, "sfx.conf"), options, payload_name)

        if options.license_text.strip():
            with open(
                os.path.join(data_dir, "license.txt"), "w", encoding="utf-8"
            ) as handle:
                handle.write(options.license_text)

        # -- AppImage metadata (a .desktop file and an icon are required) --
        app_name = "linrar-sfx"
        with open(
            os.path.join(appdir, f"{app_name}.desktop"), "w", encoding="utf-8"
        ) as handle:
            handle.write(
                "[Desktop Entry]\n"
                "Type=Application\n"
                f"Name={options.title or 'Self-extracting archive'}\n"
                "Exec=AppRun\n"
                f"Icon={app_name}\n"
                "Categories=Utility;Archiving;\n"
                "Terminal=false\n"
            )
        icon_bytes = options.icon_png or _FALLBACK_PNG
        with open(os.path.join(appdir, f"{app_name}.png"), "wb") as handle:
            handle.write(icon_bytes)
        # AppImage tooling also looks for the icon under this path.
        icon_dir = os.path.join(
            appdir, "usr", "share", "icons", "hicolor", "256x256", "apps"
        )
        os.makedirs(icon_dir, exist_ok=True)
        with open(os.path.join(icon_dir, f"{app_name}.png"), "wb") as handle:
            handle.write(icon_bytes)
        ctx.on_total(45)

        # -- squash --
        ctx.on_message("Building the SquashFS image...")
        squashfs = os.path.join(workdir, "payload.squashfs")
        runner = ProcessRunner(
            [
                mksquashfs, appdir, squashfs,
                "-root-owned", "-noappend", "-no-progress",
                # gzip keeps the image compatible with every AppImage runtime.
                "-comp", "gzip",
                # Store file data uncompressed: the payload is an archive
                # already, and leaving its bytes verbatim keeps the embedded
                # RAR signature visible so unrar (and LinRAR's own browser)
                # can open the AppImage directly, like a WinRAR SFX .exe.
                "-noD", "-noF",
            ],
            on_line=ctx.on_message,
        )
        ctx.attach(runner)
        try:
            code = runner.run()
        finally:
            ctx.detach()
        if code != 0:
            raise OperationError(
                "Failed to build the SquashFS image.\n\n" + runner.output[-800:]
            )
        ctx.on_total(80)

        # -- concatenate runtime + filesystem --
        ctx.on_message("Assembling the AppImage...")
        if not output_path.lower().endswith(".appimage"):
            output_path += ".AppImage"
        with open(output_path, "wb") as out:
            with open(runtime.path, "rb") as handle:
                shutil.copyfileobj(handle, out)
            with open(squashfs, "rb") as handle:
                shutil.copyfileobj(handle, out, length=1024 * 1024)
        os.chmod(output_path, 0o755)
        ctx.on_total(100)
        ctx.on_message(f"Created {output_path} (runtime {runtime.origin}).")
        return output_path
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def appimage_ready() -> tuple[bool, str]:
    """Report whether an AppImage can be built right now, and why not."""
    if not tools.find("squashfs"):
        return False, (
            "'mksquashfs' is not installed (package 'squashfs-tools')."
        )
    if os.path.isfile(cached_runtime_path()):
        return True, "Ready (runtime cached)."
    if find_donor_appimage():
        return True, "Ready (a runtime can be copied from an existing AppImage)."
    return True, "Ready (the runtime will be downloaded once, about 1 MB)."
