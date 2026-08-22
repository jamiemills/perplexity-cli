"""Process-level CLI contract tests.

These tests exercise the real CLI entry point (``python -m
perplexity_cli.cli``) as a separate subprocess, asserting the process
contract: exit codes, byte-level channel separation, stdin handling, and
signal behaviour.  Every command is deterministic and non-networked; the
query API boundary is replaced with a mocked gateway where a query is
needed.
"""

from __future__ import annotations

import json
import os
import select
import signal
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC_ROOT = _REPO_ROOT / "src"

_ORDINARY_TIMEOUT = 10
_SIGNAL_TIMEOUT = 15
_CHILD_TERMINATION_TIMEOUT = 5

_MOCK_SCRIPT = """
import sys

from perplexity_cli.api.models import Answer
from perplexity_cli.utils.exceptions import (
    PerplexityHTTPStatusError,
    SimpleRequest,
    SimpleResponse,
)

MODE = sys.argv[1]
CLI_ARGS = sys.argv[2:]


class _MockGateway:
    \"\"\"Deterministic QueryGateway used at the boundary for process tests.\"\"\"

    def __init__(self, token=None, cookies=None, timeout=None):
        self.token = token
        self.cookies = cookies
        self.timeout = timeout

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def close(self):
        return None

    def submit_query(self, query_input):
        raise AssertionError("submit_query must not be used in process tests")

    def get_complete_answer(self, query, search_implementation_mode="standard", **extra):
        if MODE == "error503":
            raise PerplexityHTTPStatusError(
                "HTTP 503: service unavailable",
                request=SimpleRequest(method="POST", url="https://www.perplexity.ai/api/query"),
                response=SimpleResponse(status_code=503, text="service unavailable"),
            )
        if MODE == "big":
            return Answer(text="x" * 500_000, references=[])
        if MODE == "sleep":
            sys.stderr.write("READY\\n")
            sys.stderr.flush()
            import time

            time.sleep(60)
        return Answer(text="mocked answer: " + query, references=[])


import perplexity_cli.query_deps as _query_deps

import perplexity_cli.cli  # noqa: E402  # owner: quality-infrastructure; reason: composition root must bind before the test override

from dataclasses import replace as _dc_replace

_query_deps.set_query_deps(
    _dc_replace(_query_deps.require_query_deps(), PerplexityAPI=_MockGateway)
)

from perplexity_cli.cli import main  # noqa: E402  # owner: quality-infrastructure; reason: entry point imported after the override is installed

sys.argv = ["pxcli"] + CLI_ARGS
main()
"""


def _cli_env() -> dict[str, str]:
    """Build a clean-ish environment for CLI subprocesses."""
    env = dict(os.environ)
    env["NO_COLOR"] = "1"
    env["PYTHONPATH"] = str(_SRC_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    return env


def _write_mock_script(tmp_path: Path) -> Path:
    """Write the boundary-mock helper script and return its path."""
    script = tmp_path / "mock_query_api.py"
    script.write_text(_MOCK_SCRIPT, encoding="utf-8")
    return script


def _run_cli(
    *args: str,
    input_bytes: bytes | None = None,
    timeout: int = _ORDINARY_TIMEOUT,
) -> subprocess.CompletedProcess[bytes]:
    """Run the real CLI entry point in a subprocess."""
    return subprocess.run(
        [sys.executable, "-m", "perplexity_cli.cli", *args],
        capture_output=True,
        input=input_bytes,
        timeout=timeout,
        cwd=_REPO_ROOT,
        env=_cli_env(),
    )


def _run_mock(
    script: Path,
    mode: str,
    *cli_args: str,
    input_bytes: bytes | None = None,
    timeout: int = _ORDINARY_TIMEOUT,
) -> subprocess.CompletedProcess[bytes]:
    """Run the CLI with the query boundary mocked in a subprocess."""
    return subprocess.run(
        [sys.executable, str(script), mode, *cli_args],
        capture_output=True,
        input=input_bytes,
        timeout=timeout,
        cwd=_REPO_ROOT,
        env=_cli_env(),
    )


class TestProcessContract:
    """Basic process contract: help, version, and unknown commands."""

    def test_help_exits_0_with_help_on_stdout(self):
        result = _run_cli("--help")
        assert result.returncode == 0
        assert b"Usage:" in result.stdout
        assert b"Perplexity CLI" in result.stdout
        assert result.stderr == b""

    def test_version_exits_0(self):
        result = _run_cli("--version")
        assert result.returncode == 0
        assert b"version" in result.stdout
        assert result.stderr == b""

    def test_invalid_command_exits_nonzero_with_usage_on_stderr(self):
        result = _run_cli("definitely-not-a-command")
        assert result.returncode != 0
        assert result.returncode == 2
        assert b"Usage:" in result.stderr
        assert b"No such command" in result.stderr
        assert result.stdout == b""


class TestStdinPiping:
    """Deterministic stdin handling through the real CLI."""

    def test_empty_stdin_to_query_dash_exits_2(self):
        result = _run_cli("query", "-", input_bytes=b"")
        assert result.returncode == 2
        assert result.stdout == b""
        assert b"empty input from stdin" in result.stderr

    def test_piped_query_through_mocked_boundary(self, tmp_path):
        script = _write_mock_script(tmp_path)
        result = _run_mock(
            script,
            "success",
            "query",
            "-",
            "--json",
            input_bytes=b"What is the capital of France?",
        )
        assert result.returncode == 0
        assert result.stderr == b""
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        assert payload["command"] == "pxcli query --json"
        assert payload["result"]["answer"] == "mocked answer: What is the capital of France?"


class TestUnifiedExitCodePolicy:
    """The same query failure must exit with the same taxonomy code in both modes."""

    def test_json_mode_failure_is_clean_json_with_taxonomy_code(self, tmp_path):
        script = _write_mock_script(tmp_path)
        result = _run_mock(script, "error503", "query", "--json", "hello")
        assert result.returncode == 6
        assert result.stderr == b""
        payload = json.loads(result.stdout)
        assert payload["ok"] is False
        assert payload["error"]["code"] == "network_error"

    def test_human_mode_failure_is_human_text_with_same_taxonomy_code(self, tmp_path):
        script = _write_mock_script(tmp_path)
        result = _run_mock(script, "error503", "query", "hello")
        assert result.returncode == 6
        assert result.stdout == b""
        assert b"Error: HTTP 503: service unavailable" in result.stderr

    def test_validation_failure_json_mode_exits_1(self):
        result = _run_cli("query", "--json", "--request-param", "missing-equals", "hello")
        assert result.returncode == 1
        payload = json.loads(result.stdout)
        assert payload["ok"] is False
        assert payload["error"]["code"] == "validation_error"


class TestSignalHandling:
    """Signal handling where portable."""

    def test_sigint_exits_130(self, tmp_path):
        if not hasattr(signal, "SIGINT"):
            pytest.skip("SIGINT is not supported on this platform")
        script = _write_mock_script(tmp_path)
        proc = subprocess.Popen(
            [sys.executable, str(script), "sleep", "query", "hello"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=_REPO_ROOT,
            env=_cli_env(),
        )
        try:
            ready, _, _ = select.select([proc.stderr], [], [], _SIGNAL_TIMEOUT)
            assert ready, "child never signalled readiness within timeout"
            assert proc.stderr.readline().strip() == b"READY"
            proc.send_signal(signal.SIGINT)
            proc.wait(timeout=_SIGNAL_TIMEOUT)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=_CHILD_TERMINATION_TIMEOUT)

        assert proc.returncode == 130
        assert proc.stdout.read() == b""
        assert b"Query interrupted" in proc.stderr.read()


class TestBrokenPipe:
    """Broken-pipe handling where portable."""

    def test_broken_pipe_exits_quietly(self, tmp_path):
        script = _write_mock_script(tmp_path)
        proc = subprocess.Popen(
            [sys.executable, str(script), "big", "query", "--json", "hello"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=_REPO_ROOT,
            env=_cli_env(),
        )
        try:
            proc.stdout.close()
            proc.wait(timeout=_SIGNAL_TIMEOUT)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=_CHILD_TERMINATION_TIMEOUT)

        stderr_bytes = proc.stderr.read()
        assert proc.returncode == 1
        assert b"Traceback" not in stderr_bytes
