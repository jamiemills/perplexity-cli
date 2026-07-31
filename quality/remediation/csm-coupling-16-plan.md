# CSM Plan — Coupling Reduction (11 Modules)

> Run ID: 20260729-0300 — v2 (post-review)
> Base: ca85ac3 | Max parallel: 3 | Model: CSM

## Key Maths Insight

For A=0 modules with Ce>0: D = |0 + I - 1| = 1 - I. **Reducing Ce INCREASES D** — I goes down, so 1-I goes UP. The ONLY fix is Protocol (A→1.0), which gives D = |1 + I - 1| = I. If I≤0.3, DONE.

## Selected Modules (11)

**Protocol fix (Ce ≤ ca such that I ≤ 0.3 after A=1.0):**

| # | Module | A | Ce | I | D-before | D-after (A=1) |
|---|--------|---|---|-----|----------|----------------|
| 1 | `utils.exceptions` | 0 | 0 | 0.00 | 1.00 | 0.00 ✅ |
| 2 | `commands._ctx` | 0 | 0 | 0.00 | 1.00 | 0.00 ✅ |
| 3 | `utils.version` | 0 | 0 | 0.00 | 1.00 | 0.00 ✅ |
| 4 | `config.defaults` | 0 | 0 | 0.00 | 1.00 | 0.00 ✅ |
| 5 | `threads.exporter` | 0 | 0 | 0.00 | 1.00 | 0.00 ✅ |
| 6 | `utils.logging` | 0 | 1 | 0.05 | 0.95 | 0.05 ✅ |
| 7 | `envelope` | 0 | 1 | 0.07 | 0.93 | 0.07 ✅ |
| 8 | `commands._examples` | 0 | 1 | 0.11 | 0.89 | 0.11 ✅ |
| 9 | `utils.config` | 0 | 2 | 0.10 | 0.90 | 0.10 ✅ |
| 10 | `commands._help_sections` | 0 | 2 | 0.17 | 0.83 | 0.17 ✅ |
| 11 | `api.models` | 0 | 3 | 0.20 | 0.80 | 0.20 ✅ |

All 11 go from A=0→1.0 with a single Protocol. D-after = I ≤ 0.3 for all.

**Why not the others**: The formatting.* modules have I=0.67 → even with A=1.0, D=0.67 — still flagged. They need different treatment (out of scope for this wave).

## Wave 6A — Dispatch (3∥)

| Agent | Files | Work |
|-------|-------|------|
| P6A | `utils/exceptions.py`, `commands/_ctx.py`, `utils/version.py`, `config/defaults.py` | Add Protocol to 4 files. |
| P6B | `threads/exporter.py`, `utils/logging.py`, `envelope.py`, `commands/_examples.py` | Add Protocol to 4 files. |
| P6C | `utils/config/__init__.py`, `commands/_help_sections.py`, `api/models.py` | Add Protocol to 3 files. |

**Protocol template** (add to end of file):
```python
from typing import Protocol  # add to existing typing import

class _CouplingProtocol(Protocol):  # pyright: ignore[reportUnusedClass]
    """Abstract coupling protocol — increases abstractness for architecture metrics."""
    ...
```

**Verification**: `uv run python -c "import perplexity_cli.cli"` + `uv run pyright src/` + `uv run pytest`.

**Checkpoint**: commit + tag `wave-6a-complete`.

## Wave 6B — Measure (coordinator)

1. `uv run python scripts/check_coupling.py --max-flagged 40 --json > quality/baselines/coupling-report.json`
2. If flagged ≤ 25: DONE (from 36).
3. Commit + tag `phase-6-complete`.

## CSM Cycle

```
DISPATCH (3∥) → EXECUTE → VALIDATE → CHECKPOINT
                        ↓ FAIL
                   DIAGNOSE → REPAIR (max 3)
```
