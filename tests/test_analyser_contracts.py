"""Test analyser contract validation and meta-check logic.

Exercises schema validation, state-detection, pending handling, and
the contract-check driver without requiring real analyser execution.
"""

from __future__ import annotations

import sys
from importlib import import_module
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_FIXTURES = _PROJECT_ROOT / "tests" / "fixtures" / "analyser_contracts"


def _load_check_module():
    """Import the check script module for testing."""
    sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))
    mod = import_module("check_analyser_contracts")
    return mod


def _write_contract(tmp_path: Path, analyser_body: str) -> Path:
    """Write one schema-v1 analyser contract for a focused parser test."""
    path = tmp_path / "contracts.toml"
    path.write_text(f"[schema]\nversion = 1\n\n[[analysers]]\n{analyser_body}", encoding="utf-8")
    return path


def _valid_analyser_body(extra: str = "") -> str:
    """Return a minimal valid analyser TOML body with optional extra metadata."""
    return (
        'id = "sample"\n'
        'target = "sample"\n'
        "phase = 1\n"
        'status = "active"\n'
        'description = "Sample"\n'
        f"{extra}"
        "[analysers.states.clean]\n"
        "exit_min = 0\n"
        "exit_max = 0\n"
    )


def _write_repository(tmp_path: Path, targets: tuple[str, ...] = ("sample",)) -> Path:
    """Create a minimal repository with explicit phony targets and test nodes."""
    declarations = " ".join(targets)
    recipes = "\n".join(f"{target}:\n\t@true" for target in targets)
    (tmp_path / "Makefile").write_text(f".PHONY: {declarations}\n{recipes}\n", encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_sample.py").write_text(
        "def test_function():\n    pass\n\n"
        "class TestGroup:\n"
        "    def test_method(self):\n"
        "        pass\n",
        encoding="utf-8",
    )
    return tmp_path


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


def test_unknown_analyser_key_rejected(tmp_path: Path) -> None:
    """Unknown analyser metadata cannot silently extend schema v1."""
    mod = _load_check_module()
    path = _write_contract(tmp_path, _valid_analyser_body('wiring = "ci"\n'))
    _contracts, errors = mod.load_contracts(path)
    assert any("unknown keys: wiring" in error for error in errors)


def test_unknown_state_key_rejected(tmp_path: Path) -> None:
    """Unknown state metadata cannot silently extend schema v1."""
    mod = _load_check_module()
    body = _valid_analyser_body().replace("exit_max = 0", "exit_max = 0\nmeaning = 'pass'")
    _contracts, errors = mod.load_contracts(_write_contract(tmp_path, body))
    assert any("unknown keys: meaning" in error for error in errors)


@pytest.mark.parametrize("field", ['id = "../sample"', 'target = "sample target"'])
def test_unsafe_names_rejected(tmp_path: Path, field: str) -> None:
    """Analyser IDs and targets use a conservative Make-safe name grammar."""
    mod = _load_check_module()
    key = field.split(" =", maxsplit=1)[0]
    body = _valid_analyser_body().replace(f'{key} = "sample"', field)
    _contracts, errors = mod.load_contracts(_write_contract(tmp_path, body))
    assert any("unsafe" in error for error in errors)


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


def test_duplicate_targets_detected() -> None:
    """Two curated contracts cannot claim the same canonical Make target."""
    mod = _load_check_module()
    state = {"clean": mod.StateContract(name="clean", exit_min=0, exit_max=0)}
    contracts = [
        mod.AnalyserContract("one", "shared", 1, "active", "One", state),
        mod.AnalyserContract("two", "shared", 1, "active", "Two", state),
    ]
    errors: list[str] = []
    mod._check_duplicate_ids(contracts, errors)
    assert any("Duplicate analyser target 'shared'" in error for error in errors)


# ---------------------------------------------------------------------------
# Repository reference validation
# ---------------------------------------------------------------------------


def _repository_contract(mod, target: str = "sample", refs: tuple[str, ...] = ()):
    """Build a valid contract for repository-reference tests."""
    return mod.AnalyserContract(
        id=target,
        target=target,
        phase=1,
        status="active",
        description="Sample",
        states={"clean": mod.StateContract("clean", 0, 0)},
        test_node_ids=refs,
    )


def test_explicit_phony_make_target_required(tmp_path: Path) -> None:
    """Missing, implicit, and non-phony Make targets are rejected."""
    mod = _load_check_module()
    (tmp_path / "Makefile").write_text(
        "sample:\n\t@true\n%.generated:\n\t@true\n", encoding="utf-8"
    )
    contracts = [
        _repository_contract(mod),
        _repository_contract(mod, "missing"),
        _repository_contract(mod, "thing.generated"),
    ]
    errors = mod.validate_contracts(contracts, tmp_path)
    assert any("'sample' is not phony" in error for error in errors)
    assert any("'missing' is not explicit" in error for error in errors)
    assert any("'thing.generated' is not explicit" in error for error in errors)


def test_continued_phony_declaration_supported(tmp_path: Path) -> None:
    """Standard continued .PHONY declarations resolve exact targets."""
    mod = _load_check_module()
    (tmp_path / "Makefile").write_text(
        ".PHONY: first \\\n second\nfirst:\n\t@true\nsecond:\n\t@true\n",
        encoding="utf-8",
    )
    contracts = [_repository_contract(mod, "first"), _repository_contract(mod, "second")]
    assert mod.validate_contracts(contracts, tmp_path) == []


def test_phony_parser_ignores_inline_make_comments(tmp_path: Path) -> None:
    """Comment tokens cannot certify an explicit target as phony."""
    mod = _load_check_module()
    (tmp_path / "Makefile").write_text(
        ".PHONY: real # fake is only a comment\nreal:\n\t@true\nfake:\n\t@true\n",
        encoding="utf-8",
    )
    errors = mod.validate_contracts([_repository_contract(mod, "fake")], tmp_path)
    assert any("'fake' is not phony" in error for error in errors)


def test_supported_test_reference_forms_resolve(tmp_path: Path) -> None:
    """File, function, method, and opaque parameter references are accepted."""
    mod = _load_check_module()
    root = _write_repository(tmp_path)
    refs = (
        "tests/test_sample.py",
        "tests/test_sample.py::test_function",
        "tests/test_sample.py::TestGroup::test_method",
        "tests/test_sample.py::test_function[opaque/value::not-collected]",
    )
    assert mod.validate_contracts([_repository_contract(mod, refs=refs)], root) == []


@pytest.mark.parametrize(
    ("reference", "message"),
    [
        ("../test_escape.py", "escapes the repository root"),
        ("tests/test_missing.py", "missing test file"),
        ("tests/test_sample.py::test_absent", "missing statically resolvable base node"),
        ("tests/test_sample.py::TestGroup::test_absent", "missing statically resolvable base node"),
    ],
)
def test_invalid_test_references_rejected(tmp_path: Path, reference: str, message: str) -> None:
    """Escaped, missing, and statically absent test references are rejected."""
    mod = _load_check_module()
    root = _write_repository(tmp_path)
    errors = mod.validate_contracts([_repository_contract(mod, refs=(reference,))], root)
    assert any(message in error for error in errors)


def test_duplicate_test_references_rejected(tmp_path: Path) -> None:
    """An evidence node may be owned only once in the curated registry."""
    mod = _load_check_module()
    root = _write_repository(tmp_path, ("one", "two"))
    reference = "tests/test_sample.py::test_function"
    contracts = [
        _repository_contract(mod, "one", (reference,)),
        _repository_contract(mod, "two", (reference,)),
    ]
    errors = mod.validate_contracts(contracts, root)
    assert any("duplicate test reference" in error for error in errors)


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


def test_validate_mode_never_runs_analyser(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A valid --validate invocation performs no analyser subprocess work."""
    mod = _load_check_module()
    root = _write_repository(tmp_path)
    contracts_path = _write_contract(tmp_path, _valid_analyser_body())

    def fail_run(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("subprocess.run must not be called by --validate")

    monkeypatch.setattr(mod.subprocess, "run", fail_run)
    with pytest.raises(SystemExit) as exc_info:
        mod.main(
            [
                "--validate",
                "--contracts",
                str(contracts_path),
                "--repository-root",
                str(root),
            ]
        )
    assert exc_info.value.code == 0


def test_validate_and_run_are_mutually_exclusive() -> None:
    """Schema-only validation cannot be combined with analyser execution."""
    mod = _load_check_module()
    with pytest.raises(SystemExit) as exc_info:
        mod._parse_args(["--validate", "--run"])
    assert exc_info.value.code == 2


def test_invalid_metadata_prevents_run_before_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every run mode validates the complete registry before filtering or execution."""
    mod = _load_check_module()
    root = _write_repository(tmp_path)
    contracts_path = _write_contract(tmp_path, _valid_analyser_body('unknown = "value"\n'))

    def fail_run(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("invalid metadata must prevent subprocess execution")

    monkeypatch.setattr(mod.subprocess, "run", fail_run)
    with pytest.raises(SystemExit) as exc_info:
        mod.main(
            [
                "--run",
                "--only",
                "does-not-match",
                "--contracts",
                str(contracts_path),
                "--repository-root",
                str(root),
            ]
        )
    assert exc_info.value.code == 2
