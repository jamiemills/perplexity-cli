# Parallel Execution Plan for pxcli v0.7.0

**Created:** 2026-05-09
**Last updated:** 2026-05-09
**Status:** COMPLETE — ALL 5 WAVES PASSED
**Parent plan:** `agent-cli-best-practices-plan.md` (source of truth for specs and test cases)

---

## Why Parallelise?

The original sequential plan has 9 phases executed in order: P1 → P2 → P3 → P4 → P5 → P6 → P7 → P8 → P9. This is slow because many phases create independent modules that share no files.

The constraint for parallel sub-agents is: **two agents must not modify the same file simultaneously**. The bottleneck files are:

| File | Original phases that modify it |
|------|-------------------------------|
| `commands.py` | P1, P2, P3, P5, P8 |
| `cli.py` | P1, P3, P7 |
| `query_runner.py` | P2, P3, P4, P6, P7 |

These three files form the critical path and must be handled by single agents in sequence. Everything else can be partitioned into non-overlapping file sets for parallel execution.

---

## Wave Structure

```
Wave 1: 6 parallel agents — new files only (zero conflict risk)
   │
   ▼
Wave 2: 1 agent — structural refactor (commands.py + cli.py + flag stubs)
   │
   ▼
Wave 3: 4 parallel agents — behaviour integration (disjoint file ownership)
   │
   ▼
Wave 4: 3 parallel agents — discoverability + ecosystem
   │
   ▼
Wave 5: 1 agent — release
```

**Critical path:** Agent 1.1 → Wave 2 → Agent 3.3 → Agent 4.1 → Wave 5 = **5 sequential steps** (down from 9).

---

## Wave 1: New Standalone Modules (6 parallel agents)

**Precondition:** None — this is the first wave.
**Constraint:** Every agent creates only NEW files. No existing file is modified.
**Verification:** Each agent runs its own tests in isolation: `uv run pytest <test_file> -v`

### Agent 1.1: Output Contract Core

**Creates:**
- `src/perplexity_cli/envelope.py` — Pydantic models (`Envelope`, `ErrorEnvelope`, `Meta`, `NextAction`), builder functions (`success_envelope()`, `error_envelope()`), error code string enum
- `src/perplexity_cli/exit_codes.py` — exit code integer constants, exception-to-exit-code mapping function, `format_exit_codes_help()` text generator
- `src/perplexity_cli/error_handler.py` — `handle_error()` function (JSON mode: writes error envelope to stdout; human mode: writes to stderr), delegates to envelope.py and exit_codes.py
- `tests/test_envelope.py` — tests 2.2.1–2.2.9 from parent plan (~9 tests)
- `tests/test_exit_codes.py` — tests 2.2.10–2.2.12 (~3 tests, but 2.2.11 has ~12 sub-cases)
- `tests/test_error_handler.py` — tests 2.2.13–2.2.15 (~3 tests, but 2.2.15 has ~12 sub-cases)

**Must not touch:** Any existing source file.
**Tests:** ~35 tests total.
**Spec reference:** Parent plan Phase 2, sections 2.1.1–2.1.4 and 2.2.1–2.2.15.

### Agent 1.2: NDJSON Writer

**Creates:**
- `src/perplexity_cli/ndjson.py` — NDJSON event models (`StartEvent`, `ChunkEvent`, `ProgressEvent`, `ResultEvent`), `NDJSONWriter` class that writes typed events as JSON lines to a file-like object, each line includes `ts` (ISO 8601), `type`, and event-specific fields
- `tests/test_ndjson.py` — unit tests for the writer module itself (not integration with streaming): event serialisation, line format, timestamp format, event ordering validation (~10 tests)

**Must not touch:** Any existing source file. Integration with `api/streaming.py` happens in Wave 3.
**Tests:** ~10 tests.
**Spec reference:** Parent plan Phase 6, sections 6.1.1–6.1.10 (unit-testable parts only; integration tests in Wave 3).

### Agent 1.3: Help JSON Builder

**Creates:**
- `src/perplexity_cli/help_json.py` — builds machine-readable JSON representation of CLI help (commands, options, arguments, version). Input is a Click group object; output is a dict suitable for JSON serialisation.
- `tests/test_help_json.py` — tests that the builder extracts commands, options, arguments from a mock Click group (~5 tests)

**Must not touch:** Any existing source file. Wiring into `--help --json` happens in Wave 4.
**Tests:** ~5 tests.
**Spec reference:** Parent plan Phase 5, sections 5.1.14–5.1.16.

### Agent 1.4: Session Logger

**Creates:**
- `src/perplexity_cli/session_log.py` — NDJSON session logger. Writes invocation and response events to `$XDG_DATA_HOME/pxcli/sessions/<id>.ndjson`. Activated by `PXCLI_SESSION_LOG=true` env var.
- `tests/test_session_log.py` — tests 7.1.5–7.1.8 from parent plan: file creation, conditional activation, NDJSON validity, event types (~5 tests)

**Must not touch:** Any existing source file. Wiring into the CLI entrypoint happens in Wave 3.
**Tests:** ~5 tests.
**Spec reference:** Parent plan Phase 7, sections 7.1.5–7.1.8.

### Agent 1.5: Gap-Fill Tests Batch A

**Creates (test files only — no source changes):**
- `tests/test_auth_models.py` — tests for `src/perplexity_cli/auth/models.py`: serialisation, deserialisation, validation of auth data models (test 1.2.10 from parent plan, ~4 tests)
- `tests/test_http_headers.py` — tests for `src/perplexity_cli/utils/http_headers.py`: HTTP header construction functions (test 2.2.36, ~5 tests)
- `tests/test_file_permissions.py` — tests for `src/perplexity_cli/utils/file_permissions.py`: permission verification functions (test 3.1.17, ~4 tests)

**Must not touch:** Any existing source file. Tests exercise the existing public API only.
**Tests:** ~13 tests.
**Spec reference:** Parent plan tests 1.2.10, 2.2.36, 3.1.17.

### Agent 1.6: Gap-Fill Tests Batch B

**Creates (test files only — no source changes):**
- `tests/test_config_models.py` — tests for `src/perplexity_cli/config/models.py`: `URLConfig`, `FeatureConfig`, `RateLimitConfig` Pydantic validation (test 3.1.18, ~5 tests)
- `tests/test_async_bridge.py` — tests for `src/perplexity_cli/utils/async_bridge.py`: `run_async()` helper (test 6.1.11, ~3 tests)
- `tests/test_session_factory.py` — tests for `src/perplexity_cli/utils/session_factory.py`: session creation and configuration (test 7.1.12, ~4 tests)

**Must not touch:** Any existing source file. Tests exercise the existing public API only.
**Tests:** ~12 tests.
**Spec reference:** Parent plan tests 3.1.18, 6.1.11, 7.1.12.

### Wave 1 Totals

| Metric | Count |
|--------|-------|
| Parallel agents | 6 |
| New source files | 6 |
| New test files | 12 |
| New tests (approx) | ~80 |
| Existing files modified | 0 |
| Conflict risk | None |

### Wave 1 Verification Gate

After all 6 agents complete:
```bash
uv run pytest tests/test_envelope.py tests/test_exit_codes.py tests/test_error_handler.py \
  tests/test_ndjson.py tests/test_help_json.py tests/test_session_log.py \
  tests/test_auth_models.py tests/test_http_headers.py tests/test_file_permissions.py \
  tests/test_config_models.py tests/test_async_bridge.py tests/test_session_factory.py -v

# Also verify existing tests still pass (no regressions from new imports)
uv run pytest --tb=short -q
```

---

## Wave 2: Command Restructuring (1 agent, sequential)

**Precondition:** Wave 1 complete (new modules available for import).
**Constraint:** This agent owns `commands.py` and `cli.py` exclusively. No other agent touches these files until Wave 4.

### What this agent does

1. **Restructure `commands.py`:**
   - Create Click groups: `auth_group`, `config_group`, `style_group`, `threads_group`, `skill_group`
   - Register subcommands under each group (runner functions unchanged)
   - Remove old flat command registrations (`logout`, `set-config`, `show-config`, `configure`, `view-style`, `clear-style`, `export-threads`, `show-skill`)
   - Add `--json` flag stub to every command (stored in `ctx.obj['json']`, no behaviour change yet)
   - Add short flag forms: `-s` (--stream), `-S` (--strip-references), `-o` (--output), `-p` (--port)
   - Add `--timeout`/`-t` to `query` command (stored in `ctx.obj['timeout']`, no behaviour change yet)
   - Add `--api-version` flag stub to commands with `--json` (stored in `ctx.obj['api_version']`, no behaviour change yet)

2. **Restructure `cli.py`:**
   - Add `--quiet`/`-q` flag (stored in `ctx.obj['quiet']`, no behaviour change yet)
   - Add `--no-color` flag (stored in `ctx.obj['no_color']`, no behaviour change yet)
   - Register new groups on the main CLI group
   - Remove old command registrations

3. **Create test files:**
   - `tests/test_command_tree.py` — tests 1.2.1–1.2.6 from parent plan (~20 tests)
   - `tests/test_auth_runner.py` — tests 1.2.7–1.2.9 (~5 tests)

4. **Update existing tests:**
   - Fix any test that references old command names (e.g., `pxcli logout` → `pxcli auth logout`)
   - Fix any test that invokes the CLI runner with old command paths

**Files owned (modify/create):**
- `src/perplexity_cli/commands.py` (modify)
- `src/perplexity_cli/cli.py` (modify)
- `tests/test_command_tree.py` (create)
- `tests/test_auth_runner.py` (create)
- `tests/*.py` (update references to old command names)

**Must not touch:** Any file owned by Wave 1 agents (new source modules, new test files).
**Tests:** ~25 tests new + updates to existing tests.
**Spec reference:** Parent plan Phase 1 (all sections) + flag stubs from Phases 2, 3, 8.

### Wave 2 Verification Gate

```bash
# All new tests pass
uv run pytest tests/test_command_tree.py tests/test_auth_runner.py -v

# Full suite passes (including Wave 1 tests and updated existing tests)
uv run pytest --tb=short -q
```

---

## Wave 3: Behaviour Integration (4 parallel agents)

**Precondition:** Waves 1 and 2 complete (new modules exist, command structure finalised, flag stubs wired).
**Constraint:** Each agent owns a non-overlapping set of source files. No two agents touch the same file.

### File Ownership Matrix

| Agent | Source files owned | Test files owned |
|-------|-------------------|-----------------|
| 3.1 Query Pipeline | `query_runner.py`, `api/streaming.py` | `test_stdin.py`, `test_standard_flags.py` |
| 3.2 Formatting | `formatting/json.py`, `formatting/base.py`, `formatting/registry.py` | `test_tty_detection.py`, update `test_formatters.py` |
| 3.3 Runners | `runners/auth.py`, `runners/config.py`, `runners/export.py`, `runners/skill.py`, `runners/status.py` | `test_json_output.py`, `test_status_runner.py`, `test_export_runner.py` |
| 3.4 Utils + Globals | `utils/config.py`, `utils/http_errors.py`, `utils/logging.py` | `test_xdg.py`, `test_structured_logging.py` |

### Agent 3.1: Query Pipeline

**Modifies:**
- `src/perplexity_cli/query_runner.py`:
  - Read `ctx.obj['json']` and construct envelope via `success_envelope()` / `error_envelope()`
  - Read `ctx.obj['timeout']` and pass to API client
  - Make `query_text` optional: if absent and stdin is not TTY, read from stdin; if absent and stdin is TTY, exit 2 with usage hint
  - When `--json --stream`, delegate to `NDJSONWriter` (from `ndjson.py`)
  - Generate UUID4 `trace_id` at start, record `time.monotonic()`, compute `duration_ms` at envelope construction
  - Wire `handle_error()` for exception handling
- `src/perplexity_cli/api/streaming.py`:
  - Detect JSON+stream mode and delegate to `NDJSONWriter`
  - Preserve raw text streaming for `--stream` without `--json`

**Creates:**
- `tests/test_stdin.py` — tests 3.1.1–3.1.5 (~5 tests)
- `tests/test_standard_flags.py` — tests 3.1.6–3.1.14, specifically the `--timeout` tests and short form tests that exercise query_runner (~9 tests, but --quiet/--no-color behaviour tested by 3.2/3.4)

**Must not touch:** `commands.py`, `cli.py`, any `formatting/` file, any `runners/` file, any `utils/` file.
**Tests:** ~14 tests.
**Spec reference:** Parent plan Phases 2 (envelope wiring), 3 (stdin, timeout), 6 (NDJSON integration), 7 (trace_id, timing).

### Agent 3.2: Formatting

**Modifies:**
- `src/perplexity_cli/formatting/json.py`:
  - Refactor `JSONFormatter.format_complete()` to produce new envelope shape (using `envelope.py` models)
  - Remove old `format_version: "1.0"` code path
- `src/perplexity_cli/formatting/base.py`:
  - Add TTY detection: when `sys.stdout.isatty()` is `False` and no explicit format specified, default to `plain`
  - Add `NO_COLOR` env var support: when set (any value), disable colour
  - Add `--no-color` flag support: read from formatter context/config
- `src/perplexity_cli/formatting/registry.py` (if format resolution logic lives here):
  - Wire TTY and NO_COLOR into format selection

**Creates:**
- `tests/test_tty_detection.py` — tests 4.1.1–4.1.8 (~8 tests)

**Updates:**
- `tests/test_formatters.py` — tests 2.2.16–2.2.20: JSONFormatter produces envelope, --format json and --json produce identical output, golden snapshots (~5 updated/added tests)

**Must not touch:** `commands.py`, `cli.py`, `query_runner.py`, any `runners/` file, any `utils/` file.
**Tests:** ~13 tests.
**Spec reference:** Parent plan Phases 2 (JSON format), 4 (TTY, NO_COLOR).

### Agent 3.3: Runners

**Modifies:**
- `src/perplexity_cli/runners/auth.py` — add envelope output when `--json`, wire `handle_error()`
- `src/perplexity_cli/runners/config.py` — add envelope output when `--json`, wire `handle_error()`
- `src/perplexity_cli/runners/export.py` — add envelope output when `--json`, wire `handle_error()`
- `src/perplexity_cli/runners/skill.py` — add envelope output when `--json`, wire `handle_error()`
- `src/perplexity_cli/runners/status.py` — add envelope output when `--json`, wire `handle_error()`

Each runner reads `ctx.obj['json']`. If true, wraps its output in `success_envelope()` (or `error_envelope()` on failure) and writes JSON to stdout. If false, preserves current human-readable output.

**Creates:**
- `tests/test_json_output.py` — tests 2.2.21–2.2.31 (~11 tests): per-command JSON envelope tests
- `tests/test_status_runner.py` — tests 2.2.32–2.2.33 (~4 tests)
- `tests/test_export_runner.py` — tests 2.2.34–2.2.35 (~4 tests)

**Must not touch:** `commands.py`, `cli.py`, `query_runner.py`, any `formatting/` file, any `utils/` file.
**Tests:** ~19 tests.
**Spec reference:** Parent plan Phase 2, sections 2.2.21–2.2.35 and 2.3.6.

### Agent 3.4: Utils + Globals

**Modifies:**
- `src/perplexity_cli/utils/config.py`:
  - Update `get_config_dir()` to check `XDG_CONFIG_HOME` env var first, fall back to `~/.config/pxcli`
- `src/perplexity_cli/utils/http_errors.py`:
  - Refactor to return structured error data (error code string, message, input dict) instead of just raising/printing. This structured data feeds into `error_envelope()`.
- `src/perplexity_cli/utils/logging.py`:
  - Add structured JSON log formatter: when `--json --verbose`, stderr log lines are JSON objects with `ts`, `level`, `message`, `trace_id`
  - Wire `--quiet` behaviour: when active, suppress all stderr logging output

**Creates:**
- `tests/test_xdg.py` — tests 3.1.15–3.1.16 (~3 tests)
- `tests/test_structured_logging.py` — tests 7.1.9–7.1.11 (~4 tests)

**Must not touch:** `commands.py`, `cli.py`, `query_runner.py`, any `formatting/` file, any `runners/` file.
**Tests:** ~7 tests.
**Spec reference:** Parent plan Phases 3 (XDG), 2 (structured errors), 7 (structured logging, --quiet).

### Wave 3 Totals

| Metric | Count |
|--------|-------|
| Parallel agents | 4 |
| New test files | 7 |
| Modified source files | ~12 |
| New tests (approx) | ~53 |
| File conflicts | None (disjoint ownership) |

### Wave 3 Verification Gate

```bash
# All new tests pass
uv run pytest tests/test_stdin.py tests/test_standard_flags.py \
  tests/test_tty_detection.py tests/test_json_output.py \
  tests/test_status_runner.py tests/test_export_runner.py \
  tests/test_xdg.py tests/test_structured_logging.py -v

# Full suite passes (including Waves 1-2 tests)
uv run pytest --tb=short -q
```

---

## Wave 4: Discoverability + Ecosystem (3 parallel agents)

**Precondition:** Waves 1–3 complete (envelope wired, command structure stable, all runners producing JSON).
**Constraint:** Each agent owns non-overlapping files.

### File Ownership Matrix

| Agent | Source files owned | Test files owned |
|-------|-------------------|-----------------|
| 4.1 Help + Completion + Schema | `commands.py` (adds new commands only), help formatter module | `test_help_formatting.py`, `test_completion.py`, `test_schema.py` |
| 4.2 SKILL.md | `resources/skill.md` | update `test_skill_runner.py` |
| 4.3 Ecosystem Guards | (no source changes, tests only) | `test_api_version.py`, `test_envelope_snapshots.py` |

### Agent 4.1: Help + Completion + Schema

**Modifies:**
- `src/perplexity_cli/commands.py`:
  - Add `completion` command group with `bash`/`zsh`/`fish` subcommands (shell completion script generation)
  - Add `schema` command (uses Pydantic `.model_json_schema()` to output command/envelope schema)
  - Add `--help --json` support (delegates to `help_json.py`)
  - Apply custom Click help formatter to all commands: adds EXIT CODES, SEE ALSO, ENVIRONMENT VARIABLES sections, proper example formatting

**Creates:**
- `tests/test_help_formatting.py` — tests 5.1.1–5.1.6 (~8 tests)
- `tests/test_completion.py` — tests 5.1.7–5.1.9 (~3 tests)
- `tests/test_schema.py` — tests 5.1.10–5.1.13 (~4 tests)

**Must not touch:** Any file outside `commands.py` and its own test files. `help_json.py` was already created in Wave 1.
**Tests:** ~15 tests.
**Spec reference:** Parent plan Phase 5 (all sections).

### Agent 4.2: SKILL.md

**Modifies:**
- `resources/skill.md` — full rewrite for v0.7.0: new command names, new JSON envelope format, new parsing patterns, exit codes, NDJSON streaming examples, next_actions usage

**Updates:**
- `tests/test_skill_runner.py` — tests 5.1.17–5.1.19: verify SKILL.md references new command names, envelope format, exit codes (~3 tests)

**Must not touch:** Any source file outside `resources/skill.md`.
**Tests:** ~3 tests.
**Spec reference:** Parent plan Phase 5, section 5.2.5.

### Agent 4.3: Ecosystem Guards

**Creates (test files only — no source changes):**
- `tests/test_api_version.py` — tests 8.1.1–8.1.3: `--api-version v1` accepted, `v99` rejected, identical output (~3 tests)
- `tests/test_envelope_snapshots.py` — tests 8.1.4–8.1.6: golden snapshot for every command's success envelope, additive field test, removed field regression test (~6 tests)

**Must not touch:** Any source file. These are pure verification tests.
**Tests:** ~9 tests.
**Spec reference:** Parent plan Phase 8 (all sections).

### Wave 4 Totals

| Metric | Count |
|--------|-------|
| Parallel agents | 3 |
| New test files | 5 |
| Modified source files | 2 (commands.py, skill.md) |
| New tests (approx) | ~27 |
| File conflicts | None (disjoint ownership) |

### Wave 4 Verification Gate

```bash
# All new tests pass
uv run pytest tests/test_help_formatting.py tests/test_completion.py tests/test_schema.py \
  tests/test_api_version.py tests/test_envelope_snapshots.py -v

# Full suite passes (including Waves 1-3 tests)
uv run pytest --tb=short -q
```

---

## Wave 5: Release (1 agent, sequential)

**Precondition:** Waves 1–4 complete. All tests pass.
**Constraint:** This is the final integration agent. It can touch any file.

### What this agent does

1. **Version bump:**
   - Update `pyproject.toml` version from `0.6.6` to `0.7.0`
   - Update any hardcoded version references
   - Verify `pxcli --version` returns `0.7.0`

2. **Coverage thresholds:**
   - Raise `pyproject.toml` `fail_under` from 75 to 85
   - Raise `.github/workflows/ci.yml` threshold from 40 to 75

3. **Documentation:**
   - Update `README.md`: all command examples, JSON examples, shell functions `px()`/`pxc()`, Python examples, new flags, exit codes, NDJSON streaming
   - Update `CONTRIBUTING.md` if it references command names or test patterns

4. **Quality gates:**
   ```bash
   uv run pytest --cov=perplexity_cli --cov-report=term-missing --cov-fail-under=85
   uv run ruff check && uv run ruff format --check
   uv run ty check src
   ```

5. **Build and smoke test:**
   ```bash
   uv build
   # Verify wheel contents include urls.json, skill.md, all source files
   # Smoke test: --version, --help, auth --help, schema, completion zsh
   ```

6. **Tag (on user approval):**
   ```bash
   git add -A && git commit -m "release: v0.7.0 — agent-friendly CLI"
   git tag v0.7.0
   git push origin v0.7.0
   ```

**Tests:** ~3 smoke tests.
**Spec reference:** Parent plan Phase 9 (all sections).

---

## Summary

| Wave | Agents | Sequential? | New tests | New source files | Modified source files |
|------|--------|------------|-----------|-----------------|----------------------|
| 1 | 6 | Parallel | ~80 | 6 | 0 |
| 2 | 1 | Sequential | ~25 | 0 | 2 |
| 3 | 4 | Parallel | ~53 | 0 | ~12 |
| 4 | 3 | Parallel | ~27 | 0 | 2 |
| 5 | 1 | Sequential | ~3 | 0 | ~5 |
| **Total** | **15** | — | **~188** | **6** | **~21** |

Note: test count is higher than the original plan's ~145 because parallelisation requires each agent to be self-verifying, and some integration tests are added at wave boundaries.

### Speedup Analysis

| Approach | Sequential steps | Notes |
|----------|-----------------|-------|
| Original plan | 9 | P1 → P2 → P3 → P4 → P5 → P6 → P7 → P8 → P9 |
| Parallel plan | 5 | W1 (max of 6) → W2 → W3 (max of 4) → W4 (max of 3) → W5 |

The effective speedup depends on the wall-clock time of the longest agent in each parallel wave. The theoretical maximum speedup is ~1.8x (9/5), but in practice it will be better because the parallel waves complete in the time of their slowest agent, not the sum.

---

## Agent Prompt Templates

Each agent receives a prompt that includes:
1. The full spec from the parent plan (relevant phase sections)
2. Its file ownership list (what it can create/modify)
3. Its exclusion list (what it must NOT touch)
4. The verification command to run after completion
5. The TDD cycle reminder (RED → GREEN → REFACTOR → VERIFY)
6. The project conventions (British English, no emojis, Pydantic models, etc.)
