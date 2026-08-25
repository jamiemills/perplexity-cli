format: csm-review/1

# Repository Review — perplexity-cli @ a78ec7f (2026-08-21)

## Control

- Scale: QUICK (user-named focus: problems, errors, poor architecture choices, bad patterns, poor practices → quality dimensions 1–4)
- Posture: R0 static only (user gave no rung choice; supply-chain dims 15–16 out of scope)
- Pinned SHA: `a78ec7fb2e3125e7869930d8515bf673c3f7746e` (worktree clean at intake)
- Journal:
  - [2026-08-21T22:20Z] INTAKE -> SCOPE :: cycle 1 :: trigger: activation :: rungs: R0
  - [2026-08-21T22:24Z] SCOPE -> FIND :: cycle 1 :: trigger: coverage plan recorded :: rungs: R0
  - [2026-08-21T22:26Z] FIND (subagent batch 4/4 returned EMPTY — environment instability; resilience ladder steps 1–3 previously exhausted this session) -> FIND (primary-led) :: cycle 1 :: trigger: finder failure :: rungs: R0
  - [2026-08-21T22:35Z] FIND -> CHALLENGE :: cycle 1 :: trigger: ledger complete (primary-led) :: rungs: R0
  - [2026-08-21T22:36Z] CHALLENGE -> ADJUDICATE :: cycle 1 :: trigger: primary-led challenge with recorded caveat on every finding :: rungs: R0
  - [2026-08-21T22:36Z] ADJUDICATE -> VERIFY :: cycle 1 :: trigger: adjudicated :: rungs: R0
  - [2026-08-21T22:38Z] VERIFY -> SAVED :: cycle 1 :: trigger: all gate checks passed with caveats :: rungs: R0

## How To Execute

This report fixes nothing. Remediation happens only through a future explicit `csm-plan` or `csm-grill` invocation referencing specific finding IDs.

## Executive Summary

- **F-001 (medium, E1)** — a real import cycle in `utils/config` is known to tooling (pyright warns on every run) and is tolerated as a permanent warning rather than fixed; it contradicts the repo's own enforced layering story.
- **F-002 (medium, E1)** — the application-layer `query_runner` exposes 17 module-level `Any`-typed seam attributes wired by the composition root and patched across 23 test files; this is a service-locator pattern that defeats the static layering enforcement it exists to satisfy.
- **F-003 (medium, E1)** — suppression-comment identity ratchets include line numbers, so any upstream edit forces baseline refreshes; this cost four no-growth refreshes during the current execution cycle alone.
- **F-004 (low, E3)** — lint authority is split-brained: 30 globally ignored ruff rules (incl. all FBT) plus 64 per-file ignores are compensated by a separate Semgrep policy; two sources of truth for the same policy invite drift.
- **F-005 (low, E4)** — `scripts/run_mutation.py` (764 lines) concentrates environment verification, process-group control, pattern conversion, and CLI in one module — a growing god-module in otherwise well-partitioned tooling.
- **F-006 (info, E4)** — config/build sprawl: 745-line Makefile, 303-line lefthook, 35-step CI job with 16 repeated `setup-uv` blocks and no composite actions.
- Overall posture: engineering quality is high for a CLI of this size (enforced layering, ratchets, mutation testing); the systemic theme is **mechanism accretion** — quality tooling itself is accumulating the coupling and duplication it exists to prevent.

## Methodology Disclosure

- Reviewers: primary agent (sole finder and challenger after subagent fleet returned four empty results; independence caveat applies to **every** finding — no independent challenge was achievable this run).
- Tools: pyright 1.1.410 (deterministic cycle warning), radon, ruff dev, tomllib introspection, git grep at pinned SHA.
- Rungs: R0 only. No sandbox execution; no OSV/endoflife queries (supply-chain dimensions excluded by user scope).
- Containment: read-only commands; no repository writes outside `.agents/reviews/`; intake baseline (clean tree) re-verified at VERIFY.
- Anchor editions: OWASP/ISO anchors not exercised (no security-dimension findings claimed); sizes/counts cited from pinned SHA directly.
- Residual unknowns: dimensions 5–16 not reviewed this run; all findings carry primary-only confidence caps.

## Coverage

| Dimension | src/ chunk | scripts+CI+build chunk | Verdict |
|---|---|---|---|
| 1 Correctness & defects | not systematically walked (finder empty) | not systematically walked | **gapped** — see Anti-Coverage |
| 2 Technical debt & architecture | F-001, F-002 | F-005 | covered (primary-led) |
| 3 Code smells & poor practices | F-002 (typed-Any seams) | F-003, F-004 | covered (primary-led) |
| 4 Anti-patterns | F-002 | F-006 | covered (primary-led) |

## Anti-Coverage

- **Dimension 1 (correctness/functional bugs)** — not reviewed: the dedicated finder subagent returned empty and retry budget was consumed by earlier session failures. Risk: **high** — a 105-module production surface with no independent correctness pass this run.
- **Dimensions 5–16** (security, concurrency, memory, resilience, input validation, tests, supply chain, currency) — out of QUICK scope per user's question. Risk: **medium** — no fresh dependency-advisory check this run.
- **tests/** deep review — sampled only via seam-patching counts. Risk: low-medium.
- **docs/** (README/SECURITY) — not reviewed. Risk: low.

## Findings Summary

| Severity | Count |
|---|---|
| medium | 3 (F-001..F-003) |
| low | 2 (F-004, F-005) |
| info | 1 (F-006) |

Confidence: E1 ×3, E3 ×1, E4 ×2. Dedup: 6 raw → 6 upheld, 0 merged, 0 retracted.

## Findings

### F-001 — Known import cycle in utils/config tolerated as permanent warning
- dimension: technical-debt/architecture; category: architecture-erosion
- anchor_ref: null
- severity: medium; confidence: **verified (E1)**
- locations: `src/perplexity_cli/utils/config/__init__.py:1` (cycle entry), `src/perplexity_cli/utils/config/impl.py`
- quoted_snippet: `"Cycle detected in import chain: utils/config/__init__.py -> utils/config/impl.py (reportImportCycles)"` (pyright output, reproduced this run)
- commit_sha: a78ec7f
- explanation: pyright emits this warning on every full run and the repo treats one warning as acceptable (`0 errors, 1 warning` gates pass). The cycle contradicts the strictly layered architecture the repo enforces elsewhere.
- impact: cycles make extraction/testing harder and normalise "one warning" as a baseline that can mask future cycles added to the same pair.
- remediation_sketch: break the cycle by moving the shared symbol the two modules need into a leaf module; then tighten pyright to fail on `reportImportCycles` for `utils/config`.
- verification: {method: pyright run, command: `uv run pyright src/perplexity_cli/utils/config/__init__.py`, result: cycle warning reproduced}
- challenges: [primary-led; caveat: no independent challenger available]
- status: upheld

### F-002 — Service-locator seams: 17 `Any`-typed module globals patched by 23 test files
- dimension: anti-patterns; category: service-locator / typed-Any boundary
- anchor_ref: null
- severity: medium; confidence: **verified (E1)** (mechanism), capped medium by primary-only challenge
- locations: `src/perplexity_cli/query_runner.py:90-106` (declarations), `src/perplexity_cli/cli.py:45-79` (wiring), 23 files under `tests/` (patching)
- quoted_snippet: `handle_error: Any = None` … `AttachmentUploader: Any = None` (17 consecutive declarations)
- commit_sha: a78ec7f
- explanation: the application layer avoids static adapter imports by exposing module globals typed `Any`, populated at composition time and replaced per-test via monkeypatching. This satisfies the import checker while forfeiting all static safety the layering was meant to buy: a misspelled seam or wrong collaborator type fails only at runtime.
- impact: refactors silently break; every collaborator change touches composition wiring plus many test files (shotgun surgery); the `Any` types hide contract drift between query_runner and its adapters.
- remediation_sketch: replace module globals with an injected frozen dataclass/Protocol context object (constructor parameter), letting the type checker verify collaborator contracts and tests patch one object.
- verification: {method: grep counts at pinned SHA, command: `grep -c "Any = None" query_runner.py` → 17; `grep -rln ... tests/ | wc -l` → 23, result: confirmed}
- challenges: [primary-led; caveat: no independent challenger available]
- status: upheld

### F-003 — Line-identity suppression ratchet is brittle to any upstream edit
- dimension: code smells/poor practices; category: fragile-baseline coupling
- anchor_ref: null
- severity: medium; confidence: **verified (E1)** (behaviour), capped medium
- locations: `scripts/check_suppressions.py` (identity includes line number), `quality/baselines/suppressions.json`
- quoted_snippet: `NEW scripts/run_mutation.py:391:nosec` (ratchet output after pure line movement)
- commit_sha: a78ec7f
- explanation: the no-growth ratchet keys findings on `file:line:rule`, so inserting lines above any annotated suppression changes identity and fails CI despite identical suppression semantics. During the current execution cycle alone this forced four no-growth baseline refreshes.
- impact: recurring mechanical churn trains developers to run `--update-baseline` reflexively, eroding the ratchet's purpose (detecting *new* suppressions); a careless reflex refresh could also launder genuinely new suppressions.
- remediation_sketch: key identities on `file:rule:owner:reason` content hash (or nearest-function anchor) instead of raw line numbers, keeping no-growth semantics while tolerating edits.
- verification: {method: executed ratchet during this cycle, command: `uv run python scripts/check_suppressions.py`, result: four line-move failures observed and refreshed 2026-08-21}
- challenges: [primary-led; caveat: no independent challenger available]
- status: upheld

### F-004 — Split-brain lint authority (ruff ignore-list vs Semgrep policy)
- dimension: code smells/poor practices; category: policy-drift risk
- anchor_ref: null
- severity: low; confidence: medium (E3)
- locations: `pyproject.toml` ([tool.ruff] 30 global ignores incl. FBT*, 64 per-file ignores), `.semgrep.yml` (boolean-flag-argument etc.)
- quoted_snippet: ruff ignore includes `FBT001, FBT002, FBT003` while Semgrep blocks `boolean-flag-argument`
- commit_sha: a78ec7f
- explanation: boolean-parameter policy is simultaneously disabled in ruff and enforced in Semgrep; during the current cycle this exact split let three boolean-flag violations reach full CI (caught late by Semgrep). Two overlapping authorities with different rule sets invite drift and late failures.
- impact: violations surface only at the expensive late CI stage; contributors cannot predict which linter governs a rule.
- remediation_sketch: pick one authority per rule family — either enable FBT in ruff and drop the Semgrep rule, or document Semgrep as sole owner and add a ruff `ignore` comment cross-reference in pyproject.
- challenges: [primary-led; caveat]
- status: upheld

### F-005 — run_mutation.py is becoming a god-module
- dimension: technical-debt; category: god-module
- anchor_ref: null
- severity: low; confidence: low (E4)
- locations: `scripts/run_mutation.py` (764 lines)
- quoted_snippet: module docstring spans env verification, process control, budget math, pattern conversion, and CLI
- commit_sha: a78ec7f
- explanation: one script mixes at least five responsibilities (RECORD/environment verification, process-group lifecycle, deadline budgeting, manifest→pattern conversion, report publication). Sibling tooling (`mutation_policy.py`, `mutation_evidence.py`, `mutation_manifest.py`) is well-partitioned, making this the outlier.
- impact: each new runner concern grows the file and its test matrix; the 31-test suite already spans five unrelated concern groups.
- remediation_sketch: extract `mutation_process.py` (Popen/group/signals) and `mutation_environment.py` (RECORD/identity) as pure modules mirroring the existing pattern.
- challenges: [primary-led; caveat]
- status: upheld

### F-006 — Build/config sprawl: 745-line Makefile, 303-line lefthook, 35-step CI job
- dimension: anti-patterns; category: config-sprawl / duplication
- anchor_ref: null
- severity: info; confidence: low (E4)
- locations: `Makefile`, `lefthook.yml`, `.github/workflows/ci.yml` (16 `setup-uv@…` blocks, 35 named steps)
- quoted_snippet: repeated `astral-sh/setup-uv@…` + `setup-python@…` + `uv sync --locked` preamble in every job
- commit_sha: a78ec7f
- explanation: environment preamble is copy-pasted across all 16 CI jobs instead of a composite action; the Makefile has grown past 700 lines with three distinct target families interleaved.
- impact: a toolchain bump (e.g. uv version) edits 16 places; drift between jobs is likely.
- remediation_sketch: introduce a composite action (`uses: ./.github/actions/setup-env`) and split the Makefile into included domain fragments if it keeps growing.
- challenges: [primary-led; caveat]
- status: upheld

## Adjudication Log

- All six findings: confidence capped at their evidence class (E1 findings kept verified for the mechanism but flagged medium where impact reasoning is primary-only; F-004/F-005/F-006 held at medium/low/low per class). No merges; no rejections.

## Retracted Findings

None.

## Reproducibility

- Pinned SHA: `a78ec7fb2e3125e7869930d8515bf673c3f7746e`
- Commands: `uv run pyright <file>`; `grep` counts as recorded per finding; `tomllib` parse of `pyproject.toml`
- Sandbox: none (R0)
- Evidence artifacts: pyright cycle output; seam declaration block `query_runner.py:90-106`; ratchet outputs from 2026-08-21 execution journal
- Not committed (write discipline)
