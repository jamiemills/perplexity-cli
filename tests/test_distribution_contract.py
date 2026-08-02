"""Contracts for the built distributions and the Windows CI topology.

A session-scoped fixture ensures ``dist/`` holds artefacts built from the
current source (running ``uv build`` once, offline, when the exact-version
wheel or sdist is missing).  The tests then assert, for the exact version in
``pyproject.toml``:

- the wheel and sdist bundle both declared resources, register all three
  console entry points, and carry name/version/licence/readme metadata;
- the wheel imports as the installed distribution (not the ``src/`` tree)
  inside an isolated venv, with ``skill.md`` loadable via
  ``importlib.resources``;
- the declared Windows CI topology for T030 (job name, entry points, artefact
  source, bounded smoke commands) is self-consistent and matches the built
  artefacts, without executing anything Windows-specific locally.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
_DISTRO_NAME = "pxcli"
_WINDOWS_CI_JOB_NAME = "windows_packaging_smoke"
_WINDOWS_CI_ENTRY_POINTS = frozenset({"pxcli", "perplexity-cli", "pxcli-mcp"})
_WINDOWS_CI_ARTIFACT = "wheel"
_NETWORK_SUBCOMMANDS = frozenset({"query", "auth", "threads", "models", "doctor"})
_WINDOWS_CI_SMOKE_COMMANDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("pxcli", ("--version",)),
    ("pxcli", ("config", "show")),
    ("pxcli", ("skill", "show")),
    ("perplexity-cli", ("--version",)),
    ("pxcli-mcp", ("--help",)),
)
_FORBIDDEN_BASENAMES = frozenset({".coverage", ".env", ".env.local"})
_FORBIDDEN_COMPONENTS = frozenset({"tests", "__pycache__"})


@dataclass(frozen=True, slots=True)
class WindowsCITopology:
    """Declared Windows CI requirements that T030 must implement."""

    job_name: str
    artifact: str
    entry_points: frozenset[str]
    artifact_source_glob: str
    smoke_commands: tuple[tuple[str, tuple[str, ...]], ...]


def _pyproject_version() -> str:
    """Read the project version from pyproject.toml."""
    with (REPO_ROOT / "pyproject.toml").open("rb") as fh:
        project = tomllib.load(fh)["project"]
    version = project["version"]
    assert isinstance(version, str) and version
    return version


def _windows_ci_topology(version: str) -> WindowsCITopology:
    """Return the declared Windows CI topology for T030."""
    return WindowsCITopology(
        job_name=_WINDOWS_CI_JOB_NAME,
        artifact=_WINDOWS_CI_ARTIFACT,
        entry_points=_WINDOWS_CI_ENTRY_POINTS,
        artifact_source_glob=f"{_DISTRO_NAME}-{version}-py3-none-any.whl",
        smoke_commands=_WINDOWS_CI_SMOKE_COMMANDS,
    )


@pytest.fixture(scope="session")
def built_distributions() -> tuple[Path, Path, str]:
    """Ensure dist/ holds the exact-version wheel and sdist, built offline."""
    version = _pyproject_version()
    wheel = REPO_ROOT / "dist" / f"{_DISTRO_NAME}-{version}-py3-none-any.whl"
    sdist = REPO_ROOT / "dist" / f"{_DISTRO_NAME}-{version}.tar.gz"
    if not wheel.is_file() or not sdist.is_file():
        env = dict(os.environ)
        env["UV_OFFLINE"] = "1"
        result = subprocess.run(
            ["uv", "build"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            env=env,
            timeout=300,
            check=False,
        )
        assert result.returncode == 0, f"uv build failed:\n{result.stdout}\n{result.stderr}"
    assert wheel.is_file(), f"wheel missing after build: {wheel}"
    assert sdist.is_file(), f"sdist missing after build: {sdist}"
    return wheel, sdist, version


def _wheel_members(wheel: Path) -> set[str]:
    """Return the set of member names inside a wheel."""
    with zipfile.ZipFile(wheel) as archive:
        return set(archive.namelist())


def _parse_console_scripts(text: str) -> frozenset[str]:
    """Return the console script names declared in entry-points text."""
    names: set[str] = set()
    section = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            section = stripped == "[console_scripts]"
            continue
        if section and "=" in stripped and not stripped.startswith(("#", ";")):
            names.add(stripped.split("=", 1)[0].strip())
    return frozenset(names)


def _wheel_entry_points(wheel: Path) -> frozenset[str]:
    """Return the console script names registered in the wheel metadata."""
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        entry_points_members = [name for name in names if name.endswith("entry_points.txt")]
        assert entry_points_members, f"wheel {wheel.name} has no entry_points.txt"
        text = archive.read(entry_points_members[0]).decode("utf-8")
    return _parse_console_scripts(text)


def _metadata_headers(text: str) -> dict[str, str]:
    """Parse RFC-822 style metadata headers into a dict."""
    headers: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip():
            break
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.strip()] = value.strip()
    return headers


def _metadata_description(text: str) -> str:
    """Return the metadata description body after the header block."""
    lines = text.splitlines()
    try:
        first_blank = lines.index("")
    except ValueError:
        return ""
    return "\n".join(lines[first_blank + 1 :])


def _read_tar_text(archive: tarfile.TarFile, member: str) -> str | None:
    """Return decoded text for a tar member, or None when unreadable."""
    fileobj = archive.extractfile(member)
    if fileobj is None:
        return None
    with fileobj:
        return fileobj.read().decode("utf-8")


def _assert_hygiene(member_names: set[str], prefix: str) -> None:
    """Assert no tests, caches or secrets are bundled inside an artefact."""
    for member in sorted(member_names):
        relative = member[len(prefix) :] if member.startswith(prefix) else member
        components = relative.split("/")
        assert not set(components) & _FORBIDDEN_COMPONENTS, (
            f"artefact ships forbidden component: {member}"
        )
        assert Path(relative).name not in _FORBIDDEN_BASENAMES, (
            f"artefact ships forbidden file: {member}"
        )


def test_wheel_bundles_resources_and_metadata(
    built_distributions: tuple[Path, Path, str],
) -> None:
    """The wheel contains both resources, metadata and the licence file."""
    wheel, _sdist, version = built_distributions
    members = _wheel_members(wheel)
    dist_info = f"{_DISTRO_NAME}-{version}.dist-info"
    for resource in ("perplexity_cli/config/urls.json", "perplexity_cli/resources/skill.md"):
        assert resource in members, f"wheel missing resource {resource}"
    assert f"{dist_info}/entry_points.txt" in members
    assert f"{dist_info}/METADATA" in members
    assert f"{dist_info}/WHEEL" in members
    assert f"{dist_info}/RECORD" in members
    assert f"{dist_info}/licenses/LICENSE" in members


def test_wheel_registers_all_entry_points(built_distributions: tuple[Path, Path, str]) -> None:
    """The wheel metadata registers pxcli, perplexity-cli and pxcli-mcp."""
    wheel, _sdist, _version = built_distributions
    assert _wheel_entry_points(wheel) == _WINDOWS_CI_ENTRY_POINTS


def test_wheel_metadata_fields(built_distributions: tuple[Path, Path, str]) -> None:
    """The wheel METADATA carries name, version, licence and readme."""
    wheel, _sdist, version = built_distributions
    with zipfile.ZipFile(wheel) as archive:
        metadata_text = archive.read(f"{_DISTRO_NAME}-{version}.dist-info/METADATA").decode("utf-8")
    headers = _metadata_headers(metadata_text)
    assert headers["Name"] == _DISTRO_NAME
    assert headers["Version"] == version
    assert headers["License-Expression"] == "MIT"
    assert headers["Description-Content-Type"] == "text/markdown"
    assert _metadata_description(metadata_text).strip()


def test_wheel_hygiene(built_distributions: tuple[Path, Path, str]) -> None:
    """The wheel ships no tests, caches or secrets."""
    wheel, _sdist, _version = built_distributions
    _assert_hygiene(_wheel_members(wheel), prefix="")


def test_sdist_bundles_resources_and_metadata(
    built_distributions: tuple[Path, Path, str],
) -> None:
    """The sdist contains resources, PKG-INFO, README and LICENSE."""
    _wheel, sdist, version = built_distributions
    prefix = f"{_DISTRO_NAME}-{version}/"
    with tarfile.open(sdist) as archive:
        names = set(archive.getnames())
        for resource in (
            f"{prefix}src/perplexity_cli/config/urls.json",
            f"{prefix}src/perplexity_cli/resources/skill.md",
        ):
            assert resource in names, f"sdist missing resource {resource}"
        assert f"{prefix}README.md" in names
        assert f"{prefix}LICENSE" in names
        assert f"{prefix}PKG-INFO" in names
        pkg_info_text = _read_tar_text(archive, f"{prefix}PKG-INFO")
        entry_text = _read_tar_text(archive, f"{prefix}src/pxcli.egg-info/entry_points.txt")

    assert pkg_info_text is not None
    headers = _metadata_headers(pkg_info_text)
    assert headers["Name"] == _DISTRO_NAME
    assert headers["Version"] == version
    assert headers["License-Expression"] == "MIT"
    assert _metadata_description(pkg_info_text).strip()

    assert entry_text is not None
    assert _parse_console_scripts(entry_text) == _WINDOWS_CI_ENTRY_POINTS


def test_sdist_hygiene(built_distributions: tuple[Path, Path, str]) -> None:
    """The sdist ships no tests, caches or secrets."""
    _wheel, sdist, version = built_distributions
    prefix = f"{_DISTRO_NAME}-{version}/"
    with tarfile.open(sdist) as archive:
        names = set(archive.getnames())
    _assert_hygiene(names, prefix=prefix)


def test_wheel_imports_as_installed_distribution(
    built_distributions: tuple[Path, Path, str],
    tmp_path: Path,
) -> None:
    """The wheel imports from the venv site-packages, never the src/ tree."""
    wheel, _sdist, version = built_distributions
    env = dict(os.environ)
    env["UV_OFFLINE"] = "1"
    venv_dir = tmp_path / "venv"

    result = subprocess.run(
        ["uv", "venv", str(venv_dir), "--python", sys.executable],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0, f"uv venv failed:\n{result.stderr}"

    venv_python = (
        venv_dir
        / ("Scripts" if os.name == "nt" else "bin")
        / ("python.exe" if os.name == "nt" else "python")
    )
    result = subprocess.run(
        ["uv", "pip", "install", "--offline", "--python", str(venv_python), str(wheel)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
        timeout=180,
        check=False,
    )
    if result.returncode != 0:
        # Cold-cache CI runners may lack the wheel's runtime deps in the uv
        # cache; fall back to a networked install so the contract is tested.
        result = subprocess.run(
            ["uv", "pip", "install", "--python", str(venv_python), str(wheel)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            env=env,
            timeout=180,
            check=False,
        )
    assert result.returncode == 0, f"uv pip install failed:\n{result.stderr}"

    probe = (
        "import json, importlib.metadata as md, importlib.resources as res;"
        "mod = __import__('perplexity_cli');"
        "skill = res.files('perplexity_cli.resources').joinpath('skill.md').read_text();"
        "out = {'file': mod.__file__, 'version': md.version('pxcli'), 'skill_ok': 'name:' in skill};"
        "print(json.dumps(out))"
    )
    result = subprocess.run(
        [str(venv_python), "-c", probe],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, f"venv import probe failed:\n{result.stderr}"

    payload = json.loads(result.stdout)
    assert not payload["file"].startswith(str(REPO_ROOT / "src")), (
        f"import resolved to src tree, not the installed wheel: {payload['file']}"
    )
    assert payload["version"] == version
    assert payload["skill_ok"]


def test_windows_ci_topology_is_declared_and_consistent(
    built_distributions: tuple[Path, Path, str],
) -> None:
    """T030's Windows CI topology spec is explicit and matches the artefacts."""
    wheel, _sdist, version = built_distributions
    topology = _windows_ci_topology(version)

    assert topology.job_name == _WINDOWS_CI_JOB_NAME
    assert topology.job_name.isidentifier(), "workflow job key must be a valid identifier"
    assert topology.artifact == _WINDOWS_CI_ARTIFACT
    assert topology.artifact_source_glob == f"{_DISTRO_NAME}-{version}-py3-none-any.whl"

    assert topology.entry_points == _WINDOWS_CI_ENTRY_POINTS
    assert topology.entry_points == _wheel_entry_points(wheel)

    wheels = sorted((REPO_ROOT / "dist").glob(topology.artifact_source_glob))
    assert len(wheels) == 1, f"expected one artefact matching {topology.artifact_source_glob}"

    assert topology.smoke_commands, "bounded smoke commands must be declared"
    covered: set[str] = set()
    for executable, args in topology.smoke_commands:
        assert executable in topology.entry_points, f"unexpected executable {executable}"
        covered.add(executable)
        assert not set(args) & _NETWORK_SUBCOMMANDS, (
            f"network-triggering subcommand in {executable} {args}"
        )
        if executable == "pxcli-mcp":
            assert args == ("--help",), "pxcli-mcp smoke must use --help and never daemonise"
    assert covered == topology.entry_points, "smoke commands must cover every entry point"
