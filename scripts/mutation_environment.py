"""Installed Mutmut environment verification and identity.

Verifies the installed distribution against its RECORD, hashes every
file, and builds the authoritative environment identity block for
provenance-bound reports.
"""

from __future__ import annotations

import base64
import hashlib
import importlib.metadata
import platform
import subprocess  # nosec B404  # owner: quality-infrastructure; reason: internally assembled argv without a shell
import sys
from pathlib import Path

from scripts import mutation_policy as policy

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class EnvironmentMismatchError(RuntimeError):
    """Raised when the installed Mutmut environment cannot be verified."""


def _file_digest(path: Path) -> str:
    """Return the SHA-256 digest of a file's bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verify_record_entries(dist_root: Path, record: Path) -> tuple[dict[str, str], frozenset[str]]:
    """Hash every digest-bearing RECORD entry against actual bytes.

    Args:
        dist_root: Installed distribution root directory.
        record: Path to the dist-info ``RECORD`` file.

    Returns:
        Mapping of relative path to verified SHA-256 plus the full set of
        recorded paths (including digest-free entries such as ``RECORD``).

    Raises:
        EnvironmentMismatchError: If an entry is missing or tampered.
    """
    verified: dict[str, str] = {}
    listed: set[str] = set()
    for line in record.read_text(encoding="utf-8").splitlines():
        relative, expected, _size = line.rsplit(",", 2)
        listed.add(relative)
        if not expected:
            continue
        target = dist_root / relative
        if not target.is_file():
            msg = f"installed Mutmut file is missing: {relative}"
            raise EnvironmentMismatchError(msg)
        encoded = base64.urlsafe_b64encode(hashlib.sha256(target.read_bytes()).digest())
        if f"sha256={encoded.rstrip(b'=').decode()}" != expected:
            msg = f"installed Mutmut file is tampered: {relative}"
            raise EnvironmentMismatchError(msg)
        verified[relative] = _file_digest(target)
    return verified, frozenset(listed)


def _reject_unlisted_files(dist_root: Path, record: Path, listed: frozenset[str]) -> None:
    """Fail when installed Mutmut files are absent from ``RECORD``."""
    for parent in (dist_root / "mutmut", record.parent):
        for candidate in sorted(parent.rglob("*")):
            if not candidate.is_file():
                continue
            relative = candidate.relative_to(dist_root).as_posix()
            if relative not in listed:
                msg = f"installed Mutmut file is not recorded: {relative}"
                raise EnvironmentMismatchError(msg)


def _find_record() -> tuple[Path, Path]:
    """Locate the installed Mutmut distribution root and its RECORD file."""
    dist_info = f"mutmut-{policy.LOCKED_MUTMUT_VERSION}.dist-info"
    for entry in sys.path:
        record = Path(entry) / dist_info / "RECORD"
        if record.is_file():
            return record.parent.parent, record
    msg = f"Mutmut {dist_info} RECORD was not found on sys.path"
    raise EnvironmentMismatchError(msg)


def _distribution_identity() -> tuple[str, str]:
    """Verify the installed Mutmut tree and return its digests."""
    dist_root, record = _find_record()
    installed_version = importlib.metadata.version("mutmut")
    if installed_version != policy.LOCKED_MUTMUT_VERSION:
        msg = f"Mutmut version {installed_version} is not locked {policy.LOCKED_MUTMUT_VERSION}"
        raise EnvironmentMismatchError(msg)
    verified, listed = _verify_record_entries(dist_root, record)
    _reject_unlisted_files(dist_root, record, listed)
    record_digest = hashlib.sha256(record.read_bytes()).hexdigest()
    combined = "".join(f"{path}\0{digest}\n" for path, digest in sorted(verified.items()))
    return hashlib.sha256(combined.encode()).hexdigest(), record_digest


def _uv_version() -> str:
    """Return the installed uv version string."""
    result = subprocess.run(  # nosec B603  # owner: quality-infrastructure; reason: fixed uv argv without a shell
        ("uv", "--version"),
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if result.returncode != 0:
        msg = f"uv --version failed with status {result.returncode}"
        raise EnvironmentMismatchError(msg)
    return result.stdout.strip()


def _installed_distributions_digest() -> str:
    """Digest the sorted installed distribution inventory."""
    inventory = sorted(
        f"{dist.metadata['Name']}\0{dist.version}"
        for dist in importlib.metadata.distributions()
        if dist.metadata.get("Name")
    )
    payload = "".join(f"{entry}\n" for entry in inventory)
    return hashlib.sha256(payload.encode()).hexdigest()


def verify_environment() -> policy.EnvironmentIdentity:
    """Verify installed Mutmut and build authoritative environment identity.

    Returns:
        Complete environment identity for provenance-bound reports.

    Raises:
        EnvironmentMismatchError: If verification fails.
    """
    mutmut_digest, record_digest = _distribution_identity()
    return policy.EnvironmentIdentity(
        python_implementation=platform.python_implementation(),
        python_version=platform.python_version(),
        python_cache_tag=sys.implementation.cache_tag,
        platform=platform.platform(terse=True),
        uv_version=_uv_version(),
        installed_distributions_digest=_installed_distributions_digest(),
        mutmut_distribution_digest=mutmut_digest,
        mutmut_record_digest=record_digest,
        locked_wheel_filename=policy.LOCKED_WHEEL_FILENAME,
        locked_wheel_sha256=policy.LOCKED_WHEEL_SHA256,
    )
