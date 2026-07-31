# Outstanding Work — All Plans

> Generated: 2026-07-29
> Source: comprehensive-quality-infrastructure-review-plan.md, quality-gates-hardening-plan.md,
>   quality-infrastructure-selected-remediation-plan.md, quality-debt-review.md, CSM runs 20260728-0002/0100

## Completed

- Ranks 16, 17, 21, 25, 26, 29 + bounded 10/18 prereqs (run 20260726-201025, 8 waves)
- All 12 CHECK_* gates activated, function-local imports 111→4, package pins (run 20260728-0002)
- Mutation score 57.5%→70.1%, 2177 new tests, macOS bash fix, mcp Dependabot fix, CI 12/12 green (run 20260728-0100)

## Outstanding

1. GitHub branch protection ruleset (require PRs, required checks, code-owner approval, stale-approval dismissal, blocked force-push/deletion, no agent bypass)
2. CI secrets isolation — run authenticated Safety only post-merge or from immutable trusted code; keep credential-free pip-audit on PRs
3. Release security — protect tags, require ancestry from protected master, split build from privileged publication, verified environment, hash verification, provenance attestation
4. Fuzz testing — install and lock Atheris, fail if unavailable, fail if harness count changes, fail if any fuzz test skips
5. Agent plugin protection — treat plugins as feedback not security boundary, restore pinned CI and behavioural tests, protect plugin/config files server-side, delete pseudo-security mechanisms
6. Gate policy integrity — protect gate infrastructure with independent ownership, add trusted structural policy validation against base branch, prevent test-and-policy co-modification
7. Production architecture migration — create ports package, replace concrete adapter imports in application layer with ports, eliminate app→adapter TYPE_CHECKING imports, update composition roots
8. Remove custom architecture checker — make Import Linter the sole canonical architecture engine, delete scripts/check_architecture.py after equivalence is proven
9. Coverage integrity — independently enumerate all source modules, reject missing report entries, add diff-cover with explicit base/tested SHA, validate branch data, combine unit+integration coverage fragments
10. Hermetic integration tests — local loopback HTTP/SSE server harness, query protocol chain, attachment upload chain, autouse non-loopback network guard, adversarial connection-rejection tests
11. Systematic assertion quality audit — inventory and fix generic error alternatives, swallowed exceptions, weak disjunctions
12. Mock reduction — replace internal constructor patches with application fixtures and fake outer protocol boundaries, use autospec/spec_set/AsyncMock/typed protocol fakes
13. Delete quality-plan mechanism — remove plan-gate-compliance.ts, plan-gate-check.mjs, plan-reviewer-quality.md, plan_compliance_check.py, quality_plan_generator.py, test_plan_compliance.py, Make targets, Lefthook jobs, plugin registration, package scripts, documentation claims. **COMPLETE (2026-07-31): mechanism deleted, stale mutmut ignore removed, no live documentation claims remain (remaining references are historical records).**
14. Property-test ownership — register property marker, mark every Hypothesis test, exclude property from test-unit and unit coverage, explicit -m property per target, independent mutmut marker expression, expected node-count checks, explicit profile fields, reproduction-blob meta-test
15. Hook ordering — fix pre-commit sequence (read-only before modifications, fix before format, reject partial staging, rerun after fixes)
16. Hook/CI parity — add deterministic locked repository-policy CI job
17. Ruff expansion wave 1 — C90, PL, ARG, RET, SIM, BLE, FBT
18. Ruff expansion wave 2 — ANN, TC, FA, PYI
19. Ruff expansion wave 3 — TRY, EM, RSE
20. Ruff expansion wave 4 — LOG, G, T20
21. Ruff expansion wave 5 — PTH, DTZ, SLOT, PERF, PIE
22. Ruff expansion wave 6 — PT
23. Ruff expansion wave 7 — DOC or pydoclint
24. Ruff expansion wave 8 — FURB via Ruff or Refurb
25. Strict Pyright rollout — promote strict mode by layer, enable reportImportCycles, reportUnnecessaryTypeIgnoreComment, reportUnknown*, reportMissingTypeArgument, resolve 682 findings
26. Diff coverage in PR CI — diff-cover with explicit base/tested SHA, 90-95% threshold
27. Changed-code mutation in PR CI — event-aware, 45-min timeout, no cap, explicit markers, budget-exceeded failure
28. Source-complete coverage enumeration — independently enumerate all src/**/*.py, require every executable module entry, AST-classify empty __init__.py
29. __init__.py declarative policy — structural test requiring only docs/imports/re-exports/__all__/constants
30. Suppression and exclusion integrity — track exact identities for all pragma/coverage/mutmut exclusions, remove formatting/registry.py mutation exclusion
31. Windows CI or narrow OS-independence claim
32. Deterministic tests — inject clocks, use tmp_path, locate executables dynamically
33. Delete shadow gates — remove or canonicalize check_ruff_architecture.py, check_pyright_strict.py, empty baselines
34. Sonar reports — decide role or remove
35. Reproducibility — pin remaining uvx commands, pin uv in CI
36. CodeQL JavaScript/TypeScript — add JS/TS to CodeQL default setup
37. Reporting and observability — emit JSON/SARIF, CI annotations, release quality summary, trend metrics
38. Hook/Makefile/CI/docs parity test — validate all documented blocking gates have wiring
39. Bandit strictness alignment — decide explicit severity/confidence policy
40. Test lane reclassification — remove marker selection from global addopts, add hermetic_integration marker, reclassify markers, rename mocked E2E suites, collection policy tests
41. Real API canary — deferred until rank 2; then explicit opt-in, protocol health assertions
42. Coupling module splits — split utils/config, utils/logging, utils/http_errors; promote api.models types to contracts/
43. Per-file pyright-strict debt (682 findings)
44. Per-file ruff-architecture debt (43 findings)
45. Per-file semgrep-architecture debt (4 findings baselined)
46. Suppressions debt (83 identities)
47. Coupling debt (34/40 flagged modules)
