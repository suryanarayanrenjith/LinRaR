#!/usr/bin/env bash
# Launch LinRAR for Linux from its virtual environment.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"

# The application itself refuses to start anywhere but Linux; saying so here
# too means the message arrives before the Python stack has to load at all.
KERNEL="$(uname -s 2>/dev/null || echo unknown)"
if [ "$KERNEL" != "Linux" ]; then
    printf 'LinRAR for Linux does not run on %s.\n' "$KERNEL" >&2
    printf 'On Windows use WinRAR or 7-Zip; on macOS use Keka.\n' >&2
    exit 1
fi

[ -x .venv/bin/python ] || {
    printf 'No .venv here yet, run ./install.sh first.\n' >&2
    exit 1
}
exec .venv/bin/python -m linrar "$@"
