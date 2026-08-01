"""Test analyser contract validation and meta-check logic.

Exercises schema validation, state-detection, pending handling, and the
contract-check driver. Fixture-driven execution tests run real analyser
tools against synthetic clean/failing inputs to back every active contract
with executable evidence.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from scripts import check_analyser_contracts as mod

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_FIXTURES = _PROJECT_ROOT / "tests" / "fixtures" / "analyser_contracts"
_DEFAULT_CONTRACTS = _PROJECT_ROOT / "quality" / "analyser-contracts.toml"


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
        'test_node_ids = ["tests/test_sample.py::test_function"]\n'
        f"{extra}"
        "[analysers.states.clean]\n"
        "exit_min = 0\n"
        "exit_max = 0\n"
    )


def _write_test_sample(repo: Path) -> Path:
    """Write the standard test_sample.py evidence node into *repo*."""
    tests = repo / "tests"
    tests.mkdir()
    (tests / "test_sample.py").write_text(
        "def test_function():\n    pass\n\n"
        "class TestGroup:\n"
        "    def test_method(self):\n"
        "        pass\n",
        encoding="utf-8",
    )
    return repo


def _write_repository(tmp_path: Path, targets: tuple[str, ...] = ("sample",)) -> Path:
    """Create a minimal repository with explicit phony targets and test nodes."""
    declarations = " ".join(targets)
    recipes = "\n".join(f"{target}:\n\t@true" for target in targets)
    (tmp_path / "Makefile").write_text(f".PHONY: {declarations}\n{recipes}\n", encoding="utf-8")
    return _write_test_sample(tmp_path)


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------


def test_valid_contract_parses():
    """A valid contract TOML loads without errors."""
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
    _contracts, errors = mod.load_contracts(_FIXTURES / "malformed.toml")
    assert len(errors) > 0
    assert any("'id'" in err.lower() or "missing required" in err.lower() for err in errors)


def test_missing_file_handled():
    """A non-existent contract file is handled gracefully."""
    _contracts, errors = mod.load_contracts(_FIXTURES / "nonexistent.toml")
    assert len(errors) > 0
    assert any("not found" in err.lower() for err in errors)


def test_missing_required_state():
    """Missing a required state (e.g. 'findings') is detected."""
    contracts, _schema_errors = mod.load_contracts(_FIXTURES / "missing_required_state.toml")
    assert len(contracts) == 1
    validation_errors = mod.validate_contracts(contracts)
    assert len(validation_errors) > 0
    assert any("missing required state" in err.lower() for err in validation_errors)


def test_overlapping_states_detected():
    """Overlapping exit-code ranges are flagged."""
    contracts, _schema_errors = mod.load_contracts(_FIXTURES / "overlapping_states.toml")
    assert len(contracts) == 1
    validation_errors = mod.validate_contracts(contracts)
    assert len(validation_errors) > 0
    assert any("overlap" in err.lower() for err in validation_errors)


def test_empty_states_treated_as_missing():
    """An analyser with no states section is rejected."""
    _contracts, errors = mod.load_contracts(_FIXTURES / "empty_states.toml")
    assert len(errors) > 0, "Expected errors for empty states"
    assert any("states" in err.lower() or "missing required" in err.lower() for err in errors)


def test_unknown_analyser_key_rejected(tmp_path: Path) -> None:
    """Unknown analyser metadata cannot silently extend schema v1."""
    path = _write_contract(tmp_path, _valid_analyser_body('wiring = "ci"\n'))
    _contracts, errors = mod.load_contracts(path)
    assert any("unknown keys: wiring" in error for error in errors)


def test_unknown_state_key_rejected(tmp_path: Path) -> None:
    """Unknown state metadata cannot silently extend schema v1."""
    body = _valid_analyser_body().replace("exit_max = 0", "exit_max = 0\nmeaning = 'pass'")
    _contracts, errors = mod.load_contracts(_write_contract(tmp_path, body))
    assert any("unknown keys: meaning" in error for error in errors)


@pytest.mark.parametrize("field", ['id = "../sample"', 'target = "sample target"'])
def test_unsafe_names_rejected(tmp_path: Path, field: str) -> None:
    """Analyser IDs and targets use a conservative Make-safe name grammar."""
    key = field.split(" =", maxsplit=1)[0]
    body = _valid_analyser_body().replace(f'{key} = "sample"', field)
    _contracts, errors = mod.load_contracts(_write_contract(tmp_path, body))
    assert any("unsafe" in error for error in errors)


# ---------------------------------------------------------------------------
# StateContract matching tests
# ---------------------------------------------------------------------------


def test_state_matches_exact_exit():
    """A state contract matches when exit code is within range."""
    sc = mod.StateContract(name="clean", exit_min=0, exit_max=0)
    assert sc.matches(0, None) is True
    assert sc.matches(1, None) is False
    assert sc.matches(-1, None) is False


def test_state_matches_range():
    """A state contract matches any exit code in the range."""
    sc = mod.StateContract(name="error", exit_min=2, exit_max=4)
    assert sc.matches(2, None) is True
    assert sc.matches(3, None) is True
    assert sc.matches(4, None) is True
    assert sc.matches(1, None) is False
    assert sc.matches(5, None) is False


def test_state_matches_signal():
    """A state with a signal only matches when the same signal is received."""
    sc = mod.StateContract(name="timeout", exit_min=-1, exit_max=-1, signal="SIGTERM")
    assert sc.matches(-1, "SIGTERM") is True
    assert sc.matches(-1, None) is False
    assert sc.matches(-1, "SIGKILL") is False
    assert sc.matches(0, "SIGTERM") is False


def test_state_without_signal_ignores_signal_arg():
    """A state without a signal ignores the signal argument."""
    sc = mod.StateContract(name="clean", exit_min=0, exit_max=0)
    assert sc.matches(0, "SIGTERM") is False


# ---------------------------------------------------------------------------
# Pending analyser handling
# ---------------------------------------------------------------------------


def test_pending_skipped_by_default():
    """Pending analysers are skipped when --pending-ok is not set."""
    contracts, _errors = mod.load_contracts(_FIXTURES / "pending.toml")
    selected, skipped = mod._select_contracts(contracts, only=None, pending_ok=False)
    assert len(skipped) == 1
    assert skipped[0] == "pending-one"
    assert len(selected) == 0


def test_pending_included_with_flag():
    """Pending analysers are included when --pending-ok is set."""
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
    contracts, _errors = mod.load_contracts(_FIXTURES / "valid.toml")
    analyser = _make_analyser(contracts, "format-check")
    result = _build_fake_result(mod, analyser, exit_code=0)
    matched = mod._match_state(analyser, result.exit_code, result.signal_name)
    assert matched == "clean", f"Expected 'clean', got {matched!r}"


def test_fake_findings_exit_matches_findings_state():
    """Exit code 1 matches 'findings' state for a format-check-like analyser."""
    contracts, _errors = mod.load_contracts(_FIXTURES / "valid.toml")
    analyser = _make_analyser(contracts, "format-check")
    result = _build_fake_result(mod, analyser, exit_code=1)
    matched = mod._match_state(analyser, result.exit_code, result.signal_name)
    assert matched == "findings", f"Expected 'findings', got {matched!r}"


def test_fake_unknown_exit_not_matched():
    """An exit code not in any state returns no match."""
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


def _repository_contract(
    mod, target: str = "sample", refs: tuple[str, ...] = ("tests/test_sample.py",)
):
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
    (tmp_path / "Makefile").write_text(
        "sample:\n\t@true\n%.generated:\n\t@true\n", encoding="utf-8"
    )
    _write_test_sample(tmp_path)
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
    (tmp_path / "Makefile").write_text(
        ".PHONY: first \\\n second\nfirst:\n\t@true\nsecond:\n\t@true\n",
        encoding="utf-8",
    )
    _write_test_sample(tmp_path)
    contracts = [
        _repository_contract(mod, "first", ("tests/test_sample.py::test_function",)),
        _repository_contract(mod, "second", ("tests/test_sample.py::TestGroup::test_method",)),
    ]
    assert mod.validate_contracts(contracts, tmp_path) == []


def test_phony_parser_ignores_inline_make_comments(tmp_path: Path) -> None:
    """Comment tokens cannot certify an explicit target as phony."""
    (tmp_path / "Makefile").write_text(
        ".PHONY: real # fake is only a comment\nreal:\n\t@true\nfake:\n\t@true\n",
        encoding="utf-8",
    )
    _write_test_sample(tmp_path)
    errors = mod.validate_contracts([_repository_contract(mod, "fake")], tmp_path)
    assert any("'fake' is not phony" in error for error in errors)


def test_supported_test_reference_forms_resolve(tmp_path: Path) -> None:
    """File, function, method, and opaque parameter references are accepted."""
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
    root = _write_repository(tmp_path)
    errors = mod.validate_contracts([_repository_contract(mod, refs=(reference,))], root)
    assert any(message in error for error in errors)


def test_duplicate_test_references_rejected(tmp_path: Path) -> None:
    """An evidence node may be owned only once in the curated registry."""
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
    report = mod.RunReport()
    assert report.all_contracts_honoured is True


def test_run_report_with_failures():
    """A RunReport with a failed result has all_contracts_honoured = False."""
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
    report = mod.RunReport(schema_errors=["bad schema"])
    assert report.all_contracts_honoured is False


# ---------------------------------------------------------------------------
# test_node_ids field tests
# ---------------------------------------------------------------------------


def test_test_node_ids_parsed_and_validated():
    """A valid test_node_ids array is parsed into the contract."""
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
    _contracts, errors = mod.load_contracts(_FIXTURES / "invalid_test_node_ids.toml")
    assert len(errors) > 0
    assert any("test_node_ids" in err and "array" in err for err in errors)


def test_multi_state_contract_validates():
    """An expanded multi-state analyser (clean/findings/timeout/error) validates."""
    contracts, schema_errors = mod.load_contracts(_FIXTURES / "multi_state.toml")
    assert schema_errors == []
    assert len(contracts) == 1
    validation_errors = mod.validate_contracts(contracts)
    assert validation_errors == []
    states = contracts[0].states
    assert {"clean", "findings", "timeout", "internal-error"} <= set(states.keys())


def test_active_analyser_without_evidence_is_validation_error():
    """An active analyser with empty test_node_ids is a validation error."""
    contracts, _errors = mod.load_contracts(_FIXTURES / "no_test_node_ids.toml")
    errors = mod._check_active_test_evidence(contracts)
    assert len(errors) == 1
    assert "untested-analyser" in errors[0]
    assert "test_node_ids" in errors[0]


def test_pending_analyser_without_evidence_not_required():
    """Pending analysers are not required to declare executable evidence."""
    contracts, _errors = mod.load_contracts(_FIXTURES / "pending.toml")
    assert mod._check_active_test_evidence(contracts) == []


def test_active_analyser_with_evidence_passes_evidence_check():
    """Active analysers with declared tests satisfy the evidence check."""
    contracts, _errors = mod.load_contracts(_FIXTURES / "with_test_node_ids.toml")
    assert mod._check_active_test_evidence(contracts) == []


def test_validate_mode_fails_closed_without_evidence(tmp_path: Path) -> None:
    """An active analyser with no evidence cannot pass --validate."""
    root = _write_repository(tmp_path)
    contracts_path = _write_contract(
        tmp_path,
        _valid_analyser_body().replace(
            'test_node_ids = ["tests/test_sample.py::test_function"]\n', ""
        ),
    )
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
    assert exc_info.value.code == 2


def test_run_report_has_no_warnings_channel():
    """RunReport no longer carries a warnings channel; evidence gaps are errors."""
    report = mod.RunReport()
    assert not hasattr(report, "warnings")
    assert report.all_contracts_honoured is True


def test_validate_mode_never_runs_analyser(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A valid --validate invocation performs no analyser subprocess work."""
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
    with pytest.raises(SystemExit) as exc_info:
        mod._parse_args(["--validate", "--run"])
    assert exc_info.value.code == 2


def test_invalid_metadata_prevents_run_before_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every run mode validates the complete registry before filtering or execution."""
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


# ---------------------------------------------------------------------------
# Fixture-driven execution tests (executable evidence for active contracts)
# ---------------------------------------------------------------------------


def _venv_tool(name: str) -> str:
    """Return the repository venv executable for *name*.

    Tests run inside the repository's uv-managed interpreter, so analyser
    binaries live next to ``sys.executable``. Invoking them directly keeps
    every subprocess local with no network and no uv re-resolution. The
    interpreter symlink is deliberately not resolved so the venv bin dir is
    preserved.
    """
    return str(Path(sys.executable).parent / name)


def _write(path: Path, content: str) -> None:
    """Write *content* to *path*, creating any parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@dataclass(frozen=True, slots=True)
class ToolScenario:
    """Executable clean and failing invocations for one analyser contract."""

    analyser_id: str
    clean_argv: tuple[str, ...]
    clean_cwd: Path
    failing_argv: tuple[str, ...]
    failing_cwd: Path


def _run_tool(argv: tuple[str, ...], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run *argv* in *cwd*, returning the completed process."""
    return subprocess.run(  # nosec B603  # owner: quality-infrastructure; reason: fully static local argv with no shell
        list(argv),
        capture_output=True,
        text=True,
        cwd=str(cwd),
        timeout=120,
    )


def _format_check_scenario(root: Path) -> ToolScenario:
    """Scenario for the ``ruff format --check`` analyser."""
    _write(root / "clean" / "ok.py", "def add(a: int, b: int) -> int:\n    return a + b\n")
    _write(root / "failing" / "bad.py", "def add(a,b):\n   return a+b\n")
    ruff = _venv_tool("ruff")
    return ToolScenario(
        analyser_id="format-check",
        clean_argv=(ruff, "format", "--check", "clean"),
        clean_cwd=root,
        failing_argv=(ruff, "format", "--check", "failing"),
        failing_cwd=root,
    )


def _lint_scenario(root: Path) -> ToolScenario:
    """Scenario for the ``ruff check`` analyser."""
    for name in ("clean", "failing"):
        _write(
            root / name / "pyproject.toml",
            '[tool.ruff.lint]\nselect = ["E4", "E7", "E9", "F"]\n',
        )
    _write(root / "clean" / "ok.py", "def add(a: int, b: int) -> int:\n    return a + b\n")
    _write(
        root / "failing" / "bad.py",
        "import os\n\ndef add(a: int, b: int) -> int:\n    return a + b\n",
    )
    ruff = _venv_tool("ruff")
    return ToolScenario(
        analyser_id="lint",
        clean_argv=(ruff, "check", "clean"),
        clean_cwd=root,
        failing_argv=(ruff, "check", "failing"),
        failing_cwd=root,
    )


def _pyright_scenario(root: Path) -> ToolScenario:
    """Scenario for the ``pyright`` analyser (typecheck-pyright)."""
    _write(root / "clean" / "ok.py", "def add(a: int, b: int) -> int:\n    return a + b\n")
    _write(
        root / "failing" / "bad.py",
        "def add(a: int, b: int) -> str:\n    return a + b\n",
    )
    pyright = _venv_tool("pyright")
    return ToolScenario(
        analyser_id="typecheck-pyright",
        clean_argv=(pyright, "clean"),
        clean_cwd=root,
        failing_argv=(pyright, "failing"),
        failing_cwd=root,
    )


def _pyright_strict_scenario(root: Path) -> ToolScenario:
    """Scenario for the strict-pyright ratchet analyser."""
    _write(root / "clean" / "ok.py", "def add(a: int, b: int) -> int:\n    return a + b\n")
    _write(
        root / "failing" / "bad.py",
        "def add(a: int, b: int) -> str:\n    return a + b\n",
    )
    pyright = _venv_tool("pyright")
    return ToolScenario(
        analyser_id="typecheck-strict-ratchet",
        clean_argv=(pyright, "clean"),
        clean_cwd=root,
        failing_argv=(pyright, "failing"),
        failing_cwd=root,
    )


def _ty_scenario(root: Path) -> ToolScenario:
    """Scenario for the ``ty check`` analyser."""
    _write(root / "clean" / "ok.py", "def add(a: int, b: int) -> int:\n    return a + b\n")
    _write(
        root / "failing" / "bad.py",
        "def add(a: int, b: int) -> int:\n    return a + b + undefined_name\n",
    )
    ty = _venv_tool("ty")
    return ToolScenario(
        analyser_id="typecheck-ty",
        clean_argv=(ty, "check", "clean"),
        clean_cwd=root,
        failing_argv=(ty, "check", "failing"),
        failing_cwd=root,
    )


def _bandit_scenario(root: Path) -> ToolScenario:
    """Scenario for the ``bandit`` analyser."""
    _write(root / "clean" / "ok.py", "def add(a: int, b: int) -> int:\n    return a + b\n")
    _write(
        root / "failing" / "bad.py",
        'import subprocess\n\nsubprocess.call("ls", shell=True)\n',
    )
    bandit = _venv_tool("bandit")
    return ToolScenario(
        analyser_id="bandit",
        clean_argv=(bandit, "-q", "-r", "clean"),
        clean_cwd=root,
        failing_argv=(bandit, "-q", "-r", "failing"),
        failing_cwd=root,
    )


def _deptry_scenario(root: Path) -> ToolScenario:
    """Scenario for the ``deptry`` analyser (declared-but-unused dependency)."""
    for name in ("clean", "failing"):
        _write(
            root / name / "pyproject.toml",
            '[project]\nname = "fixture"\nversion = "0.1.0"\n'
            'requires-python = ">=3.12"\ndependencies = ["requests>=2.0"]\n',
        )
        _write(root / name / "mypkg" / "__init__.py", "")
    _write(
        root / "clean" / "mypkg" / "mod.py",
        'import requests\n\ndef load() -> None:\n    requests.get("https://example.com")\n',
    )
    _write(
        root / "failing" / "mypkg" / "mod.py", "import json\n\ndef load() -> dict:\n    return {}\n"
    )
    deptry = _venv_tool("deptry")
    return ToolScenario(
        analyser_id="deptry",
        clean_argv=(deptry, "."),
        clean_cwd=root / "clean",
        failing_argv=(deptry, "."),
        failing_cwd=root / "failing",
    )


def _import_linter_scenario(root: Path) -> ToolScenario:
    """Scenario for the ``lint-imports`` analyser (forbidden import)."""
    for name in ("clean", "failing"):
        for submodule in ("core", "ui"):
            _write(root / name / "mypkg" / submodule / "__init__.py", "")
        _write(
            root / name / ".importlinter",
            "[importlinter]\nroot_package = mypkg\n\n"
            "[importlinter:contract:1]\n"
            "name = ui must not import core\n"
            "type = forbidden\n"
            "source_modules =\n    mypkg.ui\n"
            "forbidden_modules =\n    mypkg.core\n",
        )
    _write(
        root / "clean" / "mypkg" / "core" / "helper.py", 'def helper() -> str:\n    return "core"\n'
    )
    _write(root / "clean" / "mypkg" / "ui" / "widget.py", 'def run() -> str:\n    return "ok"\n')
    _write(
        root / "failing" / "mypkg" / "core" / "helper.py",
        'def helper() -> str:\n    return "core"\n',
    )
    _write(
        root / "failing" / "mypkg" / "ui" / "widget.py",
        "from mypkg.core.helper import helper\n\ndef run() -> str:\n    return helper()\n",
    )
    lint_imports = _venv_tool("lint-imports")
    return ToolScenario(
        analyser_id="import-linter",
        clean_argv=(lint_imports,),
        clean_cwd=root / "clean",
        failing_argv=(lint_imports,),
        failing_cwd=root / "failing",
    )


_SCENARIO_BUILDERS: dict[str, Callable[[Path], ToolScenario]] = {
    "format-check": _format_check_scenario,
    "lint": _lint_scenario,
    "typecheck-pyright": _pyright_scenario,
    "typecheck-ty": _ty_scenario,
    "bandit": _bandit_scenario,
    "import-linter": _import_linter_scenario,
    "deptry": _deptry_scenario,
    "typecheck-strict-ratchet": _pyright_strict_scenario,
}


def _find_non_clean_state(contract: mod.AnalyserContract) -> str:
    """Return a non-clean state whose range covers exit code 1, if any."""
    for state_name, state in contract.states.items():
        if state_name != "clean" and state.matches(1, None):
            return state_name
    raise AssertionError(f"analyser '{contract.id}' declares no finding-state covering exit 1")


def _assert_matches_declared_state(
    contract: mod.AnalyserContract, state_name: str, exit_code: int
) -> None:
    """Assert *exit_code* satisfies the declared *state_name* for *contract*."""
    state = contract.states[state_name]
    assert state.matches(exit_code, None), (
        f"analyser '{contract.id}' exited {exit_code} for state '{state_name}' "
        f"declared as {state.exit_min}-{state.exit_max}"
    )


@pytest.mark.parametrize("analyser_id", sorted(_SCENARIO_BUILDERS.keys()))
def test_active_analyser_tool_clean_and_findings_exit_ranges(
    analyser_id: str, tmp_path: Path
) -> None:
    """Each active analyser honours its declared clean and findings ranges."""
    contracts, _schema_errors = mod.load_contracts(_DEFAULT_CONTRACTS)
    contract = next(c for c in contracts if c.id == analyser_id)
    builder = _SCENARIO_BUILDERS[analyser_id]
    scenario = builder(tmp_path)
    clean_result = _run_tool(scenario.clean_argv, scenario.clean_cwd)
    _assert_matches_declared_state(contract, "clean", clean_result.returncode)
    failing_result = _run_tool(scenario.failing_argv, scenario.failing_cwd)
    _assert_matches_declared_state(
        contract, _find_non_clean_state(contract), failing_result.returncode
    )


# ---------------------------------------------------------------------------
# Fail-closed handling of the contracts file
# ---------------------------------------------------------------------------


def test_missing_contracts_file_fails_closed(tmp_path: Path) -> None:
    """A missing contracts file is a schema failure, never a silent pass."""
    missing = tmp_path / "missing.toml"
    _contracts, errors = mod.load_contracts(missing)
    assert errors and "not found" in errors[0].lower()
    with pytest.raises(SystemExit) as exc_info:
        mod.main(["--validate", "--contracts", str(missing)])
    assert exc_info.value.code == 2


def test_malformed_contracts_file_fails_closed(tmp_path: Path) -> None:
    """A syntactically invalid contracts file is a schema failure."""
    malformed = tmp_path / "malformed.toml"
    malformed.write_text("[[analysers]\nid =", encoding="utf-8")
    _contracts, errors = mod.load_contracts(malformed)
    assert errors and "malformed" in errors[0].lower()
    with pytest.raises(SystemExit) as exc_info:
        mod.main(["--validate", "--contracts", str(malformed)])
    assert exc_info.value.code == 2


def test_unreadable_contracts_file_fails_closed(tmp_path: Path) -> None:
    """An unreadable contracts path (a directory) is a schema failure."""
    unreadable = tmp_path / "contracts.toml"
    unreadable.mkdir()
    _contracts, errors = mod.load_contracts(unreadable)
    assert errors and "read" in errors[0].lower()
    with pytest.raises(SystemExit) as exc_info:
        mod.main(["--validate", "--contracts", str(unreadable)])
    assert exc_info.value.code == 2
