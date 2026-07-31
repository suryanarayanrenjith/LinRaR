#!/usr/bin/env bash
# LinRAR for Linux — installer.
#
# Sets up the Python environment, installs the command line tools LinRAR
# drives, puts a `linrar` launcher on the PATH, registers the application and
# its file types with the desktop, and adds right-click entries to the file
# managers that support them.
#
# Nothing outside this project folder is written without saying so first, and
# uninstall.sh reverses every one of those writes.

set -euo pipefail

APP_NAME="LinRAR"
APP_ID="linrar"
APP_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"

MODE="user"          # user | system
WITH_DEPS=1          # install the rar/unrar/7z tools too
ASSUME_YES=0
KEEP_VENV=0

# ---------------------------------------------------------------- helpers

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
    C_BOLD=$'\033[1m'; C_DIM=$'\033[2m'; C_OK=$'\033[32m'
    C_WARN=$'\033[33m'; C_ERR=$'\033[31m'; C_OFF=$'\033[0m'
else
    C_BOLD=""; C_DIM=""; C_OK=""; C_WARN=""; C_ERR=""; C_OFF=""
fi

step()  { printf '%s==>%s %s\n' "$C_BOLD" "$C_OFF" "$*"; }
info()  { printf '    %s\n' "$*"; }
ok()    { printf '    %s✓%s %s\n' "$C_OK" "$C_OFF" "$*"; }
warn()  { printf '    %s!%s %s\n' "$C_WARN" "$C_OFF" "$*"; }
die()   { printf '%serror:%s %s\n' "$C_ERR" "$C_OFF" "$*" >&2; exit 1; }

usage() {
    cat <<EOF
${APP_NAME} installer

Usage: ./install.sh [options]

  --user          install for the current user only (default)
  --system        install for every user (needs administrator rights)
  --no-deps       skip installing rar/unrar/7z and friends
  --keep-venv     reuse the existing .venv instead of rebuilding it
  -y, --yes       do not ask anything, assume yes
  -h, --help      show this message

The project folder itself is never moved: LinRAR runs from right here, and
the launcher simply points at it.
EOF
}

confirm() {
    [ "$ASSUME_YES" = "1" ] && return 0
    local reply
    printf '    %s [Y/n] ' "$1"
    read -r reply </dev/tty || reply="y"
    case "${reply:-y}" in [Yy]*|"") return 0 ;; *) return 1 ;; esac
}

have() { command -v "$1" >/dev/null 2>&1; }

# Run a command as root, however this system allows it.
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

# ---------------------------------------------------------------- options

while [ $# -gt 0 ]; do
    case "$1" in
        --user)      MODE="user" ;;
        --system)    MODE="system" ;;
        --no-deps)   WITH_DEPS=0 ;;
        --keep-venv) KEEP_VENV=1 ;;
        -y|--yes)    ASSUME_YES=1 ;;
        -h|--help)   usage; exit 0 ;;
        *)           die "unknown option: $1  (try --help)" ;;
    esac
    shift
done

if [ "$MODE" = "system" ]; then
    BIN_DIR="/usr/local/bin"
    DATA_DIR="/usr/local/share"
    XDG_DATA_DIRS_TARGET="/usr/local/share"
else
    BIN_DIR="${HOME}/.local/bin"
    DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}"
    XDG_DATA_DIRS_TARGET="$DATA_DIR"
fi
APPS_DIR="${DATA_DIR}/applications"
ICON_DATA="${DATA_DIR}/icons"
ICON_DIR="${ICON_DATA}/hicolor/scalable/apps"
ICON_SIZES="16 22 24 32 48 64 128 256 512"
DESKTOP_FILE="${APPS_DIR}/${APP_ID}.desktop"
LAUNCHER="${BIN_DIR}/${APP_ID}"
MANIFEST="${APP_DIR}/.install-manifest"

# Records every path we create so uninstall.sh can undo exactly this install.
: > "${MANIFEST}.tmp"
record() { printf '%s\n' "$1" >> "${MANIFEST}.tmp"; }

write_file() {   # write_file <path> <mode>   (content on stdin)
    local path="$1" mode="${2:-644}" dir
    dir="$(dirname "$path")"
    if [ "$MODE" = "system" ]; then
        as_root mkdir -p "$dir"
        as_root tee "$path" >/dev/null
        as_root chmod "$mode" "$path"
    else
        mkdir -p "$dir"
        cat > "$path"
        chmod "$mode" "$path"
    fi
    record "$path"
}

install_file() { # install_file <source> <target> [mode]
    local source="$1" target="$2" mode="${3:-644}"
    write_file "$target" "$mode" < "$source"
}

printf '\n%s%s for Linux — installer%s\n' "$C_BOLD" "$APP_NAME" "$C_OFF"
printf '%sproject: %s   mode: %s%s\n\n' "$C_DIM" "$APP_DIR" "$MODE" "$C_OFF"

for required in "linrar/__main__.py" "assets/linrar.svg" "requirements.txt"; do
    [ -f "${APP_DIR}/${required}" ] ||
        die "this does not look like the LinRAR folder (${required} is missing)"
done

if [ "$MODE" = "system" ] && ! resolve_root; then
    die "--system needs administrator rights, but sudo, doas and pkexec are all missing"
fi
resolve_root || true

# ---------------------------------------------------------------- 1. distro

step "Looking at the system"
DISTRO_ID=""; DISTRO_NAME="this system"
if [ -r /etc/os-release ]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    DISTRO_ID="${ID:-}"
    DISTRO_NAME="${PRETTY_NAME:-${NAME:-this system}}"
    DISTRO_LIKE="${ID_LIKE:-}"
fi
info "distribution: ${DISTRO_NAME}"

PM=""
for candidate in "${DISTRO_ID}" ${DISTRO_LIKE:-}; do
    case "$candidate" in
        debian|ubuntu|pop|linuxmint|elementary|zorin|kali|raspbian|deepin|mx|\
        devuan|neon|tuxedo|parrot|pureos|trisquel)            PM="apt" ;;
        fedora|rhel|centos|rocky|almalinux|nobara|ol|scientific|amzn|\
        qubes|mageia)                                         PM="dnf" ;;
        arch|manjaro|endeavouros|garuda|cachyos|artix|arcolinux|\
        archcraft|steamos)                                    PM="pacman" ;;
        opensuse*|suse|sles|sled|tumbleweed|leap)             PM="zypper" ;;
        alpine|postmarketos)                                  PM="apk" ;;
        void)                                                 PM="xbps" ;;
        solus)                                                PM="eopkg" ;;
        gentoo|funtoo|calculate)                              PM="emerge" ;;
        nixos)                                                PM="nix" ;;
        slackware)                                            PM="slackpkg" ;;
        clear-linux-os)                                       PM="swupd" ;;
        openmandriva|pclinuxos)                               PM="dnf" ;;
    esac
    [ -n "$PM" ] && break
done
if [ -z "$PM" ]; then
    for candidate in apt-get apt dnf5 dnf yum pacman zypper apk xbps-install \
                     eopkg emerge nix-env swupd slackpkg; do
        if have "$candidate"; then
            case "$candidate" in
                apt-get|apt) PM="apt" ;;
                dnf5|dnf|yum) PM="dnf" ;;
                xbps-install) PM="xbps" ;;
                nix-env)      PM="nix" ;;
                *)            PM="$candidate" ;;
            esac
            break
        fi
    done
fi

# Image-based distributions (Silverblue, Kinoite, Bazzite, Aurora, uBlue...)
# layer packages instead of installing them, and /usr is read only.
IMMUTABLE=0
if have rpm-ostree && [ -f /run/ostree-booted ]; then
    IMMUTABLE=1
    PM="rpm-ostree"
fi

[ -n "$PM" ] && info "package manager: ${PM}" || warn "no known package manager found"
[ "$IMMUTABLE" = "1" ] && info "image-based system: packages are layered, a reboot applies them"

# ---------------------------------------------------------------- 2. tools

pm_install() {  # pm_install <package>...
    [ $# -gt 0 ] || return 0
    case "$PM" in
        apt)
            have apt-get && as_root apt-get install -y "$@" \
                         || as_root apt install -y "$@" ;;
        dnf)
            if have dnf5;  then as_root dnf5 install -y "$@"
            elif have dnf; then as_root dnf install -y "$@"
            else                as_root yum install -y "$@"; fi ;;
        pacman)     as_root pacman -S --noconfirm --needed "$@" ;;
        zypper)     as_root zypper install -y "$@" ;;
        apk)        as_root apk add "$@" ;;
        xbps)       as_root xbps-install -y "$@" ;;
        eopkg)      as_root eopkg install -y "$@" ;;
        emerge)     as_root emerge --noreplace "$@" ;;
        swupd)      as_root swupd bundle-add "$@" ;;
        slackpkg)   as_root slackpkg install "$@" ;;
        rpm-ostree) as_root rpm-ostree install --idempotent --apply-live "$@" \
                    || as_root rpm-ostree install --idempotent "$@" ;;
        nix)        nix-env -iA "$@" ;;
        *)          return 1 ;;
    esac
}

packages_for() {  # packages_for <role>
    case "$PM:$1" in
        apt:python)    echo "python3 python3-venv python3-pip" ;;
        apt:qt)        echo "libxcb-cursor0 libxcb-xinerama0 libgl1" ;;
        apt:archive)   echo "unrar p7zip-full zip squashfs-tools" ;;
        apt:rar)       echo "rar" ;;
        apt:keyring)   echo "libsecret-tools" ;;

        dnf:python)    echo "python3 python3-pip" ;;
        dnf:qt)        echo "xcb-util-cursor mesa-libGL" ;;
        dnf:archive)   echo "unrar p7zip p7zip-plugins zip squashfs-tools" ;;
        dnf:rar)       echo "rar" ;;
        dnf:keyring)   echo "libsecret" ;;

        pacman:python) echo "python python-pip" ;;
        pacman:qt)     echo "xcb-util-cursor" ;;
        pacman:archive) echo "unrar p7zip zip squashfs-tools" ;;
        pacman:rar)    echo "" ;;   # AUR only
        pacman:keyring) echo "libsecret" ;;

        zypper:python) echo "python3 python3-pip" ;;
        zypper:qt)     echo "libxcb-cursor0" ;;
        zypper:archive) echo "unrar p7zip-full zip squashfs" ;;
        zypper:rar)    echo "rar" ;;
        zypper:keyring) echo "libsecret-tools" ;;

        apk:python)    echo "python3 py3-pip" ;;
        apk:qt)        echo "libxcb" ;;
        apk:archive)   echo "unrar p7zip zip squashfs-tools" ;;
        apk:rar)       echo "rar" ;;
        apk:keyring)   echo "libsecret" ;;

        xbps:python)   echo "python3 python3-pip" ;;
        xbps:qt)       echo "xcb-util-cursor" ;;
        xbps:archive)  echo "unrar p7zip zip squashfs-tools" ;;
        xbps:rar)      echo "" ;;
        xbps:keyring)  echo "libsecret" ;;

        eopkg:python)  echo "python3" ;;
        eopkg:qt)      echo "xcb-util-cursor" ;;
        eopkg:archive) echo "unrar p7zip zip squashfs-tools" ;;
        eopkg:rar)     echo "rar" ;;
        eopkg:keyring) echo "libsecret" ;;

        emerge:python)  echo "dev-lang/python" ;;
        emerge:qt)      echo "x11-libs/xcb-util-cursor" ;;
        emerge:archive) echo "app-arch/unrar app-arch/p7zip app-arch/zip sys-fs/squashfs-tools" ;;
        emerge:rar)     echo "app-arch/rar" ;;
        emerge:keyring) echo "app-crypt/libsecret" ;;

        rpm-ostree:python)  echo "python3 python3-pip" ;;
        rpm-ostree:qt)      echo "xcb-util-cursor mesa-libGL" ;;
        rpm-ostree:archive) echo "unrar p7zip p7zip-plugins zip squashfs-tools" ;;
        rpm-ostree:rar)     echo "" ;;
        rpm-ostree:keyring) echo "libsecret" ;;

        swupd:python)  echo "python-basic" ;;
        swupd:qt)      echo "desktop-libs" ;;
        swupd:archive) echo "archive-tools" ;;
        swupd:rar)     echo "" ;;
        swupd:keyring) echo "" ;;

        *) echo "" ;;
    esac
}

if [ "$PM" = "nix" ]; then
    step "NixOS detected"
    info "NixOS installs packages declaratively, so this script does not try."
    info "Add these to your configuration (or a nix-shell) and re-run with --no-deps:"
    info "  python3 unrar rar p7zip zip squashfs-tools libsecret"
    info "PyQt6 from pip needs nix-ld or a python environment with it included."
    WITH_DEPS=0
fi

if [ "$MODE" = "system" ] && [ "$IMMUTABLE" = "1" ]; then
    warn "/usr is read-only on an image-based system — installing for this user instead"
    MODE="user"
    BIN_DIR="${HOME}/.local/bin"
    DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}"
    APPS_DIR="${DATA_DIR}/applications"
    ICON_DATA="${DATA_DIR}/icons"
    ICON_DIR="${ICON_DATA}/hicolor/scalable/apps"
    DESKTOP_FILE="${APPS_DIR}/${APP_ID}.desktop"
    LAUNCHER="${BIN_DIR}/${APP_ID}"
fi

if [ "$WITH_DEPS" = "1" ] && [ -n "$PM" ]; then
    step "Installing the tools LinRAR drives"
    WANTED="$(packages_for python) $(packages_for qt) $(packages_for archive) $(packages_for keyring)"
    # shellcheck disable=SC2086
    set -- $WANTED
    info "packages: $*"
    if resolve_root; then
        if confirm "Install these with ${PM}?"; then
            if pm_install "$@"; then
                ok "packages installed"
            else
                warn "some packages could not be installed — LinRAR will still run,"
                warn "and Tools > Dependencies can retry them later"
            fi
            RAR_PKG="$(packages_for rar)"
            if [ -n "$RAR_PKG" ]; then
                info "rar (shareware, creates RAR archives): ${RAR_PKG}"
                if confirm "Install ${RAR_PKG} too?"; then
                    # shellcheck disable=SC2086
                    if pm_install $RAR_PKG; then
                        ok "rar installed"
                    else
                        warn "rar is not in your enabled repositories"
                        warn "(Ubuntu: enable 'multiverse'; Fedora: RPM Fusion nonfree)"
                    fi
                fi
            else
                warn "rar is not packaged for ${PM}; RAR *creation* will be unavailable"
                warn "until you install RARLAB's binary yourself (reading works via unrar)"
            fi
        else
            info "skipped"
        fi
    else
        warn "no sudo/doas/pkexec, so packages cannot be installed automatically"
        warn "install by hand: $*"
    fi
else
    [ "$WITH_DEPS" = "1" ] && warn "no package manager detected — skipping system tools"
fi

# ---------------------------------------------------------------- 3. venv

step "Setting up the Python environment"
have python3 || die "python3 is not installed"
PY_OK="$(python3 -c 'import sys; print(1 if sys.version_info >= (3, 9) else 0)')"
[ "$PY_OK" = "1" ] || die "Python 3.9 or newer is required"
info "python: $(python3 --version 2>&1)"

VENV="${APP_DIR}/.venv"
if [ -d "$VENV" ] && [ "$KEEP_VENV" = "0" ]; then
    info "rebuilding the existing virtual environment"
    rm -rf "$VENV"
fi
if [ ! -d "$VENV" ]; then
    if ! python3 -m venv "$VENV" 2>/dev/null; then
        warn "python3 -m venv failed — the venv module is a separate package here"
        case "$PM" in
            apt)    pm_install python3-venv python3-pip || true ;;
            dnf)    pm_install python3-libs python3-pip || true ;;
            zypper) pm_install python3-venv python3-pip || true ;;
            *)      : ;;
        esac
        python3 -m venv "$VENV" 2>/dev/null ||
            python3 -m venv --without-pip "$VENV" ||
            die "could not create a virtual environment; install your distro's python3-venv package"
    fi
fi
if ! "$VENV/bin/python" -m pip --version >/dev/null 2>&1; then
    info "bootstrapping pip inside the environment"
    "$VENV/bin/python" -m ensurepip --upgrade >/dev/null 2>&1 ||
        die "the environment has no pip; install python3-pip and run this again"
fi
"$VENV/bin/python" -m pip install --upgrade pip >/dev/null 2>&1 || true
info "installing PyQt6 (this can take a minute)"
if ! "$VENV/bin/python" -m pip install -r "${APP_DIR}/requirements.txt"; then
    warn "the wheel install failed — trying the distribution's own PyQt6"
    case "$PM" in
        apt)    pm_install python3-pyqt6 python3-pyqt6.qtsvg || true ;;
        dnf)    pm_install python3-pyqt6 python3-pyqt6-base || true ;;
        pacman) pm_install python-pyqt6 || true ;;
        zypper) pm_install python3-qt6 || true ;;
        apk)    pm_install py3-qt6 || true ;;
        xbps)   pm_install python3-PyQt6 || true ;;
        emerge) pm_install dev-python/PyQt6 || true ;;
        *)      : ;;
    esac
    # A venv that can see the system packages is the fallback of last resort.
    rm -rf "$VENV"
    python3 -m venv --system-site-packages "$VENV" ||
        die "could not install PyQt6; install it with your package manager and re-run"
    "$VENV/bin/python" -c "import PyQt6.QtWidgets" 2>/dev/null ||
        die "PyQt6 is still not importable; install python3-pyqt6 (or equivalent) first"
    info "using the system PyQt6 through a --system-site-packages environment"
fi
ok "virtual environment ready at .venv"

# The launcher and every desktop file below run this.
RUNNER="${VENV}/bin/python"

# ---------------------------------------------------------------- 4. launcher

step "Installing the launcher"
mkdir -p "$BIN_DIR" 2>/dev/null || as_root mkdir -p "$BIN_DIR"
write_file "$LAUNCHER" 755 <<EOF
#!/usr/bin/env bash
# LinRAR launcher — generated by install.sh, removed by uninstall.sh.
#
# PYTHONPATH rather than cd: the working directory has to stay wherever the
# caller was, so relative file arguments still resolve.
export PYTHONPATH="${APP_DIR}\${PYTHONPATH:+:\$PYTHONPATH}"

# Wayland sessions without the Qt wayland plugin (or with a broken one) leave
# Qt with nothing to talk to; fall back to X11 rather than refusing to start.
if [ -z "\${QT_QPA_PLATFORM:-}" ] && [ "\${XDG_SESSION_TYPE:-}" = "wayland" ]; then
    plugins="\$("${RUNNER}" -c 'import PyQt6.QtCore as c, os; print(os.path.join(c.QLibraryInfo.path(c.QLibraryInfo.LibraryPath.PluginsPath), "platforms"))' 2>/dev/null || true)"
    if [ -n "\$plugins" ] && [ ! -e "\$plugins/libqwayland-generic.so" ] \\
       && [ -n "\${DISPLAY:-}" ]; then
        export QT_QPA_PLATFORM=xcb
    fi
fi

# RESOURCE_NAME is Qt's own way to set the X11 WM_CLASS instance name, which is
# what the shell matches windows to this .desktop file (and so to the icon)
# with.  It must NOT be done by giving python a fake argv[0]: CPython works out
# where its standard library and virtual environment live from argv[0], so an
# argv[0] of "linrar" sends it looking for pyvenv.cfg next to this script,
# finds none, and falls back to the system interpreter without PyQt6.
export RESOURCE_NAME="${APP_ID}"
exec "${RUNNER}" -m linrar "\$@"
EOF
ok "${LAUNCHER}"

case ":${PATH}:" in
    *":${BIN_DIR}:"*) : ;;
    *) warn "${BIN_DIR} is not on your PATH — add this to your shell profile:"
       warn "  export PATH=\"${BIN_DIR}:\$PATH\"" ;;
esac

# ---------------------------------------------------------------- 5. desktop

step "Registering with the desktop"

# The scalable icon, plus real raster sizes: some launchers never rasterise
# SVG, and the ones that do reach for the PNG first.
install_file "${APP_DIR}/assets/linrar.svg" "${ICON_DIR}/${APP_ID}.svg" 644
PNG_TMP="$(mktemp -d)"
if "$RUNNER" - "$PNG_TMP" "$APP_DIR" <<'PYEOF' >/dev/null 2>&1
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
target, project = sys.argv[1], sys.argv[2]
sys.path.insert(0, project)
from PyQt6.QtGui import QGuiApplication
app = QGuiApplication([])
from linrar.ui import icons
for size in (16, 22, 24, 32, 48, 64, 128, 256, 512):
    if not icons.export_png("app", size, os.path.join(target, f"{size}.png")):
        raise SystemExit(1)
PYEOF
then
    for size in $ICON_SIZES; do
        install_file "${PNG_TMP}/${size}.png" \
            "${ICON_DATA}/hicolor/${size}x${size}/apps/${APP_ID}.png" 644
    done
    # Legacy location, for the handful of launchers that still only look here.
    install_file "${PNG_TMP}/128.png" "${DATA_DIR}/pixmaps/${APP_ID}.png" 644
    ok "icon (SVG + 9 raster sizes)"
else
    warn "could not render the PNG icons; the SVG alone will have to do"
fi
rm -rf "$PNG_TMP"

# gtk-update-icon-cache refuses to run on a theme directory with no index,
# and a user-level hicolor tree often has none.
if [ ! -f "${ICON_DATA}/hicolor/index.theme" ]; then
    {
        printf '[Icon Theme]\nName=Hicolor\nComment=Fallback icon theme\n'
        printf 'Directories=scalable/apps'
        for size in $ICON_SIZES; do printf ',%sx%s/apps' "$size" "$size"; done
        printf '\n\n[scalable/apps]\nSize=48\nType=Scalable\n'
        printf 'MinSize=8\nMaxSize=512\nContext=Applications\n'
        for size in $ICON_SIZES; do
            printf '\n[%sx%s/apps]\nSize=%s\nType=Fixed\nContext=Applications\n' \
                "$size" "$size" "$size"
        done
    } | write_file "${ICON_DATA}/hicolor/index.theme" 644
fi

MIMES="application/x-rar;application/vnd.rar;application/x-rar-compressed;\
application/zip;application/x-zip-compressed;application/x-7z-compressed;\
application/x-tar;application/gzip;application/x-gzip;application/x-bzip2;\
application/x-xz;application/x-compressed-tar;application/x-bzip-compressed-tar;\
application/x-xz-compressed-tar;application/x-cd-image;application/x-cab;\
application/x-lzma;application/zstd;"

write_file "$DESKTOP_FILE" 644 <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=LinRAR
GenericName=Archive Manager
Comment=Create and extract RAR, ZIP and 7z archives
Exec=${LAUNCHER} %F
TryExec=${LAUNCHER}
Icon=${APP_ID}
Terminal=false
StartupNotify=true
StartupWMClass=LinRAR
Categories=Utility;Archiving;Compression;FileTools;
MimeType=${MIMES}
Keywords=archive;rar;zip;7z;compress;extract;unpack;
Actions=ExtractHere;ExtractTo;Compress;Test;

[Desktop Action ExtractHere]
Name=Extract here
Icon=${APP_ID}
Exec=${LAUNCHER} --extract-here %F

[Desktop Action ExtractTo]
Name=Extract to...
Icon=${APP_ID}
Exec=${LAUNCHER} --extract-to %F

[Desktop Action Compress]
Name=Add to archive...
Icon=${APP_ID}
Exec=${LAUNCHER} --add %F

[Desktop Action Test]
Name=Test archive
Icon=${APP_ID}
Exec=${LAUNCHER} --test %F
EOF
ok "${DESKTOP_FILE}"

# ---------------------------------------------------------------- 6. menus

step "Adding right-click entries to file managers"

# -- KDE / Dolphin: a service menu with four actions --
for kde_dir in "${DATA_DIR}/kio/servicemenus" "${DATA_DIR}/kservices5/ServiceMenus"; do
    write_file "${kde_dir}/${APP_ID}.desktop" 755 <<EOF
[Desktop Entry]
Type=Service
ServiceTypes=KonqPopupMenu/Plugin
MimeType=${MIMES}inode/directory;
Actions=LinRARExtractHere;LinRARExtractTo;LinRARCompress;LinRARTest;LinRAROpen;
X-KDE-Priority=TopLevel
Icon=${APP_ID}
X-KDE-Submenu=LinRAR

[Desktop Action LinRAROpen]
Name=Open with LinRAR
Icon=${APP_ID}
Exec=${LAUNCHER} %F

[Desktop Action LinRARExtractHere]
Name=Extract here
Icon=${APP_ID}
Exec=${LAUNCHER} --extract-here %F

[Desktop Action LinRARExtractTo]
Name=Extract to...
Icon=${APP_ID}
Exec=${LAUNCHER} --extract-to %F

[Desktop Action LinRARCompress]
Name=Add to archive...
Icon=${APP_ID}
Exec=${LAUNCHER} --add %F

[Desktop Action LinRARTest]
Name=Test archive
Icon=${APP_ID}
Exec=${LAUNCHER} --test %F
EOF
done
ok "Dolphin (KDE) service menu"

# -- Nemo (Cinnamon): real top-level context menu actions --
nemo_action() {  # nemo_action <file> <label> <flag> <selection> <extensions>
    write_file "${DATA_DIR}/nemo/actions/$1" 644 <<EOF
[Nemo Action]
Name=$2
Comment=$2 with LinRAR
Exec=${LAUNCHER} $3 %F
Icon-Name=${APP_ID}
Selection=$4
Extensions=$5
Quote=double
EOF
}
if [ "$MODE" = "user" ] || [ -d /usr/share/nemo ]; then
    nemo_action "linrar-extract-here.nemo_action" "Extract here" \
        "--extract-here" "notnone" "rar;zip;7z;tar;gz;bz2;xz;tgz;iso;cab;"
    nemo_action "linrar-extract-to.nemo_action" "Extract to..." \
        "--extract-to" "notnone" "rar;zip;7z;tar;gz;bz2;xz;tgz;iso;cab;"
    nemo_action "linrar-compress.nemo_action" "Add to archive..." \
        "--add" "notnone" "any"
    ok "Nemo actions"
fi

# -- Nautilus / Nemo / Caja scripts: the portable fallback --
for scripts_dir in \
    "${DATA_DIR}/nautilus/scripts" \
    "${DATA_DIR}/nemo/scripts" \
    "${DATA_DIR}/caja/scripts"
do
    write_file "${scripts_dir}/LinRAR — Extract here" 755 <<EOF
#!/usr/bin/env bash
# Generated by LinRAR's installer.
IFS=\$'\n'
exec "${LAUNCHER}" --extract-here \$NAUTILUS_SCRIPT_SELECTED_FILE_PATHS \\
                                 \$NEMO_SCRIPT_SELECTED_FILE_PATHS \\
                                 \$CAJA_SCRIPT_SELECTED_FILE_PATHS
EOF
    write_file "${scripts_dir}/LinRAR — Extract to..." 755 <<EOF
#!/usr/bin/env bash
IFS=\$'\n'
exec "${LAUNCHER}" --extract-to \$NAUTILUS_SCRIPT_SELECTED_FILE_PATHS \\
                                \$NEMO_SCRIPT_SELECTED_FILE_PATHS \\
                                \$CAJA_SCRIPT_SELECTED_FILE_PATHS
EOF
    write_file "${scripts_dir}/LinRAR — Add to archive..." 755 <<EOF
#!/usr/bin/env bash
IFS=\$'\n'
exec "${LAUNCHER}" --add \$NAUTILUS_SCRIPT_SELECTED_FILE_PATHS \\
                         \$NEMO_SCRIPT_SELECTED_FILE_PATHS \\
                         \$CAJA_SCRIPT_SELECTED_FILE_PATHS
EOF
done
ok "Nautilus / Nemo / Caja scripts"

# -- Thunar (XFCE): merge into its custom-actions file --
THUNAR_UCA="${XDG_CONFIG_HOME:-$HOME/.config}/Thunar/uca.xml"
if [ "$MODE" = "user" ] && have python3; then
    if python3 - "$THUNAR_UCA" "$LAUNCHER" <<'PYEOF'
import os, shutil, sys, xml.etree.ElementTree as ET

path, launcher = sys.argv[1], sys.argv[2]
os.makedirs(os.path.dirname(path), exist_ok=True)
if os.path.exists(path):
    shutil.copy2(path, path + ".linrar-backup")
    try:
        tree = ET.parse(path)
        root = tree.getroot()
    except ET.ParseError:
        sys.exit(1)
else:
    root = ET.Element("actions")
    tree = ET.ElementTree(root)

ACTIONS = [
    ("LinRAR: Extract here", "--extract-here",
     "<archives>", "*.rar;*.zip;*.7z;*.tar;*.gz;*.bz2;*.xz;*.tgz;*.iso;*.cab"),
    ("LinRAR: Extract to...", "--extract-to",
     "<archives>", "*.rar;*.zip;*.7z;*.tar;*.gz;*.bz2;*.xz;*.tgz;*.iso;*.cab"),
    ("LinRAR: Add to archive...", "--add", "<any file>", "*"),
]
existing = {action.findtext("name", "") for action in root.findall("action")}
added = 0
for name, flag, description, patterns in ACTIONS:
    if name in existing:
        continue
    action = ET.SubElement(root, "action")
    for tag, text in (
        ("icon", "linrar"),
        ("name", name),
        ("unique-id", f"linrar-{flag.strip('-')}"),
        ("command", f'"{launcher}" {flag} %F'),
        ("description", description),
        ("patterns", patterns),
    ):
        ET.SubElement(action, tag).text = text
    for tag in ("directories", "audio-files", "image-files", "other-files",
                "text-files", "video-files"):
        ET.SubElement(action, tag)
    added += 1
if added:
    tree.write(path, encoding="UTF-8", xml_declaration=True)
PYEOF
    then
        record "$THUNAR_UCA"
        ok "Thunar custom actions (previous file backed up alongside it)"
    else
        warn "could not update Thunar's uca.xml — left untouched"
    fi
fi

# ---------------------------------------------------------------- 7. caches

step "Refreshing the desktop databases"
if have update-desktop-database; then
    if [ "$MODE" = "system" ]; then as_root update-desktop-database "$APPS_DIR" || true
    else update-desktop-database "$APPS_DIR" >/dev/null 2>&1 || true; fi
fi
if have gtk-update-icon-cache; then
    if [ "$MODE" = "system" ]; then
        as_root gtk-update-icon-cache -f -t "${DATA_DIR}/icons/hicolor" >/dev/null 2>&1 || true
    else
        gtk-update-icon-cache -f -t "${DATA_DIR}/icons/hicolor" >/dev/null 2>&1 || true
    fi
fi
if have xdg-mime && [ "$MODE" = "user" ]; then
    # Make LinRAR the default handler for the archive types it owns.
    IFS=';' read -r -a MIME_LIST <<< "$MIMES"
    for mime in "${MIME_LIST[@]}"; do
        [ -n "$mime" ] && xdg-mime default "${APP_ID}.desktop" "$mime" 2>/dev/null || true
    done
    ok "LinRAR is now the default archive handler (change it any time in your file manager)"
fi
if have kbuildsycoca6; then kbuildsycoca6 >/dev/null 2>&1 || true
elif have kbuildsycoca5; then kbuildsycoca5 >/dev/null 2>&1 || true; fi

mv "${MANIFEST}.tmp" "$MANIFEST"

# ---------------------------------------------------------------- 8. check

step "Checking that it actually runs"
# Through the launcher, from an unrelated directory, with the kind of bare
# environment the application menu hands a process — the same way the desktop
# will start it.  Testing the interpreter directly would miss anything the
# launcher itself gets wrong.
CHECK_OUT="$(cd / && env -i HOME="$HOME" PATH=/usr/bin:/bin \
    QT_QPA_PLATFORM=offscreen "$LAUNCHER" --version 2>&1)" && CHECK_OK=1 || CHECK_OK=0
if [ "$CHECK_OK" = "1" ]; then
    info "${CHECK_OUT}"
    if (cd / && env -i HOME="$HOME" PATH=/usr/bin:/bin \
            QT_QPA_PLATFORM=offscreen "$LAUNCHER" --self-test) >/dev/null 2>&1
    then
        ok "LinRAR starts from a clean environment and its window builds"
    else
        warn "LinRAR runs but the window failed to build — run 'linrar' to see why"
    fi
else
    printf '%s\n' "$CHECK_OUT" | tail -3 | while IFS= read -r line; do
        warn "$line"
    done
    case "$CHECK_OUT" in
        *libGL*)        warn "install your distro's OpenGL runtime (libgl1 / mesa-libGL)" ;;
        *xcb*)          warn "install the xcb-cursor library (libxcb-cursor0 / xcb-util-cursor)" ;;
        *PyQt6*)        warn "PyQt6 did not install; try: ${VENV}/bin/pip install PyQt6" ;;
    esac
    warn "LinRAR is installed but could not be started — fix the above and try 'linrar'"
fi

# ---------------------------------------------------------------- done

MISSING=""
for tool in unrar rar 7z 7zz zip; do
    have "$tool" || MISSING="${MISSING} ${tool}"
done
case "$MISSING" in
    *7z*7zz*) : ;;   # one of the two is enough
    *) MISSING="$(printf '%s' "$MISSING" | sed 's/ 7zz//; s/ 7z//')" ;;
esac

printf '\n%s%s is installed.%s\n\n' "$C_OK$C_BOLD" "$APP_NAME" "$C_OFF"
info "run it:            ${APP_ID}"
info "or from a menu:    Applications > Utility > LinRAR"
info "right-click a file: Extract here / Extract to... / Add to archive..."
if [ -n "$MISSING" ]; then
    printf '\n'
    warn "still missing:${MISSING}"
    warn "open LinRAR and use the highlighted Dependencies button on the toolbar"
fi
printf '\n%sto remove everything again: ./uninstall.sh%s\n\n' "$C_DIM" "$C_OFF"
