# P0 Assessment — Ranks 1–6 (Security & Governance)

> Generated: 2026-07-31
> Scope: `quality/remediation/outstanding-work.md` items 1–6 (P0)
> Base commit: `a1bb6d6` (master)
> Classification keys: `feasible-now` / `needs-github-admin` / `needs-opencode-config` / `needs-external-service`

## Summary Table

| # | Rank | Current state | Blocker | Effort | Classification |
|---|------|---------------|---------|--------|----------------|
| 1 | Branch protection ruleset | None — no ruleset, no classic protection, no CODEOWNERS | Repo owner / GitHub plan | S | `needs-github-admin` |
| 2 | CI secrets isolation | Authenticated Safety runs on same-repo PRs; pip-audit absent from CI | Protected environment binding | M | `feasible-now` + `needs-github-admin` |
| 3 | Release security | Single build-and-publish job on bare `v*` tag push; no tag protection, ancestry check, split build, verified env, provenance | Tag protection + environment | L | `feasible-now` + `needs-github-admin` |
| 4 | Fuzz authority | 17 harnesses + drift enforcement exist, but Atheris is uninstalled and tests silently skip; CI job non-blocking | Atheris wheel availability | M | `feasible-now` |
| 5 | Plugin protection | Blocking quality-gate plugin (pseudo-security); behavioural tests pinned in CI; no server-side file protection | Server-side protection | S–M | `needs-opencode-config` + `needs-github-admin` |
| 6 | Gate policy integrity | gates.conf agent-locked (client-side only); no independent ownership, no base-branch policy diff, no co-modification guard | Enforcement (CODEOWNERS / branch protection) | M | `feasible-now` + `needs-github-admin` |

## Rank 1 — GitHub branch protection ruleset

**Definition** (outstanding-work.md item 1): require PRs, required checks, code-owner approval, stale-approval dismissal, blocked force-push and branch deletion, no agent bypass.

**Current state:**
- No ruleset exists: `gh api repos/jamiemills/perplexity-cli/rulesets` → `[]`.
- No classic protection: `gh api repos/jamiemills/perplexity-cli/branches/master/protection` → `404 Branch not protected`.
- No `.github/CODEOWNERS` file (checked: absent), so code-owner review cannot be configured even in-repo.
- CI already exposes required-check candidates: secret-scan, static, test-coverage, test-compat, property, diff-coverage, mutation-diff, package, wheel-smoke (`.github/workflows/ci.yml:18-354`).

**What's missing:** the entire ruleset; a CODEOWNERS file; enforcement that agents cannot bypass (rulesets apply to all actors with appropriate bypass conditions).

**Blocker:** rulesets are server-side GitHub configuration — only the repository owner/admin can create them. The repo is single-owner (`jamiemills/perplexity-cli`). Some features (e.g. code-owner review) may be gated by the GitHub plan.

**Effort:** S — creating a ruleset is quick once admin access is confirmed.

**Classification:** `needs-github-admin`.

## Rank 2 — CI secrets isolation

**Definition** (outstanding-work.md item 2): run authenticated Safety only post-merge or from immutable trusted code; keep credential-free `pip-audit` on PRs.

**Current state:**
- `ci.yml:254-280` `safety` job runs with `SAFETY_API_KEY` (`ci.yml:279`) on: pushes to master, workflow_dispatch **and** same-repo PRs (`if: github.event_name != 'pull_request' || (head.repo.full_name == github.repository && actor != 'dependabot[bot]')`). Same-repo PR branches are not immutable trusted code, so the secret is exposed to PR-triggered runs.
- Fork PRs and dependabot PRs are correctly excluded (no `pull_request_target`, so the secret is not leaked to untrusted forks).
- `publish-to-pypi.yml:54` also passes `SAFETY_API_KEY` to `make ci-trusted` — this is post-merge trusted (tag push), acceptable.
- `pip-audit` (credential-free) exists as a Make target (`Makefile:262`) and in the local `ci` composite (`Makefile:526`), but is **not wired into any GitHub workflow** (grep over `.github/workflows/` returns zero matches).

**What's missing:**
- Restrict the authenticated `safety` job to `push: master` (and scheduled/trusted refs), or scope the secret to a protected GitHub environment.
- Add a credential-free `pip-audit` step to the PR CI lane.

**Blocker:** the workflow rewrite is in-repo; binding `SAFETY_API_KEY` to a protected deployment environment is server-side (admin).

**Effort:** M.

**Classification:** `feasible-now` (workflow + Makefile changes) with a `needs-github-admin` component (protected environment / secret scoping).

## Rank 3 — Release security

**Definition** (outstanding-work.md item 3): protect tags, require ancestry from protected master, split build from privileged publication, verified environment, hash verification, provenance attestation.

**Current state:**
- `publish-to-pypi.yml` triggers on any `push` of a `v*` tag (`publish-to-pypi.yml:3-6`) and performs build + publish in a **single job** (`publish-to-pypi.yml:13-68`).
- Workflow-level `permissions: contents: write, id-token: write` (`publish-to-pypi.yml:8-11`) — broader than the publication step needs.
- PyPI publish uses OIDC via `pypa/gh-action-pypi-publish` (`publish-to-pypi.yml:57-60`) — already good.
- Version-match validation between tag / `pyproject.toml` / runtime exists (`publish-to-pypi.yml:34-47`).
- `make release` (`Makefile:432-449`) runs `ci-trusted` locally, then commits, tags and pushes both master and the tag from a developer machine.
- `scripts/verify_wheel.py` verifies wheel contents but performs **no hash verification**.
- No tag protection (any actor with push can trigger a publish), no ancestry check (tag need not descend from master), no deployment environment, no build/publish split, no provenance attestation.

**What's missing:**
- Server-side: tag protection ruleset; protected deployment environment.
- In-repo: split build job from publish job; ancestry check (`git merge-base --is-ancestor` of tag vs master); hash-verify the built artifact before publish; add `actions/attest-build-provenance` (or sigstore) for provenance.

**Blocker:** tag protection and protected environments require repo admin. The remaining items are plain workflow changes.

**Effort:** L.

**Classification:** mixed — `feasible-now` (ancestry check, job split, hash verification, provenance attestation) + `needs-github-admin` (tag protection, environment).

## Rank 4 — Fuzz authority

**Definition** (outstanding-work.md item 4): install and lock Atheris, fail if unavailable, fail if harness count changes, fail if any fuzz test skips.

**Current state:**
- **COMPLETE (2026-07-31):** atheris>=3.1.0 added to dev group, platform-gated to linux/x86_64 (no macos/aarch64 wheels — verified via `uv sync --python-platform macos`); 17 fuzz tests run and pass; skipif guards replaced with `pytest.fail` inside `_run_harness`; CI `fuzz-status` no longer has `continue-on-error`; Makefile comment says authoritative.
- 17 harnesses in `tests/_fuzz_harnesses.py` (`_HARNESSES` registry, lines 266-284), driven by `tests/test_fuzz.py` via subprocess (`test_fuzz.py:37-51`).
- Harness drift is enforced: `TestFuzzHarnessEnforcement` (`test_fuzz.py:193-262`) checks registry ↔ test sync and a hard-coded count of 17 (`test_fuzz.py:258-262`). This class is **not** fuzz-marked, so it runs in the standard suite — count failures already fail CI.
- `make test-fuzz` (`Makefile:333-334`) runs `pytest tests/test_fuzz.py -m fuzz` — 17 passed, 4 deselected in ~13s.
- CI `fuzz-status` job (`ci.yml:147-168`) calls `make ci-fuzz-status` (`Makefile:520`), now blocking (no `continue-on-error`).

**Residual:** the `fuzz` lane fails loudly if atheris is missing on linux/x86_64; macos/aarch64 runs the standard suite (enforcement tests only) since atheris has no wheels there — fuzz lane itself is linux-only.

**What's missing:**
- Add Atheris to a locked dependency group (e.g. a `fuzz` extra/dev group) and `uv lock`.
- Replace the silent `skipif` with a fail-if-unavailable guard (either drop the skip, or add a collection guard that errors when `atheris` is not importable).
- Add a fail-if-skipped guard so any skip in a fuzz run breaks `make test-fuzz`.
- Remove `continue-on-error` and the `non-authoritative` status in CI (`ci.yml:151`, `Makefile:520`).

**Blocker:** Atheris wheel availability for the pinned interpreter (CI fuzz lane uses Python 3.12, which Atheris supports; 3.13/3.14 may need a non-wheel build). Verify during install. No GitHub-admin or opencode-config dependency.

**Effort:** M.

**Classification:** `feasible-now` (all changes are in-repo: `pyproject.toml`, `uv.lock`, `Makefile`, `tests/test_fuzz.py`, `ci.yml`).

## Rank 5 — Agent plugin protection

**Definition** (outstanding-work.md item 5): treat plugins as feedback not security boundary, restore pinned CI and behavioural tests, protect plugin/config files server-side, delete pseudo-security mechanisms.

**Current state:**
- `opencode.jsonc` registers three plugins (`.opencode/plugins/quality-gate.ts`, `pxcli-quality.ts`, `pre-push-docs-check.ts`) and agent-locks `quality/gates.conf` via a permission deny (`opencode.jsonc:11-16`).
- `.opencode/plugins/quality-gate.ts` is a **security-boundary** plugin: it blocks agent tool calls that would loosen gates (`quality-gate.ts:257-297`) and logs warnings on protected-file modifications (`quality-gate.ts:301-330`). It is client-side and bypassable (`OPENCODE_DISABLE_QUALITY_GATE=1`, `quality-gate.ts:239-241`), and only constrains the agent, not humans — i.e. a pseudo-security mechanism by the item's definition.
- Pinned CI and behavioural tests exist: the CI `static` job runs `make opencode-check` (`ci.yml:63-67`), which runs `npm run check` (lint + vitest + typecheck + config validation — `.opencode/package.json:4-9`); `make opencode-audit` runs `npm audit` (`Makefile:95-108`). `.opencode/tests/` contains vitest behavioural tests for the quality-gate and pxcli-quality plugins.
- Plugin and config files live in-repo with no server-side protection; nothing in `.github/` protects them (no CODEOWNERS, no ruleset — see Rank 1).

**What's missing:**
- Delete or downgrade the blocking behaviour in `quality-gate.ts` to feedback-only, and adjust `opencode.jsonc` accordingly (or explicitly accept the agent-side guardrail as documented non-security).
- Server-side protection of `.opencode/` and `opencode.jsonc` (CODEOWNERS / branch protection / protected environment — admin).

**Blocker:** server-side file protection requires GitHub admin. The plugin downgrade and config change are in-repo.

**Effort:** S–M.

**Classification:** `needs-opencode-config` (plugin repurpose + `opencode.jsonc`) + `needs-github-admin` (server-side protection).

## Rank 6 — Gate policy integrity

**Definition** (outstanding-work.md item 6): protect gate infrastructure with independent ownership, add trusted structural policy validation against base branch, prevent test-and-policy co-modification.

**Current state:**
- `quality/gates.conf` is the executable gate floor: `Makefile:5` includes it, `scripts/_gates.py` reads it (`_gates.py:33`). It is denied to agents only via the client-side `opencode.jsonc` deny rule (`opencode.jsonc:13-14`).
- Gate scripts (`scripts/`) and `Makefile` are protected only by the quality-gate plugin (agent-side, bypassable — see Rank 5).
- A toggle-consistency contract exists: `tests/test_help_doc_drift.py:449-463` (`test_check_toggles_match_gates_conf`) asserts key `CHECK_*` toggles are present in `gates.conf`.
- `lefthook.yml:268-269` runs `make agent-check-no-tests` on pre-commit (uses `scripts/agent_check.py`).
- **No independent ownership**: no CODEOWNERS, no second-owner requirement (single-owner repo).
- **No trusted structural validation against base branch**: no CI job diffs `gates.conf` / `pyproject.toml` thresholds / Makefile gate references against the base branch to detect loosening.
- **No test-and-policy co-modification guard**: a PR could weaken a gate and edit the enforcing test in the same PR with no independent gatekeeper.

**What's missing:**
- In-repo: a CI job that structurally validates policy files against the base branch (e.g. reuses the `quality-gate.ts` bypass-detection logic server-side) and rejects loosening.
- Admin: CODEOWNERS on `quality/`, `scripts/`, `Makefile`, `.github/workflows/` plus branch protection to enforce independent ownership and block test-and-policy co-modification.

**Blocker:** enforcement (ownership, co-modification) needs branch protection/CODEOWNERS (admin); the validation job itself is in-repo.

**Effort:** M.

**Classification:** mixed — `feasible-now` (policy-diff CI job, structural validation) + `needs-github-admin` (independent ownership, co-modification prevention).

## Classification Summary

**Feasible in this repo without external access (partial for several items):**
- Rank 4 is fully in-repo: lock Atheris, make fuzz fail on missing/skip, make CI blocking.
- Rank 2 in-repo half: restrict `SAFETY_API_KEY` to trusted refs; wire credential-free `pip-audit` into PR CI.
- Rank 3 in-repo half: split build/publish, ancestry check, hash verification, provenance attestation.
- Rank 6 in-repo half: add trusted base-branch structural policy validation to CI.

**Needs GitHub admin (owner):**
- Rank 1 in full (ruleset).
- Rank 2 environment binding for `SAFETY_API_KEY`.
- Rank 3 tag protection + protected deployment environment.
- Rank 5 server-side protection of `.opencode/` and `opencode.jsonc`.
- Rank 6 CODEOWNERS / branch protection for independent ownership and co-modification prevention.

**Needs opencode config:**
- Rank 5 in part: repurpose or delete the blocking quality-gate plugin, update `opencode.jsonc`.

**Needs external service:**
- Rank 4 has a residual dependency on Atheris wheel availability for the pinned Python versions (verify at install time; not an ongoing external service).

## Recommendation — Order of Attack

1. **Rank 4 (fuzz authority)** — do first: fully in-repo, self-contained, and converts a silently-green lane into an authoritative one. Verify Atheris installs on the CI interpreter before wiring the blocking CI job.
2. **Rank 2 (secrets isolation)** — next: workflow-only change (restrict authenticated Safety to trusted refs; add pip-audit to PRs). Close the same-repo PR secret exposure without waiting on admin.
3. **Rank 3 (release security) in-repo half** — immediately after: ancestry check, build/publish split, hash verification, provenance attestation. These reduce supply-chain risk without admin.
4. **Rank 6 (gate integrity) in-repo half** — add the base-branch structural policy validation job; it converts the agent-side bypass detection into a trusted CI check.
5. **Batch the admin-dependent work** (Ranks 1, 2/3 environment halves, 5/6 ownership halves) into a single admin session: create the branch-protection ruleset, add CODEOWNERS, scope secrets to a protected environment, add tag protection.
6. **Rank 5 (plugin protection)** — last, and only with explicit product decision: the quality-gate plugin currently functions as a security boundary; decide whether to keep it as a documented agent-side guardrail (and restore CI/behavioural pins if retained) or delete it as pseudo-security once server-side protections are live.

After this plan (`2026-07-31-final-hardening-cleanup-csm.md`) completes, the immediate next step is Rank 4, then the Rank 2/3/6 in-repo halves — none of which require GitHub admin. The admin-dependent items should be parked until the owner can create rulesets and environments.
