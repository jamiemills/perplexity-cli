# CSM Plan — Phases 4 & 5

> Run ID: 20260729-0100
> Base: e4bb5f6 (phase-3-complete tag)
> Max parallel agents: 3
> Model: cyclic state machine — dispatch → validate → repair → checkpoint

## Execution Model (CSM)

Each agent runs as a finite state machine:

1. **Dispatch** — coordinator assigns an item, an exclusive file set, and a verification command.
2. **Attempt** — agent performs the work on its files only.
3. **Validate** — agent runs its verification command (scoped) + `uv run pytest tests/ -q --tb=line -x -n auto --dist loadfile -m "not property and not hermetic_integration and not real_api and not manual and not real_user_config and not fuzz"`.
4. **Repair loop** — if validate fails, the agent re-enters Attempt (max **3 iterations**). After 3 failed iterations it **escalates** to the coordinator, which either re-partitions the file set or proposes a ratchet (ratchet requires **human approval**).
5. **Checkpoint** — only after validate passes. Coordinator commits the agent's diff, then tags the wave.

**Hard rules:**

- **One pyproject.toml editor per wave.** Only the designated agent may edit `[tool.ruff]` / `[tool.ruff.lint]`. All other agents touch code only.
- **Partition by FILE, never by identity.** Coordinator partitions the target files into disjoint sets; no two agents in a wave (or across dependent waves) edit the same file.
- **Mechanism precision.** Most target rule families are already in `select`; the work is removing specific codes from the `ignore` list (un-ignoring), not "enabling the family". Where a family is genuinely absent from `select` (EM, RSE, G, LOG, DTZ, SLOT, PIE, PT, DOC, FURB), the pyproject editor adds it. The per-agent Work column states exactly which `ignore` codes are removed.
- **Per-wave tags.** Every wave ends with an annotated tag (`git tag -a wave-Nx-complete -m …`); phase boundaries get `phase-N-complete`.
- **Human gates.** A human reviews the diff and confirms ratchets (a) at each phase boundary before the next phase starts, and (b) before Post-Phase-5 baseline harmonisation (baselines are hard to reverse).

## Current State (Baselines)

| Metric | Baseline |
|--------|----------|
| pyright-strict | 0 (clean) |
| ruff-architecture | 0 (empty baseline — latent findings untracked) |
| suppressions (`# type: ignore`) | 84 identities |
| coupling flagged | 36 modules |
| ruff waves 3-6 (un-gated, latent) | ~210 across TRY, EM, RSE, LOG, G, T20, PTH, DTZ, SLOT, PERF, PIE, PT |
| ruff DOC/FURB (preview-gated) | ~12 |

> **Suppression note.** `reportUnnecessaryTypeIgnoreComment = "error"` means every one of the 84 `# type: ignore` comments is currently *necessary* — each masks a real typing error (otherwise pyright would fail the build). There is no "unused suppression" to harvest. The only way to remove a suppression is to **resolve the underlying typing error first**, then delete the comment.

## Phase 4 — Test Quality + Ruff Waves 3-6 (3 waves)

### Wave 4A — Assertion Audit + Ruff 3 (3∥)

| Agent | Item | Exclusive files | Work |
|-------|------|----------------|------|
| P4A | #11 | `tests/test_optional_auth.py`, `tests/test_api_integration.py` (→ `test_api_component.py`), `tests/test_command_runner.py`, `tests/test_attachments_integration.py` | Assertion audit: replace generic error alternatives (`or "ERROR"`) with exact exit codes, replace swallowed `StopIteration` with specific `pytest.raises`, assert exact envelope structures, assert stdout vs stderr. Rename `test_api_integration.py` → `test_api_component.py` if it uses mocks only. |
| P4B | #12 | `tests/test_upload_manager_defensive.py`, `tests/test_upload_manager_unit.py`, `tests/test_attachment_protocol_integration.py` | Mock reduction: replace internal constructor patches with typed fakes at the outer boundary. Use `autospec=True` or `spec_set=` on all Mock calls. Create shared protocol fakes in `tests/helpers/`. |
| P4C | #19 (TRY003/EM/RSE) | **`pyproject.toml` (`[tool.ruff.lint]` only — sole editor this wave)**, `src/**/*.py` (TRY003/EM/RSE/TRY300 findings) | Pyproject edit: add `EM`, `RSE` to `select`; remove `TRY003`, `TRY300`, `EM101`, `EM102` from `ignore` (`EM101/102` are dead today — they activate once `EM` is selected). Do **not** touch `TRY004/TRY301/TRY401` — those stay ignored for Wave 4B. Then fix: TRY003 (52: messages on custom exceptions), EM101/EM102 (52: move strings out of raise), TRY300 (8: use `else`), RSE102 (redundant raise parens). |

**Verification**: `uv run ruff check src scripts` passes (TRY003/300 + EM + RSE now active, TRY004/301/401 still ignored). Pytest command (see Execution Model) passes.

**Checkpoint**: `git tag -a wave-4a-complete`.

### Wave 4B — Logging + Path/Time/Perf + remaining TRY (sequential: P4D → P4E → P4F)

> Run **sequentially**, not parallel. Only **P4D** edits `pyproject.toml`; P4E and P4F fix code only against the config P4D lands. The wave is not green until all three finish.

| Agent | Item | Exclusive files | Work |
|-------|------|----------------|------|
| P4D (1st) | #20 | **`pyproject.toml` (`[tool.ruff.lint]` only — sole editor this wave)**, `src/**/*.py` (LOG/G/T20 findings) | Single pyproject edit for the whole wave: add `LOG`, `G`, `DTZ`, `SLOT`, `PIE` to `select`; remove from `ignore` the codes this wave will fix — `G004`, `G201`, `PTH123`, `PTH101`, `PERF401`, `PERF403`, `TRY004`, `TRY301`, `TRY401`. Then fix P4D's own scope: G004 (2: logging f-string→lazy), G201 (4: logging `.exc_info`), LOG007 (4: exception without `exc_info`), T20 (residual src `print`→logger; T20 already active in `src/`, no enable needed). |
| P4E (2nd) | #21 | `src/**/*.py` (PTH/DTZ/SLOT/PERF/PIE findings) | Fix (no pyproject edits): PTH123 (16: `open`→`Path.open`), PTH101 (3: `os.chmod`→`Path.chmod`), DTZ005 (8: `datetime.now`→`datetime.now(UTC)`), DTZ006 (2), PERF401 (22: manual list comp), PERF403 (dict comp), PIE810 (4), PIE790 (2), SLOT findings. **FURB110 excluded — it is preview-only; deferred to P5A.** |
| P4F (3rd) | #19 remainder | `src/**/*.py` (TRY004/TRY401/TRY301 findings) | Fix (no pyproject edits — P4D already un-ignored these): TRY004 (7: type-check-without-type-error), TRY401 (7: verbose-log-message), TRY301 (2: raise-within-try). |

**Verification**: `uv run ruff check src scripts` passes or ratcheted (LOG/G/DTZ/SLOT/PIE now selected; PTH123/101, PERF401/403, TRY004/301/401, G004/201 now un-ignored). Pytest passes.

**Checkpoint**: `git tag -a wave-4b-complete`.

### Wave 4C — Pytest Style (1 agent)

| Agent | Item | Exclusive files | Work |
|-------|------|----------------|------|
| P4G | #22 | **`pyproject.toml` (`[tool.ruff.lint]` only — sole editor)**, `tests/**/*.py` | Add `PT` to `select`. Confirm `PT` codes are not masked by `tests/**` per-file-ignores (they are not). Fix all PT findings (pytest style) in test files. Verify all tests still pass. |

**Verification**: `uv run ruff check tests` passes or ratcheted. Pytest passes.

**Phase 4 checkpoint (human gate)**: `make check` passes. Human reviews diff + ratchets, approves. Commit + `git tag -a phase-4-complete`.

## Phase 5 — Ruff Completion + Pyright-Strict + Ruff-Architecture (3 waves)

> Coordinator partitions files before dispatch: runs `uv run ruff check src scripts --select DOC,FURB --preview`, `uv run pyright src/ 2>&1 | grep error`, and `uv run python scripts/check_suppressions.py --json`, then carves disjoint **file** sets so no two Phase-5 agents ever edit the same file.

### Wave 5A (3∥)

| Agent | Item | Exclusive files | Work |
|-------|------|----------------|------|
| P5A | #23 + #24 | **`pyproject.toml` (`[tool.ruff.lint]` + `preview` — sole editor this wave)**, `src/**/*.py` (DOC/FURB findings, disjoint set) | Add `DOC`, `FURB` to `select`; set `preview = true`. Fix DOC (pydoclint: docstring param/return consistency). Fix FURB (modernisation), **including FURB110 (11) moved here from Wave 4B**. Advisory ratchet if noisy. |
| P5B | #46 (set A) | `src/**/*.py` — disjoint file set A from the suppression partition | For each `# type: ignore` in these files: **resolve the underlying typing error** (annotate, refactor, fix the call site) so pyright is clean, **then delete the suppression**. Do not "audit for unused" — none are unused (`reportUnnecessaryTypeIgnoreComment=error`). Verify `uv run pyright <file>` stays clean per file. |
| P5C | #46 (set B) | `src/**/*.py` — disjoint file set B | Same mechanism as P5B on a disjoint file set. |

> **Preview side-effect warning (P5A).** `preview = true` is global — it changes behaviour of *all* selected rules and may surface new violations outside DOC/FURB. P5A's wave-end check must account for this; any incidental preview findings are ratcheted (human-approved) or fixed, not silently ignored.

**Verification**: `uv run ruff check src scripts --preview` passes or ratcheted. `uv run pyright src/` clean. `uv run python scripts/check_suppressions.py` shows reduced count. Pytest passes.

**Checkpoint**: `git tag -a wave-5a-complete`.

### Wave 5B (2∥)

| Agent | Item | Exclusive files | Work |
|-------|------|----------------|------|
| P5D | #46 (set C) | `src/**/*.py` — disjoint file set C (remaining suppression files) | Same mechanism as P5B/P5C on the final disjoint file set. Combined target with P5B/P5C: 84 → **≤20** identities remaining. |
| P5E | #47a | `src/perplexity_cli/utils/logging.py` (split candidate), `src/perplexity_cli/utils/http_errors.py` (split candidate) | Coupling reduction: split high-D utility modules into contracts + impl (same pattern as P3B config split). Update `architecture.toml`, regenerate `.importlinter`. Target: bring flagged 36 → ~24. |

**Verification**: `uv run pyright src/` clean; suppressions count ≤20; `uv run python scripts/check_coupling.py` shows reduced flagged; import-linter contracts pass. Pytest passes.

**Checkpoint**: `git tag -a wave-5b-complete`.

### Wave 5C (2∥)

| Agent | Item | Exclusive files | Work |
|-------|------|----------------|------|
| P5F | #47b | Coupling hotspots not already split by P5E (disjoint from P5G) | Final coupling pass: review remaining flagged modules, add ports where needed, extract constants. Update `architecture.toml` / `.importlinter`. Target: flagged → **≤20 modules** (consistent end-of-phase target). |
| P5G | #44 | **`pyproject.toml` (`[tool.ruff.lint.per-file-ignores]` only — sole editor this wave)**, `src/**/*.py` + `scripts/**/*.py` (disjoint from P5F) | ruff-architecture baseline is 0 (empty) because latent findings are masked by `per-file-ignores`. Audit: run ruff with the per-file-ignores suppressed (e.g. `uv run ruff check src scripts --config 'lint.per-file-ignores = {}'`) to surface latent findings, fix the underlying issues, then **narrow or remove** the now-redundant `per-file-ignores` entries. Establishes the first real ruff-architecture baseline. |

**Verification**: `make check` passes. Coupling flagged ≤20. ruff with per-file-ignores suppressed shows no new latent findings (or ratcheted + human-approved). Pytest passes.

**Phase 5 checkpoint (human gate)**: `make check` passes. Human reviews diff + all ratchets, approves. Commit + `git tag -a phase-5-complete`.

## Post-Phase-5 — Baseline Harmonisation (coordinator, serial, human-gated)

> Human gate: baselines are hard to reverse — human confirms final counts before locking.

1. `uv run python scripts/check_suppressions.py --update-baseline` (locks ≤20 identities).
2. `uv run python scripts/check_coupling.py --max-flagged 20 --json > quality/baselines/coupling-report.json` (locks ≤20, consistent with P5F target).
3. Regenerate ruff-architecture baseline from P5G's narrowed per-file-ignores.
4. Verify all ratchets pass (`make check`).
5. Commit: `chore: harmonise baselines after phases 4-5`.

## Resume Protocol

```bash
git log --oneline --decorate | grep -E 'wave-|phase-'   # find last checkpoint
git checkout -b resume-phase-N <tag>                      # branch from checkpoint
```

To re-run a single failed agent: checkout the wave tag, re-dispatch that agent's item + file set, then re-validate via its verification command (repair loop applies).
