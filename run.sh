#!/usr/bin/env bash
# Launch LinRAR for Linux from its virtual environment.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
exec .venv/bin/python -m linrar "$@"
