# CSM Plan — Outstanding Work Build

> Run ID: 20260729-0100
> Base: 7e38352 (current master)
> Max parallel agents: 3 (hard constraint)
> Model: cyclic state machine — each phase dispatches, validates, repairs, checkpoints
> Resumable: each phase commits a checkpoint; resume from last checkpoint

## Items In Scope

7, 9, 10, 11, 12, 14, 15, 17–25, 28, 29, 30, 32, 40, 42, 43, 44, 45, 46, 47

## Dependency Graph

```
Phase 1 (6 items, 3∥)          Phase 2 (4 items, 3∥)         Phase 3 (4 items, 3∥)
┌─────────────────────┐       ┌────────────────────┐       ┌────────────────────┐
│ P1A: #15 hook       │──────▶│ P2A: #7 arch       │──────▶│ P3A: #10 hermetic  │
│      ordering       │       │      migration     │       │      integration   │
│ P1B: #14 property   │──┐   │ P2B: #40 test lane │       │ P3B: #42 coupling  │
│      ownership      │  ├──▶│      reclass       │       │      splits        │
│ P1C: #29+#30 init  │──┘   │ P2C: #17 ruff w1   │       │ P3C: #25 strict    │
│      + suppressions │       │      findings      │       │      pyright       │
│ P1D: #32 determinism│       │ P2D: #28 src-cov   │       │ P3D: #18 ruff w2   │
│ P1E: #45 semgrep 4  │       └────────────────────┘       └────────────────────┘
│ P1F: #9 coverage    │
│      integrity      │       Phase 4 (4 items, 3∥)       Phase 5 (3 items, 3∥)
└─────────────────────┘       ┌────────────────────┐       ┌────────────────────┐
                              │ P4A: #11 assertion │       │ P5A: #23+#24 ruff  │
                              │      audit         │       │      waves 7+8     │
                              │ P4B: #12 mock      │       │ P5B: #43 pyright   │
                              │      reduction     │       │      682 findings  │
                              │ P4C: #19+#20 ruff  │       │ P5C: #44 ruff-arch │
                              │      waves 3+4     │       │      43 findings   │
                              │ P4D: #21+#22 ruff  │       └────────────────────┘
                              │      waves 5+6     │
                              └────────────────────┘       ── human gate ──
                                                           gates.conf MAX_FLAGGED=10
                                                           Phase 6 (2 items, 2∥)
                                                           ┌────────────────────┐
                                                           │ P6A: #46 suppress  │
                                                           │      83 identities │
                                                           │ P6B: #47 coupling  │
                                                           │      34/40 flagged │
                                                           └────────────────────┘
                                                           ── post-phase-6 ──
                                                           baseline/threshold updates
```

## CSM Cycle Per Phase

```
DISPATCH (3∥ agents)
    │
    ▼
EXECUTE (agents work in worktrees)
    │
    ▼
VALIDATE (coordinator runs gates)
    │
    ├── PASS ──▶ CHECKPOINT (commit, tag, advance)
    │
    └── FAIL ──▶ DIAGNOSE ──▶ REPAIR (re-dispatch failing agent) ──▶ VALIDATE
                              (max 3 cycles per phase)
```

## Phase 1 — Independent Foundations (3∥, batched into 2 waves of 3)

### Wave 1A (3∥)

File-ownership partition (no concurrent edits to the same file):

- P1A owns `lefthook.yml` only.
- P1B owns `pyproject.toml` `[tool.pytest]` / `[tool.mutmut]` sections AND `Makefile`.
- P1C owns `pyproject.toml` `[tool.coverage]` section only.

| Agent | Items | Files | Work |
|-------|-------|-------|------|
| P1A | #15 | `lefthook.yml` | Fix pre-commit hook ordering: (a) read-only linters/validators run before any modification step, (b) `ruff check --fix` runs before `ruff format` (fix then format, not the reverse), (c) reject partial staging — abort if unstaged changes exist in staged files, (d) rerun read-only linters after auto-fixers to catch regressions introduced by fixes. |
| P1B | #14 | `tests/conftest.py`, `pyproject.toml` (`[tool.pytest]`, `[tool.mutmut]` sections), `Makefile`, all `test_property.py` files | Register `property` marker. Mark every `@given` test. Exclude property from unit coverage. Add `-m property` to every test-property target. Add expected node-count checks. Define all profile fields explicitly. Add reproduction-blob meta-test. |
| P1C | #29 + #30 | `tests/test_init_policy.py` (new), `scripts/check_suppressions.py`, `quality/baselines/suppressions.json`, `pyproject.toml` (`[tool.coverage]` section only) | Add structural test for declarative `__init__.py`. Track exact suppression/exclusion identities. Remove `formatting/registry.py` mutation exclusion and add direct tests. |

### Wave 1B (3∥, after 1A checkpoint)

| Agent | Items | Files | Work |
|-------|-------|-------|------|
| P1D | #32 | `tests/test_retry.py`, `tests/test_rate_limiter.py`, `tests/test_quality_pipeline_configuration.py`, other tests using real sleeps/fixed paths | Inject clocks via monkeypatch/freezegun. Replace fixed `/tmp` with `tmp_path`. Locate executables dynamically. |
| P1E | #45 | `src/perplexity_cli/` (4 files — coordinator identifies the exact files by running `uv run python scripts/check_semgrep_architecture.py` against the baseline before dispatch and embeds the file list in the prompt) | Fix 4 baselined semgrep-architecture findings: click-echo-outside-presentation, sys-exit-outside-boundary, ad-hoc-http-status-classification, http-client-outside-transport. Update baseline to 0. |
| P1F | #9 | `scripts/check_module_coverage.py`, `pyproject.toml`, Makefile | Independently enumerate all `src/**/*.py`. Require every executable module in report. Add diff-cover with explicit base/tested SHA. Validate branch data. |

**Phase 1 checkpoint**: `make check` passes. All 6 items verified. Commit + tag `phase-1-complete`.

## Phase 2 — Architecture + Lanes (3∥, batched into 2 waves)

### Wave 2A (3∥)

| Agent | Items | Files | Work |
|-------|-------|-------|------|
| P2A | #7 | `src/perplexity_cli/ports/` (new package), `quality/architecture.toml`, `.importlinter`, `scripts/generate_importlinter.py`, application services | Create ports package with protocol ABCs: `QueryGateway`, `AuthTokenStore`, `ThreadRepository`, `AttachmentUploader`, `ModelCatalog`, `ConfigStore`. Existing ports-layer modules stay in place; the new `ports/` package holds protocol ABCs only. Update `quality/architecture.toml` to classify the new package. Regenerate `.importlinter`. Replace concrete adapter imports in application with ports. |
| P2B | #40 | `tests/conftest.py`, `pyproject.toml`, Makefile, test files with `integration` marker | Remove marker selection from global addopts. Add `hermetic_integration` marker. Reclassify current integration markers. Rename mocked E2E suites. Add collection policy tests. |
| P2C | #17 | `pyproject.toml`, source files | Fix remaining findings from already-enabled wave 1 rules (C90, PL, ARG, RET, SIM, BLE, FBT); ratchet any findings that cannot be fixed cleanly. |

### Wave 2B (1 agent, after 2A)

> Single agent because P2D edits `Makefile` and `scripts/check_module_coverage.py`, which would conflict with any concurrent agent touching the same files.

| Agent | Items | Files | Work |
|-------|-------|-------|------|
| P2D | #28 | `scripts/check_module_coverage.py`, Makefile | Source-complete coverage enumeration. AST-classify `__init__.py`. Reject omitted executable modules. Wire to `make check`. |

**Phase 2 checkpoint**: `make check` + `make import-linter` pass. Commit + tag `phase-2-complete`.

## Phase 3 — Integration + Typing (3∥, batched into 2 waves)

### Wave 3A (3∥)

| Agent | Items | Files | Work |
|-------|-------|-------|------|
| P3A | #10 | `tests/conftest.py`, `tests/test_hermetic_query.py` (new), `tests/test_hermetic_upload.py` (new), `tests/helpers/` (new) | Build local loopback HTTP/SSE server harness. Query protocol chain test. Attachment upload chain test. Autouse non-loopback network guard. Adversarial connection-rejection tests. |
| P3B | #42 | `src/perplexity_cli/utils/config/` (split), `src/perplexity_cli/utils/logging/` (split), `src/perplexity_cli/utils/http_errors/` (split), `src/perplexity_cli/contracts/` (new), `quality/architecture.toml`, `.importlinter` | Split utils/config into contracts+impl. Split utils/logging. Split utils/http_errors into typed classifier+boundary. Promote api.models types to contracts/. Reclassify split modules in `quality/architecture.toml`; regenerate `.importlinter`. |
| P3C | #25 | `pyproject.toml`, source files | Enable remaining strict sub-options (`reportUnknown*`, `reportMissingTypeArgument`); resolve findings domain→ports→application. |

### Wave 3B (1 agent, after 3A)

| Agent | Items | Files | Work |
|-------|-------|-------|------|
| P3D | #18 | `pyproject.toml`, source files | Ruff wave 2: ANN, TC, FA, PYI. Fix clean findings, ratchet noisy families. |

**Phase 3 checkpoint**: `make check` + hermetic tests pass. Commit + tag `phase-3-complete`.

## Phase 4 — Tests + Ruff (3∥, batched into 2 waves)

### Wave 4A (3∥)

| Agent | Items | Files | Work |
|-------|-------|-------|------|
| P4A | #11 | `tests/test_optional_auth.py`, `tests/test_api_integration.py`, CLI composition/runner tests, attachment suites | Systematic assertion audit. Fix generic error alternatives, swallowed exceptions, weak disjunctions. Assert exact exit codes, envelopes, error codes, stdout/stderr. |
| P4B | #12 | `tests/test_attachments_integration.py`, other mock-heavy suites | Replace internal constructor patches with application fixtures + fake protocol boundary. Use autospec/spec_set/AsyncMock. Shared adapter contract tests. |
| P4C | #19 + #20 | `pyproject.toml`, source files | Ruff wave 3: TRY, EM, RSE. Ruff wave 4: LOG, G, T20. Fix clean findings, ratchet noisy. |

### Wave 4B (1 agent, after 4A)

> Single agent because P4D edits `pyproject.toml` and source/test files that overlap with P4C's ruff configuration; serialising avoids merge conflicts on the shared config.

| Agent | Items | Files | Work |
|-------|-------|-------|------|
| P4D | #21 + #22 | `pyproject.toml`, source/test files | Ruff wave 5: PTH, DTZ, SLOT, PERF, PIE. Ruff wave 6: PT (pytest style). |

**Phase 4 checkpoint**: `make check` + all test lanes pass. Commit + tag `phase-4-complete`.

## Phase 5 — Ruff Completion + Debt (3∥)

> Coordinator runs ruff/pyright before dispatch, partitions files into disjoint sets per agent, and embeds file lists in dispatch prompts.

| Agent | Items | Files | Work |
|-------|-------|-------|------|
| P5A | #23 + #24 | `pyproject.toml`, source files | Ruff wave 7: DOC (pydoclint — distinct from the already-active D / pydocstyle rules; DOC enforces docstring parameter/return consistency, not mere presence). Ruff wave 8: FURB/Refurb. Advisory first, ratchet if useful. |
| P5B | #43 | Source files (682 pyright-strict findings — coordinator partitions into disjoint file sets) | Resolve pyright-strict findings by layer. Start with domain/ports (clean), then application, then adapters. Remove type: ignore shims as findings resolve. |
| P5C | #44 | Source files (43 ruff-architecture findings — coordinator partitions into disjoint file sets) | Fix PLR0913 (23), PLR2004 (14), C901 (4), ARG001 (1), ARG002 (1). Extract helpers, group params into dataclasses, extract constants. |

**Phase 5 checkpoint**: `make check` + ratchets show reduced baselines. Commit + tag `phase-5-complete`.

## Human Gate — Between Phase 5 and Phase 6

`quality/gates.conf` is denied to coding agents. A human must perform this step before Phase 6 dispatch:

1. Edit `opencode.jsonc` to temporarily remove the deny rule on `quality/gates.conf`.
2. Edit `quality/gates.conf`: set `MAX_FLAGGED = 10`.
3. Restore the deny rule in `opencode.jsonc`.
4. Commit: `chore: tighten coupling gate to MAX_FLAGGED=10`.

## Phase 6 — Remaining Debt (2∥)

> Coordinator runs ruff/pyright before dispatch, partitions files into disjoint sets per agent, and embeds file lists in dispatch prompts.

| Agent | Items | Files | Work |
|-------|-------|-------|------|
| P6A | #46 | Source files (83 suppression identities — coordinator partitions into disjoint file sets) | Remove type: ignore shims dissolved by pyright-strict work. Fix remaining suppressions. Target: ≤10 identities. |
| P6B | #47 | Source files (34/40 flagged modules — coordinator partitions into disjoint file sets) | Reduce coupling: split high-D modules, introduce ports where needed. Target: ≤10 flagged modules. |

**Phase 6 checkpoint**: `make check` + all ratchets at target. Commit + tag `phase-6-complete`.

## Post-Phase-6 — Baseline and Threshold Updates

After Phase 6 passes:

1. Regenerate all quality baselines (`quality/baselines/`).
2. Verify ratchet targets match actual counts (zero or agreed floor).
3. Confirm `quality/gates.conf` thresholds are at final values.
4. Commit: `chore: finalise baselines and thresholds`.

## Final Acceptance

```bash
make check                    # all 12 gates
make ci                       # full pipeline
make import-linter            # 0 broken contracts
make semgrep                  # 0 findings
make gitleaks-ci              # 0 leaks
make ratchets                 # all baselines at target
make test-property-ci         # property tests pass
make mutate-full-policy       # mutation score ≥ 70%
uv run python scripts/check_coupling.py --max-flagged 10 --blocking
```

## Resume Protocol

Each phase checkpoint is a git tag. To resume:

```bash
git log --oneline --decorate | grep phase-       # find last checkpoint
git checkout -b resume-phase-N <tag>             # create branch from checkpoint
```

Always resume on a named branch (`resume-phase-N`), never in detached HEAD, so that new commits are reachable and pushable.

## Risk Register

| Risk | Mitigation |
|------|------------|
| Architecture migration breaks imports | Ports are additive; replace one adapter at a time; run full test suite after each replacement |
| Ruff waves produce too many findings | Ratchet noisy families; hard-fail only clean families |
| Pyright strict rollout blocks on adapter typing | Roll out by layer; adapters last; ratchet if needed |
| Hermetic integration harness is complex | Start with query chain only; add upload chain after query works |
| Coupling splits break imports | Split one module at a time; run full test suite after each split |
| Phase 5 pyright debt (682) is too large | Batch by file; prioritize domain/ports/application; ratchet adapters |
| Concurrent agents edit the same config file | File-ownership partition per wave; single-agent waves where Makefile/pyproject.toml conflict is unavoidable |
| gates.conf is agent-denied but Phase 6 needs threshold change | Explicit human-gated step between Phase 5 and Phase 6 |
