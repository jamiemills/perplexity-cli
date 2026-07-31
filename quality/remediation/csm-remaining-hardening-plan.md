# CSM Plan — Remaining Quality Gates Hardening (v2)

> Base: 7624ada | Max parallel: 3 | Model: cyclic state machine

## Scope

| ID | Area | Effort | Source |
|----|------|--------|--------|
| H1 | Bandit alignment + gate wiring | S | Hardening Ph 1 |
| H2 | Empty ratchets → hard gates | S-M | Hardening Ph 2 |
| H3 | Ports adoption (remaining adapter imports) | L | Hardening Ph 3 |
| H5 | Ruff wave 8 (FURB, DOC already suppressed) | M | Hardening Ph 5 |
| H6 | Strict Pyright rollout (682 findings) | L | Hardening Ph 6 |
| H8 | CodeQL JS/TS verification | S | Hardening Ph 8 |
| H9 | Suppression reason enforcement | M | Hardening Ph 9 |
| H10 | Diff coverage CI + mutmut PR CI | M | Hardening Ph 10 |
| D2 | Split utils/logging (re-export shim) | M | Debt P2.2 |
| D3 | Split utils/http_errors (re-export shim) | M | Debt P2.3 |
| D4 | Promote api.models types → contracts/ | M | Debt P2.4 |

## Phase 1 — Quick Wins (3∥, independent)

| Agent | IDs | Files | Work |
|-------|-----|-------|------|
| P1A | H1 | `pyproject.toml` ([tool.bandit]) | Document explicit Bandit severity/confidence policy. No code changes needed — Bandit currently reports 0 findings across src+scripts. |
| P1B | H2 | `quality/gates.conf`, `quality/baselines/` | Audit empty ratchets: ruff-architecture (0), pyright-strict (0), file-size (0). Document as hard gates already enforced. No toggle changes needed — they're hard gates in practice. Add `CHECK_FILE_SIZE` toggle if missing. |
| P1C | H8 | `.github/workflows/`, docs | Verify CodeQL JS/TS exists in repo settings. Add `make codeql-status` diagnostic target. Document status in QUALITY_GATES.md. |

**Checkpoint**: `git tag hardening-p1`

## Phase 2 — Architecture + Module Splits (2∥ sequential)

> P2A runs alone. Then P2B completes. Then P2C completes. Both P2B and P2C touch `.importlinter` and `architecture.toml` — serialised to avoid merge conflicts.

### Wave 2A — Ports Adoption (1 agent)

| Agent | Files | Work |
|-------|-------|------|
| P2A | `ports/__init__.py`, `query_runner.py`, `query_streaming.py`, `services/model_service.py` | 1. Add `__enter__`/`__exit__` to `QueryGateway` protocol so it supports context-manager usage. 2. Replace `PerplexityAPI` type annotations with `QueryGateway` in query_runner where feasible (context manager usage stays with concrete class, type annotations point to protocol). 3. `TokenManager`/`load_token_optional` acknowledged as necessary adapter imports — they take concrete TokenManager, not port — document as allowed composition-root wiring. 4. Regenerate `.importlinter`. |

### Wave 2B — Module Splits (1 agent, after 2A)

| Agent | Files | Work |
|-------|-------|------|
| P2B | `utils/logging/` (new package), `utils/http_errors/` (new package), `.importlinter`, `architecture.toml` | **Strategy**: Create sub-packages with re-export shims at old paths. 1. `logging/__init__.py` — re-exports everything (0 consumer breakage). `logging/contracts.py` — contains LoggerProtocol + redact helpers grouped into a RedactionProtocol. `logging/impl.py` — actual implementations. 2. `http_errors/__init__.py` — re-export shim. `http_errors/classify.py` — classify_http_error, classify_network_error. `http_errors/handle.py` — handle_http_error, raise_http_status_error, handle_network_error, handle_unexpected_cli_error. 3. Update architecture.toml + regenerate .importlinter. |

### Wave 2C — Contracts Package (1 agent, after 2B)

| Agent | Files | Work |
|-------|-------|------|
| P2C | `contracts/` (new top-level), `api/models.py`, `api/contracts.py` (check existing), `.importlinter`, `architecture.toml` | **Note**: `api/contracts.py` already exists in ports layer. Keep it. Create `contracts/query.py` with: `QueryInput`, `TraceContext`, `Answer` (data classes used across layers). Re-export from `api/models.py` for backwards compat. Do NOT move `Block` — it's a Pydantic model, stays in api/. Update architecture.toml + .importlinter. |

**Checkpoint**: `git tag hardening-p2`. Verify `make import-linter` + `make arch-check` pass.

## Phase 3 — Ruff + Doc Suppressions (2∥)

| Agent | IDs | Files | Work |
|-------|-----|-------|------|
| P3A | H5 | `pyproject.toml` ([tool.ruff.lint]) | Remove `"FURB"` from `src/**/*.py` per-file-ignores. Fix FURB findings (FURB110/113/162). Ratchet noisy if >50. DOC stays suppressed — too many findings (692), not worth the effort. |
| P3B | H9 | `scripts/check_suppressions.py`, `quality/baselines/suppressions.json` | Enforcement: every `# noqa`, `# nosec`, `# type: ignore`, `# nosemgrep` must have `owner: <name>; reason: <text>` format. Add meta-test that scans source for suppresssions without this format and fails. Do NOT require existing 139 suppressions to reformat — ratchet new ones. |

**Checkpoint**: `git tag hardening-p3`

## Phase 4 — Pyright Rollout (3∥, file-partitioned)

> Coordinator partitions files into 3 disjoint sets before dispatch.

| Agent | IDs | Files (disjoint sets) | Work |
|-------|-----|----------------------|------|
| P4A | H6 set A | `models/`, `config/`, `_types.py`, `envelope.py`, `ndjson.py`, `exit_codes.py`, `error_handler.py`, `ports/`, `contracts/` | Resolve pyright findings in domain/ports layer. Target: ~200 findings resolved. |
| P4B | H6 set B | `auth/`, `api/endpoints.py`, `api/rest_client.py`, `formatting/`, `utils/` (half) | Resolve findings in adapter/formatter layer. Target: ~200 resolved. |
| P4C | H6 set C + H10 | `runners/`, `threads/`, `attachments/`, `query_runner.py`, `query_streaming.py`, `mcp_server.py`, `cli.py`, `command_runner.py`, `.github/workflows/ci.yml` | Resolve findings in presentation/runner layer. Add diff-coverage + mutmut-diff to CI workflow. Target: ~200 resolved. |

**Checkpoint**: `git tag hardening-p4`

## Phase 5 — Final Polish (1 agent, serial)

| Agent | IDs | Files | Work |
|-------|-----|-------|------|
| P5A | H6 remainder | All remaining pyright findings | Final pass. Target: ≤100 findings, all ratcheted with owner/reason per file. Update all baselines. Run `make check` + `make ci`. |

**Checkpoint**: `git tag hardening-complete`

## CSM Cycle

```
DISPATCH → EXECUTE → VALIDATE → CHECKPOINT
     ↓ FAIL
DIAGNOSE → REPAIR (max 3) → VALIDATE
```

## Collision Map

| File | Writers | Strategy |
|------|---------|----------|
| `.importlinter` | P2A, P2B, P2C | Serial (2A→2B→2C) |
| `architecture.toml` | P2A, P2B, P2C | Serial |
| `pyproject.toml` | P3A only | Exclusive per phase |
| `query_runner.py` | P2A, P4C | Different phases (P2→P4) |

## Resume Protocol

```bash
git tag -l 'hardening-*'                 # find last checkpoint
git checkout -b resume-hardening <tag>   # branch from checkpoint
```
