#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Thin wrapper that delegates the installed-wheel smoke test to the
# platform-neutral Python implementation (scripts/smoke_test.py).
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."
export UV_OFFLINE=1
exec uv run python scripts/smoke_test.py "$@"
