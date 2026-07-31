#!/usr/bin/env bash
# LinRAR for Linux — uninstaller.
#
# Removes everything install.sh put on the system: the launcher, the desktop
# entry, the icon, the file-manager right-click entries and (unless you say
# otherwise) the virtual environment.
#
# The project folder itself is left alone — delete it yourself when you are
# done with it.

set -euo pipefail

APP_NAME="LinRAR"
APP_ID="linrar"
APP_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
MANIFEST="${APP_DIR}/.install-manifest"

KEEP_VENV=0
PURGE_TOOLS=0
PURGE_SETTINGS=0
ASSUME_YES=0

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
    C_BOLD=$'\033[1m'; C_DIM=$'\033[2m'; C_OK=$'\033[32m'
    C_WARN=$'\033[33m'; C_ERR=$'\033[31m'; C_OFF=$'\033[0m'
else
    C_BOLD=""; C_DIM=""; C_OK=""; C_WARN=""; C_ERR=""; C_OFF=""
fi

step() { printf '%s==>%s %s\n' "$C_BOLD" "$C_OFF" "$*"; }
info() { printf '    %s\n' "$*"; }
ok()   { printf '    %s✓%s %s\n' "$C_OK" "$C_OFF" "$*"; }
warn() { printf '    %s!%s %s\n' "$C_WARN" "$C_OFF" "$*"; }
die()  { printf '%serror:%s %s\n' "$C_ERR" "$C_OFF" "$*" >&2; exit 1; }

usage() {
    cat <<EOF
${APP_NAME} uninstaller

Usage: ./uninstall.sh [options]

  --keep-venv        leave .venv in place (it is removed by default)
  --purge-tools      also remove unrar / rar / 7z / zip from the system
  --purge-settings   also delete LinRAR's saved settings and cache
  -y, --yes          do not ask anything, assume yes
  -h, --help         show this message

The virtual environment (.venv) is removed too, since install.sh created it;
./install.sh builds it again. The folder containing LinRAR is never deleted —
remove that by hand when you no longer want it.
EOF
}

confirm() {
    [ "$ASSUME_YES" = "1" ] && return 0
    local reply
    printf '    %s [y/N] ' "$1"
    read -r reply </dev/tty || reply="n"
    case "${reply:-n}" in [Yy]*) return 0 ;; *) return 1 ;; esac
}

have() { command -v "$1" >/dev/null 2>&1; }

ROOT_PREFIX=()
resolve_root() {
    if [ "$(id -u)" = "0" ]; then ROOT_PREFIX=(); return 0; fi
    if have sudo; then ROOT_PREFIX=(sudo); return 0; fi
    if have doas; then ROOT_PREFIX=(doas); return 0; fi
    if have pkexec; then ROOT_PREFIX=(pkexec); return 0; fi
    return 1
}
as_root() {
    if [ "$(id -u)" = "0" ]; then "$@"; return; fi
    [ ${#ROOT_PREFIX[@]} -gt 0 ] || return 1
    "${ROOT_PREFIX[@]}" "$@"
}

while [ $# -gt 0 ]; do
    case "$1" in
        --keep-venv)      KEEP_VENV=1 ;;
        --purge-tools)    PURGE_TOOLS=1 ;;
        --purge-settings) PURGE_SETTINGS=1 ;;
        -y|--yes)         ASSUME_YES=1 ;;
        -h|--help)        usage; exit 0 ;;
        *)                die "unknown option: $1  (try --help)" ;;
    esac
    shift
done

printf '\n%s%s for Linux — uninstaller%s\n' "$C_BOLD" "$APP_NAME" "$C_OFF"
printf '%sproject: %s%s\n\n' "$C_DIM" "$APP_DIR" "$C_OFF"

resolve_root || true

remove_path() {  # remove_path <path>
    local path="$1"
    [ -n "$path" ] || return 0
    if [ -e "$path" ] || [ -L "$path" ]; then
        if rm -f "$path" 2>/dev/null; then
            info "removed ${path}"
        elif as_root rm -f "$path" 2>/dev/null; then
            info "removed ${path} (as root)"
        else
            warn "could not remove ${path}"
        fi
    fi
}

# ---------------------------------------------------------------- 1. files

step "Removing installed files"
REMOVED=0
if [ -f "$MANIFEST" ]; then
    info "using the manifest written by install.sh"
    while IFS= read -r path; do
        [ -n "$path" ] || continue
        case "$path" in
            */Thunar/uca.xml) continue ;;   # handled separately below
        esac
        remove_path "$path"
        REMOVED=$((REMOVED + 1))
    done < "$MANIFEST"
    rm -f "$MANIFEST"
else
    warn "no install manifest — falling back to the standard locations"
fi

# Belt and braces: sweep the standard locations whether or not a manifest
# existed, so an install from an older version is cleaned up too.
USER_DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
for base in "$USER_DATA" /usr/local/share /usr/share; do
    remove_path "${base}/applications/${APP_ID}.desktop"
    remove_path "${base}/icons/hicolor/scalable/apps/${APP_ID}.svg"
    for size in 16 22 24 32 48 64 128 256 512; do
        remove_path "${base}/icons/hicolor/${size}x${size}/apps/${APP_ID}.png"
    done
    remove_path "${base}/pixmaps/${APP_ID}.png"
    remove_path "${base}/kio/servicemenus/${APP_ID}.desktop"
    remove_path "${base}/kservices5/ServiceMenus/${APP_ID}.desktop"
    for action in extract-here extract-to compress; do
        remove_path "${base}/nemo/actions/${APP_ID}-${action}.nemo_action"
    done
    for manager in nautilus nemo caja; do
        remove_path "${base}/${manager}/scripts/LinRAR — Extract here"
        remove_path "${base}/${manager}/scripts/LinRAR — Extract to..."
        remove_path "${base}/${manager}/scripts/LinRAR — Add to archive..."
    done
done
for bin in "${HOME}/.local/bin/${APP_ID}" "/usr/local/bin/${APP_ID}" "/usr/bin/${APP_ID}"; do
    remove_path "$bin"
done

# The desktop entry the app's own "Desktop integration" command may have made.
remove_path "${USER_DATA}/applications/${APP_ID}.desktop"

# ---------------------------------------------------------------- 2. thunar

THUNAR_UCA="${XDG_CONFIG_HOME:-$HOME/.config}/Thunar/uca.xml"
if [ -f "$THUNAR_UCA" ] && grep -q "linrar" "$THUNAR_UCA" 2>/dev/null; then
    step "Removing the Thunar right-click actions"
    if python3 - "$THUNAR_UCA" <<'PYEOF'
import shutil, sys, xml.etree.ElementTree as ET

path = sys.argv[1]
try:
    tree = ET.parse(path)
except (ET.ParseError, OSError):
    sys.exit(1)
root = tree.getroot()
removed = 0
for action in list(root.findall("action")):
    name = action.findtext("name", "") or ""
    unique = action.findtext("unique-id", "") or ""
    command = action.findtext("command", "") or ""
    if name.startswith("LinRAR:") or unique.startswith("linrar-") or "linrar" in command:
        root.remove(action)
        removed += 1
if removed:
    shutil.copy2(path, path + ".linrar-backup")
    tree.write(path, encoding="UTF-8", xml_declaration=True)
PYEOF
    then
        ok "Thunar actions removed"
    else
        warn "could not edit ${THUNAR_UCA} — remove the LinRAR entries by hand"
    fi
fi

# ---------------------------------------------------------------- 3. mime

step "Refreshing the desktop databases"
if have xdg-mime; then
    # Drop LinRAR from the user's default-application list.
    MIMEAPPS="${XDG_CONFIG_HOME:-$HOME/.config}/mimeapps.list"
    if [ -f "$MIMEAPPS" ] && grep -q "${APP_ID}.desktop" "$MIMEAPPS"; then
        cp "$MIMEAPPS" "${MIMEAPPS}.linrar-backup"
        grep -v "${APP_ID}.desktop" "${MIMEAPPS}.linrar-backup" > "$MIMEAPPS" || true
        info "cleaned ${MIMEAPPS} (backup kept alongside)"
    fi
fi
for dir in "${USER_DATA}/applications" /usr/local/share/applications /usr/share/applications; do
    [ -d "$dir" ] || continue
    if have update-desktop-database; then
        update-desktop-database "$dir" >/dev/null 2>&1 || \
            as_root update-desktop-database "$dir" >/dev/null 2>&1 || true
    fi
done
if have gtk-update-icon-cache; then
    gtk-update-icon-cache -f -t "${USER_DATA}/icons/hicolor" >/dev/null 2>&1 || true
fi
if have kbuildsycoca6; then kbuildsycoca6 >/dev/null 2>&1 || true
elif have kbuildsycoca5; then kbuildsycoca5 >/dev/null 2>&1 || true; fi
ok "databases refreshed"

# ---------------------------------------------------------------- 4. venv

step "Removing the Python environment"
if [ "$KEEP_VENV" = "1" ]; then
    info "kept at ${APP_DIR}/.venv (--keep-venv)"
elif [ -d "${APP_DIR}/.venv" ]; then
    # Part of the install, so part of the uninstall: install.sh builds it back.
    rm -rf "${APP_DIR}/.venv"
    ok "removed ${APP_DIR}/.venv"
else
    info "no .venv to remove"
fi

# ---------------------------------------------------------------- 5. extras

if [ "$PURGE_SETTINGS" = "1" ]; then
    step "Removing saved settings and cache"
    for path in \
        "${XDG_CONFIG_HOME:-$HOME/.config}/LinRAR" \
        "${XDG_CONFIG_HOME:-$HOME/.config}/LinRAR-Linux" \
        "${XDG_CACHE_HOME:-$HOME/.cache}/LinRAR-Linux" \
        "${XDG_CACHE_HOME:-$HOME/.cache}/LinRAR"
    do
        if [ -d "$path" ]; then rm -rf "$path"; info "removed ${path}"; fi
    done
    ok "settings and cache removed"
else
    info "settings kept in ~/.config/LinRAR (use --purge-settings to remove)"
fi

if [ "$PURGE_TOOLS" = "1" ]; then
    step "Removing the command line tools"
    warn "other applications may use these"
    PM=""
    for candidate in apt-get dnf pacman zypper apk xbps-remove eopkg; do
        have "$candidate" && { PM="$candidate"; break; }
    done
    if [ -n "$PM" ] && resolve_root && confirm "Remove unrar, rar, p7zip and zip with ${PM}?"; then
        case "$PM" in
            apt-get) as_root apt-get remove -y unrar rar p7zip-full zip || true ;;
            dnf)     as_root dnf remove -y unrar rar p7zip zip || true ;;
            pacman)  as_root pacman -R --noconfirm unrar p7zip zip || true ;;
            zypper)  as_root zypper remove -y unrar rar p7zip-full zip || true ;;
            apk)     as_root apk del unrar p7zip zip || true ;;
            xbps-remove) as_root xbps-remove -y unrar p7zip zip || true ;;
            eopkg)   as_root eopkg remove -y unrar p7zip zip || true ;;
        esac
        ok "tools removed"
    else
        info "skipped"
    fi
fi

printf '\n%s%s has been uninstalled.%s\n\n' "$C_OK$C_BOLD" "$APP_NAME" "$C_OFF"
info "the project folder is still here: ${APP_DIR}"
info "delete it yourself when you no longer need it:  rm -rf \"${APP_DIR}\""
printf '\n'
