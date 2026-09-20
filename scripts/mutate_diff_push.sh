#!/usr/bin/env bash
# Resolve diff refs for the pre-push mutation gate and delegate to make.
#
# CI provides BASE_SHA/TESTED_SHA explicitly. A local push has no such
# environment, so fall back to the upstream tracking branch tip (or
# origin/master) versus HEAD. Existing environment values always win.
set -euo pipefail

resolve_default_base() {
    local upstream
    upstream="$(git rev-parse --abbrev-ref --symbolic-full-name '@{push}' 2>/dev/null || true)"
    if [[ -n "${upstream}" ]]; then
        git rev-parse "${upstream}" 2>/dev/null && return 0
    fi
    git rev-parse origin/master 2>/dev/null
}

export BASE_SHA="${BASE_SHA:-$(resolve_default_base)}"
export TESTED_SHA="${TESTED_SHA:-$(git rev-parse HEAD)}"

exec make mutate-diff
