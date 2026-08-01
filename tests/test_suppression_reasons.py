"""Suppression-reason enforcement meta-tests.

Proves:
- unformatted suppression (no owner:/reason:) is flagged
- formatted suppression (with owner:/reason:) passes
- --update-baseline persists fingerprints
- grandfathered (baselined) suppressions pass without owner:/reason:
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


csr = _load_script("check_suppression_reasons")


def _write_py_file(tmp_path: Path, name: str, content: str) -> Path:
    """Create a Python file in a fake source tree inside *tmp_path*."""
    src = tmp_path / "src"
    src.mkdir(parents=True, exist_ok=True)
    file_path = src / name
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")
    return file_path


def _patch_roots(monkeypatch, tmp_path: Path) -> None:
    """Point the script at the temp tree instead of the real repo."""
    monkeypatch.setattr(csr, "SOURCE_ROOTS", (tmp_path / "src",))
    monkeypatch.setattr(csr, "PROJECT_ROOT", tmp_path)
    bd = tmp_path / "baselines"
    bd.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(csr, "BASELINE_DIR", bd)


def _baseline_file(tmp_path: Path) -> Path:
    return tmp_path / "baselines" / csr.BASELINE_NAME


class TestUnformattedFlagged:
    """Unformatted suppressions without owner:/reason: are flagged."""

    def test_bare_noqa_fails(self, tmp_path: Path, monkeypatch) -> None:
        _write_py_file(tmp_path, "mod.py", "x = 1  # noqa\n")
        _patch_roots(monkeypatch, tmp_path)

        with pytest.raises(SystemExit) as exc_info:
            csr.main([])
        assert exc_info.value.code == 1

    def test_noqa_with_code_fails(self, tmp_path: Path, monkeypatch) -> None:
        _write_py_file(tmp_path, "mod.py", "x = 1  # noqa: E402\n")
        _patch_roots(monkeypatch, tmp_path)

        with pytest.raises(SystemExit) as exc_info:
            csr.main([])
        assert exc_info.value.code == 1

    def test_nosec_bare_fails(self, tmp_path: Path, monkeypatch) -> None:
        _write_py_file(tmp_path, "mod.py", "hashlib.md5()  # nosec\n")
        _patch_roots(monkeypatch, tmp_path)

        with pytest.raises(SystemExit) as exc_info:
            csr.main([])
        assert exc_info.value.code == 1

    def test_nosemgrep_fails(self, tmp_path: Path, monkeypatch) -> None:
        _write_py_file(tmp_path, "mod.py", "x = 1  # nosemgrep: some-rule\n")
        _patch_roots(monkeypatch, tmp_path)

        with pytest.raises(SystemExit) as exc_info:
            csr.main([])
        assert exc_info.value.code == 1


class TestFormattedPasses:
    """Formatted suppressions with owner:/reason: pass."""

    def test_noqa_with_owner_reason_passes(self, tmp_path: Path, monkeypatch) -> None:
        _write_py_file(
            tmp_path,
            "mod.py",
            "x = 1  # noqa: X; owner: quality-team; reason: intentional\n",
        )
        _patch_roots(monkeypatch, tmp_path)

        csr.main([])

    def test_nosec_with_owner_reason_passes(self, tmp_path: Path, monkeypatch) -> None:
        _write_py_file(
            tmp_path,
            "mod.py",
            "hashlib.md5()  # nosec; owner: security; reason: test-only\n",
        )
        _patch_roots(monkeypatch, tmp_path)

        csr.main([])

    def test_nosemgrep_formatted_passes(self, tmp_path: Path, monkeypatch) -> None:
        _write_py_file(
            tmp_path,
            "mod.py",
            "x = 1  # nosemgrep: rule; owner: jamie; reason: false positive\n",
        )
        _patch_roots(monkeypatch, tmp_path)

        csr.main([])

    def test_new_formatted_always_passes(self, tmp_path: Path, monkeypatch) -> None:
        _patch_roots(monkeypatch, tmp_path)
        # Baseline is empty — new formatted suppression must pass (ratchet)
        _write_py_file(
            tmp_path,
            "mod.py",
            "x = 1  # noqa: F401; owner: me; reason: deliberate\n",
        )

        csr.main([])


class TestUpdateBaseline:
    """--update-baseline persists fingerprints and clears errors."""

    def test_baseline_written(self, tmp_path: Path, monkeypatch) -> None:
        _write_py_file(tmp_path, "mod.py", "x = 1  # noqa\n")
        _patch_roots(monkeypatch, tmp_path)

        csr.main(["--update-baseline"])

        bf = _baseline_file(tmp_path)
        assert bf.is_file(), "Baseline file must be created"
        data = json.loads(bf.read_text(encoding="utf-8"))
        assert "fingerprints" in data
        assert "src/mod.py:1:noqa" in data["fingerprints"]

    def test_update_clears_previous_errors(self, tmp_path: Path, monkeypatch) -> None:
        _write_py_file(tmp_path, "mod.py", "x = 1  # noqa\n")
        _patch_roots(monkeypatch, tmp_path)

        # Should fail before baseline
        with pytest.raises(SystemExit) as exc_info:
            csr.main([])
        assert exc_info.value.code == 1

        # Update baseline to grandfather it
        csr.main(["--update-baseline"])

        # Should now pass
        csr.main([])


class TestGrandfatheredPasses:
    """Grandfathered (baselined) unformatted suppressions pass."""

    def test_baselined_unformatted_passes(self, tmp_path: Path, monkeypatch) -> None:
        unformatted_content = "x = 1  # noqa\n"
        _write_py_file(tmp_path, "mod.py", unformatted_content)
        _patch_roots(monkeypatch, tmp_path)

        csr.main(["--update-baseline"])
        csr.main([])

    def test_mixed_formatted_and_grandfathered(self, tmp_path: Path, monkeypatch) -> None:
        content = "x = 1  # noqa\ny = 2  # noqa: X; owner: me; reason: ok\n"
        _write_py_file(tmp_path, "mod.py", content)
        _patch_roots(monkeypatch, tmp_path)

        csr.main(["--update-baseline"])
        csr.main([])

    def test_moved_suppression_detected(self, tmp_path: Path, monkeypatch) -> None:
        _patch_roots(monkeypatch, tmp_path)
        # Baseline: noqa on line 1
        _write_py_file(tmp_path, "mod.py", "x = 1  # noqa\n")
        csr.main(["--update-baseline"])

        # Move to line 2 — new fingerprint, unformatted → fails
        _write_py_file(
            tmp_path,
            "mod.py",
            "x = 1\ny = 2  # noqa\n",
        )
        with pytest.raises(SystemExit) as exc_info:
            csr.main([])
        assert exc_info.value.code == 1


class TestEdgeCases:
    """Edge cases for the suppression-reason checker."""

    def test_no_suppressions_passes(self, tmp_path: Path, monkeypatch) -> None:
        _write_py_file(tmp_path, "mod.py", "x = 1\n")
        _patch_roots(monkeypatch, tmp_path)

        csr.main([])

    def test_no_py_files_passes(self, tmp_path: Path, monkeypatch) -> None:
        (tmp_path / "src").mkdir(parents=True, exist_ok=True)
        (tmp_path / "src" / "readme.md").write_text("# No Python here\n")
        _patch_roots(monkeypatch, tmp_path)

        csr.main([])

    def test_empty_baseline_handled(self, tmp_path: Path, monkeypatch) -> None:
        _write_py_file(
            tmp_path,
            "mod.py",
            "x = 1  # noqa: F401; owner: me; reason: intentional\n",
        )
        _patch_roots(monkeypatch, tmp_path)
        bb = _baseline_file(tmp_path)
        bb.parent.mkdir(parents=True, exist_ok=True)
        bb.write_text('{"fingerprints": []}', encoding="utf-8")

        csr.main([])

    def test_corrupt_baseline_fails_closed(self, tmp_path: Path, monkeypatch) -> None:
        _write_py_file(
            tmp_path,
            "mod.py",
            "x = 1  # noqa: F401; owner: me; reason: intentional\n",
        )
        _patch_roots(monkeypatch, tmp_path)
        bb = _baseline_file(tmp_path)
        bb.parent.mkdir(parents=True, exist_ok=True)
        bb.write_text("not json", encoding="utf-8")

        with pytest.raises(SystemExit) as exc_info:
            csr.main([])
        assert exc_info.value.code == 2

    def test_unreadable_source_fails_closed(self, tmp_path: Path, monkeypatch) -> None:
        _write_py_file(tmp_path, "mod.py", "x = 1  # noqa\n")
        _patch_roots(monkeypatch, tmp_path)

        def _boom(self, *_args, **_kwargs):
            raise OSError("simulated unreadable file")

        monkeypatch.setattr(Path, "read_text", _boom)
        with pytest.raises(SystemExit) as exc_info:
            csr.main([])
        assert exc_info.value.code == 2

    def test_partial_owner_only_fails(self, tmp_path: Path, monkeypatch) -> None:
        _write_py_file(tmp_path, "mod.py", "x = 1  # noqa: X; owner: me\n")
        _patch_roots(monkeypatch, tmp_path)

        with pytest.raises(SystemExit) as exc_info:
            csr.main([])
        assert exc_info.value.code == 1

    def test_misattached_owner_reason_other_line_fails(self, tmp_path: Path, monkeypatch) -> None:
        content = "# owner: me; reason: ok\nx = 1  # noqa\n"
        _write_py_file(tmp_path, "mod.py", content)
        _patch_roots(monkeypatch, tmp_path)

        with pytest.raises(SystemExit) as exc_info:
            csr.main([])
        assert exc_info.value.code == 1

    def test_suppression_text_in_string_ignored(self, tmp_path: Path, monkeypatch) -> None:
        _write_py_file(tmp_path, "mod.py", 'x = "# noqa"\n')
        _patch_roots(monkeypatch, tmp_path)

        csr.main([])

    def test_owner_reason_in_any_order(self, tmp_path: Path, monkeypatch) -> None:
        _write_py_file(
            tmp_path,
            "mod.py",
            "x = 1  # noqa: X; reason: it is safe; owner: jamie\n",
        )
        _patch_roots(monkeypatch, tmp_path)

        csr.main([])


class TestNewSuppressionKinds:
    """type: ignore, pyright: ignore, and coverage pragmas are now enforced."""

    def test_type_ignore_unformatted_fails(self, tmp_path: Path, monkeypatch) -> None:
        _write_py_file(tmp_path, "mod.py", "x = y  # type: ignore\n")
        _patch_roots(monkeypatch, tmp_path)

        with pytest.raises(SystemExit) as exc_info:
            csr.main([])
        assert exc_info.value.code == 1

    def test_pyright_ignore_unformatted_fails(self, tmp_path: Path, monkeypatch) -> None:
        _write_py_file(tmp_path, "mod.py", "x = y  # pyright: ignore[reportAny]\n")
        _patch_roots(monkeypatch, tmp_path)

        with pytest.raises(SystemExit) as exc_info:
            csr.main([])
        assert exc_info.value.code == 1

    def test_pragma_no_cover_unformatted_fails(self, tmp_path: Path, monkeypatch) -> None:
        _write_py_file(tmp_path, "mod.py", "if x:  # pragma: no cover\n")
        _patch_roots(monkeypatch, tmp_path)

        with pytest.raises(SystemExit) as exc_info:
            csr.main([])
        assert exc_info.value.code == 1

    def test_new_kinds_grandfathered_via_baseline(self, tmp_path: Path, monkeypatch) -> None:
        content = "x = y  # type: ignore\ny = z  # pyright: ignore[reportAny]\n"
        _write_py_file(tmp_path, "mod.py", content)
        _patch_roots(monkeypatch, tmp_path)

        csr.main(["--update-baseline"])
        csr.main([])

    def test_new_kind_formatted_passes(self, tmp_path: Path, monkeypatch) -> None:
        content = "x = y  # pyright: ignore[reportAny]; owner: me; reason: known gap\n"
        _write_py_file(tmp_path, "mod.py", content)
        _patch_roots(monkeypatch, tmp_path)

        csr.main([])


class TestFingerprintFormats:
    """Fingerprint format matches spec: filename:lineno:type."""

    def test_fingerprint_format(self) -> None:
        fp = csr._make_fingerprint("src/pkg/mod.py", 42, "noqa")
        assert fp == "src/pkg/mod.py:42:noqa"

    def test_any_owner_reason_detects(self) -> None:
        line = "# noqa: X; owner: quality-team; reason: intentional"
        assert csr._any_owner_reason(line)

    def test_any_owner_reason_missing_owner(self) -> None:
        line = "# noqa: X; reason: intentional"
        assert not csr._any_owner_reason(line)

    def test_any_owner_reason_missing_reason(self) -> None:
        line = "# noqa: X; owner: me"
        assert not csr._any_owner_reason(line)

    def test_any_owner_reason_empty_values(self) -> None:
        line = "# noqa: X; owner: ; reason: "
        assert not csr._any_owner_reason(line)  # empty values → no \S after colon
