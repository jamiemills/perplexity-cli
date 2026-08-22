"""Baseline source-ledger construction and verification.

Builds the exhaustive per-module ownership ledger directly from the
production package tree and verifies recorded ledgers, including mutant
keysets when a generated workspace is available.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from scripts.mutation_evidence import GeneratedSourceError, enumerate_generated_mutants

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

LEDGER_SCHEMA_VERSION = 1
_SOURCE_ROOT_NAME = "src"
_PACKAGE_NAME = "perplexity_cli"


class LedgerMismatchError(ValueError):
    """Raised when a recorded ledger disagrees with observed reality."""


@dataclass(frozen=True, slots=True)
class ModuleRecord:
    """One production module and its dotted name."""

    module: str
    source_path: str


_MIN_PACKAGE_PARTS = 3


def _package_segments(relative_path: Path) -> list[str] | None:
    """Return dotted-name segments, or None when outside the package."""
    parts = relative_path.parts
    if len(parts) < _MIN_PACKAGE_PARTS or parts[0] != _SOURCE_ROOT_NAME:
        return None
    if relative_path.suffix != ".py" or parts[1] != _PACKAGE_NAME:
        return None
    return _stripped_segments(parts)


def _stripped_segments(parts: tuple[str, ...]) -> list[str] | None:
    """Join interior directories with the file stem, dropping ``__init__``."""
    segments = [*parts[2:-1], Path(parts[-1]).stem]
    if segments[-1] == "__init__":
        segments.pop()
    return segments


def _module_name(relative_path: Path) -> str | None:
    """Derive the dotted module name, or None outside the package."""
    segments = _package_segments(relative_path)
    if segments is None:
        return None
    if any(not segment.isidentifier() for segment in segments):
        return None
    return ".".join((_PACKAGE_NAME, *segments))


def enumerate_module_records(source_root: Path) -> tuple[ModuleRecord, ...]:
    """Enumerate every production module record under ``source_root``.

    Args:
        source_root: Repository root containing ``src/perplexity_cli``.

    Returns:
        Deterministically ordered module records.

    Raises:
        LedgerMismatchError: If no production modules are found.
    """
    records: list[ModuleRecord] = []
    package_root = source_root / _SOURCE_ROOT_NAME / _PACKAGE_NAME
    for path in sorted(package_root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        module = _module_name(path.relative_to(source_root))
        if module is None:
            continue
        records.append(ModuleRecord(module, path.relative_to(source_root).as_posix()))
    if not records:
        msg = "production package yielded no modules"
        raise LedgerMismatchError(msg)
    return tuple(records)


def canonical_digest(payload: object) -> str:
    """Digest a JSON-serialisable payload canonically (sorted, compact)."""
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def build_ledger_document(source_root: Path) -> dict[str, object]:
    """Build the complete ledger document for the production tree."""
    records = enumerate_module_records(source_root)
    entries = [{"module": r.module, "source_path": r.source_path} for r in records]
    return {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "module_count": len(entries),
        "modules": entries,
        "ledger_sha256": canonical_digest(entries),
    }


def load_json(path: Path) -> dict[str, object]:
    """Load one JSON document, failing closed on unreadable content."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        msg = f"unreadable manifest: {path}"
        raise LedgerMismatchError(msg) from exc
    if not isinstance(payload, dict):
        msg = f"manifest is not an object: {path}"
        raise LedgerMismatchError(msg)
    return cast("dict[str, object]", payload)


def verify_ledger_document(document: dict[str, object], source_root: Path) -> list[str]:
    """Verify a recorded ledger against the live production tree.

    Args:
        document: Previously recorded ledger document.
        source_root: Repository root containing ``src/perplexity_cli``.

    Returns:
        Sorted disagreement descriptions; empty means verified.
    """
    issues: list[str] = []
    if document.get("schema_version") != LEDGER_SCHEMA_VERSION:
        issues.append("unsupported ledger schema_version")
    expected = build_ledger_document(source_root)
    if document.get("ledger_sha256") != expected["ledger_sha256"]:
        issues.append("ledger_sha256 does not match the production tree")
    if document.get("module_count") != expected["module_count"]:
        issues.append(f"module_count {document.get('module_count')} != {expected['module_count']}")
    return sorted(issues)


def collect_generated_keysets(
    mutants_dir: Path, source_root_name: str = _SOURCE_ROOT_NAME
) -> dict[str, list[str]]:
    """Enumerate generated mutant keys per module from a fresh workspace.

    Args:
        mutants_dir: The freshly generated ``mutants/`` workspace root.
        source_root_name: Source root directory name below the workspace.

    Returns:
        Mapping of dotted module name to its sorted generated keys.

    Raises:
        LedgerMismatchError: If generated Python cannot be parsed.
    """

    generated_root = mutants_dir / source_root_name / _PACKAGE_NAME
    keysets: dict[str, list[str]] = {}
    for path in sorted(generated_root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        relative = path.relative_to(mutants_dir)
        module = _module_name(relative)
        if module is not None:
            _extend_module_keys(keysets, module, relative, path)
    ordered: dict[str, list[str]] = {module: sorted(keysets[module]) for module in sorted(keysets)}
    return ordered


def _extend_module_keys(
    keysets: dict[str, list[str]], module: str, relative: Path, path: Path
) -> None:
    """Extend one module's keys from generated source, failing closed."""
    try:
        evidence = enumerate_generated_mutants(path.read_text(encoding="utf-8"), relative)
    except GeneratedSourceError as exc:
        msg = f"generated source unusable: {relative}"
        raise LedgerMismatchError(msg) from exc
    if evidence.dictionary_disagreements:
        msg = f"dictionary disagreement in {relative}"
        raise LedgerMismatchError(msg)
    keysets.setdefault(module, []).extend(sorted(evidence.keys))


def build_keysets_document(mutants_dir: Path) -> dict[str, object]:
    """Build the recorded keyset manifest from a fresh workspace."""
    keysets = collect_generated_keysets(mutants_dir)
    total = sum(len(keys) for keys in keysets.values())
    return {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "total_keys": total,
        "keysets_sha256": canonical_digest(keysets),
        "keysets": keysets,
    }


def verify_keysets_document(document: dict[str, object], mutants_dir: Path) -> list[str]:
    """Verify a recorded keyset manifest against a fresh enumeration."""
    expected = build_keysets_document(mutants_dir)
    issues: list[str] = []
    if document.get("schema_version") != LEDGER_SCHEMA_VERSION:
        issues.append("unsupported keyset schema_version")
    if document.get("keysets_sha256") != expected["keysets_sha256"]:
        issues.append("keysets_sha256 does not match fresh enumeration")
    if document.get("total_keys") != expected["total_keys"]:
        issues.append(f"total_keys {document.get('total_keys')} != {expected['total_keys']}")
    return sorted(issues)


def write_json(path: Path, payload: dict[str, object]) -> None:
    """Write one manifest with deterministic formatting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    logger.info("Manifest written to %s", path)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse manifest CLI arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build", help="Record baseline manifests")
    build.add_argument("--mutants-dir", type=Path, required=True)
    build.add_argument("--output-dir", type=Path, required=True)
    check = subparsers.add_parser("check", help="Verify recorded manifests")
    check.add_argument("--manifest-dir", type=Path, required=True)
    check.add_argument("--with-generated", action="store_true")
    check.add_argument("--mutants-dir", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; exit 0 verified, 2 mismatch or tool error."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = _parse_args(argv)
    failure: LedgerMismatchError | None = None
    issues: list[str] = []
    try:
        if args.command == "build":
            return _run_build(args)
        issues = _run_check(args)
    except LedgerMismatchError as exc:
        failure = exc
    if failure is not None:
        logger.error("manifest verification failed: %s", type(failure).__name__)
        return 2
    for issue in issues:
        logger.error("%s", issue)
    return 0 if not issues else 1


def _run_build(args: argparse.Namespace) -> int:
    """Record ledger and keyset manifests from a fresh workspace."""
    ledger = build_ledger_document(PROJECT_ROOT)
    keysets = build_keysets_document(args.mutants_dir)
    write_json(args.output_dir / "source-ledger.json", ledger)
    write_json(args.output_dir / "keysets.json", keysets)
    return 0


def _run_check(args: argparse.Namespace) -> list[str]:
    """Verify recorded manifests with optional generated reconciliation."""
    manifest_dir: Path = args.manifest_dir
    issues = verify_ledger_document(load_json(manifest_dir / "source-ledger.json"), PROJECT_ROOT)
    if args.with_generated:
        if args.mutants_dir is None:
            return [*issues, "--with-generated requires --mutants-dir"]
        issues += verify_keysets_document(
            load_json(manifest_dir / "keysets.json"), args.mutants_dir
        )
    return issues


if __name__ == "__main__":
    sys.exit(main())
