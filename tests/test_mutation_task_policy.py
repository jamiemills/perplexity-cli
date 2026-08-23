"""Unit tests for the per-task mutation policy wrapper."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts import mutation_policy as policy
from scripts import mutation_task_policy as mtp


def _write_triage(tmp_path: Path, tasks: list[dict[str, Any]]) -> Path:
    path = tmp_path / "triage.json"
    path.write_text(json.dumps({"tasks": tasks}), encoding="utf-8")
    return path


def _task_entry(task_id: str = "T009", keys: list[str] | None = None) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "keys": keys if keys is not None else ["b.x__mutmut_2", "a.x__mutmut_1"],
        "total": len(keys) if keys is not None else 2,
        "categories": {"survived": len(keys) if keys is not None else 2},
    }


class TestLoadTaskKeys:
    def test_returns_sorted_exact_keys(self, tmp_path: Path) -> None:
        path = _write_triage(tmp_path, [_task_entry()])
        assert mtp.load_task_keys(path, "T009") == ("a.x__mutmut_1", "b.x__mutmut_2")

    def test_missing_task_fails_closed(self, tmp_path: Path) -> None:
        path = _write_triage(tmp_path, [_task_entry("T008")])
        with pytest.raises(mtp.TaskPolicyError, match="T009 missing"):
            mtp.load_task_keys(path, "T009")

    def test_empty_keyset_fails_closed(self, tmp_path: Path) -> None:
        path = _write_triage(tmp_path, [_task_entry(keys=[])])
        with pytest.raises(mtp.TaskPolicyError, match="empty keyset"):
            mtp.load_task_keys(path, "T009")

    def test_malformed_keyset_fails_closed(self, tmp_path: Path) -> None:
        entry = _task_entry()
        entry["keys"] = "not-a-list"
        path = _write_triage(tmp_path, [entry])
        with pytest.raises(mtp.TaskPolicyError, match="malformed"):
            mtp.load_task_keys(path, "T009")

    def test_unreadable_artifact_fails_closed(self, tmp_path: Path) -> None:
        with pytest.raises(mtp.TaskPolicyError, match="unreadable"):
            mtp.load_task_keys(tmp_path / "absent.json", "T009")


class TestVerifyReportCoverage:
    def _payload(self, keys: tuple[str, ...], **overrides: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "scope": {"kind": "selected", "patterns": list(keys)},
            "status": policy.STATUS_CLEAN,
            "total_mutants": len(keys),
        }
        payload.update(overrides)
        return payload

    def test_clean_exact_match_has_no_issues(self) -> None:
        keys = ("a.x__mutmut_1",)
        assert mtp.verify_report_coverage(self._payload(keys), keys) == []

    def test_pattern_mismatch_flagged(self) -> None:
        issues = mtp.verify_report_coverage(self._payload(("a.x__mutmut_1",)), ("b.y__mutmut_1",))
        assert issues == ["report scope patterns do not equal the task keyset"]

    def test_non_clean_status_flagged(self) -> None:
        keys = ("a.x__mutmut_1",)
        payload = self._payload(keys, status=policy.STATUS_FINDINGS)
        assert any("status" in issue for issue in mtp.verify_report_coverage(payload, keys))

    def test_total_mutants_mismatch_flagged(self) -> None:
        keys = ("a.x__mutmut_1", "b.x__mutmut_2")
        payload = self._payload(keys, total_mutants=1)
        assert any("total_mutants" in issue for issue in mtp.verify_report_coverage(payload, keys))

    def test_issues_are_sorted_and_deterministic(self) -> None:
        keys = ("a.x__mutmut_1",)
        payload = self._payload(keys, status="findings", total_mutants=9)
        issues = mtp.verify_report_coverage(payload, keys)
        assert issues == sorted(issues)


class TestLoadExclusions:
    def _write_exclusions(self, tmp_path: Path, entries: list[dict[str, Any]]) -> Path:
        path = tmp_path / "exclusions.json"
        path.write_text(json.dumps({"entries": entries}), encoding="utf-8")
        return path

    def _entry(self, **overrides: Any) -> dict[str, str]:
        record = {
            "task": "T009",
            "key": "a.x__mutmut_1",
            "disposition": "removed-by-simplification",
            "owner": "quality-infra",
            "reason": "mutation site deleted",
            "proof": "behaviour-equivalent rewrite verified",
        }
        record.update(overrides)
        return record

    def test_missing_file_yields_no_exclusions(self, tmp_path: Path) -> None:
        keys = ("a.x__mutmut_1",)
        assert mtp.load_exclusions(tmp_path / "absent.json", "T009", keys) == {}

    def test_valid_entry_loaded(self, tmp_path: Path) -> None:
        path = self._write_exclusions(tmp_path, [self._entry()])
        assert mtp.load_exclusions(path, "T009", ("a.x__mutmut_1",)) == {
            "a.x__mutmut_1": "removed-by-simplification"
        }

    def test_other_task_entries_ignored(self, tmp_path: Path) -> None:
        path = self._write_exclusions(tmp_path, [self._entry(task="T010")])
        assert mtp.load_exclusions(path, "T009", ("a.x__mutmut_1",)) == {}

    def test_unknown_key_fails_closed(self, tmp_path: Path) -> None:
        path = self._write_exclusions(tmp_path, [self._entry(key="zzz.y__mutmut_9")])
        with pytest.raises(mtp.TaskPolicyError, match="does not belong"):
            mtp.load_exclusions(path, "T009", ("a.x__mutmut_1",))

    def test_blank_provenance_fails_closed(self, tmp_path: Path) -> None:
        path = self._write_exclusions(tmp_path, [self._entry(proof="  ")])
        with pytest.raises(mtp.TaskPolicyError, match="provenance"):
            mtp.load_exclusions(path, "T009", ("a.x__mutmut_1",))

    def test_invalid_disposition_fails_closed(self, tmp_path: Path) -> None:
        path = self._write_exclusions(tmp_path, [self._entry(disposition="just-because")])
        with pytest.raises(mtp.TaskPolicyError, match="disposition"):
            mtp.load_exclusions(path, "T009", ("a.x__mutmut_1",))


class TestExecuteTaskValidation:
    def test_non_positive_timeout_fails_closed(self, tmp_path: Path) -> None:
        spec = mtp.TaskRunSpec(
            task_id="T009",
            triage_path=tmp_path / "t.json",
            report_path=tmp_path / "r.json",
            timeout_seconds=0,
        )
        with pytest.raises(mtp.TaskPolicyError, match="positive"):
            mtp.execute_task(spec)


class TestParseArgs:
    def test_defaults_apply(self) -> None:
        args = mtp.parse_args(["--task", "T009", "--report-path", "r.json"])
        assert args.triage_path == mtp.DEFAULT_TRIAGE_PATH
        assert args.timeout_seconds == mtp.DEFAULT_TIMEOUT_SECONDS

    def test_task_is_required(self) -> None:
        with pytest.raises(SystemExit):
            mtp.parse_args(["--report-path", "r.json"])
