#!/usr/bin/env bash
# Secret detection for pre-push and CI.
#
# Pre-push stdin is the format documented by githooks(5):
#   <local-ref> <local-oid> <remote-ref> <remote-oid>
#
# Exit codes are 0 for clean, 10 for findings, and another non-zero value for
# input, Git, configuration, or scanner errors.

set -u

readonly REQUIRED_GITLEAKS_VERSION="8.30.1"

_die() {
    echo "gitleaks_check: ERROR: $*" >&2
    exit 3
}

_require_gitleaks() {
    command -v gitleaks &>/dev/null || _die "gitleaks is required but not installed"
}

_check_version() {
    local raw_version version
    raw_version="$(gitleaks version 2>/dev/null)" || _die "failed to run 'gitleaks version'"

    version="$raw_version"
    version="${version#"${version%%[!$' \t\r\n']*}"}"
    version="${version%"${version##*[!$' \t\r\n']}"}"
    version="${version#v}"
    if [[ "$version" != "$REQUIRED_GITLEAKS_VERSION" ]]; then
        _die "unsupported gitleaks version '$version' (requires exactly $REQUIRED_GITLEAKS_VERSION)"
    fi
}

_load_object_format_length() {
    local output_name="$1" object_format
    local -n output="$output_name"
    object_format="$(git rev-parse --show-object-format 2>/dev/null)" || {
        _die "unable to determine Git object format"
    }
    case "$object_format" in
        sha1) output=40 ;;
        sha256) output=64 ;;
        *) _die "unsupported Git object format '$object_format'" ;;
    esac
}

_validate_oid() {
    local oid="$1" label="$2" expected_length="$3"
    if [[ ${#oid} -ne $expected_length || ! "$oid" =~ ^[0-9a-fA-F]+$ ]]; then
        _die "malformed $label OID (expected $expected_length hexadecimal characters)"
    fi
}

_is_zero_oid() {
    local oid="$1"
    [[ "$oid" =~ ^0+$ ]]
}

_require_object() {
    local oid="$1" label="$2"
    git cat-file -e "$oid^{object}" 2>/dev/null || {
        _die "$label object $oid is unavailable locally"
    }
}

_load_commit_oid() {
    local output_name="$1" oid="$2" label="$3"
    local -n output="$output_name"
    _require_object "$oid" "$label"
    output="$(git rev-parse --verify "$oid^{commit}" 2>/dev/null)" || {
        _die "$label object $oid does not peel to a commit"
    }
}

_load_remote_query_target() {
    local output_name="$1" requested="$2" location="$3" configured
    local -n output="$output_name"
    [[ -n "$requested" && "$requested" != *$'\n'* ]] || _die "invalid remote destination"
    [[ -n "$location" && "$location" != *$'\n'* ]] || _die "invalid remote destination"
    while IFS= read -r configured; do
        if [[ "$configured" == "$requested" ]]; then
            [[ "$requested" != -* ]] || _die "configured remote name must not begin with '-'"
            output="$requested"
            return 0
        fi
    done < <(git remote 2>/dev/null) || _die "unable to enumerate configured remotes"
    output="$location"
}

_load_advertised_remote_commits() {
    local output_name="$1" query_target="$2" expected_length="$3" advertisement
    local advertised_oid advertised_ref extra commit
    local _raw_commits=""

    advertisement="$(git ls-remote -- "$query_target" 2>/dev/null)" || {
        _die "failed to query advertised remote refs"
    }
    [[ -n "$advertisement" ]] || _die "remote unexpectedly advertised no refs"

    while read -r advertised_oid advertised_ref extra; do
        [[ -n "$advertised_oid" && -n "$advertised_ref" && -z "${extra:-}" ]] || {
            _die "remote returned a malformed advertised ref"
        }
        _validate_oid "$advertised_oid" "advertised remote" "$expected_length"
        _load_commit_oid commit "$advertised_oid" "advertised remote"
        _raw_commits+="$commit"$'\n'
    done <<< "$advertisement"

    local _deduped
    _deduped="$(printf '%s' "$_raw_commits" | sort -u)"
    [[ -n "$_deduped" ]] || _die "remote advertised no usable commit refs"
    local _arr=()
    while IFS= read -r commit; do
        _arr+=("$commit")
    done <<< "$_deduped"
    eval "$output_name=(\"\${_arr[@]}\")"
}

_append_reachable_difference() {
    local output_name="$1"
    shift
    local reachable_commits

    reachable_commits="$(git rev-list "$@" 2>/dev/null)" || {
        _die "unable to establish commit reachability"
    }
    if [[ -n "$reachable_commits" ]]; then
        local _existing
        eval "_existing=(\"\${${output_name}[@]:-}\")"
        local _commit
        while IFS= read -r _commit; do
            _existing+=("$_commit")
        done <<< "$reachable_commits"
        local _deduped
        _deduped="$(printf '%s\n' "${_existing[@]}" | sort -u)"
        local _arr=()
        while IFS= read -r _commit; do
            [[ -n "$_commit" ]] && _arr+=("$_commit")
        done <<< "$_deduped"
        eval "$output_name=(\"\${_arr[@]}\")"
    fi
}

_scan_exact_commits() {
    local -a exact_commits=("$@")
    local log_opts="--no-walk=unsorted --diff-merges=first-parent"
    local commit

    for commit in "${exact_commits[@]}"; do
        log_opts+=" $commit"
    done
    echo "gitleaks: scanning exact union of ${#exact_commits[@]} commit(s)"
    gitleaks git --verbose --redact --exit-code 10 --log-opts="$log_opts"
}

_pre_push_scan() {
    local remote_arg="$1" remote_location="$2" expected_length remote_query_target=""
    local local_ref local_oid remote_ref remote_oid extra local_commit remote_commit
    local row_count=0
    local -a commits=()
    local -a advertised_commits=()
    local advertisements_loaded=false

    _load_object_format_length expected_length

    while read -r local_ref local_oid remote_ref remote_oid extra; do
        [[ -n "$local_ref" && -n "$local_oid" && -n "$remote_ref" && -n "$remote_oid" && -z "${extra:-}" ]] || {
            _die "malformed pre-push row (expected: local-ref local-oid remote-ref remote-oid)"
        }
        row_count=$((row_count + 1))
        _validate_oid "$local_oid" "local" "$expected_length"
        _validate_oid "$remote_oid" "remote" "$expected_length"

        if _is_zero_oid "$local_oid"; then
            if ! _is_zero_oid "$remote_oid"; then
                _require_object "$remote_oid" "remote"
            fi
            echo "gitleaks: skipping deleted ref $remote_ref"
            continue
        fi

        _load_commit_oid local_commit "$local_oid" "local"
        if ! _is_zero_oid "$remote_oid"; then
            _load_commit_oid remote_commit "$remote_oid" "remote"
            echo "gitleaks: existing ref $local_ref"
            _append_reachable_difference commits "$local_commit" --not "$remote_commit"
            continue
        fi

        echo "gitleaks: new ref $local_ref"
        if [[ "$advertisements_loaded" == false ]]; then
            _load_remote_query_target remote_query_target "$remote_arg" "$remote_location"
            _load_advertised_remote_commits advertised_commits "$remote_query_target" "$expected_length"
            advertisements_loaded=true
        fi
        _append_reachable_difference commits "$local_commit" --not "${advertised_commits[@]}"
    done

    if [[ $row_count -eq 0 ]]; then
        echo "gitleaks: no refs received on stdin"
        return 0
    fi
    if [[ ${#commits[@]} -eq 0 ]]; then
        echo "gitleaks: no commits to scan"
        return 0
    fi
    _scan_exact_commits "${commits[@]}"
}

_scan_range() {
    local range="$1"
    echo "gitleaks: scanning commits in range '$range'"
    gitleaks git --verbose --redact --exit-code 10 --log-opts="$range"
}

_ci_full_scan() {
    echo "gitleaks: CI full-history scan"
    gitleaks detect --source . --verbose --redact --exit-code 10
}

_range_scan_cmd() {
    local old_ref="$1" new_ref="$2"
    git rev-parse --verify "$old_ref^{commit}" &>/dev/null || _die "invalid old ref: $old_ref"
    git rev-parse --verify "$new_ref^{commit}" &>/dev/null || _die "invalid new ref: $new_ref"
    _scan_range "$old_ref..$new_ref"
}

_local_range_scan() {
    local branch range base
    branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null)" || _die "unable to resolve HEAD"
    if [[ "$branch" == "HEAD" ]]; then
        range="HEAD"
    elif git rev-parse --verify "origin/$branch" &>/dev/null; then
        range="origin/$branch..HEAD"
    else
        base="origin/main"
        git rev-parse --verify "$base" &>/dev/null || base="origin/master"
        if git rev-parse --verify "$base" &>/dev/null; then
            range="$base..HEAD"
        else
            range="HEAD"
        fi
    fi
    _scan_range "$range"
}

main() {
    git rev-parse --git-dir &>/dev/null || _die "not a git repository"
    local mode="${1:-}"
    [[ $# -eq 0 ]] || shift

    case "$mode" in
        pre-push)
            [[ $# -eq 2 && -n "$1" && -n "$2" ]] || {
                _die "usage: $0 pre-push REMOTE_NAME REMOTE_URL"
            }
            _require_gitleaks
            _check_version
            _pre_push_scan "$1" "$2"
            ;;
        ci-full)
            [[ $# -eq 0 ]] || _die "usage: $0 ci-full"
            _require_gitleaks
            _check_version
            _ci_full_scan
            ;;
        range)
            [[ $# -eq 2 && -n "$1" && -n "$2" ]] || _die "usage: $0 range OLD NEW"
            _require_gitleaks
            _check_version
            _range_scan_cmd "$1" "$2"
            ;;
        "")
            _require_gitleaks
            _check_version
            if [[ "${CI_NO_SKIP:-}" == "1" || "${CI_NO_SKIP:-}" == "true" ]]; then
                _ci_full_scan
            elif [[ ! -t 0 ]]; then
                _pre_push_scan "origin" "origin"
            else
                _local_range_scan
            fi
            ;;
        *) _die "unknown mode '$mode' (expected: pre-push, ci-full, or range)" ;;
    esac
}

main "$@"
