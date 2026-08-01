"""Fixture-based rule tests for the Semgrep policy manifest.

These tests exercise the PRODUCTION Semgrep configs (``.semgrep.yml`` plus the
``.semgrep-community-*.yml`` packs used by ``make semgrep``) against the
positive/negative fixtures registered in ``quality/semgrep-policy.toml``,
instead of the duplicate test-only ruleset that previously lived in
``tests/fixtures/semgrep/test-rules.yml`` (now deleted).

Three concerns are covered:

* **Parity** — every rule in ``.semgrep.yml`` is registered in the policy
  manifest with fixture references, and every referenced fixture exists.
* **Behaviour** — each rule's positive fixture must fire that rule and each
  negative fixture must not, when scanned with the production config set.
  Fixtures are copied into a temporary directory under ``build/`` (outside
  the ``tests/**`` paths the rules and the Makefile exclude) and scanned with
  ``--no-git-ignore`` so the git-ignored ``build/`` directory is included.
* **Exit semantics** — the scanner exit code is validated exactly: ``0`` when
  clean, ``1`` when findings are present, and a distinct non-zero code for
  tool errors. A non-zero exit is never accepted merely because stdout is
  non-empty.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tomllib
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = PROJECT_ROOT / "quality" / "semgrep-policy.toml"
SEMGREP_VERSION = "1.171.0"
SCAN_ROOT = PROJECT_ROOT / "build" / "semgrep-policy-scan"
SCAN_TIMEOUT = 120

# Configs are exactly the SEMGREP_CONFIGS the Makefile passes to ``make semgrep``.
PRODUCTION_CONFIGS = (
    ".semgrep.yml",
    ".semgrep-community-python.yml",
    ".semgrep-community-comment.yml",
    ".semgrep-community-best-practices.yml",
)

# Documented fixture defects, keyed by rule id. Behaviour tests for these
# rules are marked ``xfail`` with the defect explanation.
POSITIVE_FIXTURE_DEFECTS: dict[str, str] = {}
NEGATIVE_FIXTURE_DEFECTS: dict[str, str] = {}

_RULE_ID_LINE = re.compile(r"^\s+- id: ([a-zA-Z0-9._-]+)\s*$", re.MULTILINE)

# (scanner exit code, findings, rule id -> copied fixture path)
ScanResult = tuple[int, list[dict[str, Any]], dict[str, Path]]


def _semgrep_argv(*extra: str) -> list[str]:
    """Build the scanner argv using the same pinned invocation as the Makefile."""
    return ["uvx", "--from", f"semgrep=={SEMGREP_VERSION}", "semgrep", *extra]


def _load_policy_rules() -> list[dict[str, Any]]:
    """Load the rule entries from the canonical policy manifest."""
    with POLICY_PATH.open("rb") as handle:
        manifest = tomllib.load(handle)
    return list(manifest["rules"])


def _config_rule_ids(config: Path) -> set[str]:
    """Extract rule ids from a Semgrep YAML config without a YAML dependency."""
    text = config.read_text(encoding="utf-8")
    return set(_RULE_ID_LINE.findall(text))


def _copied_fixture_name(rule_id: str, kind: str) -> str:
    """Return the temp-file name used for a rule's copied fixture."""
    stem = re.sub(r"[^a-zA-Z0-9]", "_", rule_id)
    return f"{stem}_{kind}.py"


def _copy_fixtures(scan_dir: Path, kind: str) -> dict[str, Path]:
    """Copy every rule's <kind> fixture into scan_dir and map rule id to path.

    Fixtures live under ``tests/**`` which the production rules and the
    Makefile exclude, so the content is copied into a temporary directory
    outside those paths before scanning.
    """
    copied: dict[str, Path] = {}
    for rule in _load_policy_rules():
        source = PROJECT_ROOT / rule[f"{kind}_fixture"]
        target = scan_dir / _copied_fixture_name(rule["id"], kind)
        shutil.copyfile(source, target)
        copied[rule["id"]] = target
    return copied


def _run_scan(target: Path) -> subprocess.CompletedProcess[str]:
    """Run the production configs against target with strict exit semantics."""
    cmd = _semgrep_argv()
    for config in PRODUCTION_CONFIGS:
        cmd += ["--config", config]
    cmd += ["--json", "--quiet", "--metrics=off", "--error", "--no-git-ignore", str(target)]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        timeout=SCAN_TIMEOUT,
        check=False,
    )


def _parse_results(result: subprocess.CompletedProcess[str]) -> list[dict[str, Any]]:
    """Validate scanner exit semantics and return the findings.

    Only exit codes 0 (clean) and 1 (findings) are accepted; any other code is
    a tool error regardless of whether stdout is non-empty.
    """
    if result.returncode not in (0, 1):
        pytest.fail(
            f"semgrep tool error (exit {result.returncode}, not a findings exit): {result.stderr}"
        )
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        pytest.fail(f"semgrep produced invalid JSON: {exc}; stderr: {result.stderr}")
    return list(data.get("results", []))


def _attributed_outcomes(results: list[dict[str, Any]], copied: dict[str, Path]) -> dict[str, bool]:
    """Map rule id to whether the rule fired on its own copied fixture."""
    outcomes: dict[str, bool] = {}
    for rule_id, fixture_path in copied.items():
        outcomes[rule_id] = any(
            finding.get("check_id") == rule_id and _same_target(finding, fixture_path)
            for finding in results
        )
    return outcomes


def _same_target(finding: dict[str, Any], fixture_path: Path) -> bool:
    """Return whether a finding's path resolves to the given fixture file."""
    try:
        return Path(finding.get("path", "")).resolve() == fixture_path.resolve()
    except OSError:
        return str(fixture_path).endswith(str(finding.get("path", "")))


@pytest.fixture(scope="session")
def semgrep_available() -> None:
    """Probe the pinned scanner; skip scanner tests when it is unavailable."""
    try:
        probe = subprocess.run(
            _semgrep_argv("--version"),
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        pytest.skip(f"semgrep unavailable locally: {exc}")
    if probe.returncode != 0:
        pytest.skip(f"semgrep unavailable locally: {probe.stderr.strip()}")


@pytest.fixture(scope="session")
def scan_dir() -> Path:
    """Create a throwaway scan directory under build/ and clean it up."""
    shutil.rmtree(SCAN_ROOT, ignore_errors=True)
    SCAN_ROOT.mkdir(parents=True, exist_ok=True)
    yield SCAN_ROOT
    shutil.rmtree(SCAN_ROOT, ignore_errors=True)


@pytest.fixture(scope="session")
def positive_scan(semgrep_available: None, scan_dir: Path) -> ScanResult:
    """Scan every positive fixture against the production configs in one pass."""
    copied = _copy_fixtures(scan_dir, "positive")
    result = _run_scan(scan_dir)
    return result.returncode, _parse_results(result), copied


@pytest.fixture(scope="session")
def negative_scan(semgrep_available: None, scan_dir: Path) -> ScanResult:
    """Scan every negative fixture against the production configs in one pass."""
    copied = _copy_fixtures(scan_dir, "negative")
    result = _run_scan(scan_dir)
    return result.returncode, _parse_results(result), copied


class TestPolicyParity:
    """Rule/config/manifest/fixture parity checks (no scanner required)."""

    def test_production_configs_exist(self) -> None:
        """The production configs used by ``make semgrep`` all exist."""
        for config in PRODUCTION_CONFIGS:
            assert (PROJECT_ROOT / config).is_file(), f"Production config missing: {config}"

    def test_policy_matches_production_config(self) -> None:
        """Every rule in .semgrep.yml is registered in the policy manifest."""
        manifest_ids = {rule["id"] for rule in _load_policy_rules()}
        production_ids = _config_rule_ids(PROJECT_ROOT / ".semgrep.yml")
        assert manifest_ids == production_ids, (
            "Rule inventory drift: "
            f"policy-only={sorted(manifest_ids - production_ids)} "
            f"config-only={sorted(production_ids - manifest_ids)}"
        )

    def test_every_rule_has_fixture_references(self) -> None:
        """Every policy rule declares a positive and negative fixture."""
        for rule in _load_policy_rules():
            assert rule.get("positive_fixture"), f"{rule['id']} lacks a positive fixture"
            assert rule.get("negative_fixture"), f"{rule['id']} lacks a negative fixture"

    def test_every_referenced_fixture_exists(self) -> None:
        """Every fixture referenced by the policy manifest exists on disk."""
        for rule in _load_policy_rules():
            for kind in ("positive_fixture", "negative_fixture"):
                fixture = PROJECT_ROOT / rule[kind]
                assert fixture.is_file(), f"{rule['id']} references missing fixture {rule[kind]}"

    def test_policy_source_configs_exist(self) -> None:
        """Every rule's source config is present in the repository."""
        for rule in _load_policy_rules():
            source = PROJECT_ROOT / rule["source"]
            assert source.is_file(), f"{rule['id']} references missing source {rule['source']}"

    def test_no_duplicate_rule_ids(self) -> None:
        """The policy manifest contains no duplicate rule ids."""
        rule_ids = [rule["id"] for rule in _load_policy_rules()]
        assert len(rule_ids) == len(set(rule_ids)), "Duplicate rule id in policy manifest"


class TestFixtureBehaviour:
    """Positive/negative fixture behaviour against the production configs."""

    @pytest.mark.parametrize("rule_id", [rule["id"] for rule in _load_policy_rules()])
    def test_positive_fixture_matches(self, rule_id: str, positive_scan: ScanResult) -> None:
        """Each rule's positive fixture fires that rule under production configs."""
        returncode, results, copied = positive_scan
        if rule_id in POSITIVE_FIXTURE_DEFECTS:
            pytest.xfail(POSITIVE_FIXTURE_DEFECTS[rule_id])
        outcomes = _attributed_outcomes(results, copied)
        assert returncode == 1, "Production scan over positive fixtures found no findings"
        assert outcomes[rule_id], (
            f"Rule {rule_id} did not fire on its positive fixture {copied[rule_id].name}"
        )

    @pytest.mark.parametrize("rule_id", [rule["id"] for rule in _load_policy_rules()])
    def test_negative_fixture_does_not_match(self, rule_id: str, negative_scan: ScanResult) -> None:
        """Each rule's negative fixture must not fire that rule under production configs."""
        _, results, copied = negative_scan
        if rule_id in NEGATIVE_FIXTURE_DEFECTS:
            pytest.xfail(NEGATIVE_FIXTURE_DEFECTS[rule_id])
        outcomes = _attributed_outcomes(results, copied)
        assert not outcomes[rule_id], (
            f"Rule {rule_id} fired on its negative fixture {copied[rule_id].name}"
        )


class TestScannerExitSemantics:
    """Exact scanner exit-code semantics: 0 clean, 1 findings, distinct failure."""

    def test_clean_target_exits_zero(self, semgrep_available: None, scan_dir: Path) -> None:
        """A finding-free target makes the scanner exit 0 with no results."""
        clean_file = scan_dir / "clean.py"
        clean_file.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
        result = _run_scan(clean_file)
        assert result.returncode == 0, f"expected clean exit 0: {result.stderr}"
        assert _parse_results(result) == []

    def test_findings_target_exits_one(self, positive_scan: ScanResult) -> None:
        """A target with findings makes the scanner exit 1, not 0."""
        returncode, results, _ = positive_scan
        assert results, "positive fixtures batch produced no findings"
        assert returncode == 1, "expected findings exit 1 from the positive fixtures batch"

    def test_tool_error_has_distinct_exit(self, semgrep_available: None, scan_dir: Path) -> None:
        """A tool error exits with a distinct code, even when stdout is non-empty.

        Regression guard for the old behaviour that accepted any non-zero exit
        merely because stdout was non-empty, which masked scanner failures.
        """
        bogus_config = PROJECT_ROOT / "build" / "no-such-config.yml"
        cmd = [
            *_semgrep_argv(),
            "--config",
            str(bogus_config),
            "--json",
            "--quiet",
            "--metrics=off",
            "--error",
            str(scan_dir),
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
            timeout=SCAN_TIMEOUT,
            check=False,
        )
        assert result.returncode not in (0, 1), (
            f"tool error must exit a distinct code, got {result.returncode}"
        )
        assert result.returncode != 0, "tool error must not be reported as clean"
