# Agent-Friendly CLI: Implementation Plan for pxcli v0.7.0

**Created:** 2026-05-09
**Last updated:** 2026-05-09
**Status:** APPROVED -- READY FOR IMPLEMENTATION
**Target version:** 0.7.0

---

## Resolved Decisions

| Question | Decision |
|---|---|
| Version bump | 0.7.0 (pre-1.0 breaking changes are expected) |
| Command restructuring | Yes -- clean rename, no aliases, old names removed entirely |
| `--json` scope | Per-command (not global) |
| `--json --stream` behaviour | NDJSON streaming: one JSON line per event, terminal line is the full envelope |
| SKILL.md backward compatibility | Not a concern -- just improve it |
| JSON migration strategy | Clean break -- `--format json` produces the new envelope in 0.7.0, no compatibility shim |
| Command migration strategy | Clean rename in 0.7.0. Old names removed entirely. No aliases, no deprecation warnings. |
| Development methodology | TDD -- tests written before implementation in every phase (red-green-refactor) |
| Coverage threshold | 85% (pyproject.toml), 75% (CI) |

---

## Breaking Changes

### BC-1: JSON output shape (Phase 2) -- SEVERITY: HIGH

The entire JSON structure changes. Every consumer that parses `--format json` output breaks.

**Before (v0.6.x):**
```json
{
  "format_version": "1.0",
  "answer": "Python is a programming language...",
  "references": [
    { "index": 1, "title": "...", "url": "...", "snippet": "..." }
  ]
}
```

**After (v0.7.0):**
```json
{
  "ok": true,
  "command": "pxcli query --json \"What is Python?\"",
  "result": {
    "answer": "Python is a programming language...",
    "references": [
      { "index": 1, "title": "...", "url": "...", "snippet": null }
    ]
  },
  "meta": { "duration_ms": 1423, "version": "0.7.0", "trace_id": "..." },
  "next_actions": [...]
}
```

**What breaks:**

| Consumer pattern | Status |
|---|---|
| `jq -r '.answer'` | BREAKS -- now `.result.answer` |
| `jq -r '.references[]'` | BREAKS -- now `.result.references[]` |
| `jq '.references \| length'` | BREAKS -- now `.result.references` |
| `data["answer"]` (Python subprocess) | BREAKS -- KeyError |
| `data["format_version"]` | BREAKS -- field removed |
| README shell function `px()` | BREAKS -- parses `.answer` |
| README shell function `pxc()` | BREAKS -- parses `.answer` |
| README Python subprocess example | BREAKS -- parses `data["answer"]` |
| SKILL.md agent parsing patterns | BREAKS -- all `jq` and Python examples |

**Migration for consumers:** Change `.answer` to `.result.answer`, `.references` to `.result.references`. Check `.ok` field for success/failure.

**Decision:** Clean break. `--format json` and `--json` both produce the new envelope from 0.7.0. No compatibility shim.

---

### BC-2: Exit codes change from uniform 1 to differentiated 1-7 (Phase 2) -- SEVERITY: LOW

**Before:** All errors exit with code 1.
**After:** Errors exit with codes 1-7 depending on type.

| Consumer pattern | Status |
|---|---|
| `pxcli ... \|\| echo "failed"` | SAFE -- any non-zero still triggers |
| `if ! pxcli ...; then ...` | SAFE -- any non-zero |
| `if [ $? -ne 0 ]; then ...` | SAFE -- any non-zero |
| `if [ $? -eq 1 ]; then ...` | BREAKS -- misses auth (4), transient (6), validation (7) |

**Likelihood of impact:** Very low. Checking `$? -eq 1` specifically is unusual.

---

### BC-3: Command names removed (Phase 1) -- SEVERITY: HIGH

Old command names are removed entirely in 0.7.0. No aliases, no deprecation period.

| Old name | New name |
|---|---|
| `pxcli auth` | `pxcli auth login` |
| `pxcli logout` | `pxcli auth logout` |
| `pxcli status` | `pxcli auth status` |
| `pxcli set-config` | `pxcli config set` |
| `pxcli show-config` | `pxcli config show` |
| `pxcli configure` | `pxcli style set` |
| `pxcli view-style` | `pxcli style show` |
| `pxcli clear-style` | `pxcli style clear` |
| `pxcli export-threads` | `pxcli threads export` |
| `pxcli show-skill` | `pxcli skill show` |

**What breaks:** Every script, cron job, shell alias, and agent skill definition that uses the old command names. The `--help` output at root level shows new group structure instead of old flat list.

---

### BC-4: Default output format changes when stdout is not a TTY (Phase 4) -- SEVERITY: LOW

**Before:** Default format is always `rich` regardless of TTY.
**After:** Default format is `plain` when stdout is not a TTY.

| Consumer pattern | Status |
|---|---|
| `pxcli query "..." > file.txt` | CHANGES -- gets plain text instead of ANSI-coded text (improvement) |
| `pxcli query "..." \| grep ...` | CHANGES -- gets clean text instead of ANSI-coded text (improvement) |
| `pxcli query --format rich "..." > file.txt` | SAFE -- explicit format honoured |

**Likelihood of impact:** Net improvement. No sane consumer depends on ANSI escape codes in redirected output.

---

### BC-5: `--help` text changes (Phases 5, 1) -- SEVERITY: NEGLIGIBLE

Help text for every command will change: new sections (EXIT CODES, SEE ALSO, ENVIRONMENT VARIABLES), better example formatting, new command names in cross-references.

**What breaks:** Only scripts or tests that do exact string comparison of `--help` output. No external consumer should depend on help text shape.

---

### BC-6: SKILL.md content changes (Phase 5) -- SEVERITY: MEDIUM

The entire skill definition will be rewritten with new command names, new JSON shapes, new parsing patterns. Any agent that previously cached the skill output will have stale information.

**Decision:** Accepted. Just improve it.

---

### BC-7: `query` argument becomes optional (Phase 3) -- SEVERITY: NEGLIGIBLE

**Before:** `QUERY` is required. Omitting it produces a Click usage error (exit 2).
**After:** `QUERY` is optional. Omitting it reads from stdin (if not a TTY) or shows a usage hint (exit 2).

Existing invocations with a positional argument are completely unaffected.

---

### Breaking changes NOT introduced

The following are explicitly **not** breaking:

- Adding new flags (`--json`, `--quiet`, `--no-color`, `--timeout`) -- additive
- Adding short forms for existing flags (`-s`, `-S`, `-o`, `-p`) -- additive
- Adding new commands (`completion`, `schema`) -- additive
- Adding new fields to the JSON envelope in future minor versions -- additive per contract
- `XDG_CONFIG_HOME` support -- only changes behaviour when the env var is set
- `NO_COLOR` support -- only changes behaviour when the env var is set

---

## TDD Methodology

Every phase follows this cycle:

```
1. SPECIFY  -- define the contract (Pydantic models, expected shapes, behaviours)
2. RED      -- write tests that assert the contract; all tests fail
3. GREEN    -- write minimum code to make tests pass
4. REFACTOR -- improve structure without changing behaviour; re-run tests
5. VERIFY   -- full test suite passes, coverage threshold met
```

Test files are created **before** source files in each phase.

---

## Phase 1: Command Grammar Restructuring (TDD)

### 1.1 Specify the new command tree

```
pxcli query "..."
pxcli auth login [--port PORT]
pxcli auth logout
pxcli auth status [--verify]
pxcli config set KEY VALUE
pxcli config show
pxcli style set STYLE
pxcli style show
pxcli style clear
pxcli threads export [--from-date] [--to-date] [--output] [--force-refresh] [--clear-cache]
pxcli doctor security
pxcli skill show
pxcli completion {bash|zsh|fish}     # placeholder, implemented in Phase 5
pxcli schema                         # placeholder, implemented in Phase 5
```

### 1.2 RED -- write tests first

Create `tests/test_command_tree.py`:

1.2.1 Test every new group is invocable: `pxcli auth --help`, `pxcli config --help`, `pxcli style --help`, `pxcli threads --help`, `pxcli skill --help` -- all exit 0.

1.2.2 Test every subcommand is invocable: `pxcli auth login --help`, `pxcli auth logout --help`, `pxcli auth status --help`, `pxcli config set --help`, `pxcli config show --help`, `pxcli style set --help`, `pxcli style show --help`, `pxcli style clear --help`, `pxcli threads export --help`, `pxcli skill show --help` -- all exit 0.

1.2.3 Test old command names are gone: `pxcli logout`, `pxcli status`, `pxcli set-config`, `pxcli show-config`, `pxcli configure`, `pxcli view-style`, `pxcli clear-style`, `pxcli export-threads`, `pxcli show-skill` -- all exit 2 (Click "no such command").

1.2.4 Test `query` remains at root level: `pxcli query --help` exits 0.

1.2.5 Test `doctor security` still works: `pxcli doctor security --help` exits 0.

1.2.6 Test root `--help` lists groups: output contains `auth`, `config`, `style`, `threads`, `doctor`, `skill`, `query`.

Create `tests/test_auth_runner.py` (filling existing gap):

1.2.7 Test `auth login` invokes `run_auth_command` with correct port.

1.2.8 Test `auth logout` invokes `run_logout_command`.

1.2.9 Test `auth status` invokes `run_status_command` with `--verify` flag.

Create `tests/test_auth_models.py` (filling existing gap):

1.2.10 Test auth data models serialise/deserialise correctly.

### 1.3 GREEN -- implement minimum code

1.3.1 Create new Click groups: `auth_group`, `config_group`, `style_group`, `threads_group`, `skill_group`.

1.3.2 Register subcommands under each group. Runner functions remain unchanged.

1.3.3 Remove old command registrations from `register_commands()`.

1.3.4 Update `cli.py` module-level exports to reference new command paths.

### 1.4 REFACTOR

1.4.1 Clean up `commands.py` -- remove dead code from old flat registrations.

1.4.2 Ensure all `--help` text and examples reference new command names.

### 1.5 VERIFY

1.5.1 All new tests pass.

1.5.2 Run full existing test suite -- update any tests that reference old command names.

---

## Phase 2: Output Contract (TDD)

### 2.1 Specify the envelope schema

2.1.1 Success envelope shape:
```json
{
  "ok": true,
  "command": "pxcli query --json \"What is Python?\"",
  "result": { ... },
  "meta": {
    "duration_ms": 1423,
    "version": "0.7.0",
    "trace_id": "a1b2c3d4-...",
    "truncated": false
  },
  "next_actions": [
    {
      "command": "pxcli query --json --strip-references \"What is Python?\"",
      "description": "Re-run without inline citations"
    }
  ]
}
```

2.1.2 Error envelope shape:
```json
{
  "ok": false,
  "command": "pxcli query --json \"...\"",
  "error": {
    "code": "authentication_required",
    "message": "File attachments require authentication.",
    "input": {}
  },
  "fix": "Run `pxcli auth login` to authenticate.",
  "next_actions": [
    { "command": "pxcli auth login", "description": "Authenticate with Perplexity.ai" }
  ]
}
```

2.1.3 Exit code enum:

| Constant | Value | Meaning |
|---|---|---|
| `SUCCESS` | 0 | Operation completed successfully |
| `GENERAL_FAILURE` | 1 | Unclassified error |
| `USAGE_ERROR` | 2 | Bad arguments, invalid flags, missing required input |
| `NOT_FOUND` | 3 | Requested resource not found |
| `AUTH_REQUIRED` | 4 | Authentication missing or denied (HTTP 401, 403) |
| `CONFLICT` | 5 | Resource already exists |
| `TRANSIENT` | 6 | Retryable error (timeout, rate limit, HTTP 5xx) |
| `VALIDATION` | 7 | Input or upstream validation failure |
| `INTERRUPTED` | 130 | User interrupted (SIGINT) |

2.1.4 Error code string enum:
- `authentication_required`
- `permission_denied`
- `rate_limited`
- `network_error`
- `timeout`
- `upstream_schema_error`
- `configuration_error`
- `attachment_error`
- `validation_error`
- `not_found`
- `internal_error`

2.1.5 Per-command result payload shapes:

| Command (new name) | Result payload shape |
|---|---|
| `query` | `{answer: str, references: [{index, title, url, snippet}]}` |
| `auth status` | `{authenticated: bool, token_path: str, token_age_days: int, cookies_stored: int, verified: bool\|null}` |
| `config show` | `{config_path: str, save_cookies: bool, debug_mode: bool, env_overrides: [str]}` |
| `threads export` | `{threads: [{title, created_at, url}], total: int, output_path: str, date_range: {from, to}}` |
| `doctor security` | `{storage_backend: str, token_path: str, token_permissions: str, cache_path: str, cache_permissions: str, cookies_enabled: bool}` |
| `auth login` | `{token_path: str, cookies_stored: int}` |
| `auth logout` | `{credentials_existed: bool}` |
| `style set` | `{style: str}` |
| `style show` | `{style: str\|null}` |
| `style clear` | `{had_style: bool}` |
| `config set` | `{key: str, value: bool}` |

### 2.2 RED -- write tests first

Create `tests/test_envelope.py`:

2.2.1 Test `Envelope` model: required fields (`ok`, `command`, `result`), optional fields (`meta`, `next_actions`), serialisation round-trip.

2.2.2 Test `ErrorEnvelope` model: required fields (`ok=False`, `command`, `error`), optional fields (`fix`, `next_actions`), `error` must have `code` and `message`.

2.2.3 Test `NextAction` model: `command` and `description` required, `params` optional.

2.2.4 Test `Meta` model: `duration_ms` (int), `version` (str), `trace_id` (str), `truncated` (optional bool).

2.2.5 Test `success_envelope()` builder: produces valid `Envelope`, `ok` is `True`.

2.2.6 Test `error_envelope()` builder: produces valid `ErrorEnvelope`, `ok` is `False`, error code is from the enum.

2.2.7 Test every error code string is a valid enum member.

2.2.8 Golden snapshot test: success envelope shape (structure with type placeholders).

2.2.9 Golden snapshot test: error envelope shape.

Create `tests/test_exit_codes.py`:

2.2.10 Test every constant has the expected integer value.

2.2.11 Test exception-to-exit-code mapping: `AuthenticationError` -> 4, `RateLimitError` -> 6, `PerplexityHTTPStatusError` (401) -> 4, `PerplexityHTTPStatusError` (429) -> 6, `PerplexityHTTPStatusError` (500) -> 6, `PerplexityRequestError` -> 6, `ConfigurationError` -> 7, `UpstreamSchemaError` -> 7, `AttachmentError` -> 7, `ValueError` -> 1, `Exception` -> 1, `KeyboardInterrupt` -> 130.

2.2.12 Test `format_exit_codes_help()` produces the expected text block.

Create `tests/test_error_handler.py`:

2.2.13 Test `handle_error()` in JSON mode: writes error envelope to stdout, nothing to stderr (except logs), exits with correct code.

2.2.14 Test `handle_error()` in human mode: writes human-readable text to stderr, nothing to stdout, exits with correct code.

2.2.15 Test every exception type through `handle_error()` in both modes.

Update `tests/test_formatters.py`:

2.2.16 Test `JSONFormatter.format_complete()` returns valid envelope (not old flat shape).

2.2.17 Test `--format json` and `--json` produce identical output.

2.2.18 Test `--json` on `query` with mocked API: success envelope with `.result.answer`.

2.2.19 Golden snapshot: query success envelope.

2.2.20 Golden snapshot: query error envelope (auth required).

Create `tests/test_json_output.py` (per-command JSON tests):

2.2.21 Test `--json` on `auth status`: valid envelope with `result.authenticated`, `result.token_path`, etc.

2.2.22 Test `--json` on `config show`: valid envelope with `result.save_cookies`, `result.debug_mode`, etc.

2.2.23 Test `--json` on `threads export`: valid envelope with `result.threads`, `result.total`, etc.

2.2.24 Test `--json` on `doctor security`: valid envelope with `result.storage_backend`, etc.

2.2.25 Test `--json` on `auth login`: valid envelope with `result.token_path`, etc.

2.2.26 Test `--json` on `auth logout`: valid envelope with `result.credentials_existed`.

2.2.27 Test `--json` on `style set`: valid envelope with `result.style`.

2.2.28 Test `--json` on `style show`: valid envelope with `result.style` (null when none set).

2.2.29 Test `--json` on `style clear`: valid envelope with `result.had_style`.

2.2.30 Test `--json` on `config set`: valid envelope with `result.key`, `result.value`.

2.2.31 Test `--json` error paths: each command's common failure mode produces error envelope.

Create `tests/test_status_runner.py` (filling existing gap):

2.2.32 Test `run_status_command` human output.

2.2.33 Test `run_status_command` JSON output.

Create `tests/test_export_runner.py` (filling existing gap):

2.2.34 Test `run_export_threads_command` human output.

2.2.35 Test `run_export_threads_command` JSON output.

Create `tests/test_http_headers.py` (filling existing gap):

2.2.36 Test HTTP header construction functions.

### 2.3 GREEN -- implement minimum code

2.3.1 Create `src/perplexity_cli/envelope.py` with Pydantic models and builders.

2.3.2 Create `src/perplexity_cli/exit_codes.py` with constants and mappings.

2.3.3 Create `src/perplexity_cli/error_handler.py` with `handle_error()`.

2.3.4 Add `--json` flag to every command in `commands.py`.

2.3.5 Refactor `JSONFormatter.format_complete()` to produce envelope.

2.3.6 Refactor every runner to use `handle_error()` and produce envelopes when `--json` is active.

2.3.7 Refactor `http_errors.py` to return structured data.

### 2.4 REFACTOR

2.4.1 Extract shared `--json` decorator/callback.

2.4.2 Consolidate duplicate error handling patterns across runners.

2.4.3 Remove old `format_version: "1.0"` code paths.

### 2.5 VERIFY

2.5.1 All new tests pass.

2.5.2 Full test suite passes (update any tests broken by envelope change).

---

## Phase 3: Input Design (TDD)

### 3.1 RED -- write tests first

Create `tests/test_stdin.py`:

3.1.1 Test `pxcli query -` with piped stdin reads from stdin.

3.1.2 Test `echo "question" | pxcli query` (no arg, stdin not TTY) reads from stdin.

3.1.3 Test `pxcli query` with no arg, stdin is TTY: exits 2 with usage hint.

3.1.4 Test empty stdin: exits 2.

3.1.5 Test `pxcli query "text"` still works (positional arg, unchanged).

Create `tests/test_standard_flags.py`:

3.1.6 Test `--quiet` suppresses all stderr output.

3.1.7 Test `--quiet` preserves stdout output.

3.1.8 Test `--no-color` produces plain text (no ANSI codes).

3.1.9 Test `--timeout 10` passes timeout value through to API client.

3.1.10 Test `--timeout abc` (non-integer) exits 2.

3.1.11 Test `-s` is equivalent to `--stream`.

3.1.12 Test `-S` is equivalent to `--strip-references`.

3.1.13 Test `-o` is equivalent to `--output` (on `threads export`).

3.1.14 Test `-p` is equivalent to `--port` (on `auth login`).

Create `tests/test_xdg.py`:

3.1.15 Test `XDG_CONFIG_HOME=/tmp/test` changes config directory.

3.1.16 Test unset `XDG_CONFIG_HOME` falls back to `~/.config`.

Create `tests/test_file_permissions.py` (filling existing gap):

3.1.17 Test file permission verification functions.

Create `tests/test_config_models.py` (filling existing gap):

3.1.18 Test `URLConfig`, `FeatureConfig`, `RateLimitConfig` Pydantic validation.

### 3.2 GREEN -- implement

3.2.1 Make `query_text` an optional Click argument with stdin fallback.

3.2.2 Add `--quiet`/`-q`, `--no-color` to `main` group.

3.2.3 Add `--timeout`/`-t` to `query` command.

3.2.4 Add short forms: `-s`, `-S`, `-o`, `-p`.

3.2.5 Update `get_config_dir()` to check `XDG_CONFIG_HOME`.

### 3.3 REFACTOR

3.3.1 Extract stdin reading logic into a utility function.

### 3.4 VERIFY

3.4.1 All new and existing tests pass.

---

## Phase 4: TTY / Non-Interactive Intelligence (TDD)

### 4.1 RED -- write tests first

Create `tests/test_tty_detection.py`:

4.1.1 Test non-TTY stdout with no explicit format: output is `plain` (no ANSI).

4.1.2 Test non-TTY stdout with `--format rich`: honoured, produces rich output.

4.1.3 Test non-TTY stdout with `--json`: produces JSON.

4.1.4 Test TTY stdout with no explicit format: output is `rich`.

4.1.5 Test `NO_COLOR=1` env var: disables colour.

4.1.6 Test `NO_COLOR` with any value (empty string): disables colour.

4.1.7 Test `--no-color` flag + `NO_COLOR` env: both disable colour (same effect).

4.1.8 Test precedence: `--no-color` flag > `NO_COLOR` env > TTY detection.

### 4.2 GREEN -- implement

4.2.1 Check `sys.stdout.isatty()` in format resolution; default to `plain` when not TTY.

4.2.2 Check `os.environ.get("NO_COLOR")` in colour decision.

### 4.3 VERIFY

4.3.1 All tests pass.

---

## Phase 5: Discoverability (TDD)

### 5.1 RED -- write tests first

Create `tests/test_help_formatting.py`:

5.1.1 Test root `--help` contains EXIT CODES section.

5.1.2 Test `query --help` contains EXIT CODES section.

5.1.3 Test `auth login --help` contains SEE ALSO referencing `auth status`, `auth logout`.

5.1.4 Test `query --help` examples are properly indented (not word-wrapped into prose).

5.1.5 Test `query --help` contains ENVIRONMENT VARIABLES section.

5.1.6 Snapshot test: `--help` output for every command.

Create `tests/test_completion.py`:

5.1.7 Test `pxcli completion bash` exits 0, produces non-empty output.

5.1.8 Test `pxcli completion zsh` exits 0, produces non-empty output.

5.1.9 Test `pxcli completion fish` exits 0, produces non-empty output.

Create `tests/test_schema.py`:

5.1.10 Test `pxcli schema` exits 0, produces valid JSON.

5.1.11 Test schema JSON contains entry for every command.

5.1.12 Test each command entry has `input` and `output` keys.

5.1.13 Test schema output validates against JSON Schema meta-schema.

Create `tests/test_help_json.py`:

5.1.14 Test `pxcli --help --json` produces valid JSON.

5.1.15 Test JSON help contains all commands with their options and arguments.

5.1.16 Test JSON help contains version field.

Update `tests/test_skill_runner.py`:

5.1.17 Test SKILL.md content references new command names.

5.1.18 Test SKILL.md content references envelope format.

5.1.19 Test SKILL.md content references exit codes.

### 5.2 GREEN -- implement

5.2.1 Custom Click help formatter with `\b` markers, EXIT CODES, SEE ALSO, ENV VARS.

5.2.2 Create `completion` command group with `bash`/`zsh`/`fish` subcommands.

5.2.3 Create `schema` command using Pydantic `.model_json_schema()`.

5.2.4 Create `help_json.py` for machine-readable help.

5.2.5 Rewrite `resources/skill.md` for v0.7.0.

### 5.3 REFACTOR

5.3.1 Extract help section generation into reusable functions.

### 5.4 VERIFY

5.4.1 All tests pass, including snapshots.

---

## Phase 6: Structured Streaming / NDJSON (TDD)

### 6.1 RED -- write tests first

Create `tests/test_ndjson.py`:

6.1.1 Test `--json --stream`: each stdout line is valid JSON.

6.1.2 Test first line has `"type": "start"` and `command` field.

6.1.3 Test chunk lines have `"type": "chunk"` and `text` field.

6.1.4 Test last line has `"type": "result"` and is a complete envelope.

6.1.5 Test all lines have `ts` field in ISO 8601 format.

6.1.6 Test event order: `start` first, `result` last, `chunk`/`progress` in between.

6.1.7 Test `--json` without `--stream`: single JSON envelope (no NDJSON lines).

6.1.8 Test `--stream` without `--json`: raw text streaming (current behaviour preserved).

6.1.9 Test neither flag: buffered rich text (current behaviour preserved).

6.1.10 Test error mid-stream: error envelope as final `result` line, `ok: false`.

Create `tests/test_async_bridge.py` (filling existing gap):

6.1.11 Test `run_async()` helper executes and returns result.

### 6.2 GREEN -- implement

6.2.1 Create `src/perplexity_cli/ndjson.py` with NDJSON writer and event models.

6.2.2 Refactor `streaming.py` to detect JSON mode and delegate to NDJSON writer.

### 6.3 REFACTOR

6.3.1 Extract event construction into typed factory functions.

### 6.4 VERIFY

6.4.1 All tests pass.

---

## Phase 7: Observability (TDD)

### 7.1 RED -- write tests first

Update `tests/test_envelope.py`:

7.1.1 Test every `--json` envelope has `meta.trace_id` field.

7.1.2 Test `trace_id` matches UUID4 format.

7.1.3 Test two invocations produce different trace IDs.

7.1.4 Test every envelope has `meta.duration_ms` as a positive integer.

Create `tests/test_session_log.py`:

7.1.5 Test session log file created at `$XDG_DATA_HOME/pxcli/sessions/<id>.ndjson` when `PXCLI_SESSION_LOG=true`.

7.1.6 Test session log file not created when env var is unset and not verbose/debug.

7.1.7 Test session log contains valid NDJSON.

7.1.8 Test session log records both `invocation` and `response` events.

Create `tests/test_structured_logging.py`:

7.1.9 Test stderr output is structured JSON (one object per line) when `--json --verbose`.

7.1.10 Test stderr output is text (current format) when `--verbose` without `--json`.

7.1.11 Test structured log lines contain `ts`, `level`, `message`, `trace_id`.

Create `tests/test_session_factory.py` (filling existing gap):

7.1.12 Test session factory creates sessions with expected configuration.

### 7.2 GREEN -- implement

7.2.1 Generate UUID4 at invocation start, thread through context.

7.2.2 Record `time.monotonic()` at start, compute `duration_ms` at envelope construction.

7.2.3 Create `src/perplexity_cli/session_log.py` for NDJSON session logging.

7.2.4 Add structured JSON log formatter activated by JSON mode.

### 7.3 REFACTOR

7.3.1 Consolidate trace ID and timing into a shared invocation context object.

### 7.4 VERIFY

7.4.1 All tests pass.

---

## Phase 8: Ecosystem (TDD)

### 8.1 RED -- write tests first

Create `tests/test_api_version.py`:

8.1.1 Test `--api-version v1` accepted on every command with `--json`.

8.1.2 Test `--api-version v99` exits 2 with error envelope.

8.1.3 Test `--api-version v1` produces identical output to no `--api-version` (only v1 exists).

Create `tests/test_envelope_snapshots.py`:

8.1.4 Golden snapshot test for every command's success envelope shape.

8.1.5 Test adding a new field to result does not break snapshots (additive).

8.1.6 Test removing a field from result does break snapshot (regression caught).

### 8.2 GREEN -- implement

8.2.1 Add `--api-version` flag to commands with `--json`.

8.2.2 Document the output contract (section in README or standalone file).

### 8.3 VERIFY

8.3.1 All tests pass.

---

## Phase 9: Release

### 9.1 Version bump

9.1.1 Update version in `pyproject.toml` from `0.6.6` to `0.7.0`.

9.1.2 Update any hardcoded version references.

9.1.3 Verify `pxcli --version` returns `0.7.0`.

### 9.2 Update documentation

9.2.1 Update README.md: all command examples, JSON examples, shell functions, Python examples, new flags, exit codes, NDJSON streaming.

9.2.2 Update CONTRIBUTING.md if it references command names or test patterns.

### 9.3 Coverage and quality gates

9.3.1 Raise `pyproject.toml` coverage threshold from 75% to 85%.

9.3.2 Raise CI workflow coverage threshold from 40% to 75%.

9.3.3 Run full test suite: `uv run pytest --cov=perplexity_cli --cov-report=term-missing --cov-fail-under=85`

9.3.4 Run linting: `uv run ruff check && uv run ruff format --check`

9.3.5 Run type checking: `uv run ty check src`

### 9.4 Build and smoke test

9.4.1 Build wheel: `uv build`

9.4.2 Verify wheel contents include `urls.json`, `skill.md`, all source files.

9.4.3 Smoke test in isolated environment: `--version`, `--help`, `auth --help`, `schema`, `completion zsh`.

### 9.5 Tag and publish

9.5.1 Commit all changes.

9.5.2 Create git tag: `git tag v0.7.0`

9.5.3 Push tag: `git push origin v0.7.0`

9.5.4 Existing `publish-to-pypi.yml` workflow triggers on `v*` tags, validates version consistency, publishes via OIDC.

9.5.5 Verify PyPI publish succeeds.

9.5.6 Verify installation: `uv pip install pxcli==0.7.0` in a clean environment.

---

## Implementation Order

```
Phase 1: Command Restructuring    <- no dependencies, establishes final names
Phase 2: Output Contract          <- no dep on 1, but uses new names in envelopes
Phase 3: Input Design             <- independent
Phase 4: TTY / Non-Interactive    <- depends on 2 (--json) and 3 (--quiet, --no-color)
Phase 5: Discoverability          <- depends on 2 (envelope) and 1 (final names)
Phase 6: NDJSON Streaming         <- depends on 2 (envelope)
Phase 7: Observability            <- depends on 2 (envelope)
Phase 8: Ecosystem                <- depends on 2, 5, 1
Phase 9: Release                  <- depends on all above
```

**Execution order:** 1 -> 2 -> 3 -> 4 -> 5 -> 6 -> 7 -> 8 -> 9

---

## Test Count Summary

| Phase | New test files | New tests (approx) |
|---|---|---|
| 1. Command Restructuring | 3 | ~20 |
| 2. Output Contract | 5 | ~45 |
| 3. Input Design | 4 | ~20 |
| 4. TTY / Non-Interactive | 1 | ~8 |
| 5. Discoverability | 4 | ~19 |
| 6. NDJSON Streaming | 2 | ~12 |
| 7. Observability | 3 | ~12 |
| 8. Ecosystem | 2 | ~6 |
| 9. Release | 0 | ~3 (smoke) |
| **Total** | **24** | **~145** |

Combined with existing 663 tests, the target is roughly **808 tests** at release.

---

## Files Impacted (Summary)

**Modified:**
- `src/perplexity_cli/cli.py` -- global flags, group restructuring
- `src/perplexity_cli/commands.py` -- per-command `--json`, new groups, old commands removed
- `src/perplexity_cli/query_runner.py` -- envelope construction, stdin, timeout
- `src/perplexity_cli/formatting/json.py` -- envelope format
- `src/perplexity_cli/formatting/base.py` -- TTY detection, NO_COLOR
- `src/perplexity_cli/api/streaming.py` -- NDJSON delegation
- `src/perplexity_cli/utils/config.py` -- XDG_CONFIG_HOME
- `src/perplexity_cli/utils/http_errors.py` -- return structured data
- `src/perplexity_cli/utils/logging.py` -- structured JSON format
- `src/perplexity_cli/runners/*.py` -- all runners (envelope, error handling, --json)
- `resources/skill.md` -- updated for v0.7.0
- `pyproject.toml` -- version, coverage thresholds
- `.github/workflows/ci.yml` -- coverage threshold
- `README.md` -- all examples, new features
- `CONTRIBUTING.md` -- if it references command names

**New:**
- `src/perplexity_cli/envelope.py` -- envelope models and builders
- `src/perplexity_cli/exit_codes.py` -- exit code constants
- `src/perplexity_cli/error_handler.py` -- centralised error handling
- `src/perplexity_cli/ndjson.py` -- NDJSON writer
- `src/perplexity_cli/help_json.py` -- machine-readable help
- `src/perplexity_cli/session_log.py` -- session NDJSON logger

**New test files (24):**
- `tests/test_command_tree.py`
- `tests/test_auth_runner.py`
- `tests/test_auth_models.py`
- `tests/test_envelope.py`
- `tests/test_exit_codes.py`
- `tests/test_error_handler.py`
- `tests/test_json_output.py`
- `tests/test_status_runner.py`
- `tests/test_export_runner.py`
- `tests/test_http_headers.py`
- `tests/test_stdin.py`
- `tests/test_standard_flags.py`
- `tests/test_xdg.py`
- `tests/test_file_permissions.py`
- `tests/test_config_models.py`
- `tests/test_tty_detection.py`
- `tests/test_help_formatting.py`
- `tests/test_completion.py`
- `tests/test_schema.py`
- `tests/test_help_json.py`
- `tests/test_ndjson.py`
- `tests/test_async_bridge.py`
- `tests/test_session_log.py`
- `tests/test_structured_logging.py`
- `tests/test_session_factory.py`
- `tests/test_api_version.py`
- `tests/test_envelope_snapshots.py`
