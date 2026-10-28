#!/bin/sh
# gis-agent-bridges quickstart wrapper for macOS/Linux.
# Usage: ./scripts/quickstart.sh --package qgis --selftest
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
if command -v python3 >/dev/null 2>&1; then
  exec python3 "$ROOT/scripts/quickstart.py" "$@"
fi
exec python "$ROOT/scripts/quickstart.py" "$@"
