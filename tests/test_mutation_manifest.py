"""Contract tests for baseline manifest construction and verification."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import mutation_manifest as mm


@pytest.fixture
def package_root(tmp_path: Path) -> Path:
    """Create a miniature production package tree."""
    for relative in (
        "src/perplexity_cli/__init__.py",
        "src/perplexity_cli/alpha.py",
        "src/perplexity_cli/nested/__init__.py",
        "src/perplexity_cli/nested/beta.py",
        "tests/unrelated.py",
    ):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("value = 1\n")
    return tmp_path


class TestModuleEnumeration:
    def test_enumerates_package_modules_deterministically(self, package_root: Path) -> None:
        records = mm.enumerate_module_records(package_root)
        modules = [record.module for record in records]
        assert modules == [
            "perplexity_cli",
            "perplexity_cli.alpha",
            "perplexity_cli.nested",
            "perplexity_cli.nested.beta",
        ]
        assert records[1].source_path == "src/perplexity_cli/alpha.py"

    def test_empty_package_fails_closed(self, tmp_path: Path) -> None:
        (tmp_path / "src" / "perplexity_cli").mkdir(parents=True)
        with pytest.raises(mm.LedgerMismatchError, match="no modules"):
            mm.enumerate_module_records(tmp_path)

    def test_ledger_document_is_stable_and_digest_bound(self, package_root: Path) -> None:
        first = mm.build_ledger_document(package_root)
        second = mm.build_ledger_document(package_root)
        assert first == second
        entries = first["modules"]
        assert first["ledger_sha256"] == mm.canonical_digest(entries)
        assert first["module_count"] == len(entries) == 4

    def test_verification_detects_tree_drift(self, package_root: Path) -> None:
        document = mm.build_ledger_document(package_root)
        assert mm.verify_ledger_document(document, package_root) == []
        (package_root / "src/perplexity_cli/gamma.py").write_text("value = 2\n")
        issues = mm.verify_ledger_document(document, package_root)
        assert any("ledger_sha256" in issue for issue in issues)
        assert any("module_count" in issue for issue in issues)


class TestKeysetDocuments:
    @staticmethod
    def _write_generated(root: Path, relative: str, body: str) -> Path:
        target = root / "mutants" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body)
        return target

    def test_collects_keys_per_module_with_dictionary_check(self, tmp_path: Path) -> None:
        self._write_generated(
            tmp_path,
            "src/perplexity_cli/alpha.py",
            "def x_run__mutmut_1():\n    return 1\n"
            'x_run__mutmut_mutants: object = {"x_run__mutmut_1": x_run__mutmut_1}\n',
        )
        keysets = mm.collect_generated_keysets(tmp_path / "mutants")
        assert keysets == {"perplexity_cli.alpha": ["perplexity_cli.alpha.x_run__mutmut_1"]}

    def test_swapped_dictionaries_fail_closed(self, tmp_path: Path) -> None:
        self._write_generated(
            tmp_path,
            "src/perplexity_cli/alpha.py",
            "def x_first__mutmut_1():\n"
            "    return 1\n"
            "def x_second__mutmut_1():\n"
            "    return 2\n"
            'x_first__mutmut_mutants: object = {"x_second__mutmut_1": x_second__mutmut_1}\n'
            'x_second__mutmut_mutants: object = {"x_first__mutmut_1": x_first__mutmut_1}\n',
        )
        with pytest.raises(mm.LedgerMismatchError, match="dictionary disagreement"):
            mm.collect_generated_keysets(tmp_path / "mutants")

    def test_keyset_document_round_trip(self, tmp_path: Path) -> None:
        self._write_generated(
            tmp_path,
            "src/perplexity_cli/alpha.py",
            "def x_run__mutmut_1():\n    return 1\n"
            'x_run__mutmut_mutants: object = {"x_run__mutmut_1": x_run__mutmut_1}\n',
        )
        document = mm.build_keysets_document(tmp_path / "mutants")
        assert document["total_keys"] == 1
        assert mm.verify_keysets_document(document, tmp_path / "mutants") == []
        self._write_generated(
            tmp_path,
            "src/perplexity_cli/alpha.py",
            "def x_run__mutmut_2():\n    return 1\n"
            'x_run__mutmut_mutants: object = {"x_run__mutmut_2": x_run__mutmut_2}\n',
        )
        issues = mm.verify_keysets_document(document, tmp_path / "mutants")
        assert any("keysets_sha256" in issue for issue in issues)


class TestCliSurface:
    def test_build_then_check_round_trip(self, package_root: Path, tmp_path: Path) -> None:
        from scripts.mutation_manifest import main as manifest_main

        generated = package_root / "generated"
        target = generated / "src/perplexity_cli/alpha.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            "def x_run__mutmut_1():\n    return 1\n"
            'x_run__mutmut_mutants: object = {"x_run__mutmut_1": x_run__mutmut_1}\n'
        )

        # Build reads production tree via PROJECT_ROOT; point it at the fixture.
        original_root = mm.PROJECT_ROOT
        mm.PROJECT_ROOT = package_root
        try:
            build_exit = manifest_main(
                [
                    "build",
                    "--mutants-dir",
                    str(generated),
                    "--output-dir",
                    str(tmp_path / "baseline"),
                ]
            )
            ledger = json.loads((tmp_path / "baseline/source-ledger.json").read_text())
            assert build_exit == 0
            check_exit = manifest_main(["check", "--manifest-dir", str(tmp_path / "baseline")])
        finally:
            mm.PROJECT_ROOT = original_root
        assert check_exit == 0
        assert ledger["schema_version"] == 1
