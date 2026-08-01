"""Verify the built wheel and sdist satisfy the packaging contract.

Checks, for the exact version declared in ``pyproject.toml``:

- both declared resources are bundled (``config/urls.json`` and
  ``resources/skill.md``);
- all three console entry points are registered (``pxcli``,
  ``perplexity-cli``, ``pxcli-mcp``);
- distribution metadata (name, version, licence, readme) is present;
- no tests, byte-code caches, coverage files or dot-env secrets leak into
  the artefacts.

The version is read from ``pyproject.toml`` and used to select the exact
wheel and sdist in ``dist/``; artefacts are never picked by lexicographic
sort.

Usage::

    UV_OFFLINE=1 uv run python scripts/verify_wheel.py

Exits non-zero with per-artefact diagnostics on any failed contract.
"""

from __future__ import annotations

import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path

_DISTRO_NAME = "pxcli"
_EXPECTED_ENTRY_POINTS = frozenset({"pxcli", "perplexity-cli", "pxcli-mcp"})
_REQUIRED_RESOURCES = ("config/urls.json", "resources/skill.md")
_FORBIDDEN_COMPONENTS = frozenset({"tests", "__pycache__"})
_FORBIDDEN_BASENAMES = frozenset({".coverage", ".env", ".env.local"})

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _read_version() -> str:
    """Read the project version from pyproject.toml."""
    pyproject_path = _REPO_ROOT / "pyproject.toml"
    with pyproject_path.open("rb") as fh:
        pyproject_data = tomllib.load(fh)
    project = pyproject_data["project"]
    version = project.get("version")
    if not isinstance(version, str) or not version:
        msg = "pyproject.toml [project] must declare a string version"
        raise SystemExit(msg)
    return version


def _glob_for_kind(kind: str, version: str) -> tuple[str, str]:
    """Return (exact-version glob, any-version glob) for a dist kind."""
    if kind == "wheel":
        return f"{_DISTRO_NAME}-{version}-*.whl", f"{_DISTRO_NAME}-*.whl"
    return f"{_DISTRO_NAME}-{version}.tar.gz", f"{_DISTRO_NAME}-*.tar.gz"


def _select_single(dist_dir: Path, version: str, kind: str) -> Path:
    """Return the unique exact-version artefact of *kind*, or fail."""
    version_glob, all_glob = _glob_for_kind(kind, version)
    matches = sorted(dist_dir.glob(version_glob))
    if len(matches) != 1:
        candidates = ", ".join(p.name for p in sorted(dist_dir.glob(all_glob)))
        msg = (
            f"Expected exactly one {kind} for {_DISTRO_NAME}=={version} in dist/, "
            f"found {len(matches)} (candidates: {candidates or 'none'})"
        )
        raise SystemExit(msg)
    return matches[0]


def _select_artefacts(version: str) -> tuple[Path, Path]:
    """Return the exact-version wheel and sdist from dist/, or fail."""
    dist_dir = _REPO_ROOT / "dist"
    wheel = _select_single(dist_dir, version, "wheel")
    sdist = _select_single(dist_dir, version, "sdist")
    return wheel, sdist


def _resource_failures(names: set[str], prefix: str) -> list[str]:
    """Report any declared package resource missing from an artefact."""
    failures: list[str] = []
    for resource in _REQUIRED_RESOURCES:
        member = f"{prefix}perplexity_cli/{resource}"
        if member not in names:
            failures.append(f"missing packaged resource: {member}")
    return failures


def _is_section_header(line: str) -> bool:
    """Return True when *line* starts a metadata section."""
    return line.startswith("[")


def _is_script_entry(line: str) -> bool:
    """Return True when *line* declares a console script mapping."""
    return "=" in line and not line.startswith(("#", ";"))


def _parse_console_scripts(text: str) -> set[str]:
    """Return the console script names declared in entry-points text."""
    names: set[str] = set()
    section = False
    for line in text.splitlines():
        stripped = line.strip()
        if _is_section_header(stripped):
            section = stripped == "[console_scripts]"
        elif section and _is_script_entry(stripped):
            names.add(stripped.split("=", 1)[0].strip())
    return names


def _entry_point_failures(text: str) -> list[str]:
    """Report any expected console entry point that is not registered."""
    registered = _parse_console_scripts(text)
    missing = sorted(_EXPECTED_ENTRY_POINTS - registered)
    return [f"console entry point not registered: {name}" for name in missing]


def _description_body(text: str) -> str:
    """Return the metadata description body after the header block."""
    lines = text.splitlines()
    try:
        first_blank = lines.index("")
    except ValueError:
        return ""
    return "\n".join(lines[first_blank + 1 :])


def _has_licence_field(text: str) -> bool:
    """Return True when metadata declares a licence field."""
    return "License-Expression:" in text or "License:" in text


def _has_readme(text: str) -> bool:
    """Return True when metadata declares a non-empty readme body."""
    return "Description-Content-Type:" in text and bool(_description_body(text).strip())


def _metadata_failures(text: str, version: str) -> list[str]:
    """Report missing name/version/licence/readme fields in metadata."""
    failures: list[str] = []
    if f"Name: {_DISTRO_NAME}" not in text:
        failures.append(f"metadata missing 'Name: {_DISTRO_NAME}'")
    if f"Version: {version}" not in text:
        failures.append(f"metadata missing 'Version: {version}'")
    if not _has_licence_field(text):
        failures.append("metadata missing licence field")
    if not _has_readme(text):
        failures.append("metadata readme (description) is missing or empty")
    return failures


def _forbidden_component(relative: str) -> bool:
    """Return True when a path component is forbidden (tests/caches)."""
    return bool(set(relative.split("/")) & _FORBIDDEN_COMPONENTS)


def _forbidden_basename(relative: str) -> bool:
    """Return True when the final component is a forbidden file name."""
    return relative.rsplit("/", 1)[-1] in _FORBIDDEN_BASENAMES


def _hygiene_failures(names: set[str], prefix: str) -> list[str]:
    """Report tests, caches or secrets bundled inside an artefact."""
    failures: list[str] = []
    for member in sorted(names):
        relative = member[len(prefix) :] if member.startswith(prefix) else member
        if _forbidden_component(relative):
            failures.append(f"forbidden path component in artefact: {member}")
        if _forbidden_basename(relative):
            failures.append(f"forbidden file in artefact: {member}")
    return failures


def _read_tar_text(archive: tarfile.TarFile, member: str) -> str | None:
    """Return decoded text for a tar member, or None when unreadable."""
    fileobj = archive.extractfile(member)
    if fileobj is None:
        return None
    with fileobj:
        return fileobj.read().decode("utf-8")


def _check_tar_entry_points(
    archive: tarfile.TarFile,
    names: set[str],
    member: str,
) -> list[str]:
    """Verify console entry points in a tar metadata member."""
    if member not in names:
        return [f"sdist metadata missing {member}"]
    text = _read_tar_text(archive, member)
    if text is None:
        return [f"unable to read {member}"]
    return _entry_point_failures(text)


def _check_tar_metadata(
    archive: tarfile.TarFile,
    names: set[str],
    member: str,
    version: str,
) -> list[str]:
    """Verify name/version/licence/readme fields in a tar metadata member."""
    if member not in names:
        return [f"sdist metadata missing {member}"]
    text = _read_tar_text(archive, member)
    if text is None:
        return [f"unable to read {member}"]
    return _metadata_failures(text, version)


def _verify_wheel(wheel_path: Path, version: str) -> list[str]:
    """Verify the wheel distribution contract, returning diagnostics."""
    failures: list[str] = []
    dist_info = f"{_DISTRO_NAME}-{version}.dist-info"
    with zipfile.ZipFile(wheel_path) as archive:
        names = set(archive.namelist())
        failures.extend(_resource_failures(names, prefix=""))
        entry_points_name = f"{dist_info}/entry_points.txt"
        metadata_name = f"{dist_info}/METADATA"
        if entry_points_name not in names:
            failures.append(f"wheel metadata missing {entry_points_name}")
        else:
            failures.extend(_entry_point_failures(archive.read(entry_points_name).decode("utf-8")))
        if metadata_name not in names:
            failures.append(f"wheel metadata missing {metadata_name}")
        else:
            failures.extend(
                _metadata_failures(archive.read(metadata_name).decode("utf-8"), version)
            )
        licence_member = f"{dist_info}/licenses/LICENSE"
        if licence_member not in names:
            failures.append(f"wheel missing licence file {licence_member}")
        failures.extend(_hygiene_failures(names, prefix=""))
    return failures


def _verify_sdist(sdist_path: Path, version: str) -> list[str]:
    """Verify the sdist distribution contract, returning diagnostics."""
    failures: list[str] = []
    prefix = f"{_DISTRO_NAME}-{version}/"
    with tarfile.open(sdist_path) as archive:
        names = set(archive.getnames())
        failures.extend(_resource_failures(names, prefix=f"{prefix}src/"))
        entry_points_name = f"{prefix}src/{_DISTRO_NAME}.egg-info/entry_points.txt"
        metadata_name = f"{prefix}PKG-INFO"
        failures.extend(_check_tar_entry_points(archive, names, entry_points_name))
        failures.extend(_check_tar_metadata(archive, names, metadata_name, version))
        for required in (f"{prefix}README.md", f"{prefix}LICENSE"):
            if required not in names:
                failures.append(f"sdist missing {required}")
        failures.extend(_hygiene_failures(names, prefix=prefix))
    return failures


def main() -> None:
    """Verify the current wheel and sdist against the packaging contract."""
    version = _read_version()
    wheel_path, sdist_path = _select_artefacts(version)
    failures: list[str] = []
    for artefact_path, checker in ((wheel_path, _verify_wheel), (sdist_path, _verify_sdist)):
        diagnostics = checker(artefact_path, version)
        if diagnostics:
            failures.append(f"{artefact_path.name}:")
            failures.extend(f"  - {message}" for message in diagnostics)

    if failures:
        print("\n".join(failures), file=sys.stderr)
        raise SystemExit(1)

    print(f"Verified {wheel_path.name} and {sdist_path.name} (version {version})")
    print("  resources:     config/urls.json, resources/skill.md")
    print("  entry points:  pxcli, perplexity-cli, pxcli-mcp")
    print("  metadata:      name, version, licence, readme")
    print("  hygiene:       no tests/, __pycache__, .coverage, .env")


if __name__ == "__main__":
    main()
