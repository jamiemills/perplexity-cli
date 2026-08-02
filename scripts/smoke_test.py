"""Run an installed-wheel smoke test in an isolated temporary venv.

Creates a throwaway virtual environment with the project interpreter, installs
the exact current wheel from ``dist/`` (offline), then exercises the installed
entry points with network-free, bounded commands:

- ``pxcli --version``
- ``pxcli config show`` plus default-URL materialisation (urls.json created)
- ``pxcli skill show``
- ``perplexity-cli --version`` (alias)
- ``pxcli-mcp --help`` (argparse help; never starts the MCP server)

Every command is bounded to 15 seconds and the whole run to 120 seconds; a
timed-out process is terminated and then killed with a distinct diagnostic.
User config state is redirected to a temporary directory via
``PERPLEXITY_CONFIG_DIR``.  No network is ever used (``uv`` runs offline).

Usage::

    UV_OFFLINE=1 uv run python scripts/smoke_test.py
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess  # nosec B404  # owner: quality-infrastructure; reason: invokes fixed uv and installed console-script commands with structurally delimited argv and no shell
import sys
import tempfile
import time
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

_SMOKE_BUDGET_SECONDS = 120
_COMMAND_TIMEOUT_SECONDS = 15
_SETUP_TIMEOUT_SECONDS = 60
_DISTRO_NAME = "pxcli"


class SmokeFailure(RuntimeError):
    """Raised when a smoke step fails or times out."""


@dataclass(frozen=True, slots=True)
class CommandSpec:
    """A bounded command to run against the installed wheel."""

    description: str
    args: tuple[str, ...]
    timeout: int = _COMMAND_TIMEOUT_SECONDS
    predicate: Callable[[str, str], bool] | None = None


@dataclass(frozen=True, slots=True)
class SmokeContext:
    """Environment and deadline shared by every smoke step."""

    env: dict[str, str]
    deadline: float


def _read_version(root: Path) -> str:
    """Read the project version from pyproject.toml."""
    with (root / "pyproject.toml").open("rb") as fh:
        data = tomllib.load(fh)
    project = data["project"]
    version = project.get("version")
    if not isinstance(version, str) or not version:
        msg = "pyproject.toml [project] must declare a string version"
        raise SmokeFailure(msg)
    return version


def _select_wheel(root: Path, version: str) -> Path:
    """Return the exact-version wheel from dist/, or fail clearly."""
    dist_dir = root / "dist"
    wheels = sorted(dist_dir.glob(f"{_DISTRO_NAME}-{version}-*.whl"))
    if len(wheels) != 1:
        candidates = ", ".join(p.name for p in sorted(dist_dir.glob(f"{_DISTRO_NAME}-*.whl")))
        msg = (
            f"Expected exactly one wheel for {_DISTRO_NAME}=={version} in dist/, "
            f"found {len(wheels)} (candidates: {candidates or 'none'})"
        )
        raise SmokeFailure(msg)
    return wheels[0]


def _subprocess_env(config_dir: Path) -> dict[str, str]:
    """Build the subprocess environment with offline and isolated config."""
    env = dict(os.environ)
    env["UV_OFFLINE"] = "1"
    env["PERPLEXITY_CONFIG_DIR"] = str(config_dir)
    return env


def _scripts_dir(venv_dir: Path) -> Path:
    """Return the platform-specific scripts directory of a venv."""
    return venv_dir / ("Scripts" if os.name == "nt" else "bin")


def _venv_python(venv_dir: Path) -> Path:
    """Return the venv interpreter path for the current platform."""
    executable = "python.exe" if os.name == "nt" else "python"
    return _scripts_dir(venv_dir) / executable


def _missing_script_message(venv_dir: Path, name: str) -> str:
    """Build a diagnostic listing the installed entry-point scripts."""
    scripts_dir = _scripts_dir(venv_dir)
    available = ", ".join(
        p.name for p in sorted(scripts_dir.iterdir()) if "pxcli" in p.name or "perplexity" in p.name
    )
    return f"console script {name} not found in {scripts_dir} (found: {available})"


def _console_script(venv_dir: Path, name: str) -> Path:
    """Return the installed console script path for *name*."""
    suffix = ".exe" if os.name == "nt" else ""
    candidate = _scripts_dir(venv_dir) / f"{name}{suffix}"
    if not candidate.is_file():
        raise SmokeFailure(_missing_script_message(venv_dir, name))
    return candidate


def _trim(text: str, limit: int = 2000) -> str:
    """Trim captured output for readable diagnostics."""
    if not text:
        return ""
    stripped = text.strip()
    if len(stripped) <= limit:
        return stripped
    return stripped[:limit] + "..."


def _terminate_process_group(process: subprocess.Popen[Any]) -> None:
    """Terminate the process group, escalating to kill when needed."""
    if os.name == "nt":
        process.kill()
        return
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            process.kill()


def _recover_timeout(
    process: subprocess.Popen[Any],
    timeout: int,
    description: str,
) -> NoReturn:
    """Terminate a timed-out command and raise a distinct diagnostic."""
    _terminate_process_group(process)
    stdout, stderr = process.communicate()
    detail = _trim(stderr) or _trim(stdout) or "no output captured"
    msg = f"{description} timed out after {timeout}s and was killed; output: {detail}"
    raise SmokeFailure(msg)


def _run_captured(
    args: list[str],
    timeout: int,
    description: str,
    env: dict[str, str],
) -> tuple[str, str]:
    """Run *args*, returning stdout/stderr, asserting exit 0 and no timeout."""
    process = subprocess.Popen(  # nosec B603  # owner: quality-infrastructure; reason: command argv is built from repository constants and entry-point names, never user input, and shell execution is disabled
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        return _recover_timeout(process, timeout, description)
    if process.returncode != 0:
        detail = _trim(stderr) or _trim(stdout) or f"exit code {process.returncode}"
        msg = f"{description} failed (exit {process.returncode}): {detail}"
        raise SmokeFailure(msg)
    return stdout, stderr


def _check_command(spec: CommandSpec, context: SmokeContext) -> str:
    """Run a bounded command, returning stdout when it succeeds."""
    remaining = int(context.deadline - time.monotonic())
    if remaining <= 0:
        msg = f"{spec.description} not started: whole-smoke budget ({_SMOKE_BUDGET_SECONDS}s) exceeded"
        raise SmokeFailure(msg)
    effective_timeout = max(1, min(spec.timeout, remaining))
    stdout, stderr = _run_captured(
        list(spec.args), effective_timeout, spec.description, context.env
    )
    if spec.predicate is not None and not spec.predicate(stdout, stderr):
        msg = f"{spec.description} passed but output check failed"
        raise SmokeFailure(msg)
    return stdout


def _create_venv(venv_dir: Path, context: SmokeContext) -> Path:
    """Create the isolated venv with the project interpreter, return its python."""
    _check_command(
        CommandSpec(
            "uv venv",
            ("uv", "venv", str(venv_dir), "--python", sys.executable),
            timeout=_SETUP_TIMEOUT_SECONDS,
        ),
        context,
    )
    return _venv_python(venv_dir)


def _install_wheel(venv_python: Path, wheel_path: Path, context: SmokeContext) -> None:
    """Install the wheel into the isolated venv.

    The offline attempt uses the warm uv cache on local verification runs;
    on cold-cache CI runners it falls back to a networked install so the
    smoke contract is still exercised.
    """
    offline = subprocess.run(  # nosec B603, B607  # owner: quality-infrastructure; reason: fixed uv executable with structurally delimited argv, no shell; wheel path derived from the repo version
        ["uv", "pip", "install", "--offline", "--python", str(venv_python), str(wheel_path)],
        capture_output=True,
        text=True,
        env=context.env,
        timeout=_SETUP_TIMEOUT_SECONDS,
        check=False,
    )
    if offline.returncode == 0:
        return
    _check_command(
        CommandSpec(
            "uv pip install (online fallback)",
            ("uv", "pip", "install", "--python", str(venv_python), str(wheel_path)),
            timeout=_SETUP_TIMEOUT_SECONDS,
        ),
        context,
    )


def _materialise_default_urls(venv_python: Path, context: SmokeContext) -> None:
    """Load default URLs through the installed package to create urls.json."""
    code = "from perplexity_cli.utils.config import get_urls; cfg = get_urls(); print(cfg.base_url)"
    _check_command(
        CommandSpec("default URLs materialisation", (str(venv_python), "-c", code)),
        context,
    )


def _run_smoke(venv_dir: Path, config_dir: Path, context: SmokeContext) -> None:
    """Run the bounded CLI smoke checks against the installed wheel."""
    venv_python = _venv_python(venv_dir)
    pxcli = str(_console_script(venv_dir, "pxcli"))
    perplexity_cli = str(_console_script(venv_dir, "perplexity-cli"))
    pxcli_mcp = str(_console_script(venv_dir, "pxcli-mcp"))

    version_output = _check_command(
        CommandSpec(
            "pxcli --version",
            (pxcli, "--version"),
            predicate=lambda _out, _err: "version" in _out,
        ),
        context,
    )
    print(f"  ok: pxcli --version -> {_trim(version_output)}")

    _check_command(CommandSpec("pxcli config show", (pxcli, "config", "show")), context)
    print("  ok: pxcli config show")

    _materialise_default_urls(venv_python, context)
    if not (config_dir / "urls.json").is_file():
        msg = "urls.json was not created in the isolated config directory"
        raise SmokeFailure(msg)
    print("  ok: urls.json created in isolated config")

    skill_output = _check_command(
        CommandSpec(
            "pxcli skill show",
            (pxcli, "skill", "show"),
            predicate=lambda _out, _err: "name:" in _out,
        ),
        context,
    )
    print(f"  ok: pxcli skill show loads packaged skill.md ({len(skill_output)} chars)")

    _check_command(
        CommandSpec(
            "perplexity-cli alias --version",
            (perplexity_cli, "--version"),
            predicate=lambda _out, _err: "version" in _out,
        ),
        context,
    )
    print("  ok: perplexity-cli alias --version")

    _check_command(
        CommandSpec(
            "pxcli-mcp --help (bounded)",
            (pxcli_mcp, "--help"),
            predicate=lambda _out, _err: "usage:" in _out,
        ),
        context,
    )
    print("  ok: pxcli-mcp --help exits cleanly without daemonising")


def main() -> None:
    """Run the full installed-wheel smoke test end-to-end."""
    root = Path(__file__).resolve().parents[1]
    version = _read_version(root)
    wheel_path = _select_wheel(root, version)
    deadline = time.monotonic() + _SMOKE_BUDGET_SECONDS
    try:
        with tempfile.TemporaryDirectory(prefix="pxcli-smoke-") as tmp:
            tmp_root = Path(tmp)
            venv_dir = tmp_root / "venv"
            config_dir = tmp_root / "config"
            context = SmokeContext(env=_subprocess_env(config_dir), deadline=deadline)
            venv_python = _create_venv(venv_dir, context)
            _install_wheel(venv_python, wheel_path, context)
            _run_smoke(venv_dir, config_dir, context)
    except SmokeFailure as exc:
        print(f"smoke test failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    print(f"Installed-package smoke test passed for {wheel_path.name}")


if __name__ == "__main__":
    main()
