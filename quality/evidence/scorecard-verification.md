# Scorecard Workflow Verification Checklist

> Run ID: 20260728-0100
> Task ID: P3B-SCORECARD
> Workflow: `.github/workflows/scorecard.yml`
> Scope: Local pre-push validation and post-push verification of the OpenSSF
> Scorecard producer/validator workflow.

## 1. Local Pre-Push Validation (completed)

- [x] `actionlint .github/workflows/scorecard.yml` passes with no findings.
- [x] `uv run python scripts/validate_workflow_policy.py --dir .github/workflows --json`
      reports `pass: true` and `scorecard.yml` has `0` findings.
- [x] `ossf/scorecard-action` is pinned to a full 40-character commit SHA
      (`2d1146689b8cda280b9bc96326124645441f03bc`, `v2.4.4`), not a mutable tag.
- [x] Top-level `permissions` is scoped to `contents: read`.
- [x] `concurrency.group` is defined with `cancel-in-progress` gated on event type.
- [x] Both jobs set `timeout-minutes: 10`.
- [x] Producer job permissions are `contents: read`, `id-token: write`,
      `security-events: write`.
- [x] Validator job (`scorecard-validate`) `needs: [scorecard]`, downloads the
      SARIF artifact, validates it, and only then uploads to code scanning.

## 2. Post-Push Verification

Run these steps after the commit lands on the default branch.

### 2.1 Trigger a run

- [ ] Open **Actions → OpenSSF Scorecard** and select **Run workflow**
      (`workflow_dispatch`), or wait for the Monday `0 6 * * 1` schedule.
- [ ] Confirm a new run appears and the concurrency group resolves to
      `scorecard-dispatch-<run_id>` for manual runs.

### 2.2 Producer job (`Scorecard (producer)`)

- [ ] Job completes successfully within the 10-minute timeout.
- [ ] The `Run Scorecard` step logs the pinned action SHA
      `2d1146689b8cda280b9bc96326124645441f03bc`.
- [ ] The `Upload SARIF artifact` step succeeds and publishes an artifact named
      `scorecard-results-<run_id>-<run_attempt>`.

### 2.3 Validator job (`Scorecard (validator)`)

- [ ] Job starts only after the producer job (`needs: [scorecard]`).
- [ ] `Download SARIF artifact` retrieves `results.sarif` into `sarif/`.
- [ ] `Validate SARIF` emits a `::notice::SARIF valid (...)` line and writes the
      job summary (version, runs, results, bytes).
- [ ] `Upload to code scanning` succeeds with `category: openssf-scorecard`.

### 2.4 Downstream confirmation

- [ ] **Security → Code scanning** shows a fresh `openssf-scorecard` analysis.
- [ ] The run summary displays the OpenSSF Scorecard validation section.
- [ ] No unexpected permission or secret-scanning alerts were raised by the run.

## 3. Rollback / Failure Notes

- If the validator reports `SARIF file not found` or `empty`, re-run the producer
  job; the artifact `if-no-files-found: error` guard should surface the failure.
- If code scanning upload fails, confirm the repository has code scanning enabled
  and that `security-events: write` is permitted for the workflow.
- The workflow is additive; disabling it does not affect CI or publishing.
