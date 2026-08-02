#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Thin wrapper that delegates the installed-wheel smoke test to the
# platform-neutral Python implementation (scripts/smoke_test.py).
#
# Note: UV_OFFLINE is intentionally NOT exported here. `uv run` must be able
# to sync the project environment on cold-cache CI runners; smoke_test.py
# itself attempts offline installs first and falls back to the network.
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."
exec uv run python scripts/smoke_test.py "$@"
