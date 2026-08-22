"""Process-group management for Mutmut subprocess execution."""

from __future__ import annotations

import logging
import os
import signal
import subprocess  # nosec B404  # owner: quality-infrastructure; reason: internally assembled argv without a shell
import time
from pathlib import Path
from types import FrameType
from typing import Any

from scripts import mutation_policy as policy
from scripts.mutation_environment import EnvironmentMismatchError

logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _log_timeout(budget: int) -> None:
    """Log a budget overrun before group termination."""
    logger.error("Mutation run exceeded its %ss budget; terminating group", budget)


TERMINATION_GRACE_S = 5
_SANITISED_ENV_KEYS = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "VIRTUAL_ENV")


def _sanitised_environment() -> dict[str, str]:
    """Build a minimal credential-free, offline-forced child environment."""
    source = os.environ
    child = {key: source[key] for key in _SANITISED_ENV_KEYS if key in source}
    child["UV_OFFLINE"] = "1"
    return child


def _termination_grace_s() -> int:
    """Return the bounded teardown grace period before SIGKILL."""
    return TERMINATION_GRACE_S


def _terminate_process_group(process_group_id: int) -> None:
    """Terminate then kill one process group after a grace period."""
    for send in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(process_group_id, send)
        except ProcessLookupError:
            return
        if send == signal.SIGTERM:
            time.sleep(_termination_grace_s())


class _SignalForwarder:
    """Forward termination signals to the mutation process group."""

    def __init__(self) -> None:
        self.process_group_id: int | None = None

    def __call__(self, signum: int, _frame: FrameType | None) -> None:
        if self.process_group_id is not None:
            _terminate_process_group(self.process_group_id)
            self._exit(signum)

    @staticmethod
    def _exit(signum: int) -> None:
        forwarded = f"forwarded signal {signum} to the mutation group"
        raise SystemExit(forwarded)


def launch_mutmut(argv_suffix: tuple[str, ...], budget: int) -> None:
    """Run Mutmut inside its own process group with a hard budget.

    Args:
        argv_suffix: Arguments after ``run`` (patterns for selected scope).
        budget: Maximum seconds before controlled termination.

    Raises:
        EnvironmentMismatchError: On timeout or non-zero Mutmut exit.
    """
    command = (*policy.MUTMUT_PREFIX, "run", *argv_suffix)
    logger.info("Running %s with %ss budget", " ".join(command), budget)
    forwarder = _SignalForwarder()
    process = subprocess.Popen(  # nosec B603  # owner: quality-infrastructure; reason: pinned mutmut argv without a shell
        command,
        cwd=PROJECT_ROOT,
        env=_sanitised_environment(),
        start_new_session=True,
    )
    forwarder.process_group_id = os.getpgid(process.pid)
    previous = _install_forwarders(forwarder)
    try:
        returncode = process.wait(timeout=budget)
        _raise_on_infrastructure_exit(returncode)
    except subprocess.TimeoutExpired:
        _log_timeout(budget)
        _terminate_process_group(forwarder.process_group_id)
        msg = f"mutation run timed out after {budget}s"
        raise EnvironmentMismatchError(msg) from None
    finally:
        signal.signal(signal.SIGINT, previous[signal.SIGINT])
        signal.signal(signal.SIGTERM, previous[signal.SIGTERM])
        if process.poll() is None:
            _terminate_process_group(forwarder.process_group_id)
            process.kill()
            process.wait()


def _install_forwarders(forwarder: _SignalForwarder) -> dict[int, Any]:
    """Install SIGINT/SIGTERM forwarders and return the previous handlers."""
    signums: tuple[int, int] = (signal.SIGINT, signal.SIGTERM)
    previous: dict[int, Any] = {signum: signal.getsignal(signum) for signum in signums}
    for signum in signums:
        signal.signal(signum, forwarder)
    return previous


def _raise_on_infrastructure_exit(returncode: int) -> None:
    """Treat any Mutmut exit beyond clean/findings as an infrastructure error."""
    if returncode not in (0, 1):
        msg = f"mutmut exited with status {returncode}"
        raise EnvironmentMismatchError(msg)
