"""Test analyser contract validation and meta-check logic.

Exercises schema validation, state-detection, pending handling, and
the contract-check driver without requiring real analyser execution.
"""

from __future__ import annotations

import sys
from importlib import import_module
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_FIXTURES = _PROJECT_ROOT / "tests" / "fixtures" / "analyser_contracts"


def _load_check_module():
    """Import the check script module for testing."""
    sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))
    mod = import_module("check_analyser_contracts")
    return mod


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------


def test_valid_contract_parses():
    """A valid contract TOML loads without errors."""
    mod = _load_check_module()
    contracts, errors = mod.load_contracts(_FIXTURES / "valid.toml")
    assert len(errors) == 0, f"Unexpected schema errors: {errors}"
    assert len(contracts) == 1
    assert contracts[0].id == "format-check"
    assert contracts[0].phase == 1
    assert contracts[0].status == "active"
    assert "clean" in contracts[0].states
    assert "findings" in contracts[0].states


def test_malformed_rejected():
    """A contract missing required keys produces schema errors."""
    mod = _load_check_module()
    _contracts, errors = mod.load_contracts(_FIXTURES / "malformed.toml")
    assert len(errors) > 0
    assert any("'id'" in err.lower() or "missing required" in err.lower() for err in errors)


def test_missing_file_handled():
    """A non-existent contract file is handled gracefully."""
    mod = _load_check_module()
    _contracts, errors = mod.load_contracts(_FIXTURES / "nonexistent.toml")
    assert len(errors) > 0
    assert any("not found" in err.lower() for err in errors)


def test_missing_required_state():
    """Missing a required state (e.g. 'findings') is detected."""
    mod = _load_check_module()
    contracts, _schema_errors = mod.load_contracts(_FIXTURES / "missing_required_state.toml")
    assert len(contracts) == 1
    validation_errors = mod.validate_contracts(contracts)
    assert len(validation_errors) > 0
    assert any("missing required state" in err.lower() for err in validation_errors)


def test_overlapping_states_detected():
    """Overlapping exit-code ranges are flagged."""
    mod = _load_check_module()
    contracts, _schema_errors = mod.load_contracts(_FIXTURES / "overlapping_states.toml")
    assert len(contracts) == 1
    validation_errors = mod.validate_contracts(contracts)
    assert len(validation_errors) > 0
    assert any("overlap" in err.lower() for err in validation_errors)


def test_empty_states_treated_as_missing():
    """An analyser with no states section is rejected."""
    mod = _load_check_module()
    _contracts, errors = mod.load_contracts(_FIXTURES / "empty_states.toml")
    assert len(errors) > 0, "Expected errors for empty states"
    assert any("states" in err.lower() or "missing required" in err.lower() for err in errors)


# ---------------------------------------------------------------------------
# StateContract matching tests
# ---------------------------------------------------------------------------


def test_state_matches_exact_exit():
    """A state contract matches when exit code is within range."""
    mod = _load_check_module()
    sc = mod.StateContract(name="clean", exit_min=0, exit_max=0)
    assert sc.matches(0, None) is True
    assert sc.matches(1, None) is False
    assert sc.matches(-1, None) is False


def test_state_matches_range():
    """A state contract matches any exit code in the range."""
    mod = _load_check_module()
    sc = mod.StateContract(name="error", exit_min=2, exit_max=4)
    assert sc.matches(2, None) is True
    assert sc.matches(3, None) is True
    assert sc.matches(4, None) is True
    assert sc.matches(1, None) is False
    assert sc.matches(5, None) is False


def test_state_matches_signal():
    """A state with a signal only matches when the same signal is received."""
    mod = _load_check_module()
    sc = mod.StateContract(name="timeout", exit_min=-1, exit_max=-1, signal="SIGTERM")
    assert sc.matches(-1, "SIGTERM") is True
    assert sc.matches(-1, None) is False
    assert sc.matches(-1, "SIGKILL") is False
    assert sc.matches(0, "SIGTERM") is False


def test_state_without_signal_ignores_signal_arg():
    """A state without a signal ignores the signal argument."""
    mod = _load_check_module()
    sc = mod.StateContract(name="clean", exit_min=0, exit_max=0)
    assert sc.matches(0, "SIGTERM") is False


# ---------------------------------------------------------------------------
# Pending analyser handling
# ---------------------------------------------------------------------------


def test_pending_skipped_by_default():
    """Pending analysers are skipped when --pending-ok is not set."""
    mod = _load_check_module()
    contracts, _errors = mod.load_contracts(_FIXTURES / "pending.toml")
    selected, skipped = mod._select_contracts(contracts, only=None, pending_ok=False)
    assert len(skipped) == 1
    assert skipped[0] == "pending-one"
    assert len(selected) == 0


def test_pending_included_with_flag():
    """Pending analysers are included when --pending-ok is set."""
    mod = _load_check_module()
    contracts, _errors = mod.load_contracts(_FIXTURES / "pending.toml")
    selected, skipped = mod._select_contracts(contracts, only=None, pending_ok=True)
    assert len(skipped) == 0
    assert len(selected) == 1
    assert selected[0].id == "pending-one"


# ---------------------------------------------------------------------------
# Mock / fake exit-code detection
# ---------------------------------------------------------------------------


def _make_analyser(contracts, aid="test-analyser"):
    """Return the analyser contract with the given ID from a contracts list."""
    for c in contracts:
        if c.id == aid:
            return c
    raise ValueError(f"Analyser {aid} not found")


def _build_fake_result(mod, analyser, exit_code=0, signal_name=None):
    """Build a fake ContractResult using the module types."""
    sc = mod.ContractResult(
        analyser_id=analyser.id,
        target=analyser.target,
        exit_code=exit_code,
        signal_name=signal_name,
        matched_state=None,
        duration_s=0.0,
        expected=False,
    )
    return sc


def test_fake_clean_exit_matches_clean_state():
    """Exit code 0 matches 'clean' state for a format-check-like analyser."""
    mod = _load_check_module()
    contracts, _errors = mod.load_contracts(_FIXTURES / "valid.toml")
    analyser = _make_analyser(contracts, "format-check")
    result = _build_fake_result(mod, analyser, exit_code=0)
    matched = mod._match_state(analyser, result.exit_code, result.signal_name)
    assert matched == "clean", f"Expected 'clean', got {matched!r}"


def test_fake_findings_exit_matches_findings_state():
    """Exit code 1 matches 'findings' state for a format-check-like analyser."""
    mod = _load_check_module()
    contracts, _errors = mod.load_contracts(_FIXTURES / "valid.toml")
    analyser = _make_analyser(contracts, "format-check")
    result = _build_fake_result(mod, analyser, exit_code=1)
    matched = mod._match_state(analyser, result.exit_code, result.signal_name)
    assert matched == "findings", f"Expected 'findings', got {matched!r}"


def test_fake_unknown_exit_not_matched():
    """An exit code not in any state returns no match."""
    mod = _load_check_module()
    contracts, _errors = mod.load_contracts(_FIXTURES / "valid.toml")
    analyser = _make_analyser(contracts, "format-check")
    result = _build_fake_result(mod, analyser, exit_code=42)
    matched = mod._match_state(analyser, result.exit_code, result.signal_name)
    assert matched is None, f"Unexpected match for exit 42: {matched!r}"


# ---------------------------------------------------------------------------
# Duplicate ID detection
# ---------------------------------------------------------------------------


def test_duplicate_ids_detected(monkeypatch):
    """Duplicate analyser IDs in the contract array are flagged."""
    mod = _load_check_module()
    contracts = sorted(
        [
            mod.AnalyserContract(
                id="dup",
                target="t1",
                phase=1,
                status="active",
                description="d",
                states={"clean": mod.StateContract(name="clean", exit_min=0, exit_max=0)},
            ),
            mod.AnalyserContract(
                id="dup",
                target="t2",
                phase=1,
                status="active",
                description="d",
                states={"clean": mod.StateContract(name="clean", exit_min=0, exit_max=0)},
            ),
        ],
        key=lambda c: c.id,
    )
    errors: list[str] = []
    mod._check_duplicate_ids(contracts, errors)
    assert len(errors) > 0
    assert any("dup" in err for err in errors)


# ---------------------------------------------------------------------------
# RunReport aggregation tests
# ---------------------------------------------------------------------------


def test_run_report_all_passed():
    """An empty RunReport has all_contracts_honoured = True."""
    mod = _load_check_module()
    report = mod.RunReport()
    assert report.all_contracts_honoured is True


def test_run_report_with_failures():
    """A RunReport with a failed result has all_contracts_honoured = False."""
    mod = _load_check_module()
    failure = mod.ContractResult(
        analyser_id="test",
        target="test",
        exit_code=99,
        signal_name=None,
        matched_state=None,
        duration_s=0.0,
        expected=False,
    )
    report = mod.RunReport(results=[failure])
    assert report.all_contracts_honoured is False


def test_run_report_schema_errors_fails():
    """Schema errors make the report not honoured."""
    mod = _load_check_module()
    report = mod.RunReport(schema_errors=["bad schema"])
    assert report.all_contracts_honoured is False


# ---------------------------------------------------------------------------
# test_node_ids field tests
# ---------------------------------------------------------------------------


def test_test_node_ids_parsed_and_validated():
    """A valid test_node_ids array is parsed into the contract."""
    mod = _load_check_module()
    contracts, errors = mod.load_contracts(_FIXTURES / "with_test_node_ids.toml")
    assert errors == []
    assert len(contracts) == 1
    ids = contracts[0].test_node_ids
    assert ids == (
        "tests/test_with_tests.py::test_one",
        "tests/test_with_tests.py::test_two",
    )


def test_invalid_test_node_ids_rejected():
    """A non-array test_node_ids value produces a schema error."""
    mod = _load_check_module()
    _contracts, errors = mod.load_contracts(_FIXTURES / "invalid_test_node_ids.toml")
    assert len(errors) > 0
    assert any("test_node_ids" in err and "array" in err for err in errors)


def test_multi_state_contract_validates():
    """An expanded multi-state analyser (clean/findings/timeout/error) validates."""
    mod = _load_check_module()
    contracts, schema_errors = mod.load_contracts(_FIXTURES / "multi_state.toml")
    assert schema_errors == []
    assert len(contracts) == 1
    validation_errors = mod.validate_contracts(contracts)
    assert validation_errors == []
    states = contracts[0].states
    assert {"clean", "findings", "timeout", "internal-error"} <= set(states.keys())


def test_coverage_gap_warning_for_active_analyser():
    """An active analyser with empty test_node_ids produces a coverage warning."""
    mod = _load_check_module()
    contracts, _errors = mod.load_contracts(_FIXTURES / "no_test_node_ids.toml")
    warnings = mod.collect_coverage_gap_warnings(contracts)
    assert len(warnings) == 1
    assert "untested-analyser" in warnings[0]
    assert "coverage gap" in warnings[0]


def test_coverage_gap_warning_silent_for_pending():
    """Pending analysers with empty test_node_ids do not produce warnings."""
    mod = _load_check_module()
    contracts, _errors = mod.load_contracts(_FIXTURES / "pending.toml")
    warnings = mod.collect_coverage_gap_warnings(contracts)
    assert warnings == []


def test_coverage_gap_warning_absent_when_tests_declared():
    """Active analysers with declared tests produce no coverage warning."""
    mod = _load_check_module()
    contracts, _errors = mod.load_contracts(_FIXTURES / "with_test_node_ids.toml")
    warnings = mod.collect_coverage_gap_warnings(contracts)
    assert warnings == []


def test_run_report_carries_warnings():
    """RunReport carries the warnings list without affecting pass/fail state."""
    mod = _load_check_module()
    report = mod.RunReport(warnings=["coverage gap: foo"])
    assert report.warnings == ["coverage gap: foo"]
    assert report.all_contracts_honoured is True
