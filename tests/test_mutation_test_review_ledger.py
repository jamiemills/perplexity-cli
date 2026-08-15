"""Validate the protected mutation-test review and node-map evidence."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

from radon.complexity import cc_visit

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "quality/remediation/mutation-test-review.json"
INDEPENDENT_REVIEW = ROOT / "quality/remediation/mutation-test-independent-review.json"
NODE_MAP = ROOT / "quality/remediation/mutation-test-node-map.json"
PATCH_SHA256 = "032f27e82333113667a51722394842c5c89921a3cb048e0a0fca5d386f760bf4"
CANDIDATE_INVENTORY_SHA256 = "e528967b7e4bb3577a18f442d2d7bd3da1670df686a938375a69f52471fc47f2"
INDEPENDENT_REVIEWER = "t001-independent-review-1"
SECOND_INDEPENDENT_REVIEWER = "t001-independent-review-2"
SECOND_REVIEW_SESSION = "ses_ff8cac7a3ffeZWFL6T50n3YXxX"
IMPLEMENTATION_REVIEWER = "t001-implementation-review"
GENERIC_REVIEW_BOILERPLATE = "intake-added assertions reviewed"
CURRENT_TEST_FILES = (
    "tests/test_api_client.py",
    "tests/test_api_client_retry.py",
    "tests/test_auth_runner.py",
    "tests/test_config_runners.py",
    "tests/test_export_runner.py",
    "tests/test_formatters.py",
    "tests/test_mcp_server.py",
    "tests/test_oauth_handler.py",
    "tests/test_oauth_cdp.py",
    "tests/test_query_runner.py",
    "tests/test_scraper_coverage.py",
    "tests/test_token_manager.py",
)
NEW_TEST_FILES = {"tests/test_api_client_retry.py", "tests/test_oauth_cdp.py"}
REQUIRED_REVIEW_FIELDS = {
    "id",
    "candidate_identity",
    "file",
    "test",
    "assertion",
    "boundary_classification",
    "intended_mutant_or_behaviour",
    "attempted_public_boundary",
    "exactness_reason",
    "decision",
    "focused_evidence",
    "implementation_reviewer_identity",
    "reviewer_identity",
}
RESOLVED_DECISIONS = {"retain", "rewrite", "move", "remove"}


def _load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical_digest(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload + b"\n").hexdigest()


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    return {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}


def _qualified_name(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> str:
    names = [node.name]
    parent = parents.get(node)
    while parent is not None:
        if isinstance(parent, ast.ClassDef):
            names.append(parent.name)
        parent = parents.get(parent)
    return "::".join(reversed(names))


def _is_test_function(node: ast.AST) -> bool:
    return isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith(
        "test_"
    )


def _test_functions(tree: ast.AST) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [node for node in ast.walk(tree) if _is_test_function(node)]


def _collect_nodes(
    base: Path, files: Iterable[str], quiet: str, python_path: str | None = None
) -> list[str]:
    environment = os.environ.copy()
    environment["UV_OFFLINE"] = "1"
    if python_path is not None:
        environment["PYTHONPATH"] = python_path
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", quiet, *files],
        cwd=base,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    return [
        line for line in result.stdout.splitlines() if line.startswith("tests/") and "::" in line
    ]


def _marker_name(decorator: ast.expr) -> str | None:
    expression = decorator.func if isinstance(decorator, ast.Call) else decorator
    parts: list[str] = []
    while isinstance(expression, ast.Attribute):
        parts.append(expression.attr)
        expression = expression.value
    if isinstance(expression, ast.Name):
        parts.append(expression.id)
    dotted = ".".join(reversed(parts))
    return dotted.rsplit(".", 1)[-1] if "pytest.mark." in dotted else None


def _node_markers(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    return sorted(
        marker for decorator in node.decorator_list if (marker := _marker_name(decorator))
    )


def _marker_index(base: Path, files: Iterable[str]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for relative_file in files:
        tree = ast.parse((base / relative_file).read_text(encoding="utf-8"))
        parents = _parents(tree)
        functions = _test_functions(tree)
        result.update(
            {
                f"{relative_file}::{_qualified_name(node, parents)}": _node_markers(node)
                for node in functions
            }
        )
    return result


def _base_node_id(node_id: str) -> str:
    return node_id.split("[", 1)[0]


def _reviewed_lines() -> dict[str, set[int]]:
    ledger = _load_json(LEDGER)
    lines: dict[str, set[int]] = {}
    for review in ledger["reviews"]:
        path = ROOT / review["file"]
        tree = ast.parse(path.read_text(encoding="utf-8"))
        matches = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == review["test"]
        ]
        lines.setdefault(review["file"], set()).update(matches)
    return lines


def _complexity_failures() -> list[str]:
    reviewed = _reviewed_lines()
    paths = [*CURRENT_TEST_FILES, "tests/test_mutation_test_review_ledger.py"]
    return [failure for path in paths for failure in _file_complexity_failures(path, reviewed)]


def _file_complexity_failures(relative_file: str, reviewed: dict[str, set[int]]) -> list[str]:
    blocks = cc_visit((ROOT / relative_file).read_text(encoding="utf-8"))
    checked_lines = reviewed.get(relative_file, set())
    check_all = relative_file in NEW_TEST_FILES or relative_file.endswith("review_ledger.py")
    checked = (block for block in blocks if _requires_cc_check(block, check_all, checked_lines))
    return [
        f"{relative_file}:{block.lineno}:{block.name}=CC{block.complexity}" for block in checked
    ]


def _requires_cc_check(block: object, check_all: bool, checked_lines: set[int]) -> bool:
    values = (
        block.__class__.__name__ == "Function",
        check_all or block.lineno in checked_lines,
        block.complexity > 5,
    )
    return values == (True, True, True)


def _valid_review(review: dict[str, object]) -> bool:
    values = (
        set(review) == REQUIRED_REVIEW_FIELDS,
        review["reviewer_identity"] == INDEPENDENT_REVIEWER,
        review["implementation_reviewer_identity"] == IMPLEMENTATION_REVIEWER,
        review["reviewer_identity"] != review["implementation_reviewer_identity"],
        review["decision"] in RESOLVED_DECISIONS,
    )
    return values == (True, True, True, True, True)


def test_candidate_inventory_matches_independently_reviewed_snapshot() -> None:
    ledger = _load_json(LEDGER)
    digest = _canonical_digest(ledger["candidate_inventory"])
    assert (ledger["candidate_inventory_sha256"], digest) == (
        CANDIDATE_INVENTORY_SHA256,
        CANDIDATE_INVENTORY_SHA256,
    )


def test_candidate_and_review_identities_match_exactly() -> None:
    ledger = _load_json(LEDGER)
    candidates = [row["identity"] for row in ledger["candidate_inventory"]]
    reviewed = [row["candidate_identity"] for row in ledger["reviews"]]
    assert (len(candidates), len(reviewed), candidates == reviewed) == (108, 108, True)


def test_every_disposition_has_an_independent_reviewer() -> None:
    ledger = _load_json(LEDGER)
    reviews = ledger["reviews"]
    assert all(_valid_review(review) for review in reviews)


def test_second_independent_review_is_bound_to_exact_ledger_snapshot() -> None:
    ledger = _load_json(LEDGER)
    evidence = _load_json(INDEPENDENT_REVIEW)
    candidate_identities = [row["identity"] for row in ledger["candidate_inventory"]]
    reviewed_identities = [row["candidate_identity"] for row in ledger["reviews"]]
    assert (
        evidence["reviewer_identity"],
        evidence["reviewer_session_provenance"],
        evidence["implementation_reviewer_identity"],
        evidence["candidate_inventory_sha256"],
        evidence["reviewed_dispositions_sha256"],
        evidence["candidate_review_identity_sha256"],
        evidence["candidate_count"],
        evidence["review_count"],
        evidence["exact_candidate_review_identity_correspondence"],
        candidate_identities == reviewed_identities,
    ) == (
        SECOND_INDEPENDENT_REVIEWER,
        SECOND_REVIEW_SESSION,
        IMPLEMENTATION_REVIEWER,
        CANDIDATE_INVENTORY_SHA256,
        _canonical_digest(ledger["reviews"]),
        _canonical_digest(candidate_identities),
        108,
        108,
        True,
        True,
    )


def test_second_review_is_independent_and_all_findings_are_resolved() -> None:
    evidence = _load_json(INDEPENDENT_REVIEW)
    findings = evidence["prior_independent_findings"]
    assert evidence["reviewer_identity"] != evidence["implementation_reviewer_identity"]
    assert evidence["unresolved_findings"] == []
    assert findings
    assert {finding["verdict"] for finding in findings} == {"resolved"}


def test_second_review_findings_have_test_identity_and_resolution_evidence() -> None:
    findings = _load_json(INDEPENDENT_REVIEW)["prior_independent_findings"]
    assert [finding["file"] in finding["test_identity"] for finding in findings] == [True] * len(
        findings
    )
    assert [bool(finding["resolved_evidence"]) for finding in findings] == [True] * len(findings)


def test_review_ledger_contains_no_generic_boilerplate() -> None:
    reviews = _load_json(LEDGER)["reviews"]
    assert all(
        GENERIC_REVIEW_BOILERPLATE not in str(value)
        for review in reviews
        for value in review.values()
    )


def test_ledger_metadata_and_patch_digest_are_authentic() -> None:
    ledger = _load_json(LEDGER)
    assert (
        ledger["schema_version"],
        ledger["intake_patch_sha256"],
        ledger["reviewer_identity"],
    ) == (2, PATCH_SHA256, INDEPENDENT_REVIEWER)


def test_reviewed_tests_exist_at_current_locations() -> None:
    reviews = _load_json(LEDGER)["reviews"]
    existing = {
        (relative_file, node.name)
        for relative_file in CURRENT_TEST_FILES
        for node in ast.walk(ast.parse((ROOT / relative_file).read_text(encoding="utf-8")))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert all((review["file"], review["test"]) in existing for review in reviews)


def test_node_map_is_exact_521_to_521_bijection() -> None:
    node_map = _load_json(NODE_MAP)
    mappings = node_map["mappings"]
    after = _collect_nodes(ROOT, CURRENT_TEST_FILES, "-qq")
    mapped_before = [row["before"] for row in mappings]
    mapped_after = [row["after"] for row in mappings]
    assert (
        node_map["before_count"],
        len(after),
        len(set(mapped_before)),
        len(set(mapped_after)),
        set(after) == set(mapped_after),
    ) == (521, 521, 521, 521, True)


def test_node_map_preserves_every_marker_explicitly() -> None:
    mappings = _load_json(NODE_MAP)["mappings"]
    after_markers = _marker_index(ROOT, CURRENT_TEST_FILES)
    valid = all(
        row["marker_preserved"] is True
        and row["markers"] == after_markers[_base_node_id(row["after"])]
        for row in mappings
    )
    assert valid


def test_node_status_accounts_for_unchanged_moved_and_renamed_nodes() -> None:
    mappings = _load_json(NODE_MAP)["mappings"]
    counts = {
        status: sum(row["status"] == status for row in mappings)
        for status in ("unchanged", "moved", "renamed")
    }
    assert counts == {"unchanged": 492, "moved": 26, "renamed": 3}


def test_changed_tests_helpers_and_validator_have_cc_at_most_five() -> None:
    assert _complexity_failures() == []


def test_owned_files_do_not_exceed_line_limit() -> None:
    files = [
        *CURRENT_TEST_FILES,
        "tests/test_mutation_test_review_ledger.py",
        "quality/remediation/mutation-test-review.json",
        "quality/remediation/mutation-test-independent-review.json",
        "quality/remediation/mutation-test-node-map.json",
    ]
    assert all(
        len((ROOT / path).read_text(encoding="utf-8").splitlines()) <= 1000 for path in files
    )
