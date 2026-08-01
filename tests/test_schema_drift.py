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

This test is therefore an accepted-debt RATCHET rather than a zero-debt
invariant. It records the *current* hand-written schema debt as a known
baseline and fails if the set grows. Shrinking the set (deleting a hand-written
schema in favour of model derivation) is always allowed and updates the
baseline.
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


def test_no_new_handwritten_schema_dicts() -> None:
    """No hand-written schema dict may be added beyond the accepted debt."""
    current = _collect_handwritten_schema_dicts()
    new = current - _ACCEPTED_DEBT
    assert not new, (
        "New hand-written schema dict(s) detected — derive command output "
        "schemas from Pydantic models via model_json_schema() instead "
        "(see the module docstring for the ratchet rationale):\n  " + "\n  ".join(sorted(new))
    )


def test_accepted_debt_still_exists() -> None:
    """Each accepted-debt entry must still be present (catches stale baselines)."""
    current = _collect_handwritten_schema_dicts()
    stale = _ACCEPTED_DEBT - current
    assert not stale, (
        "Accepted schema-debt entry removed — good! Update _ACCEPTED_DEBT in "
        "tests/test_schema_drift.py to shrink the baseline:\n  " + "\n  ".join(sorted(stale))
    )
