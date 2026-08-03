#!/usr/bin/env bash
# LinRAR: build the artifacts a release is made of.
#
#     tools/package.sh                 -> dist/linrar-2.1.0.tar.gz
#                                         dist/SHA256SUMS
#
# The tarball is the project as it is installed: unpack it anywhere and run
# ./install.sh, exactly as with a clone.  What a clone does *not* have is
# linrar/_build.py, the stamp written below — it records which commit this copy
# was cut from, and it is how an installed LinRAR can tell "the published
# 2.1.0" from "somebody's working tree that calls itself 2.1.0".
#
# The build is reproducible: same commit in, byte-identical tarball out.  File
# order, ownership and every timestamp are pinned, so the checksum a user
# verifies is one anybody can reproduce rather than one they have to trust.
#
# Nothing is published from here.  This script only ever writes inside dist/,
# and .github/workflows/release.yml is what uploads what it produced.

set -euo pipefail

ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
cd "$ROOT"

DIST="${DIST:-${ROOT}/dist}"
KEEP_STAGING=0

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
LinRAR release packager

  tools/package.sh [options]

  --dist DIR      where to write the artifacts (default: dist/)
  --keep-staging  leave the unpacked tree beside the tarball
  -h, --help      this text

Environment: DIST overrides --dist; SOURCE_DATE_EPOCH pins every timestamp in
the tarball (default: the commit's own date).
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --dist)         DIST="${2:?--dist needs a directory}"; shift 2 ;;
        --keep-staging) KEEP_STAGING=1; shift ;;
        -h|--help)      usage; exit 0 ;;
        *)              usage >&2; die "unknown option: $1" ;;
    esac
done

command -v git >/dev/null 2>&1 || die "git is needed to know what to package"
command -v python3 >/dev/null 2>&1 || die "python3 is needed to read the version"
git rev-parse --is-inside-work-tree >/dev/null 2>&1 ||
    die "not a git checkout; the artifact is built from the tracked files"

# ------------------------------------------------------------------ what

step "Working out what to build"

VERSION="$(python3 "${ROOT}/tools/release.py" current)" ||
    die "could not read the version; run tools/release.py check"
NAME="linrar-${VERSION}"
TARBALL="${DIST}/${NAME}.tar.gz"

COMMIT="$(git rev-parse HEAD 2>/dev/null || echo "")"
[ -n "$COMMIT" ] || die "no commit to build from"
TAG="v${VERSION}"

# Every timestamp in the tarball, so the same commit always produces the same
# bytes.  The commit's own date is the natural choice: it is a property of what
# is being packaged rather than of when somebody happened to run this.
if [ -z "${SOURCE_DATE_EPOCH:-}" ]; then
    SOURCE_DATE_EPOCH="$(git log -1 --pretty=%ct 2>/dev/null || date +%s)"
fi
export SOURCE_DATE_EPOCH
BUILD_DATE="$(date -u -d "@${SOURCE_DATE_EPOCH}" '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null ||
              date -u -r "${SOURCE_DATE_EPOCH}" '+%Y-%m-%dT%H:%M:%SZ')"

info "version    ${VERSION}"
info "commit     ${COMMIT}"
info "timestamp  ${BUILD_DATE}"

if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
    warn "the working tree has uncommitted changes"
    warn "they go into the tarball, but the stamp will name ${COMMIT} — do not publish this"
fi

# ------------------------------------------------------------- 1. staging

step "Staging the tracked files"

STAGING="${DIST}/${NAME}"
rm -rf "$STAGING"
mkdir -p "$STAGING"

# Tracked files only, so nothing untracked (a venv, a receipt, scratch
# archives, __pycache__) can ever be shipped by accident.  -z and read -d
# survive a file name with a space or a newline in it.
COUNT=0
while IFS= read -r -d '' file; do
    mkdir -p "${STAGING}/$(dirname "$file")"
    cp -p "$file" "${STAGING}/${file}"
    COUNT=$((COUNT + 1))
done < <(git ls-files -z)
[ "$COUNT" -gt 0 ] || die "git ls-files listed nothing to package"
ok "${COUNT} files"

# --------------------------------------------------------------- 2. stamp

step "Stamping the build"

cat > "${STAGING}/linrar/_build.py" <<EOF
"""Which build this copy is — written by tools/package.sh, never committed.

A source checkout does not have this file, and linrar/version.py treats its
absence as the ordinary case: that is precisely how "a published release" and
"a working tree with the same version number" tell themselves apart.
"""

BUILD = {
    "commit": "${COMMIT}",
    "date": "${BUILD_DATE}",
    "tag": "${TAG}",
    "version": "${VERSION}",
}
EOF
ok "linrar/_build.py  ${COMMIT}"

# The release's own inventory: every file it installs, relative to the project
# folder.  The updater reads the *installed* copy of this to know exactly which
# files the version it is replacing put on disk, and so which of them to delete
# -- without it there is no way to tell a file left over from the last release
# from one the user keeps in the folder themselves.  It lists itself, because
# it is one of the files a release installs.
INVENTORY="${STAGING}/linrar/_files.txt"
{
    printf '# Files installed by LinRAR %s.  Written by tools/package.sh.\n' \
        "$VERSION"
    printf '# The updater uses this to remove what a new release no longer ships.\n'
} > "$INVENTORY"
( cd "$STAGING" && find . -type f -printf '%P\n' | LC_ALL=C sort ) >> "$INVENTORY"
ok "linrar/_files.txt  $(( $(wc -l < "$INVENTORY") - 2 )) files"

# -------------------------------------------------------------- 3. tarball

step "Building ${NAME}.tar.gz"

# Reproducibility: a fixed file order, no ownership, one timestamp, and gzip
# without its own timestamp header (-n).  Without --sort the order comes from
# the filesystem and differs between machines.
TAR_FLAGS="--owner=0 --group=0 --numeric-owner --mtime=@${SOURCE_DATE_EPOCH}"
if tar --version 2>/dev/null | head -1 | grep -qi 'GNU tar'; then
    TAR_FLAGS="--sort=name ${TAR_FLAGS} --pax-option=exthdr.name=%d/PaxHeaders/%f,delete=atime,delete=ctime"
else
    warn "not GNU tar: the tarball will be correct but not bit-reproducible"
fi

# shellcheck disable=SC2086  # the flags are ours and are meant to split
tar $TAR_FLAGS -C "$DIST" -cf - "$NAME" | gzip -9 -n > "$TARBALL"
ok "$(cd "$DIST" && du -h "${NAME}.tar.gz" | cut -f1)  ${TARBALL}"

# ------------------------------------------------------------- 4. checksums

step "Checksums"

if command -v sha256sum >/dev/null 2>&1; then
    (cd "$DIST" && sha256sum "${NAME}.tar.gz" > SHA256SUMS)
elif command -v shasum >/dev/null 2>&1; then
    (cd "$DIST" && shasum -a 256 "${NAME}.tar.gz" > SHA256SUMS)
else
    die "no sha256sum or shasum; a release without checksums is not a release"
fi
info "$(cat "${DIST}/SHA256SUMS")"
ok "${DIST}/SHA256SUMS"

# ---------------------------------------------------------------- 5. proof

step "Checking the artifact"

# Unpack what was just written, somewhere unrelated, and ask it its version.
# A tarball that cannot answer that is one nobody should be offered: this
# catches a truncated archive, a lost file and a stamp that did not take,
# before the thing is published rather than after.
PROOF="$(mktemp -d)"
trap 'rm -rf "$PROOF"' EXIT

tar -xzf "$TARBALL" -C "$PROOF" || die "the tarball does not unpack"
UNPACKED="${PROOF}/${NAME}"

[ -f "${UNPACKED}/install.sh" ] || die "install.sh is missing from the tarball"
[ -x "${UNPACKED}/install.sh" ] || die "install.sh is not executable in the tarball"
[ -f "${UNPACKED}/linrar/_build.py" ] || die "the build stamp did not survive"
[ ! -e "${UNPACKED}/.venv" ] || die "a virtual environment got into the tarball"

REPORTED="$(cd "$UNPACKED" && python3 -c 'import linrar; print(linrar.__version__)')"
[ "$REPORTED" = "$VERSION" ] ||
    die "the tarball reports ${REPORTED}, not ${VERSION}"
CHANNEL="$(cd "$UNPACKED" && python3 -c 'from linrar import version; print(version.channel())')"
[ "$CHANNEL" != "source" ] ||
    die "the tarball still thinks it is a source checkout; the stamp is not being read"

ok "unpacks, imports, and reports ${REPORTED} (${CHANNEL})"

if [ "$KEEP_STAGING" = "0" ]; then
    rm -rf "$STAGING"
fi

printf '\n%sPackaged LinRAR %s%s  %s%s%s\n' \
    "$C_BOLD" "$VERSION" "$C_OFF" "$C_DIM" "$DIST" "$C_OFF"
