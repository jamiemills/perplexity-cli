# Fix Flaky gitleaks + semgrep Tests Under `-n auto` CSM Plan

## How To Execute
- Start work only through a separate, explicit `csm-build` invocation naming this plan; the planning session must not begin execution.
- Commit policy and live state are maintained in Control by csm-build.
- Risk summary: 3 tasks — all low risk (test-only, no production code, no dependencies, no Makefile/CI changes). No task requires independent review beyond the standard self-review; none touch security, data, or destructive paths.

## Control
- Plan ID: gitleaks-semgrep-flake-fixes
- Status: ready
- Current CSM state: NOT_STARTED
- Cycle: 0
- Commits: allowed
- Last checkpoint: 2026-08-04 — plan drafted after confirmed root-cause research (shared semgrep scan-dir race; hidden git stderr in gitleaks provisioning)
- Next transition: On a future explicit csm-build invocation, NOT_STARTED -> RECOVER
- Active tasks: none
- Blockers: none

## Goal
Make `make test` (pytest `-n auto`, 4 xdist workers) reliable by fixing two pre-existing flaky test failures:

1. **Semgrep-policy flake** (reproducible): `tests/test_semgrep_policy.py` failures — `test_clean_target_exits_zero` fails and `TestFixtureBehaviour` tests error under `-n 4`, because a single fixed `build/semgrep-policy-scan` directory is wiped/recreated by every xdist worker's session-scoped `scan_dir` fixture (a cross-worker race). Fix: give each worker its own unique scan directory.
2. **Gitleaks flake** (intermittent, full-suite-only, local-only): `TestOidHandling::test_new_ref_remote_zeros_triggers_new_branch_path` git-provisioning steps fail transiently under full-suite load, and `subprocess.run(check=True, capture_output=True)` swallows git's stderr so the failure is opaque. Fix: a bounded 2-attempt retry helper that also surfaces stdout/stderr in the failure message.

Deliverables:
1. `tests/test_semgrep_policy.py`: `scan_dir` fixture uses a per-worker unique directory (`tmp_path_factory.mktemp`) instead of the shared fixed `SCAN_ROOT`.
2. `tests/test_gitleaks.py`: new `_run_provisioning` helper (2-attempt retry + stderr surfacing) and refactor of the flaky test's git provisioning to use it.
3. New unit tests for `_run_provisioning` (retry-once behaviour; stderr in failure message).

Constraints:
- No new dependencies: `pytest-rerunfailures` is NOT installed; the retry is hand-rolled and bounded (2 attempts, 0.5s delay).
- No Makefile changes: `xdist_group` is a no-op under the `load`/`loadfile` distributions that `make test` and `make test-coverage` use; not relied upon.
- No production-code changes; only the two test files.
- Keep `TestOidHandling._skip_on_ci` behaviour unchanged (the gitleaks ref tests remain CI-skipped).
- Keep the semgrep test semantics identical per worker (same dir shared by that worker's positive/negative scans), only the path becomes unique.

Exclusions:
- Do NOT touch the attachments-integration order-dependence failures or any other pre-existing suite issue (out of scope; documented only).
- Do NOT change `make test` parallelism, `.github/workflows`, `pyproject.toml` deps, or `scripts/semgrep_policy.py`.
- Do NOT mask failures: the retry is bounded and surfaces the underlying stderr; no unconditional skip / catch-and-ignore.

## Acceptance Criteria
1. `uv run pytest tests/test_semgrep_policy.py -n 4 -q` passes on 5 consecutive runs (this reproduced a failure ~100% before the fix; must now be stable).
2. `uv run pytest tests/test_gitleaks.py -n 4 -q` passes on 5 consecutive runs.
3. New `_run_provisioning` unit tests pass: (a) a command failing once then succeeding is retried and returns success; (b) a command failing twice raises `AssertionError` whose message contains both captured stdout and stderr.
4. `rg "SCAN_ROOT|semgrep-policy-scan" tests/` shows the shared fixed path removed from `test_semgrep_policy.py` (scan dir is now `tmp_path_factory.mktemp`).
5. `uv run pytest tests/test_gitleaks.py tests/test_semgrep_policy.py -p no:xdist -q` passes.
6. A full `make test` run completes with the gitleaks and semgrep test files green; any remaining failures are unrelated pre-existing ones (e.g. attachments integration), recorded with evidence.

## Current-State Evidence
- `Makefile:333-336` `test` target: `uv run pytest tests/ ... -n auto ...` with no `--dist` -> xdist default `load`, 4 workers on this machine (`nproc` = 4). `make test-coverage` uses `--dist loadfile` (Makefile:338-343). CI `test-compat` job runs `make test` (`-n auto`, default `load`) on py3.13/3.14, so the semgrep race is CI-reachable; the gitleaks ref tests are CI-skipped.
- `tests/test_semgrep_policy.py:39` `SCAN_ROOT = PROJECT_ROOT / "build" / "semgrep-policy-scan"`; `:170-176` session-scoped `scan_dir` fixture does `shutil.rmtree(SCAN_ROOT, ignore_errors=True)` then `SCAN_ROOT.mkdir(...)` (and rmtree on teardown); `:179-192` session fixtures `positive_scan`/`negative_scan` copy fixtures into `scan_dir` and run `_run_scan(scan_dir)`. Under `-n auto`, each worker builds its own session fixture over the SAME physical path: worker B's rmtree/mkdir can delete worker A's scan root mid-scan.
- Confirmed semgrep failure signature: `test_clean_target_exits_zero` (line 273) asserts `returncode == 0` but semgrep returned 2 with JSON `"paths":{"scanned":[]}` and empty stderr; probed semgrep 1.171.0 directly: exit 2 + empty stderr + `scanned:[]` is exactly `{"errors":[{"code":2,"message":"Invalid scanning root: <path>"}]}` — the scan directory was missing at scan start. Reproduced 4/4 parallel runs; the same files pass 72/72 with `-p no:xdist`.
- 4 concurrent `uvx --from semgrep==1.171.0 semgrep --version` all exit 0 (uvx/uv-cache contention is NOT the cause).
- `tests/test_gitleaks.py:230-259`: the flaky test provisions a repo via `subprocess.run(["bash", "tests/fixtures/gitleaks/clean-repo-setup.sh", repo], check=True, capture_output=True, text=True)` then `git clone --bare`, `git remote add`, `git add`, `git commit`, `git rev-parse` — all with `check=True` + `capture_output=True` (git stderr swallowed). Observed twice under full `make test -n auto`: `CalledProcessError` exit 128 (once) and exit 1 (once) from `clean-repo-setup.sh`. Passes in isolation and 8/8 under `-n 4` for the file alone.
- Root-cause probes that did NOT reproduce the gitleaks flake: 24 concurrent fixture runs (all exit 0), full-sequence 8-process concurrency (all exit 0), `ulimit -v` 64/128/256 MB (all exit 0), 4 concurrent semgrep storms + 30 fixture runs (all exit 0), disk/inode check (6.7 GB free, 35% inodes) — so the exact git error remains unknown; the fix is defensive (retry + surface stderr so a recurrence becomes diagnosable).
- `pytest-xdist` 3.8.0 installed; `pytest-rerunfailures` NOT installed; `rg xdist_group tests/ Makefile pyproject.toml` -> no usage. `@pytest.mark.xdist_group` is marker-registered but only effective under `--dist=loadgroup` (not used here).
- No other file references `SCAN_ROOT` or `build/semgrep-policy-scan` (verified: only `test_semgrep_policy.py`).
- `TestOidHandling._skip_on_ci` (test_gitleaks.py:204-209) skips the ref-test class when `CI` is set -> the gitleaks flake is local-only.

## Assumptions And Decisions
| ID | Statement | Type | Evidence or rationale | Status |
|----|-----------|------|-----------------------|--------|
| A1 | Semgrep flake root cause is the shared fixed `SCAN_ROOT` directory raced across xdist workers | Evidence | `scan_dir` fixture rmtree/mkdir over one path; reproduced 4/4 parallel, 72/72 serial; probed "Invalid scanning root" | Confirmed |
| A2 | Fix = per-worker unique scan dir via `tmp_path_factory.mktemp` | Decision | pytest tmp_path_factory is per-worker-unique under xdist; scheduler-agnostic; fixes CI compat too | Accepted |
| A3 | Gitleaks fix = bounded 2-attempt retry + stderr surfacing, no new dependency | Decision | pytest-rerunfailures absent; hand-rolled retry matches repo convention; surfaces hidden git error | Accepted |
| A4 | No Makefile/`--dist loadgroup` change | Decision | xdist_group is a no-op under `load`/`loadfile`; avoid global scheduling changes | Accepted |
| A5 | Scope limited to `test_gitleaks.py` + `test_semgrep_policy.py` | Decision | Observed flakes; sibling gitleaks files not observed flaky | Accepted |
| A6 | Keep per-worker scan semantics (positive then negative share one dir per worker) | Decision | Matches existing design; only the path isolation changes | Accepted |
| A7 | The exact gitleaks git error is not yet known; the retry is defensive and the surfaced stderr makes any recurrence diagnosable | Decision | Cannot reproduce outside the full suite despite extensive probes | Accepted |

## R&D Record
| ID | Question | Method/tool | Isolation and no-change evidence | Observation | Plan implication |
|----|----------|-------------|----------------------------------|-------------|------------------|
| R1 | Why do semgrep-policy tests fail under `-n 4` but pass serially? | Read test_semgrep_policy.py; ran `uv run pytest tests/test_semgrep_policy.py -n 4` (4/4 fail); probed semgrep 1.171.0 with missing/empty dirs; ran 4 concurrent `uvx semgrep --version` | No repo writes; probes in /tmp; uv cache read | Shared fixed `SCAN_ROOT` raced across worker session fixtures; semgrep exit 2 "Invalid scanning root", `paths.scanned:[]`; uvx cache not the cause | Isolate scan dir per worker (T002) |
| R2 | Where do the gitleaks git calls live and what hides the failure? | Read test_gitleaks.py; enumerated all subprocess call sites; probed 24-way + 8-way + memory-limited + semgrep-storm concurrency | All probes in /tmp; no repo writes | 6 git provisioning calls in TestOidHandling use `check=True`+`capture_output=True` (stderr swallowed); flake not reproducible outside the full suite; local-only (CI skip) | Add retry+stderr helper (T001) |
| R3 | What retry/serialisation primitives are available? | Checked installed plugins and xdist API | Read-only | pytest-rerunfailures absent; xdist 3.8.0 `xdist_group` marker registered but inert under `load`/`loadfile`; `tmp_path_factory.mktemp` is per-worker-unique | Hand-rolled retry; use tmp_path_factory for isolation |

## Discovered Requirements
- Retry must be bounded (2 attempts) and surface captured stdout+stderr in the failure message; never an unconditional skip. 0.5s sleep between attempts.
- The fixture-setup script (`clean-repo-setup.sh`, `set -euo pipefail`) can abort mid-way leaving a partial repo; the retry must wipe-and-recreate the target dir before every attempt (use `shutil.rmtree(..., ignore_errors=True)` + `mkdir`; `shutil` is already imported in test_gitleaks.py).
- `tests/test_gitleaks.py` needs `import time` and, under `TYPE_CHECKING`, `from collections.abc import Sequence`.
- `tmp_path_factory.mktemp("semgrep-policy-scan")` returns an already-created unique `Path`; no `mkdir` needed; teardown should still `shutil.rmtree(..., ignore_errors=True)`.
- Tests are not pyright-checked (only `scripts/` is); ruff applies with the `tests/**` per-file-ignores (complexity/args relaxed for tests, but keep the helper simple anyway).
- pytest's default `tmp_path_factory` root is cleaned by pytest's retention policy; no `.gitignore` impact (scan dirs move out of `build/`).
- No new entries needed in `quality/baselines/suppressions.json` (no new suppressions introduced).

## Design
**Semgrep flake (T002):** Replace the shared fixed scan root with a per-worker unique directory.

- `tests/test_semgrep_policy.py:39` — remove `SCAN_ROOT = PROJECT_ROOT / "build" / "semgrep-policy-scan"`.
- `:170-176` — change the `scan_dir` fixture to:
  ```python
  @pytest.fixture(scope="session")
  def scan_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
      """Create a unique per-worker scan directory and clean it up."""
      scan_path = tmp_path_factory.mktemp("semgrep-policy-scan")
      yield scan_path
      shutil.rmtree(scan_path, ignore_errors=True)
  ```
  Under xdist each worker's `tmp_path_factory` resolves to a distinct base root, so workers can no longer delete each other's scan target. `positive_scan`/`negative_scan` are unchanged and still share the one per-worker dir, preserving semantics.

**Gitleaks flake (T001):** Add a provisioning helper and route the flaky test through it.

- Add after `_assert_missing_mode_error` (test_gitleaks.py ~line 76):
  ```python
  def _run_provisioning(
      command: Sequence[str],
      *,
      cwd: Path | None = None,
      reset_dir: Path | None = None,
  ) -> subprocess.CompletedProcess[str]:
      """Run a git provisioning command, retrying once on transient failure.

      The single retry after a short sleep absorbs the intermittent non-zero
      exits seen when parallel xdist workers saturate the machine.  When
      *reset_dir* is set it is wiped and recreated before every attempt so a
      partially-created repository is never committed on top of.  Captured
      stdout and stderr are surfaced in the failure message rather than
      swallowed by ``check=True``.

      Raises:
          AssertionError: The command failed on every attempt.
      """
      last_error = ""
      for _attempt in range(2):
          if reset_dir is not None:
              shutil.rmtree(reset_dir, ignore_errors=True)
              reset_dir.mkdir()
          result = subprocess.run(
              [*command],
              capture_output=True,
              text=True,
              cwd=str(cwd) if cwd is not None else None,
          )
          if result.returncode == 0:
              return result
          last_error = f"stdout: {result.stdout}\nstderr: {result.stderr}"
          time.sleep(0.5)
      raise AssertionError(f"git provisioning failed:\n{last_error}")
  ```
- Refactor `test_new_ref_remote_zeros_triggers_new_branch_path` (test_gitleaks.py:230-259) so the six git-provisioning calls (setup script with `reset_dir=repo`, `git clone --bare`, `git remote add`, `git add`, `git commit`, `git rev-parse`) go through `_run_provisioning`. The setup-script call passes `reset_dir=repo`; the clone call must wipe any partial `origin.git` before each attempt (pass `reset_dir=remote`); `remote add`/`add`/`commit`/`rev-parse` run with `cwd=repo` and no reset.
- Add `import time` to the stdlib imports and `Sequence` to the `TYPE_CHECKING` block.

**Tests (T003):** Add two unit tests to `tests/test_gitleaks.py`:
- `test_run_provisioning_retries_on_transient_failure` — a command that exits 1 then 0 (e.g. `["bash", "-c", "test -e <flag> || exit 1; exit 0"]` style, or a small helper script under `tmp_path`) returns success and runs twice.
- `test_run_provisioning_surfaces_stderr` — a command that always exits non-zero (e.g. `["git", "config", "--get", "definitely.not.a.key"]`) raises `AssertionError` whose message contains both `stdout:` and `stderr:`.

## Execution Graph
Dependencies:
```
T001 (gitleaks helper)  [G1]  depends: none
T002 (semgrep isolation) [G1]  depends: none
T003 (tests + verify)    [G2]  depends: T001, T002
```
Critical path: (T001 or T002) -> T003.
Parallel groups: G1 = {T001, T002} — two disjoint files, fully independent. G2 = {T003}. No overlapping write ownership.

## Numbered Plan
1. [pending] Add `_run_provisioning` helper and refactor the flaky gitleaks test
   - Task ID: T001
   - Depends on: none
   - Parallel group: G1
   - Risk: low
   - Owned scope: `tests/test_gitleaks.py` only
   - Not in scope: sibling files (`test_gitleaks_prepush.py`, `test_gitleaks_integration.py`), `scripts/`, fixtures
   - Spike candidate: none (helper design verified in R&D R2/R3)
   - Actions: Add `import time` and `Sequence` (TYPE_CHECKING); add `_run_provisioning(command, *, cwd=None, reset_dir=None)` per Design; refactor `test_new_ref_remote_zeros_triggers_new_branch_path` (lines 230-259) to route the setup script (`reset_dir=repo`), `git clone --bare` (`reset_dir=remote`), `git remote add origin` (`cwd=repo`), `git add` (`cwd=repo`), `git commit` (`cwd=repo`), and `git rev-parse HEAD` (`cwd=repo`) through it. Keep the test's assertions and `_skip_on_ci` fixture unchanged.
   - Acceptance signal: `uv run pytest tests/test_gitleaks.py -q -p no:xdist` exits 0, and `rg "subprocess.run|check_output" tests/test_gitleaks.py` shows no remaining `check=True`+`capture_output=True` git-provisioning call in `TestOidHandling` (all routed through `_run_provisioning`).
   - Validation: `uv run ruff check tests/test_gitleaks.py` exits 0; `uv run ruff format --check tests/test_gitleaks.py` exits 0.
   - Acceptance evidence: pytest green; the flaky test passes; grep confirms the refactor.
   - Repair attempts: 0
   - Recovery note: partial work = helper missing or test still using `subprocess.run`; grep + pytest identify it; resume by completing the helper and call-site swaps.

2. [pending] Isolate the semgrep-policy scan directory per worker
   - Task ID: T002
   - Depends on: none
   - Parallel group: G1
   - Risk: low
   - Owned scope: `tests/test_semgrep_policy.py` only
   - Not in scope: `scripts/semgrep_policy.py`, `build/` layout, `.gitignore`, Makefile
   - Spike candidate: none (mechanism confirmed in R&D R1; `tmp_path_factory` per-worker-unique verified)
   - Actions: Remove the `SCAN_ROOT` constant (line 39) and rewrite the `scan_dir` fixture (lines 170-176) to `tmp_path_factory.mktemp("semgrep-policy-scan")` per Design. Leave `positive_scan`/`negative_scan` and all behaviour tests unchanged.
   - Acceptance signal: `uv run pytest tests/test_semgrep_policy.py -n 4 -q` exits 0, and `rg "SCAN_ROOT|semgrep-policy-scan" tests/test_semgrep_policy.py` returns no matches.
   - Validation: `uv run pytest tests/test_semgrep_policy.py -p no:xdist -q` exits 0; `uv run ruff check tests/test_semgrep_policy.py` and `uv run ruff format --check tests/test_semgrep_policy.py` exit 0.
   - Acceptance evidence: pytest green under `-n 4` and serial; fixed-path constant gone.
   - Repair attempts: 0
   - Recovery note: partial work = fixture still uses SCAN_ROOT; grep catches it; resume by completing the fixture rewrite.

3. [pending] Add retry-helper unit tests and run sustained parallel verification
   - Task ID: T003
   - Depends on: T001, T002
   - Parallel group: G2
   - Risk: low
   - Owned scope: `tests/test_gitleaks.py` (two new test methods), no other files
   - Not in scope: no new test files, no new dependencies
   - Spike candidate: none
   - Actions: Add `TestRunProvisioning` with (a) `test_run_provisioning_retries_on_transient_failure` (a command failing once then succeeding, asserting the successful return) and (b) `test_run_provisioning_surfaces_stderr` (a command failing twice, asserting `AssertionError` message contains both `stdout:` and `stderr:`). Then run the acceptance commands below.
   - Acceptance signal: `uv run pytest tests/test_gitleaks.py -k "RunProvisioning" -q -p no:xdist` exits 0 with 2 passed.
   - Validation: `uv run pytest tests/test_gitleaks.py -n 4 -q` 5 consecutive passes; `uv run pytest tests/test_semgrep_policy.py -n 4 -q` 5 consecutive passes; `uv run pytest tests/test_gitleaks.py tests/test_semgrep_policy.py -p no:xdist -q` passes; then `make test` (document any remaining unrelated failures with evidence, e.g. attachments integration).
   - Acceptance evidence: 2 new unit tests green; 5× `-n 4` runs green for both files; full `make test` recorded.
   - Repair attempts: 0
   - Recovery note: partial work = a sustained run fails; capture the failing test's stderr (now surfaced by T001) to diagnose; resume by fixing the affected test or, if a new mechanism appears, re-planning.

## Verification Strategy
- Cheapest first per task: `uv run ruff check <file>` then `uv run ruff format --check <file>` then the focused pytest target.
- Unit: `-k "RunProvisioning"` (T003).
- Integration (the flake gates): 5 consecutive `uv run pytest tests/test_gitleaks.py -n 4 -q` and 5 consecutive `uv run pytest tests/test_semgrep_policy.py -n 4 -q` — these are the exact conditions that previously failed (semgrep ~100%, gitleaks intermittently).
- Batch/final: `make test` full run; gitleaks + semgrep files must be green; unrelated pre-existing failures (attachments) recorded, not fixed.
- Serial sanity: `-p no:xdist` runs of both files to prove serial parity is preserved.
- Known environment-sensitive: the gitleaks flake is not deterministically reproducible, so acceptance is (a) no regression, (b) the retry helper is proven by unit tests, (c) future failures become diagnosable via surfaced stderr.

## Risks And Recovery
- R1 (medium): The gitleaks retry may not capture the true root cause (unreproducible). Mitigation: bounded 2-attempt retry with surfaced stderr; if it recurs, the error message now reveals git's actual failure. If recurrence shows a genuine bug, the surfaced stderr lets a follow-up fix target it.
- R2 (low): `tmp_path_factory.mktemp` semantics differ from the fixed `build/` path (e.g. scan dir not under `build/`). Mitigation: no other test references the path (verified); pytest cleans its tmp root.
- R3 (low): The semgrep fix leaves the latent single-worker quirk (`negative_scan` scans a dir that also holds positive fixtures). Mitigation: unchanged behaviour today (per-file attribution); documented, not in scope.
- R4 (low): 5× `-n 4` runs are time-consuming (~70s each for semgrep). Mitigation: they are the authoritative flake gate; run them in T003.
- Rollback: both tasks are confined to two test files; a `git checkout` of those files fully reverts.

## Critique Resolution
| Finding | Severity | Resolution | Evidence |
|---|---|---|---|
| (primary-led hostile self-review) Does the gitleaks retry risk masking a genuine bug? | Major | Bounded (2 attempts) + stderr surfaced; the semgrep fix removes the largest contention source; acceptance requires no-regression AND diagnosability rather than claiming the flake is impossible | R2 probes; surfaced-stderr design |
| Is `tmp_path_factory` safe in a session-scoped fixture under xdist? | Major | pytest provides `tmp_path_factory` to session fixtures; per-worker unique roots are pytest-xdist documented behaviour; verified xdist 3.8.0 | R3; A2 |
| Does isolating the scan dir change test semantics? | Minor | Same per-worker shared dir for positive/negative scans; only the path becomes unique; all behaviour tests unchanged | A6 |
| Should the fix also touch sibling gitleaks files? | Minor | Not observed flaky; out of scope (A5); noted as a discovered requirement for a follow-up if they flake | R2 call-site table |
| Is a 0.5s sleep acceptable in the suite? | Nit | Bounded to one retry; worst case adds 0.5s to a failing path only | Design |

## Progress Journal
| Timestamp | Cycle | Transition | Tasks | Evidence/result | Next state |
|---|---|---|---|---|---|
| 2026-08-04 | 0 | INTAKE | — | Ask = fix pre-existing flaky gitleaks test; user expanded scope to also fix the related semgrep-policy flake under `-n auto` | DISCOVER |
| 2026-08-04 | 0 | DISCOVER | — | Read failing tests/fixtures; confirmed no hooksPath/git-env pollution; extensive reproduction probes (24-way, 8-way, memory limits, semgrep storms, 8× `-n 4`) all passed for gitleaks; semgrep reproduced 4/4 under `-n 4` | RESEARCH |
| 2026-08-04 | 0 | RESEARCH | — | Two parallel tracks: semgrep root cause confirmed (shared fixed SCAN_ROOT raced across workers; "Invalid scanning root"); gitleaks call sites enumerated, pytest-rerunfailures absent, xdist_group inert under load/loadfile, CI facts | DRAFT |
| 2026-08-04 | 0 | DRAFT | — | 3-task plan written (gitleaks helper, semgrep isolation, tests+verification) | CRITIQUE |
| 2026-08-04 | 0 | CRITIQUE | — | Primary-led hostile self-review (small, low-risk test-only plan); findings recorded above | REMEDIATE |
| 2026-08-04 | 0 | REMEDIATE | — | Findings reconciled: retry design justified, tmp_path_factory verified, scope contained | VERIFY |
| 2026-08-04 | 0 | VERIFY | — | Primary agent approved: AC1-AC6 map to T001-T003; commands match repo; gitleaks retry is bounded+diagnosable | SAVED |

## Completion Review
(filled by csm-build when all criteria are verified)
