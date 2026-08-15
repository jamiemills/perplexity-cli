"""Tests for canonical mutation classification and report contracts."""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from scripts import mutation_policy as policy
from scripts.mutation_evidence import EvidenceDisagreements, MutationSelection

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = PROJECT_ROOT / "quality" / "schemas" / "mutation-report.json"
KEY_ONE = "perplexity_cli.example.x_run__mutmut_1"
KEY_TWO = "perplexity_cli.example.x_run__mutmut_2"
SHA = "a" * 40
DIGEST = "b" * 64
NO_DISAGREEMENTS = EvidenceDisagreements()


def _environment() -> policy.EnvironmentIdentity:
    return policy.EnvironmentIdentity(
        python_implementation="CPython",
        python_version="3.12.11",
        python_cache_tag="cpython-312",
        platform="linux-x86_64",
        uv_version="0.8.10",
        installed_distributions_digest=DIGEST,
        mutmut_distribution_digest=DIGEST,
        mutmut_record_digest=DIGEST,
        locked_wheel_filename="mutmut-3.5.0-py3-none-any.whl",
        locked_wheel_sha256="f19f2dd2e977eb9dc17255d8cb11e24fbfc3191620fba3108cac25779c9d78c9",
    )


def _context(
    selection: MutationSelection | None = None,
    *,
    current: bool = True,
    run_outcome: policy.RunOutcome = "completed",
) -> policy.ReportContext:
    provenance = policy.Provenance(SHA, SHA, DIGEST, current)
    return policy.ReportContext(
        "3.5.0", selection or MutationSelection("full"), provenance, _environment(), run_outcome
    )


def _line(key: str, status: str) -> str:
    return f"    {key}: {status}\n"


def _run(
    results_text: str,
    generated: tuple[str, ...] = (KEY_ONE,),
    context: policy.ReportContext | None = None,
    disagreements: EvidenceDisagreements = NO_DISAGREEMENTS,
) -> policy.MutationReport:
    entries = policy.parse_results_text(results_text)
    return policy.build_report(context or _context(), generated, entries, disagreements)


def test_all_raw_statuses_remain_distinct() -> None:
    statuses = {
        "killed": "killed",
        "survived": "survived",
        "timeout": "timeout",
        "suspicious": "suspicious",
        "no tests": "no_tests",
        "skipped": "skipped",
        "not checked": "not_checked",
        "check was interrupted by user": "interrupted",
        "segfault": "segfault",
        "caught by type check": "caught_by_type_check",
        "teleported": "unknown",
    }
    for raw_status, category in statuses.items():
        assert policy.parse_results_text(_line(KEY_ONE, raw_status))[0].category == category


@pytest.mark.parametrize("raw_status", ["survived", "timeout", "suspicious", "no tests"])
def test_actionable_statuses_are_findings(raw_status: str) -> None:
    report = _run(_line(KEY_ONE, raw_status))
    assert report.status == policy.STATUS_FINDINGS
    assert report.findings[0].category == policy.STATUS_TO_CATEGORY[raw_status]


@pytest.mark.parametrize(
    "raw_status",
    ["skipped", "not checked", "check was interrupted by user", "segfault", "teleported"],
)
def test_unsafe_and_unknown_statuses_are_tool_errors(raw_status: str) -> None:
    report = _run(_line(KEY_ONE, raw_status))
    assert report.status == policy.STATUS_TOOL_ERROR
    assert report.error


def test_killed_and_caught_by_type_check_are_clean() -> None:
    report = _run(
        _line(KEY_ONE, "killed") + _line(KEY_TWO, "caught by type check"),
        (KEY_ONE, KEY_TWO),
    )
    assert report.status == policy.STATUS_CLEAN
    assert report.categories.killed == 1
    assert report.categories.caught_by_type_check == 1


def test_empty_malformed_stale_and_failed_runs_fail_closed() -> None:
    assert _run("", ()).status == policy.STATUS_TOOL_ERROR
    assert _run(_line(KEY_ONE, "killed"), context=_context(current=False)).status == "tool-error"
    failed = _context(run_outcome="interrupted")
    assert _run(_line(KEY_ONE, "killed"), context=failed).status == "tool-error"
    with pytest.raises(policy.ResultsParseError):
        policy.parse_results_text("not indented")


def test_missing_extra_duplicate_and_dictionary_disagreement_fail_closed() -> None:
    assert _run(_line(KEY_ONE, "killed"), (KEY_ONE, KEY_TWO)).status == "tool-error"
    assert _run(_line(KEY_TWO, "killed"), (KEY_ONE,)).status == "tool-error"
    assert _run(_line(KEY_ONE, "killed") * 2, (KEY_ONE,)).status == "tool-error"
    assert _run(_line(KEY_ONE, "killed"), (KEY_ONE, KEY_ONE)).status == "tool-error"
    report = _run(
        _line(KEY_ONE, "killed"),
        disagreements=EvidenceDisagreements(dictionary=("dictionary mismatch",)),
    )
    assert report.status == "tool-error"


@pytest.mark.parametrize(
    ("raw_status", "detail_field", "category"),
    [
        ("survived", "findings", "survived"),
        ("skipped", "unsafe_results", "skipped"),
    ],
)
def test_duplicate_results_write_tool_error_report(
    tmp_path: Path,
    raw_status: str,
    detail_field: str,
    category: str,
    schema: dict[str, object],
) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    report_path = tmp_path / "duplicate.json"
    duplicate_results = _line(KEY_ONE, raw_status) + _line(KEY_ONE, raw_status)
    policy_input = policy.PolicyInput(
        _context(), (KEY_ONE,), EvidenceDisagreements(), duplicate_results
    )

    assert policy.run_policy(policy_input, report_path) == policy.EXIT_TOOL_ERROR
    payload = json.loads(report_path.read_text())
    assert payload["status"] == policy.STATUS_TOOL_ERROR
    assert payload["categories"][category] == 2
    assert payload["evidence"]["duplicate_results"] == [KEY_ONE]
    assert len(payload[detail_field]) == 1
    jsonschema.validate(payload, schema)


def test_selected_scope_ignores_non_selected_not_checked() -> None:
    selection = MutationSelection("selected", ("perplexity_cli.example.*", "*.missing.*"))
    other_key = "perplexity_cli.other.x_f__mutmut_1"
    results = _line(KEY_ONE, "killed") + _line(other_key, "not checked")
    report = _run(results, (KEY_ONE, other_key), _context(selection))
    assert report.status == "clean"
    assert (report.evidence.generated_count, report.evidence.selected_count) == (2, 1)
    assert report.evidence.result_count == 1


def test_category_totals_and_checked_count_reconcile() -> None:
    entries = policy.parse_results_text(_line(KEY_ONE, "killed") + _line(KEY_TWO, "not checked"))
    report = policy.build_report(_context(), (KEY_ONE, KEY_TWO), entries)
    payload = policy.report_to_dict(report)
    assert sum(payload["categories"].values()) == payload["evidence"]["result_count"]
    assert payload["evidence"]["checked_count"] == 1


def test_result_digest_binds_raw_status_not_only_key() -> None:
    killed = _run(_line(KEY_ONE, "killed"))
    survived = _run(_line(KEY_ONE, "survived"))
    assert killed.evidence.generated_digest == survived.evidence.generated_digest
    assert killed.evidence.result_digest != survived.evidence.result_digest


def test_run_policy_writes_unknown_status_tool_error(tmp_path: Path) -> None:
    report_path = tmp_path / "report.json"
    input_data = policy.PolicyInput(
        _context(), (KEY_ONE,), EvidenceDisagreements(), _line(KEY_ONE, "teleported")
    )
    assert policy.run_policy(input_data, report_path) == policy.EXIT_TOOL_ERROR
    payload = json.loads(report_path.read_text())
    assert payload["categories"]["unknown"] == 1
    assert payload["evidence"]["result_count"] == 1
    assert payload["unsafe_results"] == [
        {"key": KEY_ONE, "status": "teleported", "category": "unknown"}
    ]


def test_run_policy_writes_malformed_tool_error(tmp_path: Path) -> None:
    report_path = tmp_path / "report.json"
    input_data = policy.PolicyInput(_context(), (KEY_ONE,), EvidenceDisagreements(), "malformed")
    assert policy.run_policy(input_data, report_path) == policy.EXIT_TOOL_ERROR
    assert json.loads(report_path.read_text())["status"] == "tool-error"


def test_fetch_results_uses_locked_click_boolean_syntax(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_run(args: tuple[str, ...]) -> str:
        calls.append(args)
        return ""

    monkeypatch.setattr(policy, "_run_mutmut", fake_run)
    policy.fetch_results_text()
    assert calls == [("results", "--all", "True")]


def test_version_parser_is_strict() -> None:
    assert policy.parse_version_text("mutmut, version 3.5.0\n") == "3.5.0"
    with pytest.raises(policy.MutmutUnavailableError):
        policy.parse_version_text("mutmut 3.5.0\n")


def test_parsers_do_not_reflect_untrusted_process_output() -> None:
    secret = "credential-secret"
    with pytest.raises(policy.MutmutUnavailableError) as version_error:
        policy.parse_version_text(secret)
    with pytest.raises(policy.ResultsParseError) as results_error:
        policy.parse_results_text(secret)
    assert secret not in str(version_error.value)
    assert secret not in str(results_error.value)


@pytest.fixture(scope="module")
def schema() -> dict[str, object]:
    return json.loads(SCHEMA_PATH.read_text())


@pytest.mark.parametrize("status", ["clean", "findings", "tool-error", "not-applicable"])
def test_reports_match_schema(status: str, schema: dict[str, object]) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    reports = {
        "clean": lambda: _run(_line(KEY_ONE, "killed")),
        "findings": lambda: _run(_line(KEY_ONE, "no tests")),
        "tool-error": lambda: _run(_line(KEY_ONE, "skipped")),
        "not-applicable": lambda: _run("", (), _context(run_outcome="not-applicable")),
    }
    report = reports[status]()
    assert report.status == status
    jsonschema.validate(policy.report_to_dict(report), schema)


def test_schema_rejects_missing_provenance_and_extra_fields(schema: dict[str, object]) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    payload = policy.report_to_dict(_run(_line(KEY_ONE, "killed")))
    del payload["provenance"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)
    payload = policy.report_to_dict(_run(_line(KEY_ONE, "killed")))
    payload["mutation_score"] = 100
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def test_schema_rejects_clean_report_with_unsafe_category(schema: dict[str, object]) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    payload = policy.report_to_dict(_run(_line(KEY_ONE, "killed")))
    payload["categories"]["skipped"] = 1
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def test_direct_script_help_advertises_scope_patterns_and_report_path() -> None:
    result = subprocess.run(
        ["uv", "run", "python", "scripts/mutation_policy.py", "--help"],
        cwd=PROJECT_ROOT,
        env={**os.environ, "UV_OFFLINE": "1"},
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0
    assert all(option in result.stdout for option in ("--scope", "--pattern", "--report-path"))


def test_cli_fails_closed_without_independent_generated_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(policy, "detect_version", lambda: "3.5.0")
    monkeypatch.setattr(policy, "fetch_results_text", lambda: _line(KEY_ONE, "killed"))
    report_path = tmp_path / "report.json"
    assert policy.main(["--report-path", str(report_path)]) == policy.EXIT_TOOL_ERROR
    payload = json.loads(report_path.read_text())
    assert payload["status"] == "tool-error"
    assert payload["version"] == "3.5.0"


def test_tool_error_placeholder_contract_is_schema_valid(schema: dict[str, object]) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    context = policy.placeholder_context(MutationSelection("full"))
    report = policy.build_tool_error_report(context, "preflight failed")
    jsonschema.validate(policy.report_to_dict(report), schema)


def test_non_applicable_with_results_is_tool_error() -> None:
    context = _context(run_outcome="not-applicable")
    report = _run(_line(KEY_ONE, "killed"), (KEY_ONE,), context)
    assert report.status == "tool-error"


def test_report_context_can_be_rebound_to_fresh_provenance() -> None:
    stale = _context(current=False)
    fresh = replace(stale, provenance=replace(stale.provenance, evidence_current=True))
    assert _run(_line(KEY_ONE, "killed"), context=fresh).status == "clean"


@pytest.mark.parametrize(
    "context",
    [
        replace(_context(), version="3.5.1"),
        replace(_context(), provenance=replace(_context().provenance, source_revision="unknown")),
        replace(_context(), provenance=replace(_context().provenance, input_fingerprint="unknown")),
        replace(_context(), environment=replace(_environment(), python_version="unknown")),
        replace(
            _context(),
            environment=replace(_environment(), locked_wheel_filename="mutmut-3.5.1.whl"),
        ),
        replace(_context(), environment=replace(_environment(), locked_wheel_sha256="c" * 64)),
        replace(
            _context(),
            environment=replace(_environment(), mutmut_record_digest="unknown"),
        ),
    ],
)
def test_publishable_statuses_reject_incomplete_or_wrong_identity(
    context: policy.ReportContext,
) -> None:
    assert _run(_line(KEY_ONE, "killed"), context=context).status == policy.STATUS_TOOL_ERROR


def test_not_applicable_requires_authoritative_provenance() -> None:
    context = replace(
        policy.placeholder_context(MutationSelection("full")), run_outcome="not-applicable"
    )
    assert _run("", (), context).status == policy.STATUS_TOOL_ERROR


def test_findings_require_authoritative_environment() -> None:
    context = replace(_context(), environment=replace(_environment(), uv_version="unknown"))
    assert _run(_line(KEY_ONE, "survived"), context=context).status == policy.STATUS_TOOL_ERROR


def test_structural_exclusion_disagreement_is_tool_error_evidence() -> None:
    disagreements = EvidenceDisagreements(structural_exclusions=("undeclared pragma",))
    report = _run(_line(KEY_ONE, "killed"), disagreements=disagreements)
    assert report.status == policy.STATUS_TOOL_ERROR
    assert report.evidence.structural_exclusion_disagreements == ("undeclared pragma",)


def _clean_payload() -> dict[str, Any]:
    return policy.report_to_dict(_run(_line(KEY_ONE, "killed")))


def _set_total_mismatch(payload: dict[str, Any]) -> None:
    payload["total_mutants"] = 2


def _set_category_mismatch(payload: dict[str, Any]) -> None:
    payload["categories"]["killed"] = 2


def _set_checked_mismatch(payload: dict[str, Any]) -> None:
    payload["evidence"]["checked_count"] = 0


def _set_selected_above_generated(payload: dict[str, Any]) -> None:
    payload["evidence"]["generated_count"] = 0


def _set_selected_result_mismatch(payload: dict[str, Any]) -> None:
    payload["evidence"].update(generated_count=2, selected_count=2)


def _set_full_generated_selected_mismatch(payload: dict[str, Any]) -> None:
    payload["evidence"]["generated_count"] = 2


def _set_actionable_count_mismatch(payload: dict[str, Any]) -> None:
    payload["categories"]["survived"] = 1


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (_set_total_mismatch, "total/result"),
        (_set_category_mismatch, "category/result"),
        (_set_checked_mismatch, "checked count"),
        (_set_selected_above_generated, "selected exceeds"),
        (_set_selected_result_mismatch, "incomplete completeness"),
        (_set_full_generated_selected_mismatch, "full-scope"),
        (_set_actionable_count_mismatch, "category/result"),
    ],
)
def test_semantic_validator_rejects_arithmetic_invariants(
    mutate: Callable[[dict[str, Any]], None], message: str
) -> None:
    payload = deepcopy(_clean_payload())
    mutate(payload)
    with pytest.raises(policy.ReportValidationError, match=message):
        policy.validate_report_payload(payload)


def test_semantic_validator_rejects_findings_correspondence_and_duplicates() -> None:
    payload = policy.report_to_dict(_run(_line(KEY_ONE, "survived")))
    payload["findings"] = []
    with pytest.raises(policy.ReportValidationError, match="findings do not correspond"):
        policy.validate_report_payload(payload)
    payload = policy.report_to_dict(_run(_line(KEY_ONE, "survived")))
    payload["findings"].append(deepcopy(payload["findings"][0]))
    with pytest.raises(policy.ReportValidationError, match="duplicate findings"):
        policy.validate_report_payload(payload)


def test_semantic_validator_rejects_unsafe_correspondence_and_duplicates() -> None:
    payload = policy.report_to_dict(_run(_line(KEY_ONE, "skipped")))
    payload["unsafe_results"] = []
    with pytest.raises(policy.ReportValidationError, match="unsafe results do not correspond"):
        policy.validate_report_payload(payload)
    payload = policy.report_to_dict(_run(_line(KEY_ONE, "skipped")))
    payload["unsafe_results"].append(deepcopy(payload["unsafe_results"][0]))
    with pytest.raises(policy.ReportValidationError, match="duplicate unsafe results"):
        policy.validate_report_payload(payload)


def test_semantic_validator_prevents_placeholder_clean_publication() -> None:
    payload = _clean_payload()
    payload["provenance"]["source_revision"] = "unknown"
    with pytest.raises(policy.ReportValidationError, match="source revision"):
        policy.validate_report_payload(payload)


def test_semantic_validator_rejects_status_and_completeness_mismatch() -> None:
    payload = _clean_payload()
    payload["evidence"]["complete"] = False
    with pytest.raises(policy.ReportValidationError, match="incomplete"):
        policy.validate_report_payload(payload)
    payload = policy.report_to_dict(_run(_line(KEY_ONE, "survived")))
    payload["status"] = "clean"
    with pytest.raises(policy.ReportValidationError, match="status/actionable"):
        policy.validate_report_payload(payload)


def test_semantic_validator_rejects_duplicate_evidence_entries() -> None:
    payload = policy.report_to_dict(_run(_line(KEY_ONE, "skipped")))
    payload["evidence"]["missing_results"] = [KEY_ONE, KEY_ONE]
    with pytest.raises(policy.ReportValidationError, match="duplicate missing_results"):
        policy.validate_report_payload(payload)


def test_schema_rejects_duplicate_report_entries(schema: dict[str, object]) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    payload = policy.report_to_dict(_run(_line(KEY_ONE, "survived")))
    payload["findings"].append(deepcopy(payload["findings"][0]))
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        (None, "version", "3.5.1"),
        ("provenance", "source_revision", "unknown"),
        ("provenance", "evidence_current", False),
        ("environment", "python_version", "tbd"),
        ("environment", "mutmut_distribution_digest", "unknown"),
        ("environment", "locked_wheel_filename", "unknown"),
        ("environment", "locked_wheel_sha256", "unknown"),
    ],
)
def test_schema_rejects_non_authoritative_publishable_identity(
    schema: dict[str, object], section: str | None, field: str, value: object
) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    payload = _clean_payload()
    target = payload if section is None else payload[section]
    target[field] = value
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def test_not_applicable_schema_rejects_placeholder_provenance(
    schema: dict[str, object],
) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    report = _run("", (), _context(run_outcome="not-applicable"))
    payload = policy.report_to_dict(report)
    payload["provenance"]["source_tree"] = "unknown"
    with pytest.raises(policy.ReportValidationError, match="source tree"):
        policy.validate_report_payload(payload)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def test_mutmut_failure_does_not_disclose_captured_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "credential-secret"
    completed = subprocess.CompletedProcess([], 7, stdout=secret, stderr=secret)

    def fake_subprocess_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return completed

    monkeypatch.setattr(policy.subprocess, "run", fake_subprocess_run)
    with pytest.raises(policy.MutmutUnavailableError) as caught:
        policy.fetch_results_text()
    assert secret not in str(caught.value)
    assert str(caught.value) == "mutmut exited with status 7"
