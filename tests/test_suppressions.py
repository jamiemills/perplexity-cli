"""Identity-fingerprint suppression ratchet tests.

Proves:
- moved suppression detected
- broadened suppression detected
- new identity fails
- clean passes
- count-only not sufficient (same per-file totals, identity drift detected)
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _load_script(name: str) -> ModuleType:
    """Load a ``scripts/`` module by path without mutating ``sys.path``."""
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / f"{name}.py")
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load script: {name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_ratchet = _load_script("_ratchet")
cs = _load_script("check_suppressions")
diff_fingerprints = _ratchet.diff_fingerprints
save_fingerprints = _ratchet.save_fingerprints
load_fingerprints = _ratchet.load_fingerprints


def _make_src_tree(tmp_path: Path, files: dict[str, str]) -> Path:
    """Create a fake ``src/`` directory populated with Python files."""
    src = tmp_path / "src"
    src.mkdir()
    for name, content in files.items():
        file_path = src / name
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content)
    return src


def _make_pyproject(
    tmp_path: Path,
    *,
    omit: list[str] | None = None,
    exclude_lines: list[str] | None = None,
    exclude_also: list[str] | None = None,
    partial_branches: list[str] | None = None,
    do_not_mutate: list[str] | None = None,
) -> Path:
    """Create a minimal pyproject.toml with optional coverage/mutmut sections."""
    lines: list[str] = []
    if omit:
        lines.append("[tool.coverage.run]")
        lines.append(f"omit = {json.dumps(omit)}")
    if exclude_lines or exclude_also or partial_branches:
        lines.append("[tool.coverage.report]")
        if exclude_lines:
            lines.append(f"exclude_lines = {json.dumps(exclude_lines)}")
        if exclude_also:
            lines.append(f"exclude_also = {json.dumps(exclude_also)}")
        if partial_branches:
            lines.append(f"partial_branches = {json.dumps(partial_branches)}")
    if do_not_mutate:
        lines.append("[tool.mutmut]")
        lines.append(f"do_not_mutate = {json.dumps(do_not_mutate)}")
    content = "\n".join(lines) + "\n"
    path = tmp_path / "pyproject.toml"
    path.write_text(content)
    return path


def _patch_check_module(monkeypatch, tmp_path: Path, src: Path, pyproject: Path) -> None:
    """Redirect ``check_suppressions`` globals to the temp tree."""
    monkeypatch.setattr(cs, "SOURCE_ROOTS", (src,))
    monkeypatch.setattr(cs, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(cs, "PYPROJECT", pyproject)


def _temp_baseline_dir(monkeypatch, tmp_path: Path) -> Path:
    """Create a temporary baseline directory and point ``_ratchet`` at it."""
    bd = tmp_path / "baselines"
    bd.mkdir()
    monkeypatch.setattr(cs, "BASELINE_DIR", bd)
    # Also patch _ratchet itself so save_fingerprints writes to the right place.
    import _ratchet

    import scripts._ratchet

    monkeypatch.setattr(_ratchet, "BASELINE_DIR", bd)
    monkeypatch.setattr(scripts._ratchet, "BASELINE_DIR", bd)
    return bd


# ── Collect-identities unit tests ──────────────────────────────────────────


class TestCollectSourceIdentities:
    """Unit tests for ``_collect_source_identities``."""

    def test_noqa_bare(self, tmp_path: Path):
        src = _make_src_tree(tmp_path, {"mod.py": "x = 1  # noqa\n"})
        ids = cs._collect_source_identities(src, tmp_path)
        assert "src/mod.py:1:noqa" in ids

    def test_noqa_with_code(self, tmp_path: Path):
        src = _make_src_tree(tmp_path, {"mod.py": "x = 1  # noqa: F401\n"})
        ids = cs._collect_source_identities(src, tmp_path)
        assert "src/mod.py:1:noqa:F401" in ids

    def test_no_cover_pragma(self, tmp_path: Path):
        src = _make_src_tree(tmp_path, {"mod.py": "if x:  # pragma: no cover\n"})
        ids = cs._collect_source_identities(src, tmp_path)
        assert "src/mod.py:1:no-cover" in ids

    def test_no_branch_pragma(self, tmp_path: Path):
        src = _make_src_tree(tmp_path, {"mod.py": "if x:  # pragma: no branch\n"})
        ids = cs._collect_source_identities(src, tmp_path)
        assert "src/mod.py:1:no-branch" in ids

    def test_no_mutate_pragma(self, tmp_path: Path):
        src = _make_src_tree(tmp_path, {"mod.py": "x = 1  # pragma: no mutate\n"})
        ids = cs._collect_source_identities(src, tmp_path)
        assert "src/mod.py:1:no-mutate" in ids

    def test_no_mutate_pragma_with_detail(self, tmp_path: Path):
        src = _make_src_tree(
            tmp_path,
            {"mod.py": "x = 1  # pragma: no mutate: operator-name\n"},
        )
        ids = cs._collect_source_identities(src, tmp_path)
        assert "src/mod.py:1:no-mutate:operator-name" in ids

    def test_multiple_suppressions_same_line(self, tmp_path: Path):
        src = _make_src_tree(tmp_path, {"mod.py": "x = 1  # noqa: F401  # type: ignore\n"})
        ids = cs._collect_source_identities(src, tmp_path)
        assert "src/mod.py:1:noqa:F401" in ids
        assert "src/mod.py:1:type-ignore" in ids

    def test_type_ignore_with_code(self, tmp_path: Path):
        src = _make_src_tree(tmp_path, {"mod.py": "x = foo()  # type: ignore[arg-type]\n"})
        ids = cs._collect_source_identities(src, tmp_path)
        assert "src/mod.py:1:type-ignore:arg-type" in ids

    def test_pyright_ignore_with_code(self, tmp_path: Path):
        src = _make_src_tree(
            tmp_path,
            {"mod.py": "x = y  # pyright: ignore[reportAny]\n"},
        )
        ids = cs._collect_source_identities(src, tmp_path)
        assert "src/mod.py:1:pyright-ignore:reportAny" in ids

    def test_nosec_bare(self, tmp_path: Path):
        src = _make_src_tree(tmp_path, {"mod.py": "hashlib.md5()  # nosec\n"})
        ids = cs._collect_source_identities(src, tmp_path)
        assert "src/mod.py:1:nosec" in ids

    def test_nosemgrep_with_rule(self, tmp_path: Path):
        src = _make_src_tree(tmp_path, {"mod.py": "x = 1  # nosemgrep: some-rule-id\n"})
        ids = cs._collect_source_identities(src, tmp_path)
        assert "src/mod.py:1:nosemgrep:some-rule-id" in ids


class TestCollectConfigIdentities:
    """Unit tests for config-derived identity collection."""

    def test_mutmut_do_not_mutate(self, tmp_path: Path):
        pyproject = _make_pyproject(tmp_path, do_not_mutate=["**/foo.py", "**/bar.py"])
        ids = cs._collect_mutmut_config_identities(pyproject)
        assert len(ids) == 2
        assert "pyproject.toml:0:mutmut-do-not-mutate:**/foo.py" in ids
        assert "pyproject.toml:0:mutmut-do-not-mutate:**/bar.py" in ids

    def test_coverage_omit(self, tmp_path: Path):
        pyproject = _make_pyproject(tmp_path, omit=["tests/*", "setup.py"])
        ids = cs._collect_coverage_config_identities(pyproject)
        assert len(ids) == 2
        assert "pyproject.toml:0:coverage-omit:tests/*" in ids
        assert "pyproject.toml:0:coverage-omit:setup.py" in ids

    def test_coverage_exclude_lines(self, tmp_path: Path):
        pyproject = _make_pyproject(
            tmp_path,
            exclude_lines=["pragma: no cover", "def __repr__"],
        )
        ids = cs._collect_coverage_config_identities(pyproject)
        assert len(ids) == 2
        assert any("coverage-exclude-lines" in i for i in ids)

    def test_coverage_exclude_also(self, tmp_path: Path):
        pyproject = _make_pyproject(
            tmp_path,
            exclude_also=["raise NotImplementedError"],
        )
        ids = cs._collect_coverage_config_identities(pyproject)
        assert len(ids) == 1
        assert "coverage-exclude-also" in ids[0]

    def test_coverage_partial_branch(self, tmp_path: Path):
        pyproject = _make_pyproject(
            tmp_path,
            partial_branches=["if 0:.*"],
        )
        ids = cs._collect_coverage_config_identities(pyproject)
        assert len(ids) == 1
        assert "coverage-partial-branch" in ids[0]


# ── Token-aware scanning tests ──────────────────────────────────────────────


class TestTokenAwareScanning:
    """Only real comments count — suppression text in strings/docstrings is ignored."""

    def test_suppression_text_in_string_ignored(self, tmp_path: Path):
        src = _make_src_tree(tmp_path, {"mod.py": 'x = "# noqa: F401"\n'})
        ids = cs._collect_source_identities(src, tmp_path)
        assert ids == []

    def test_suppression_text_in_docstring_ignored(self, tmp_path: Path):
        src = _make_src_tree(
            tmp_path,
            {"mod.py": '"""Example: "# pragma: no cover"\n"""\nx = 1\n'},
        )
        ids = cs._collect_source_identities(src, tmp_path)
        assert ids == []

    def test_multiple_suppressions_in_one_comment(self, tmp_path: Path):
        src = _make_src_tree(
            tmp_path,
            {"mod.py": "x = 1  # noqa: F401  # type: ignore[arg-type]\n"},
        )
        ids = cs._collect_source_identities(src, tmp_path)
        assert "src/mod.py:1:noqa:F401" in ids
        assert "src/mod.py:1:type-ignore:arg-type" in ids


# ── Fail-closed tests ───────────────────────────────────────────────────────


class TestFailClosed:
    """Unreadable sources, malformed TOML, and corrupt baselines must error out."""

    def test_unreadable_source_raises_tool_error(self, tmp_path: Path, monkeypatch) -> None:
        src = _make_src_tree(tmp_path, {"mod.py": "x = 1  # noqa\n"})

        def _boom(self, *_args, **_kwargs):
            raise OSError("simulated unreadable file")

        monkeypatch.setattr(Path, "read_text", _boom)
        with pytest.raises(cs.ToolError):
            cs._collect_source_identities(src, tmp_path)

    def test_malformed_toml_raises_tool_error(self, tmp_path: Path) -> None:
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("[tool.coverage\nomit = [\n")
        with pytest.raises(cs.ToolError):
            cs._collect_coverage_config_identities(pyproject)

    def test_corrupt_baseline_raises_tool_error(self, tmp_path: Path, monkeypatch) -> None:
        _temp_baseline_dir(monkeypatch, tmp_path)
        (tmp_path / "baselines" / "suppressions.json").write_text("not json")
        with pytest.raises(cs.ToolError):
            cs._load_baseline_identities("suppressions.json")

    def test_main_exits_tool_error_code(self, tmp_path: Path, monkeypatch) -> None:
        src = _make_src_tree(tmp_path, {"mod.py": "x = 1\n"})
        pyproject = _make_pyproject(tmp_path)
        _patch_check_module(monkeypatch, tmp_path, src, pyproject)
        _temp_baseline_dir(monkeypatch, tmp_path)
        (tmp_path / "baselines" / "suppressions.json").write_text("not json")

        monkeypatch.setattr(sys, "argv", ["check_suppressions.py"])
        exited_with: list[int] = []
        monkeypatch.setattr(sys, "exit", exited_with.append)
        cs.main()
        assert exited_with == [2]


# ── Regression detection tests ─────────────────────────────────────────────


class TestMovedSuppressionDetected:
    """Moving a suppression to a different line creates a new identity → fails."""

    def test_moved_noqa_detected(self, tmp_path: Path, monkeypatch) -> None:
        src = _make_src_tree(tmp_path, {"mod.py": "x = 1  # noqa\n"})
        pyproject = _make_pyproject(tmp_path)
        _patch_check_module(monkeypatch, tmp_path, src, pyproject)
        _temp_baseline_dir(monkeypatch, tmp_path)

        baseline_fps = ["src/mod.py:10:noqa"]
        save_fingerprints("suppressions.json", baseline_fps)

        current = cs.collect_identities()
        from _ratchet import load_fingerprints

        bl = load_fingerprints("suppressions.json")
        diff = diff_fingerprints(current, bl)

        assert diff.is_regression, "Moved suppression must be detected"
        assert "src/mod.py:1:noqa" in diff.new
        assert "src/mod.py:10:noqa" in diff.removed

    def test_moved_pragma_no_cover_detected(self, tmp_path: Path, monkeypatch) -> None:
        src = _make_src_tree(tmp_path, {"mod.py": "x = 1  # pragma: no cover\n"})
        pyproject = _make_pyproject(tmp_path)
        _patch_check_module(monkeypatch, tmp_path, src, pyproject)
        _temp_baseline_dir(monkeypatch, tmp_path)

        baseline_fps = ["src/mod.py:5:no-cover"]
        save_fingerprints("suppressions.json", baseline_fps)

        current = cs.collect_identities()
        from _ratchet import load_fingerprints

        bl = load_fingerprints("suppressions.json")
        diff = diff_fingerprints(current, bl)

        assert diff.is_regression, "Moved pragma must be detected"
        assert "src/mod.py:1:no-cover" in diff.new
        assert "src/mod.py:5:no-cover" in diff.removed


class TestBroadenedSuppressionDetected:
    """Broadening a suppression changes the identity detail → fails."""

    def test_noqa_broadened_flat(self, tmp_path: Path, monkeypatch) -> None:
        # Baseline: specific code  |  Current: bare (broader — covers all)
        src = _make_src_tree(tmp_path, {"mod.py": "x = 1  # noqa\n"})
        pyproject = _make_pyproject(tmp_path)
        _patch_check_module(monkeypatch, tmp_path, src, pyproject)
        _temp_baseline_dir(monkeypatch, tmp_path)

        baseline_fps = ["src/mod.py:1:noqa:F401"]
        save_fingerprints("suppressions.json", baseline_fps)

        current = cs.collect_identities()
        from _ratchet import load_fingerprints

        bl = load_fingerprints("suppressions.json")
        diff = diff_fingerprints(current, bl)

        assert diff.is_regression, "Broadened noqa must be detected"
        assert "src/mod.py:1:noqa" in diff.new
        assert "src/mod.py:1:noqa:F401" in diff.removed

    def test_type_ignore_broadened(self, tmp_path: Path, monkeypatch) -> None:
        # Baseline: type: ignore[arg-type]  →  Current: type: ignore (bare)
        src = _make_src_tree(tmp_path, {"mod.py": "x = foo()  # type: ignore\n"})
        pyproject = _make_pyproject(tmp_path)
        _patch_check_module(monkeypatch, tmp_path, src, pyproject)
        _temp_baseline_dir(monkeypatch, tmp_path)

        baseline_fps = ["src/mod.py:1:type-ignore:arg-type"]
        save_fingerprints("suppressions.json", baseline_fps)

        current = cs.collect_identities()
        from _ratchet import load_fingerprints

        bl = load_fingerprints("suppressions.json")
        diff = diff_fingerprints(current, bl)

        assert diff.is_regression, "Broadened type: ignore must be detected"
        assert "src/mod.py:1:type-ignore" in diff.new
        assert "src/mod.py:1:type-ignore:arg-type" in diff.removed


class TestNewIdentityFails:
    """Adding a brand-new suppression → fails."""

    def test_new_noqa_fails(self, tmp_path: Path, monkeypatch) -> None:
        src = _make_src_tree(tmp_path, {"mod.py": "x = 1  # noqa\n"})
        pyproject = _make_pyproject(tmp_path)
        _patch_check_module(monkeypatch, tmp_path, src, pyproject)
        _temp_baseline_dir(monkeypatch, tmp_path)

        baseline_fps: list[str] = []
        save_fingerprints("suppressions.json", baseline_fps)

        current = cs.collect_identities()
        from _ratchet import load_fingerprints

        bl = load_fingerprints("suppressions.json")
        diff = diff_fingerprints(current, bl)

        assert diff.is_regression, "New suppression must fail"
        assert "src/mod.py:1:noqa" in diff.new

    def test_new_no_cover_fails(self, tmp_path: Path, monkeypatch) -> None:
        src = _make_src_tree(tmp_path, {"mod.py": "if x:  # pragma: no cover\n"})
        pyproject = _make_pyproject(tmp_path)
        _patch_check_module(monkeypatch, tmp_path, src, pyproject)
        _temp_baseline_dir(monkeypatch, tmp_path)

        baseline_fps: list[str] = []
        save_fingerprints("suppressions.json", baseline_fps)

        current = cs.collect_identities()
        from _ratchet import load_fingerprints

        bl = load_fingerprints("suppressions.json")
        diff = diff_fingerprints(current, bl)

        assert diff.is_regression, "New pragma: no cover must fail"
        assert "src/mod.py:1:no-cover" in diff.new


class TestCleanPasses:
    """Identical fingerprints → passes."""

    def test_clean_pass_identical(self, tmp_path: Path, monkeypatch) -> None:
        src = _make_src_tree(tmp_path, {"mod.py": "x = 1  # noqa\nif y:  # pragma: no cover\n"})
        pyproject = _make_pyproject(tmp_path, do_not_mutate=["**/x.py"])
        _patch_check_module(monkeypatch, tmp_path, src, pyproject)
        _temp_baseline_dir(monkeypatch, tmp_path)

        current = cs.collect_identities()
        save_fingerprints("suppressions.json", current)

        # Re-collect and diff — must be clean
        current2 = cs.collect_identities()
        from _ratchet import load_fingerprints

        bl = load_fingerprints("suppressions.json")
        diff = diff_fingerprints(current2, bl)

        assert not diff.is_regression, "Identical fingerprints must pass"
        assert diff.new == []

    def test_clean_pass_shrinkage_allowed(self, tmp_path: Path, monkeypatch) -> None:
        src = _make_src_tree(tmp_path, {"mod.py": "x = 1\n"})
        pyproject = _make_pyproject(tmp_path)
        _patch_check_module(monkeypatch, tmp_path, src, pyproject)
        _temp_baseline_dir(monkeypatch, tmp_path)

        baseline_fps = ["src/mod.py:1:noqa"]
        save_fingerprints("suppressions.json", baseline_fps)

        current = cs.collect_identities()
        from _ratchet import load_fingerprints

        bl = load_fingerprints("suppressions.json")
        diff = diff_fingerprints(current, bl)

        assert not diff.is_regression, "Removing suppressions must pass"
        assert "src/mod.py:1:noqa" in diff.removed
        assert diff.new == []


class TestCountOnlyNotSufficient:
    """Same per-file suppression count but changed identities → must fail."""

    def test_swapped_identities_same_count(self, tmp_path: Path, monkeypatch) -> None:
        # Baseline: line 1 = noqa, line 2 = type-ignore (2 suppressions)
        # Current:  line 1 = type-ignore, line 2 = noqa (still 2, but swapped)
        src = _make_src_tree(
            tmp_path,
            {"mod.py": ("x = 1  # type: ignore\ny = 2  # noqa\n")},
        )
        pyproject = _make_pyproject(tmp_path)
        _patch_check_module(monkeypatch, tmp_path, src, pyproject)
        _temp_baseline_dir(monkeypatch, tmp_path)

        baseline_fps = [
            "src/mod.py:1:noqa",
            "src/mod.py:2:type-ignore",
        ]
        save_fingerprints("suppressions.json", baseline_fps)

        current = cs.collect_identities()
        from _ratchet import load_fingerprints

        bl = load_fingerprints("suppressions.json")
        diff = diff_fingerprints(current, bl)

        # Per-file count perspective: baseline = 2, current = 2 — would pass.
        baseline_count = len(baseline_fps)
        current_count = len([i for i in current if i.startswith("src/mod.py")])
        assert baseline_count == current_count, (
            "Count is the same — count-only approach would pass, "
            "but identity approach must detect the swap"
        )

        assert diff.is_regression, "Count-only not sufficient: swapped identities must be detected"
        assert "src/mod.py:2:noqa" in diff.new
        assert "src/mod.py:1:type-ignore" in diff.new
        assert "src/mod.py:1:noqa" in diff.removed
        assert "src/mod.py:2:type-ignore" in diff.removed

    def test_replaced_identities_same_file_total(self, tmp_path: Path, monkeypatch) -> None:
        # Baseline: two
        # Current:  two bare type: ignore on lines 1 and 2 (same count, diff type)
        src = _make_src_tree(
            tmp_path,
            {"mod.py": ("x = 1  # type: ignore\ny = 2  # type: ignore\n")},
        )
        pyproject = _make_pyproject(tmp_path)
        _patch_check_module(monkeypatch, tmp_path, src, pyproject)
        _temp_baseline_dir(monkeypatch, tmp_path)

        baseline_fps = [
            "src/mod.py:1:noqa",
            "src/mod.py:2:noqa",
        ]
        save_fingerprints("suppressions.json", baseline_fps)

        current = cs.collect_identities()
        from _ratchet import load_fingerprints

        bl = load_fingerprints("suppressions.json")
        diff = diff_fingerprints(current, bl)

        baseline_count = len(baseline_fps)
        current_count = len([i for i in current if i.startswith("src/mod.py")])
        assert baseline_count == current_count, "Count is identical — count-only ratchet would pass"

        assert diff.is_regression, (
            "Count-only not sufficient: replaced identity types must be detected"
        )
        assert "src/mod.py:1:type-ignore" in diff.new
        assert "src/mod.py:2:type-ignore" in diff.new

    def test_config_identity_change_same_count(self, tmp_path: Path, monkeypatch) -> None:
        # Baseline: 1 config identity (omit: tests/*)
        # Current:   1 config identity (omit: **/tests/*) — broadened
        # Same count (1), different identity detail → must fail
        src = _make_src_tree(tmp_path, {"mod.py": "\n"})
        pyproject = _make_pyproject(tmp_path, omit=["**/tests/*"])
        _patch_check_module(monkeypatch, tmp_path, src, pyproject)
        _temp_baseline_dir(monkeypatch, tmp_path)

        baseline_fps = ["pyproject.toml:0:coverage-omit:tests/*"]
        save_fingerprints("suppressions.json", baseline_fps)

        current = cs.collect_identities()
        from _ratchet import load_fingerprints

        bl = load_fingerprints("suppressions.json")
        diff = diff_fingerprints(current, bl)

        assert diff.is_regression, "Broadened config omit must be detected"
        assert "pyproject.toml:0:coverage-omit:**/tests/*" in diff.new
        assert "pyproject.toml:0:coverage-omit:tests/*" in diff.removed


# ── Migration tests ────────────────────────────────────────────────────────


class TestMigration:
    """Legacy count-based baseline auto-migrates to fingerprint format."""

    def test_legacy_format_migrates(self, tmp_path: Path, monkeypatch) -> None:
        src = _make_src_tree(tmp_path, {"mod.py": "x = 1  # noqa\n"})
        pyproject = _make_pyproject(tmp_path)
        _patch_check_module(monkeypatch, tmp_path, src, pyproject)
        bd = _temp_baseline_dir(monkeypatch, tmp_path)

        # Write legacy-format baseline
        legacy = {"src/mod.py": 1}
        (bd / "suppressions.json").write_text(json.dumps(legacy))

        result = cs._load_baseline_identities("suppressions.json")
        assert "src/mod.py:1:noqa" in result, (
            "Migrated baseline must contain fingerprint identities"
        )

        # Verify the file was rewritten to fingerprint format
        raw = json.loads((bd / "suppressions.json").read_text())
        assert "fingerprints" in raw, "File must be rewritten to fingerprint format"

    def test_new_format_loads_directly(self, tmp_path: Path, monkeypatch) -> None:
        _temp_baseline_dir(monkeypatch, tmp_path)
        expected = ["src/mod.py:1:noqa", "src/mod.py:2:type-ignore"]
        save_fingerprints("suppressions.json", expected)

        result = cs._load_baseline_identities("suppressions.json")
        assert result == sorted(expected)

    def test_missing_baseline_returns_empty(self, tmp_path: Path, monkeypatch) -> None:
        _temp_baseline_dir(monkeypatch, tmp_path)
        result = cs._load_baseline_identities("suppressions.json")
        assert result == []


# ── Integration tests ──────────────────────────────────────────────────────


class TestMainIntegration:
    """Full-path tests exercising ``main()`` via sys.exit and sys.argv mocking."""

    def test_main_passes_when_clean(self, tmp_path: Path, monkeypatch) -> None:
        src = _make_src_tree(tmp_path, {"mod.py": "x = 1  # noqa\n"})
        pyproject = _make_pyproject(tmp_path)
        _patch_check_module(monkeypatch, tmp_path, src, pyproject)
        _temp_baseline_dir(monkeypatch, tmp_path)

        current = cs.collect_identities()
        save_fingerprints("suppressions.json", current)

        monkeypatch.setattr(sys, "argv", ["check_suppressions.py"])
        exited_with: list[int] = []

        def _fake_exit(code: int) -> None:
            exited_with.append(code)

        monkeypatch.setattr(sys, "exit", _fake_exit)
        cs.main()
        assert not exited_with

    def test_main_fails_on_regression(self, tmp_path: Path, monkeypatch) -> None:
        src = _make_src_tree(
            tmp_path,
            {"mod.py": "x = 1  # noqa\ny = 2  # type: ignore\n"},
        )
        pyproject = _make_pyproject(tmp_path)
        _patch_check_module(monkeypatch, tmp_path, src, pyproject)
        _temp_baseline_dir(monkeypatch, tmp_path)

        baseline_fps = ["src/mod.py:1:noqa"]
        save_fingerprints("suppressions.json", baseline_fps)

        monkeypatch.setattr(sys, "argv", ["check_suppressions.py"])
        exited_with: list[int] = []

        def _fake_exit(code: int) -> None:
            exited_with.append(code)

        monkeypatch.setattr(sys, "exit", _fake_exit)
        cs.main()
        assert exited_with == [1]
