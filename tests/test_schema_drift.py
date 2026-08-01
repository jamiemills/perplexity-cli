"""Schema-drift guard test.

Why this ratchet exists
-----------------------

Command-output envelopes (``--json`` mode) advertise a JSON shape to
downstream consumers. That shape is declared in two places that can drift
apart:

1. the Pydantic result models that produce the real runtime output, and
2. hand-written per-command result-schema dicts used for documentation and
   validation.

Hand-written dicts are the drift hazard: they duplicate the model structure by
hand, so a model change that is not mirrored into the dict silently breaks the
advertised contract. The accepted solution is to derive command output schemas
from the Pydantic models via ``model_json_schema()`` so there is exactly one
source of truth.

This test is therefore a monotonic accepted-debt RATCHET rather than a
zero-debt invariant. It records the *currently accepted* hand-written schema
debt as a known baseline and fails if the set grows. Shrinking the set
(deleting a hand-written schema in favour of model derivation) is always
allowed — the ratchet never blocks cleanup, and ``_ACCEPTED_DEBT`` may
therefore contain entries that have already been paid down (prune them by
hand when convenient).
"""

from __future__ import annotations

import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"

# Accepted debt: hand-written schema dicts currently in the tree.  Each entry
# is ``relative/path.py:NAME``.  Delete an entry (and the dict) once it is
# replaced by model_json_schema() derivation.
_ACCEPTED_DEBT = frozenset(
    {
        "src/perplexity_cli/commands/_schemas.py:COMMAND_RESULT_SCHEMAS",
    }
)


def _dict_assignment_names(node: ast.stmt) -> list[str]:
    """Return SCHEMA-named targets for a module-level dict assignment."""
    targets: list[ast.expr] = []
    if isinstance(node, ast.Assign):
        targets = list(node.targets)
    elif isinstance(node, ast.AnnAssign):
        targets = [node.target]
    else:
        return []
    if not isinstance(getattr(node, "value", None), ast.Dict):
        return []
    return [
        target.id
        for target in targets
        if isinstance(target, ast.Name) and "SCHEMA" in target.id.upper()
    ]


def _collect_handwritten_schema_dicts() -> set[str]:
    """Return ``{path:NAME}`` for module-level dict literals named ``*SCHEMA*``."""
    found: set[str] = set()
    for path in sorted(SRC.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in tree.body:
            for name in _dict_assignment_names(node):
                rel = path.relative_to(PROJECT_ROOT)
                found.add(f"{rel}:{name}")
    return found


def _assert_no_new_schema_debt(current: set[str]) -> None:
    """Assert that *current* stays within the accepted-debt baseline."""
    new = current - _ACCEPTED_DEBT
    assert not new, (
        "New hand-written schema dict(s) detected — derive command output "
        "schemas from Pydantic models via model_json_schema() instead "
        "(see the module docstring for the ratchet rationale):\n  " + "\n  ".join(sorted(new))
    )


def test_no_new_handwritten_schema_dicts() -> None:
    """No hand-written schema dict may be added beyond the accepted debt."""
    _assert_no_new_schema_debt(_collect_handwritten_schema_dicts())


def test_accepted_debt_removal_passes() -> None:
    """Removing accepted debt (good cleanup) must pass the monotonic ratchet."""
    paid_down = _ACCEPTED_DEBT - {"src/perplexity_cli/commands/_schemas.py:COMMAND_RESULT_SCHEMAS"}
    _assert_no_new_schema_debt(set(paid_down))
