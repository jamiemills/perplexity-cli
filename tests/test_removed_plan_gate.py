from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
_GIT_BIN = shutil.which("git")

_DELETED_MECHANISM_KEYWORDS = (
    "plan-compliance-gate",
    "check-plan-gate",
    "quality-plan-reviewer",
    "check_plan_compliance",
    "generate_quality_plan",
)


def _tracked_non_dotclaude_files() -> list[str]:
    assert _GIT_BIN is not None, "git binary not found on PATH"
    result = subprocess.run(
        [_GIT_BIN, "ls-files", "-z", "--", ":/"],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        check=False,
    )
    assert result.returncode == 0, f"git ls-files failed:\n{result.stdout}{result.stderr}"
    all_files = result.stdout.split("\0")
    return [
        f
        for f in all_files
        if f and not f.startswith(".claude/") and not f.startswith("tests/test_removed_plan_gate")
    ]


def _grep_references(files: list[str]) -> dict[str, list[str]]:
    hits: dict[str, list[str]] = {}
    for filepath in files:
        full_path = PROJECT_ROOT / filepath
        try:
            text = full_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for keyword in _DELETED_MECHANISM_KEYWORDS:
            if keyword in text:
                hits.setdefault(keyword, []).append(filepath)
    return hits


@pytest.mark.skipif(_GIT_BIN is None, reason="git not installed")
def test_no_plan_compliance_gate_in_opencode_jsonc() -> None:
    config_path = PROJECT_ROOT / "opencode.jsonc"
    assert config_path.exists(), "opencode.jsonc is missing"
    content = config_path.read_text()

    assert "plan-compliance-gate" not in content, (
        "opencode.jsonc still references 'plan-compliance-gate'. "
        "Remove the plugin entry and its comment from the configuration."
    )


@pytest.mark.skipif(_GIT_BIN is None, reason="git not installed")
def test_no_plan_gate_in_opencode_package_json() -> None:
    pkg_path = PROJECT_ROOT / ".opencode" / "package.json"
    assert pkg_path.exists(), ".opencode/package.json is missing"
    data = json.loads(pkg_path.read_text())

    scripts = data.get("scripts", {})
    failures: list[str] = []

    if "check:plan-gate" in scripts:
        failures.append("'check:plan-gate' script still present")
    if "plan-compliance" in json.dumps(scripts):
        failures.append("'plan-compliance' reference found in scripts block")

    assert not failures, (
        ".opencode/package.json still references plan-gate mechanisms:\n"
        + "\n".join(f"  - {f}" for f in failures)
    )


@pytest.mark.skipif(_GIT_BIN is None, reason="git not installed")
def test_no_tracked_file_references_deleted_plan_gate() -> None:
    tracked = _tracked_non_dotclaude_files()
    hits = _grep_references(tracked)

    if not hits:
        return

    lines: list[str] = []
    for keyword, files in sorted(hits.items()):
        lines.append(f"  '{keyword}':")
        for f in sorted(files):
            lines.append(f"    {f}")

    assert False, (
        "Tracked non-.claude files still reference deleted plan-gate mechanism:\n"
        + "\n".join(lines)
        + "\n\n"
        "These references must be removed by the coordinator before this test can pass. "
        "Protected files (Makefile, lefthook.yml, opencode.jsonc, .opencode/package.json, "
        "pyproject.toml) should be cleaned in separate coordinated commits."
    )
