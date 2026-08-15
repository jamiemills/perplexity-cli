"""Tests for independent Mutmut 3.5 generated-key evidence."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.mutation_evidence import (
    EvidenceDisagreements,
    GeneratedSourceError,
    MutationSelection,
    SourceDocument,
    StructuralExclusion,
    compare_evidence,
    enumerate_generated_mutants,
    normalise_generated_module,
    validate_structural_exclusions,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
GENERATED_FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "mutation_generated" / "representative.py"
REAL_FIXTURE = (
    PROJECT_ROOT / "tests" / "fixtures" / "mutation_generated" / "real_query_runner_excerpt.txt"
)
POLICY_FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "mutation_policy"


def test_locked_generated_grammar_enumerates_only_numeric_definitions() -> None:
    evidence = enumerate_generated_mutants(
        GENERATED_FIXTURE.read_text(), "mutants/perplexity_cli/services/example.py"
    )
    assert evidence.keys == (
        "perplexity_cli.services.example.x_outer__mutmut_1",
        "perplexity_cli.services.example.x_fetch__mutmut_2",
        "perplexity_cli.services.example.x___str____mutmut_3",
        "perplexity_cli.services.example.xǁHandlerǁhandle__mutmut_4",
    )
    assert evidence.dictionary_keys == evidence.keys
    assert not evidence.dictionary_disagreements


def test_original_trampoline_alias_nested_and_malformed_names_are_rejected() -> None:
    evidence = enumerate_generated_mutants(
        GENERATED_FIXTURE.read_text(), "perplexity_cli/example.py"
    )
    names = "\n".join(evidence.keys)
    assert all(
        word not in names for word in ("orig", "trampoline", "alias", "nested", "zero", "_01")
    )


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("mutants/perplexity_cli/__init__.py", "perplexity_cli"),
        ("mutants/src/perplexity_cli/api/client.py", "perplexity_cli.api.client"),
        ("/tmp/run/mutants/src/perplexity_cli/query_runner.py", "perplexity_cli.query_runner"),
        ("src/perplexity_cli/query_runner.py", "perplexity_cli.query_runner"),
        ("perplexity_cli/api/client.py", "perplexity_cli.api.client"),
    ],
)
def test_package_and_module_paths_are_normalised(path: str, expected: str) -> None:
    assert normalise_generated_module(path) == expected


def test_invalid_generated_path_and_python_are_rejected() -> None:
    with pytest.raises(GeneratedSourceError):
        normalise_generated_module("README.md")
    with pytest.raises(GeneratedSourceError):
        enumerate_generated_mutants("def broken(", "perplexity_cli/example.py")


def test_dictionary_alias_disagreement_is_fail_closed() -> None:
    source = """
def x_run__mutmut_1():
    return 1
x_run__mutmut_mutants: object = {"x_run__mutmut_1": alias}
"""
    generated = enumerate_generated_mutants(source, "perplexity_cli/example.py")
    assert "does not map to itself" in generated.dictionary_disagreements[0]
    summary = compare_evidence(
        generated.keys,
        generated.keys,
        MutationSelection("full"),
        EvidenceDisagreements(dictionary=generated.dictionary_disagreements),
    )
    assert summary.complete is False


def test_dictionary_missing_and_extra_keys_are_reported() -> None:
    source = """
def x_run__mutmut_1():
    return 1
x_run__mutmut_mutants: object = {"x_run__mutmut_2": x_run__mutmut_2}
"""
    generated = enumerate_generated_mutants(source, "perplexity_cli/example.py")
    assert generated.dictionary_disagreements == (
        "extra dictionary key: perplexity_cli.example.x_run__mutmut_2",
        "missing dictionary key: perplexity_cli.example.x_run__mutmut_1",
    )


def test_swapped_dictionary_keys_are_rejected_per_owner() -> None:
    source = """
def x_first__mutmut_1():
    return 1
def x_second__mutmut_1():
    return 2
x_first__mutmut_mutants: object = {"x_second__mutmut_1": x_second__mutmut_1}
x_second__mutmut_mutants: object = {"x_first__mutmut_1": x_first__mutmut_1}
"""
    generated = enumerate_generated_mutants(source, "perplexity_cli/example.py")
    assert len(generated.dictionary_disagreements) == 2
    assert all(
        "belongs to a different mutant dictionary" in issue
        for issue in generated.dictionary_disagreements
    )


def test_full_comparison_detects_missing_extra_and_duplicates() -> None:
    generated = ("pkg.x_f__mutmut_1", "pkg.x_f__mutmut_1", "pkg.x_f__mutmut_2")
    results = ("pkg.x_f__mutmut_1", "pkg.x_f__mutmut_3", "pkg.x_f__mutmut_3")
    summary = compare_evidence(generated, results, MutationSelection("full"))
    assert summary.missing_results == ("pkg.x_f__mutmut_1", "pkg.x_f__mutmut_2")
    assert summary.extra_results == ("pkg.x_f__mutmut_3",)
    assert summary.duplicate_generated == ("pkg.x_f__mutmut_1",)
    assert summary.duplicate_results == ("pkg.x_f__mutmut_3",)
    assert summary.complete is False


def test_repeated_selected_patterns_apply_independently() -> None:
    generated = (
        "pkg.api.x_one__mutmut_1",
        "pkg.auth.x_two__mutmut_1",
        "pkg.other.x_three__mutmut_1",
    )
    results = (
        "pkg.api.x_one__mutmut_1",
        "pkg.auth.x_two__mutmut_1",
        "pkg.other.x_unrelated__mutmut_9",
    )
    selection = MutationSelection("selected", ("pkg.api.*", "pkg.auth.*", "pkg.api.*"))
    summary = compare_evidence(generated, results, selection)
    assert (summary.generated_count, summary.selected_count, summary.result_count) == (3, 2, 2)
    assert summary.complete is True


def test_empty_full_and_selected_scopes_are_incomplete() -> None:
    assert compare_evidence((), (), MutationSelection("full")).complete is False
    selected = MutationSelection("selected", ("pkg.missing.*",))
    assert compare_evidence(("pkg.other.x_f__mutmut_1",), (), selected).complete is False


def test_selection_contract_rejects_invalid_pattern_combinations() -> None:
    with pytest.raises(ValueError, match="full scope"):
        MutationSelection("full", ("pkg.*",))
    with pytest.raises(ValueError, match="selected scope"):
        MutationSelection("selected")
    with pytest.raises(ValueError, match="cannot be empty"):
        MutationSelection("selected", ("",))


def test_multiset_digests_are_order_independent_and_duplicate_sensitive() -> None:
    selection = MutationSelection("full")
    first = compare_evidence(("b", "a"), ("a", "b"), selection)
    second = compare_evidence(("a", "b"), ("b", "a"), selection)
    duplicate = compare_evidence(("a", "a", "b"), ("a", "a", "b"), selection)
    assert first.generated_digest == second.generated_digest
    assert first.generated_digest != duplicate.generated_digest


def test_real_mutmut_layout_reconciles_exact_result_keys() -> None:
    generated = enumerate_generated_mutants(
        REAL_FIXTURE.read_text(),
        "/tmp/retained/mutants/src/perplexity_cli/query_runner.py",
    )
    expected = ("perplexity_cli.query_runner.xǁ_Formatterǁformat_answer__mutmut_1",)
    assert generated.keys == expected
    assert generated.dictionary_keys == expected
    assert compare_evidence(expected, expected, MutationSelection("full")).complete is True


def test_nested_generated_definition_is_not_a_separate_mutant_key() -> None:
    generated = enumerate_generated_mutants(
        GENERATED_FIXTURE.read_text(), "mutants/src/perplexity_cli/services/example.py"
    )
    assert "perplexity_cli.services.example.x_outer__mutmut_1" in generated.keys
    assert all("nested" not in key for key in generated.keys)


def _valid_exclusions() -> tuple[StructuralExclusion, ...]:
    return (
        StructuralExclusion(
            "src/example.py",
            6,
            "Reader.read",
            "protocol-method",
            "core",
            "non-executable",
            "reviewer",
        ),
        StructuralExclusion(
            "src/example.py",
            10,
            "Reader.read_abstractly",
            "abstract-method",
            "core",
            "non-executable",
            "reviewer",
        ),
        StructuralExclusion(
            "src/example.py",
            16,
            "BaseWriter.write",
            "abstract-method",
            "core",
            "non-executable",
            "reviewer",
        ),
    )


def test_structural_exclusion_manifest_accepts_only_exact_reviewed_declarations() -> None:
    source = SourceDocument("src/example.py", (POLICY_FIXTURES / "structural_valid.py").read_text())
    assert not validate_structural_exclusions((source,), _valid_exclusions())


def test_structural_exclusion_manifest_rejects_ineligible_and_undeclared_pragmas() -> None:
    source = SourceDocument(
        "src/invalid.py", (POLICY_FIXTURES / "structural_invalid.py").read_text()
    )
    issues = validate_structural_exclusions((source,), ())
    assert issues == (
        "ineligible pragma: src/invalid.py:11",
        "ineligible pragma: src/invalid.py:6",
        "non-canonical pragma: src/invalid.py:17",
    )


def test_structural_exclusion_manifest_rejects_stale_duplicate_and_placeholder_entries() -> None:
    source = SourceDocument("src/example.py", (POLICY_FIXTURES / "structural_valid.py").read_text())
    stale = StructuralExclusion(
        "src/example.py", 7, "Reader.read", "protocol-method", "unknown", "tbd", "none"
    )
    issues = validate_structural_exclusions((source,), (stale, stale))
    assert any(issue.startswith("duplicate manifest entry") for issue in issues)
    assert any(issue.startswith("stale manifest entry") for issue in issues)
    assert any(issue.startswith("undeclared pragma") for issue in issues)
    assert any(issue.startswith("invalid owner") for issue in issues)


def test_structural_exclusion_manifest_requires_independent_reviewer() -> None:
    source = SourceDocument("src/example.py", (POLICY_FIXTURES / "structural_valid.py").read_text())
    entries = list(_valid_exclusions())
    entries[0] = StructuralExclusion(
        "src/example.py", 6, "Reader.read", "protocol-method", "same", "reason", "same"
    )
    issues = validate_structural_exclusions((source,), entries)
    assert any(issue.startswith("owner must differ from reviewer") for issue in issues)


def test_structural_exclusion_manifest_rejects_wrong_kind_and_declaration() -> None:
    source = SourceDocument("src/example.py", (POLICY_FIXTURES / "structural_valid.py").read_text())
    wrong = (
        StructuralExclusion(
            "src/example.py", 6, "Reader.other", "abstract-method", "core", "reason", "reviewer"
        ),
    )
    issues = validate_structural_exclusions((source,), wrong)
    assert any(issue.startswith("stale manifest entry") for issue in issues)
    assert any(issue.startswith("undeclared pragma") for issue in issues)


def test_structural_exclusion_manifest_accepts_supported_import_aliases() -> None:
    source_text = (
        "from typing import Protocol as Interface\n"
        "from abc import abstractmethod as abstract\n"
        "class Reader(Interface):\n"
        "    def read(self):  # pragma: no mutate\n"
        "        ...\n"
        "class Base:\n"
        "    @abstract\n"
        "    def write(self):  # pragma: no mutate\n"
        "        pass\n"
    )
    declared = (
        StructuralExclusion(
            "src/aliases.py", 4, "Reader.read", "protocol-method", "core", "reason", "reviewer"
        ),
        StructuralExclusion(
            "src/aliases.py", 8, "Base.write", "abstract-method", "core", "reason", "reviewer"
        ),
    )
    source = SourceDocument("src/aliases.py", source_text)
    assert not validate_structural_exclusions((source,), declared)


def test_structural_exclusion_manifest_accepts_exact_module_imports() -> None:
    source_text = (
        "import abc as abstract_base\n"
        "import typing as standard_typing\n"
        "import typing_extensions as extended_typing\n"
        "class First(standard_typing.Protocol):\n"
        "    def read(self):  # pragma: no mutate\n"
        "        ...\n"
        "class Second(extended_typing.Protocol):\n"
        "    @abstract_base.abstractmethod\n"
        "    def write(self):  # pragma: no mutate\n"
        "        pass\n"
    )
    declared = (
        StructuralExclusion(
            "src/modules.py", 5, "First.read", "protocol-method", "core", "reason", "reviewer"
        ),
        StructuralExclusion(
            "src/modules.py", 9, "Second.write", "abstract-method", "core", "reason", "reviewer"
        ),
    )
    source = SourceDocument("src/modules.py", source_text)
    assert not validate_structural_exclusions((source,), declared)


def test_structural_exclusion_manifest_rejects_import_shadowing() -> None:
    source_text = (
        "from abc import abstractmethod\n"
        "from typing import Protocol\n"
        "class LocalBase:\n"
        "    pass\n"
        "Protocol = LocalBase\n"
        "def local_decorator(function):\n"
        "    return function\n"
        "abstractmethod = local_decorator\n"
        "class Fake(Protocol):\n"
        "    def read(self):  # pragma: no mutate\n"
        "        ...\n"
        "class Concrete:\n"
        "    @abstractmethod\n"
        "    def write(self):  # pragma: no mutate\n"
        "        pass\n"
    )
    source = SourceDocument("src/shadowed.py", source_text)
    assert validate_structural_exclusions((source,), ()) == (
        "ineligible pragma: src/shadowed.py:10",
        "ineligible pragma: src/shadowed.py:14",
    )


def test_structural_exclusion_manifest_rejects_compound_import_shadowing() -> None:
    source_text = (
        "from typing import Protocol\n"
        "if True:\n"
        "    from local_types import Protocol\n"
        "class Fake(Protocol):\n"
        "    def read(self):  # pragma: no mutate\n"
        "        ...\n"
    )
    source = SourceDocument("src/compound_shadow.py", source_text)
    assert validate_structural_exclusions((source,), ()) == (
        "ineligible pragma: src/compound_shadow.py:5",
    )


def test_structural_exclusion_manifest_rejects_suffix_spoofs() -> None:
    source_text = (
        "def not_abstractmethod(function):\n"
        "    return function\n"
        "class NotAProtocol:\n"
        "    pass\n"
        "class Fake(NotAProtocol):\n"
        "    def read(self):  # pragma: no mutate\n"
        "        ...\n"
        "class Concrete:\n"
        "    @not_abstractmethod\n"
        "    def write(self):  # pragma: no mutate\n"
        "        pass\n"
    )
    source = SourceDocument("src/spoof.py", source_text)
    assert validate_structural_exclusions((source,), ()) == (
        "ineligible pragma: src/spoof.py:10",
        "ineligible pragma: src/spoof.py:6",
    )
