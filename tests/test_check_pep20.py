"""Tests for the PEP 20 adherence analyser.

All tests are hermetic: the gh client is always faked, never a real network
call, and repo-mode tests walk small ``tmp_path`` fixture trees.
"""

from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path

import pytest

from scripts import check_pep20
from scripts._pep20_detectors import (
    DETECTORS,
    RUBRICS,
    VERDICT_RULES,
    verdict_for,
)
from scripts._pep20_metrics import collect_module_signals
from scripts._pep20_report import build_report, render_json, render_markdown
from scripts._pep20_scoping import (
    GhClient,
    GhError,
    added_line_ranges,
    in_pr,
    parse_diff_hunks,
)
from scripts._pep20_types import (
    NON_MECHANICAL,
    AggregateSignals,
    AphorismId,
    DiffEntry,
    Finding,
    FunctionMetrics,
    ModuleSignals,
    Severity,
    Verdict,
)

FIXTURE_GOOD = '"""A documented module."""\n\n\ndef documented(value: int) -> int:\n    """Return a value unchanged."""\n    return value\n'
FIXTURE_BAD = (
    "def leaky(data):\n"
    "    try:\n"
    "        return data\n"
    "    except ValueError:\n"
    "        pass\n"
    "    if len(data) > 3:\n"
    "        return data[:1]\n"
)


def _namespace(**kwargs: object) -> argparse.Namespace:
    """Build an argparse Namespace with PEP 20 defaults overridden by kwargs."""
    defaults = {
        "root": "src",
        "pr": None,
        "repo": None,
        "json": False,
        "output": None,
        "post_comment": False,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _finding(aphorism: AphorismId, line: int = 1) -> Finding:
    """Build a minimal Finding for verdict tests."""
    return Finding(
        aphorism=aphorism,
        severity=Severity.ERROR,
        code="test",
        path="x.py",
        line=line,
        end_line=line,
        message="test finding",
    )


class TestMetrics:
    """Signal extraction on synthetic sources (plan T007 item a)."""

    def test_silent_swallow_detected(self) -> None:
        module = collect_module_signals("try:\n    pass\nexcept ValueError:\n    pass\n", "a.py")
        assert module.silent_swallow_count == 1
        assert module.excepts[0].kind == "pass"

    def test_bare_except_detected(self) -> None:
        module = collect_module_signals("try:\n    pass\nexcept:\n    pass\n", "a.py")
        assert module.bare_except_count == 1
        assert module.excepts[0].kind == "bare"

    def test_logged_handler_not_silent(self) -> None:
        source = "try:\n    pass\nexcept OSError:\n    logger.warning('x')\n"
        module = collect_module_signals(source, "a.py")
        assert module.silent_swallow_count == 0
        assert module.excepts[0].kind == "logged"

    def test_parse_error_captured(self) -> None:
        module = collect_module_signals("def broken(\n", "a.py")
        assert module.parse_error is not None
        assert module.functions == ()

    def test_magic_number_in_comparison(self) -> None:
        module = collect_module_signals("if size > 3:\n    pass\n", "a.py")
        assert (1, 3) in module.magic_numbers

    def test_wildcard_import_detected(self) -> None:
        module = collect_module_signals("from os import *\n", "a.py")
        assert module.wildcard_import_count == 1

    def test_function_docstring_presence(self) -> None:
        module = collect_module_signals(FIXTURE_GOOD, "a.py")
        assert module.functions
        assert module.functions[0].has_docstring
        assert module.functions[0].arg_count == 1

    def test_long_line_flagged(self) -> None:
        long_line = "x = " + "a" * 120 + "\n"
        module = collect_module_signals(long_line, "a.py")
        assert module.long_line_count == 1
        assert module.long_lines[0][1] > 100

    def test_url_line_not_flagged(self) -> None:
        url_line = 'url = "https://example.com/' + "x" * 120 + '"\n'
        module = collect_module_signals(url_line, "a.py")
        assert module.long_line_count == 0


class TestDetectors:
    """Per-detector good and bad samples (plan T007 item b)."""

    def test_nineteen_detectors_registered(self) -> None:
        assert len(DETECTORS) == 19
        assert len(VERDICT_RULES) == 19
        assert len(RUBRICS) == 3
        assert set(RUBRICS) == set(NON_MECHANICAL)

    def test_complexity_detector_flags_high_cc(self) -> None:
        module = ModuleSignals(
            module_path="a.py",
            functions=(
                FunctionMetrics(
                    cc=9,
                    nesting_depth=2,
                    arg_count=2,
                    return_count=1,
                    statement_count=10,
                    has_docstring=True,
                    start_line=1,
                    end_line=5,
                ),
            ),
        )
        findings = DETECTORS[AphorismId.SIMPLE](module)
        assert any(f.code == "complexity" for f in findings)

    def test_errors_silent_detector_flags_swallow(self) -> None:
        module = ModuleSignals(
            module_path="a.py",
            excepts=(type("Ex", (), {"kind": "pass", "line": 4})(),),  # type: ignore[attr-defined]  # owner: test-infrastructure; reason: ad hoc ExceptMetrics record
        )
        findings = DETECTORS[AphorismId.ERRORS_SILENT](module)
        assert any(f.code == "silent-swallow" for f in findings)

    def test_non_mechanical_detectors_return_empty(self) -> None:
        for aphorism_id in sorted(NON_MECHANICAL):
            assert DETECTORS[aphorism_id](ModuleSignals(module_path="a.py")) == []

    def test_namespaces_detector_flags_init_without_all(self) -> None:
        module = ModuleSignals(
            module_path="pkg/__init__.py",
            has_all_in_init=False,
            code_line_count=1,
        )
        findings = DETECTORS[AphorismId.NAMESPACES](module)
        assert any(f.code == "missing-all" for f in findings)

    def test_namespaces_detector_accepts_all(self) -> None:
        module = ModuleSignals(
            module_path="pkg/__init__.py",
            has_all_in_init=True,
            code_line_count=1,
        )
        assert DETECTORS[AphorismId.NAMESPACES](module) == []

    def test_empty_signals_do_not_crash(self) -> None:
        for aphorism_id in sorted(AphorismId):
            DETECTORS[aphorism_id](ModuleSignals(module_path="a.py"))


class TestVerdicts:
    """Deterministic verdict rules (plan T007 item c)."""

    def test_strict_zero_findings_strong(self) -> None:
        assert verdict_for(AphorismId.SIMPLE, [], AggregateSignals()) is Verdict.STRONG

    def test_strict_below_threshold_moderate(self) -> None:
        findings = [_finding(AphorismId.SIMPLE) for _ in range(2)]
        assert verdict_for(AphorismId.SIMPLE, findings, AggregateSignals()) is Verdict.MODERATE

    def test_strict_at_threshold_weak(self) -> None:
        findings = [_finding(AphorismId.SIMPLE) for _ in range(5)]
        assert verdict_for(AphorismId.SIMPLE, findings, AggregateSignals()) is Verdict.WEAK

    def test_advisory_thresholds(self) -> None:
        assert verdict_for(AphorismId.NOW, [], AggregateSignals()) is Verdict.STRONG
        middle = [_finding(AphorismId.NOW) for _ in range(5)]
        assert verdict_for(AphorismId.NOW, middle, AggregateSignals()) is Verdict.MODERATE
        weak = [_finding(AphorismId.NOW) for _ in range(10)]
        assert verdict_for(AphorismId.NOW, weak, AggregateSignals()) is Verdict.WEAK

    def test_non_mechanical_not_assessable(self) -> None:
        for aphorism_id in sorted(NON_MECHANICAL):
            assert verdict_for(aphorism_id, [], AggregateSignals()) is Verdict.NOT_ASSESSABLE

    def test_readability_composite_strong(self) -> None:
        aggregates = AggregateSignals(
            function_total=10,
            docstring_function_count=9,
            comment_line_count=100,
            code_line_count=900,
        )
        assert verdict_for(AphorismId.READABILITY, [], aggregates) is Verdict.STRONG

    def test_readability_composite_weak(self) -> None:
        aggregates = AggregateSignals(
            function_total=10,
            docstring_function_count=4,
            comment_line_count=0,
            code_line_count=100,
        )
        assert verdict_for(AphorismId.READABILITY, [], aggregates) is Verdict.WEAK

    def test_easy_explain_composite(self) -> None:
        strong = AggregateSignals(function_total=10, easy_function_count=9)
        assert verdict_for(AphorismId.EASY_EXPLAIN, [], strong) is Verdict.STRONG
        weak = AggregateSignals(function_total=10, easy_function_count=5)
        assert verdict_for(AphorismId.EASY_EXPLAIN, [], weak) is Verdict.WEAK


class TestScoping:
    """Diff-hunk parsing and line intersection (plan T007 items d, e)."""

    def test_omitted_count_hunk(self) -> None:
        hunks = parse_diff_hunks("@@ -1 +1,6 @@\n-Hello\n+Hello World\n")
        assert hunks[0].start_line == 1
        assert hunks[0].length == 6

    def test_deleted_only_hunk(self) -> None:
        hunks = parse_diff_hunks("@@ -1,58 +0,0 @@\n-removed\n")
        assert hunks[0].length == 0
        assert hunks[0].start_line == 0

    def test_no_newline_metadata_ignored(self) -> None:
        patch = "@@ -1 +1,2 @@\n-old\n+new\n\\ No newline at end of file\n"
        assert len(parse_diff_hunks(patch)) == 1

    def test_added_line_ranges(self) -> None:
        ranges = added_line_ranges(parse_diff_hunks("@@ -5,3 +10,3 @@\n"))
        assert ranges == [(10, 12)]

    def test_in_pr_intersection(self) -> None:
        ranges = [(10, 12), (20, 25)]
        assert in_pr((11, 11), ranges)
        assert in_pr((12, 14), ranges)
        assert not in_pr((13, 13), ranges)
        assert not in_pr((26, 30), ranges)


class TestGhClient:
    """gh client parsing with a faked subprocess layer (plan T007 items f, o)."""

    def _client(self, files_text: str, content: str | None = None) -> GhClient:
        client = GhClient()
        meta = json.dumps(
            {
                "state": "OPEN",
                "baseSha": "base",
                "headSha": "head123",
                "baseRef": "master",
                "headRef": "patch",
            }
        )

        def run_gh(args: list[str], timeout: int = 60) -> str:
            joined = " ".join(args)
            if "/files" in joined:
                return files_text
            if ".content" in joined:
                assert content is not None
                return base64.b64encode(content.encode("utf-8")).decode("ascii")
            return meta

        client._run_gh = run_gh  # type: ignore[method-assign]  # owner: test-infrastructure; reason: inject canned subprocess output
        return client

    def test_pr_meta_parsed(self) -> None:
        client = self._client("")
        meta = client.pr_meta("owner/repo", 1)
        assert meta["headSha"] == "head123"

    def test_pr_files_flattened(self) -> None:
        files_text = (
            '{"filename":"a.py","status":"modified","additions":2,"deletions":0,'
            '"patch":"@@ -1 +1,2 @@"}\n'
            '{"filename":"b.py","status":"added","additions":1,"deletions":0,'
            '"patch":"@@ -1 +1,1 @@"}\n'
        )
        client = self._client(files_text)
        entries = client.pr_files("owner/repo", 1)
        assert [entry.filename for entry in entries] == ["a.py", "b.py"]
        assert all(entry.head_sha == "head123" for entry in entries)

    def test_pr_files_missing_patch_is_none(self) -> None:
        files_text = '{"filename":"a.py","status":"modified","additions":1,"deletions":0}\n'
        entries = self._client(files_text).pr_files("owner/repo", 1)
        assert entries[0].patch is None

    def test_fetch_head_file_decodes(self) -> None:
        client = self._client("", content='print("hi")\n')
        assert client.fetch_head_file("owner/repo", 1, "a.py", "head123") == 'print("hi")\n'

    def test_fetch_head_file_decodes_line_wrapped_base64(self) -> None:
        """gh wraps base64 at 76 chars; validate=False must ignore newlines."""
        long_content = 'x = "seventy"  # ' + "a" * 80 + "\n"
        wrapped = "\n".join(
            base64.b64encode(long_content.encode("utf-8")).decode("ascii")[index : index + 76]
            for index in range(0, len(base64.b64encode(long_content.encode("utf-8"))), 76)
        )
        client = self._client("", content=None)

        def run_gh(args: list[str], timeout: int = 60) -> str:
            return wrapped

        client._run_gh = run_gh  # type: ignore[method-assign]  # owner: test-infrastructure; reason: inject wrapped base64
        assert client.fetch_head_file("owner/repo", 1, "a.py", "head123") == long_content

    def test_gh_error_on_nonzero(self) -> None:
        client = GhClient()

        def fail(args: list[str], timeout: int = 60) -> str:
            raise GhError("gh api exited 1", "boom")

        client._run_gh = fail  # type: ignore[method-assign]  # owner: test-infrastructure; reason: inject failure
        with pytest.raises(GhError) as excinfo:
            client.pr_meta("owner/repo", 1)
        assert excinfo.value.stderr == "boom"


class TestReport:
    """Rendering determinism and schema (plan T007 items g, i)."""

    def _report(self) -> object:
        verdicts = {
            aphorism_id: Verdict.STRONG
            if aphorism_id not in NON_MECHANICAL
            else Verdict.NOT_ASSESSABLE
            for aphorism_id in AphorismId
        }
        return build_report(
            target="x",
            findings_by_aphorism={},
            verdicts=verdicts,
            aggregates=AggregateSignals(function_total=1),
            meta={"tool": "check_pep20"},
            unscoped_files=["large.py"],
            rubrics=RUBRICS,
        )

    def test_render_is_deterministic(self) -> None:
        report = self._report()
        first = render_markdown(report)
        assert render_markdown(report) == first
        assert render_json(report) == render_json(report)

    def test_markdown_has_all_nineteen_rows(self) -> None:
        text = render_markdown(self._report())
        row_count = len(
            [line for line in text.splitlines() if line.startswith("| ") and line[2].isdigit()]
        )
        assert row_count == 19

    def test_json_schema(self) -> None:
        payload = json.loads(render_json(self._report()))
        assert len(payload["aphorisms"]) == 19
        assert "summary" in payload
        assert payload["unscoped_files"] == ["large.py"]
        rubric_rows = [a for a in payload["aphorisms"] if not a["assessable"]]
        assert len(rubric_rows) == 3

    def test_unscoped_warning_rendered(self) -> None:
        assert "line-scope unavailable" in render_markdown(self._report())


class TestCli:
    """Repo-mode CLI behaviour (plan T007 items h, j, r, s)."""

    def test_repo_mode_self_assessment(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tmp_path / "good.py").write_text(FIXTURE_GOOD)
        (tmp_path / "bad.py").write_text(FIXTURE_BAD)
        args = _namespace(root=str(tmp_path))
        exit_code = check_pep20._run_repo_mode(args)
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "# PEP 20 Assessment" in captured.out
        assert "[silent-swallow]" in captured.out

    def test_repo_mode_bad_root_exits_2(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        args = _namespace(root=str(tmp_path / "missing"))
        assert check_pep20._run_repo_mode(args) == 2

    def test_repo_mode_json_output(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tmp_path / "good.py").write_text(FIXTURE_GOOD)
        args = _namespace(root=str(tmp_path), json=True)
        assert check_pep20._run_repo_mode(args) == 0
        payload = json.loads(capsys.readouterr().out)
        assert len(payload["aphorisms"]) == 19

    def test_output_path_writes_file(self, tmp_path: Path) -> None:
        (tmp_path / "good.py").write_text(FIXTURE_GOOD)
        out_path = tmp_path / "report.md"
        args = _namespace(root=str(tmp_path), output=str(out_path))
        assert check_pep20._run_repo_mode(args) == 0
        assert out_path.exists()
        assert out_path.read_text().startswith("# PEP 20 Assessment")

    def test_init_module_handling(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        package = tmp_path / "pkg"
        package.mkdir()
        (package / "__init__.py").write_text("from .mod import thing\n")
        (package / "mod.py").write_text("thing = 1\n")
        args = _namespace(root=str(tmp_path))
        check_pep20._run_repo_mode(args)
        assert "[missing-all]" in capsys.readouterr().out

    def test_parse_error_reported(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        (tmp_path / "broken.py").write_text("def x(\n")
        args = _namespace(root=str(tmp_path))
        check_pep20._run_repo_mode(args)
        assert "[parse-error]" in capsys.readouterr().out

    def test_main_exit_zero(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(check_pep20.sys, "argv", ["check_pep20.py", "--root", str(tmp_path)])
        with pytest.raises(SystemExit) as excinfo:
            check_pep20.main()
        assert excinfo.value.code == 0


class _FakeGh:
    """In-memory gh client returning canned PR data."""

    def __init__(self, files: list[DiffEntry], contents: dict[str, str]) -> None:
        """Initialise with files and head file contents."""
        self.files = files
        self.contents = contents
        self.posted: list[str] = []

    def pr_meta(self, repo: str, number: int) -> dict[str, str]:
        """Return a fixed PR metadata mapping."""
        return {
            "state": "OPEN",
            "baseSha": "base",
            "headSha": "head",
            "baseRef": "master",
            "headRef": "patch",
        }

    def pr_files(self, repo: str, number: int) -> list[DiffEntry]:
        """Return the canned changed files."""
        return self.files

    def fetch_head_file(self, repo: str, number: int, path: str, head_sha: str) -> str:
        """Return a canned head file, raising for unknown paths."""
        if path not in self.contents:
            raise GhError("not found", "404")
        return self.contents[path]

    def post_comment(self, repo: str, number: int, body: str) -> None:
        """Record a posted comment body."""
        self.posted.append(body)


def _entry(
    filename: str,
    status: str = "modified",
    patch: str | None = "@@ -1 +1,2 @@\n+x\n",
) -> DiffEntry:
    """Build a DiffEntry with sensible defaults."""
    return DiffEntry(
        filename=filename,
        status=status,
        previous_filename=None,
        additions=1,
        deletions=0,
        patch=patch,
        head_sha="head",
    )


class TestPrMode:
    """PR-mode orchestration with a mocked gh client (plan T007 items k-n, p)."""

    def _run(
        self,
        monkeypatch: pytest.MonkeyPatch,
        files: list[DiffEntry],
        contents: dict[str, str],
        post_comment: bool = False,
    ) -> tuple[int, str]:
        fake = _FakeGh(files, contents)
        monkeypatch.setattr(check_pep20, "GhClient", lambda: fake)
        args = _namespace(pr=7, repo="owner/repo", post_comment=post_comment)
        exit_code = check_pep20._run_pr_mode(args)
        return exit_code, fake

    def test_pr_mode_end_to_end_scopes_findings(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # a.py adds a silent swallow on lines 3-4 (in the added range)
        content = "def f():\n    try:\n        return 1\n    except ValueError:\n        pass\n"
        files = [_entry("a.py", patch="@@ -1,6 +1,6 @@\n     except ValueError:\n        pass\n")]
        exit_code, _fake = self._run(monkeypatch, files, {"a.py": content})
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "[silent-swallow]" in captured.out

    def test_removed_and_pure_rename_skipped(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        files = [
            _entry("removed.py", status="removed"),
            DiffEntry(
                filename="renamed.py",
                status="renamed",
                previous_filename="old.py",
                additions=0,
                deletions=0,
                patch=None,
                head_sha="head",
            ),
            _entry("keep.py"),
        ]
        exit_code, _fake = self._run(monkeypatch, files, {"keep.py": FIXTURE_GOOD})
        assert exit_code == 0
        # only keep.py assessed; neither removed nor rename errors
        assert "removed.py" not in capsys.readouterr().out

    def test_renamed_with_patch_analysed(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        files = [
            DiffEntry(
                filename="renamed.py",
                status="renamed",
                previous_filename="old.py",
                additions=1,
                deletions=0,
                patch="@@ -1 +1,1 @@\n+x\n",
                head_sha="head",
            )
        ]
        exit_code, _fake = self._run(monkeypatch, files, {"renamed.py": "x = 1\n"})
        assert exit_code == 0

    def test_non_python_files_filtered(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        files = [_entry("README.md"), _entry("docs/guide.md"), _entry("mod.py")]
        exit_code, _fake = self._run(monkeypatch, files, {"mod.py": FIXTURE_GOOD})
        assert exit_code == 0
        assert "README.md" not in capsys.readouterr().out

    def test_missing_patch_unscoped_warning(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        files = [_entry("big.py", patch=None)]
        exit_code, _fake = self._run(monkeypatch, files, {"big.py": FIXTURE_GOOD})
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "line-scope unavailable" in captured.out
        assert "big.py" in captured.out

    def test_pr_not_found_exits_2(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        class FailingGh:
            def pr_meta(self, repo: str, number: int) -> dict[str, str]:
                raise GhError("gh api exited 1", "not found")

            def pr_files(self, repo: str, number: int) -> list[DiffEntry]:
                raise GhError("gh api exited 1", "not found")

        monkeypatch.setattr(check_pep20, "GhClient", FailingGh)
        args = _namespace(pr=99999, repo="owner/repo")
        assert check_pep20._run_pr_mode(args) == 2
        assert "error" in capsys.readouterr().err

    def test_fetch_failure_reported_unscoped(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        files = [_entry("missing.py")]
        exit_code, _fake = self._run(monkeypatch, files, {})
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "missing.py" in captured.out

    def test_post_comment_only_when_requested(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        files = [_entry("mod.py")]
        exit_code, fake = self._run(monkeypatch, files, {"mod.py": FIXTURE_GOOD})
        assert exit_code == 0
        assert fake.posted == []

        exit_code, fake = self._run(monkeypatch, files, {"mod.py": FIXTURE_GOOD}, post_comment=True)
        assert exit_code == 0
        assert fake.posted and fake.posted[0].startswith("# PEP 20 Assessment")
