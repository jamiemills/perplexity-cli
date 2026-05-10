#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Installed-package smoke test.
#
# Installs the newest wheel from dist/ into an isolated venv and verifies
# that the CLI entry-point, config subsystem, and packaged resources all
# work correctly.
# ---------------------------------------------------------------------------
set -euo pipefail

TMP_ROOT=$(mktemp -d)
VENV_DIR="$TMP_ROOT/venv"
CONFIG_DIR="$TMP_ROOT/config"

cleanup() {
    rm -rf "$TMP_ROOT"
}
trap cleanup EXIT

WHEEL_PATH=$(ls dist/pxcli-*.whl 2>/dev/null | sort | tail -n 1)
if [ -z "$WHEEL_PATH" ]; then
    echo "No built wheel found in dist/" >&2
    exit 1
fi

uv venv "$VENV_DIR" >/dev/null
uv pip install --python "$VENV_DIR/bin/python" "$WHEEL_PATH" >/dev/null

export PERPLEXITY_CONFIG_DIR="$CONFIG_DIR"

"$VENV_DIR/bin/pxcli" --version >/dev/null
"$VENV_DIR/bin/pxcli" config show >/dev/null

QUERY_ENDPOINT=$(
    "$VENV_DIR/bin/python" -c \
        "from perplexity_cli.utils.config import get_query_endpoint; print(get_query_endpoint())"
)

if [ -z "$QUERY_ENDPOINT" ]; then
    echo "Installed-package smoke test failed: empty query endpoint" >&2
    exit 1
fi

if [ ! -f "$CONFIG_DIR/urls.json" ]; then
    echo "Installed-package smoke test failed: urls.json was not created in isolated config" >&2
    exit 1
fi

echo "Installed-package smoke test passed"
