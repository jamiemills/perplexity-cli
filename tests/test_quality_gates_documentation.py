"""Semantic cross-source drift tests for ``QUALITY_GATES.md``.

This module statically validates the quality guide against executable sources
(``quality/gates.conf``, ``lefthook.yml``, the Makefile, workflow YAML files,
``opencode.jsonc`` and ``tests/conftest.py``).  It never executes an analyser,
gate, hook or workflow: it only parses files and compares the guide's claims
with the actual topology and policy values.

Parser helpers accept text and return violation lists so that synthetic
negative cases can prove the parsers fail closed (a parser that silently
ignores a missing or extra element must not return an empty violation list).

Known guide/card-format workarounds (reported to the primary agent):

* ``automation.release-drafter.update_release_draft`` uses underscores and
  therefore fails the strict ``[a-z0-9-]`` dotted-ID pattern; it is the only
  such card and is asserted explicitly so a new non-conforming ID fails.
* Every card carries all thirteen canonical fields declared in Section 8,
  including ``Trigger and scope`` and ``Execution context``.  The completeness
  check enforces all thirteen on every card and separately asserts that the
  guide's Section 8 field declaration still names all thirteen canonical
  fields.
* Automation and release cards label the ordering field ``Concurrency`` instead
  of ``Ordering and concurrency``; ``inline.reject-partial-staging`` uses
  combined labels.  Alias handling below normalises these to the canonical
  field names.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from ruamel.yaml import YAML

if TYPE_CHECKING:
    from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
QUALITY_GATES = PROJECT_ROOT / "QUALITY_GATES.md"
GATES_CONF = PROJECT_ROOT / "quality" / "gates.conf"
LEFTHOOK = PROJECT_ROOT / "lefthook.yml"
MAKEFILE = PROJECT_ROOT / "Makefile"
WORKFLOWS = PROJECT_ROOT / ".github" / "workflows"
OPCODE_CONFIG = PROJECT_ROOT / "opencode.jsonc"
CONFTEST = PROJECT_ROOT / "tests" / "conftest.py"

GUIDE_TEXT = QUALITY_GATES.read_text(encoding="utf-8")

_CARD_ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]*(\.[a-z0-9-]+)+$")
_CARD_HEADING = re.compile(r"^#### `([^`]+)`(?:: (.*))?$")
_CARD_FIELD = re.compile(r"^\s*- \*\*(.+?):\*\*(.*)$")

_ALLOWED_NAMESPACES = frozenset(
    {"session", "hook", "make", "ci", "automation", "release", "inline", "test"}
)
# Underscore IDs fail the strict dotted pattern but are pinned by other
# authorities (the workflow job key must be a valid identifier per
# tests/test_distribution_contract.py). New non-conforming IDs must be
# added here only with a matching authority.
_UNDERSCORE_ID_EXCEPTIONS = frozenset(
    {
        "automation.release-drafter.update_release_draft",
        "ci.ci.windows_packaging_smoke",
    }
)

_FIELD_ALIASES = {
    "Purpose": {"Purpose", "Purpose/authoritative source"},
    "Authoritative source": {"Authoritative source", "Purpose/authoritative source"},
    "Canonical invocation": {"Canonical invocation"},
    "Trigger and scope": {"Trigger and scope"},
    "Execution context": {"Execution context"},
    "Contextual enforcement": {"Contextual enforcement"},
    "Skip semantics": {"Skip semantics"},
    "Inputs and configuration": {
        "Inputs and configuration",
        "Inputs/outputs/requirements/side effects/replication",
    },
    "Ordering and concurrency": {"Ordering and concurrency", "Concurrency"},
    "Outputs and evidence": {
        "Outputs and evidence",
        "Inputs/outputs/requirements/side effects/replication",
    },
    "Requirements": {
        "Requirements",
        "Inputs/outputs/requirements/side effects/replication",
    },
    "Side effects": {
        "Side effects",
        "Inputs/outputs/requirements/side effects/replication",
    },
    "Replication checks": {
        "Replication checks",
        "Inputs/outputs/requirements/side effects/replication",
    },
}

_REQUIRED_CARD_FIELDS = (
    "Purpose",
    "Authoritative source",
    "Canonical invocation",
    "Trigger and scope",
    "Execution context",
    "Contextual enforcement",
    "Skip semantics",
    "Inputs and configuration",
    "Ordering and concurrency",
    "Outputs and evidence",
    "Requirements",
    "Side effects",
    "Replication checks",
)

_SCHEMA_DECLARED_FIELDS = (
    "Purpose",
    "Authoritative source",
    "Canonical invocation",
    "Trigger and scope",
    "Execution context",
    "Contextual enforcement",
    "Skip / not-applicable / tool-error semantics",
    "Inputs and configuration",
    "Ordering and concurrency",
    "Outputs and evidence",
    "Requirements",
    "Side effects",
    "Replication checks",
)

_PRECOMMIT_STAGES = (
    "reject-partial-staging",
    "lint-and-validate",
    "fix-formatting",
    "lint-after-fix",
    "pytest-check",
)
_PREPUSH_STAGES = (
    "gitleaks-detect",
    "static-checks",
    "pytest-coverage",
    "property-and-advisory",
    "mutate-diff",
    "safety-and-fuzz",
)

_WORKFLOW_PREFIXES = {
    "ci.yml": "ci",
    "mutation-scheduled.yml": "automation",
    "scorecard.yml": "automation",
    "semgrep-advisory.yml": "automation",
    "release-drafter.yml": "automation",
    "publish-to-pypi.yml": "release",
}

_STALE_PHRASES = (
    "three pre-commit stages",
    "three baseline-aware",
    "MAX_FLAGGED = 10",
    "skip notice and exits 0",
    "five ratchet",
    "quality/evidence/mutation-report.json",
    "mutation-report-v1.json",
    "mutation-waivers.toml",
    "quality/schemas/diff-coverage-v1.json",
)


# ---------------------------------------------------------------------------
# Shared parsing helpers
# ---------------------------------------------------------------------------


def _strict_yaml() -> YAML:
    """Build a ruamel parser that rejects duplicate mapping keys."""
    parser = YAML(typ="safe")
    parser.allow_duplicate_keys = False
    return parser


def _load_yaml(path: Path) -> dict[str, Any]:
    """Parse ``path`` with the strict YAML parser."""
    return _strict_yaml().load(path.read_text(encoding="utf-8"))


def _parse_gates_conf(text: str) -> dict[str, str]:
    """Parse ``KEY = VALUE`` pairs from ``gates.conf``, ignoring comments."""
    pairs: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.split("#", 1)[0].strip()
        if not stripped or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        pairs[key.strip()] = value.strip()
    return pairs


def _parse_guide_policy_table(text: str) -> dict[str, str]:
    """Extract key/value rows from the guide's Current Policy Values tables."""
    start = text.index("## 5. Current Policy Values")
    end = text.index("## 6. Phase Runbooks")
    section = text[start:end]
    pairs: dict[str, str] = {}
    for line in section.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [cell.strip().strip("`") for cell in line.strip("|").split("|")]
        if len(cells) < 2 or cells[0] == "Key" or set(cells[0]) <= {"-", ":"}:
            continue
        if cells[0]:
            pairs[cells[0]] = cells[1]
    return pairs


def _parse_cards(text: str) -> list[dict[str, Any]]:
    """Split ``text`` into card blocks keyed by stable ID."""
    cards: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in text.splitlines():
        heading = _CARD_HEADING.match(line)
        if heading:
            current = {"id": heading.group(1), "name": heading.group(2) or "", "lines": []}
            cards.append(current)
            continue
        if current is not None:
            current["lines"].append(line)
    return cards


def _card_field_counts(card: dict[str, Any]) -> dict[str, int]:
    """Map canonical field names to how many labels provide them."""
    counts: dict[str, int] = {}
    for line in card["lines"]:
        field = _CARD_FIELD.match(line)
        if not field:
            continue
        raw_label = field.group(1).strip()
        for canonical, aliases in _FIELD_ALIASES.items():
            if raw_label in aliases:
                counts[canonical] = counts.get(canonical, 0) + 1
    return counts


def _card_field_values(card: dict[str, Any]) -> dict[str, list[str]]:
    """Map canonical field names to the first-line values that supply them."""
    values: dict[str, list[str]] = {}
    for line in card["lines"]:
        field = _CARD_FIELD.match(line)
        if not field:
            continue
        raw_label = field.group(1).strip()
        value = field.group(2).strip()
        for canonical, aliases in _FIELD_ALIASES.items():
            if raw_label in aliases:
                values.setdefault(canonical, []).append(value)
    return values


def _card_completeness_violations(cards: list[dict[str, Any]]) -> list[str]:
    """Return violations for duplicate IDs, bad IDs and missing fields."""
    violations: list[str] = []
    seen_ids: set[str] = set()
    for card in cards:
        card_id = card["id"]
        if card_id in seen_ids:
            violations.append(f"duplicate card ID: {card_id}")
        seen_ids.add(card_id)
        namespace = card_id.split(".", 1)[0]
        if namespace not in _ALLOWED_NAMESPACES:
            violations.append(f"{card_id}: namespace {namespace!r} not allowed")
        if not _CARD_ID_PATTERN.match(card_id) and card_id not in _UNDERSCORE_ID_EXCEPTIONS:
            violations.append(f"{card_id}: ID does not match dotted pattern")
        counts = _card_field_counts(card)
        values = _card_field_values(card)
        for field in _REQUIRED_CARD_FIELDS:
            present = counts.get(field, 0)
            if present != 1:
                violations.append(f"{card_id}: field {field!r} present {present} times")
            elif not any(values.get(field, [])):
                violations.append(f"{card_id}: field {field!r} is empty")
    return violations


def _lefthook_stage_names(data: dict[str, Any], phase: str) -> tuple[str, ...]:
    """Return the ordered top-level stage names for ``phase``."""
    jobs = data.get(phase, {}).get("jobs", [])
    return tuple(job.get("name", "") for job in jobs if isinstance(job, dict))


def _lefthook_group(data: dict[str, Any], phase: str, stage: str) -> dict[str, Any]:
    """Return the ``group`` dict for ``stage`` in ``phase`` (or an empty dict)."""
    for job in data.get(phase, {}).get("jobs", []):
        if isinstance(job, dict) and job.get("name") == stage:
            return job.get("group") or {}
    return {}


def _lefthook_leaf_names(data: dict[str, Any], phase: str) -> list[str]:
    """Return every leaf job name in ``phase``, including inside groups."""
    leaves: list[str] = []

    def walk(jobs: list[Any]) -> None:
        for job in jobs:
            if not isinstance(job, dict):
                continue
            if "group" in job and isinstance(job["group"], dict):
                walk(job["group"].get("jobs", []))
            else:
                leaves.append(job.get("name", ""))

    walk(data.get(phase, {}).get("jobs", []))
    return leaves


def _lefthook_stdin_consumers(data: dict[str, Any], phase: str) -> list[str]:
    """Return leaf names in ``phase`` that set ``use_stdin: true``."""
    consumers: list[str] = []

    def walk(jobs: list[Any]) -> None:
        for job in jobs:
            if not isinstance(job, dict):
                continue
            if "group" in job and isinstance(job["group"], dict):
                walk(job["group"].get("jobs", []))
            elif job.get("use_stdin") is True:
                consumers.append(job.get("name", ""))

    walk(data.get(phase, {}).get("jobs", []))
    return consumers


def _lefthook_violations(data: dict[str, Any]) -> list[str]:
    """Return violations when the Lefthook topology diverges from the guide."""
    violations: list[str] = []
    pre_commit = data.get("pre-commit", {})
    pre_push = data.get("pre-push", {})
    if pre_commit.get("piped") is not True:
        violations.append("pre-commit is not piped")
    if _lefthook_stage_names(data, "pre-commit") != _PRECOMMIT_STAGES:
        violations.append("pre-commit stage names/order differ")
    lint_group = _lefthook_group(data, "pre-commit", "lint-and-validate")
    if lint_group.get("parallel") is not True:
        violations.append("lint-and-validate is not parallel")
    fix_group = _lefthook_group(data, "pre-commit", "fix-formatting")
    fixers = fix_group.get("jobs", [])
    if fix_group.get("piped") is not True:
        violations.append("fix-formatting is not piped")
    if len(fixers) != 4 or not all(
        isinstance(job, dict) and job.get("stage_fixed") is True for job in fixers
    ):
        violations.append("fix-formatting must have exactly four stage_fixed fixers")
    if _lefthook_group(data, "pre-commit", "lint-after-fix").get("parallel") is not True:
        violations.append("lint-after-fix is not parallel")
    if _lefthook_stage_names(data, "pre-commit")[-1:] != ("pytest-check",):
        violations.append("pytest-check must be the last pre-commit stage")
    if pre_push.get("piped") is not True:
        violations.append("pre-push is not piped")
    if _lefthook_stage_names(data, "pre-push") != _PREPUSH_STAGES:
        violations.append("pre-push stage names/order differ")
    stdin_consumers = _lefthook_stdin_consumers(data, "pre-push")
    if stdin_consumers != ["gitleaks-detect"]:
        violations.append(f"unexpected stdin consumers: {stdin_consumers}")
    return violations


def _makefile_prereqs(target: str) -> list[str]:
    """Return the prerequisite tokens for a Make target's definition line."""
    for line in MAKEFILE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped.startswith(f"{target}:") or stripped.startswith(f"{target}:="):
            continue
        body = stripped.split("##", 1)[0]
        return [token for token in body.split(":", 1)[1].split() if token]
    return []


def _guide_card_block(card_id: str) -> str:
    """Return the guide text from a card heading up to the next card heading."""
    start = GUIDE_TEXT.index(f"#### `{card_id}`")
    remainder = GUIDE_TEXT[start + 1 :]
    match = re.search(r"^#### `", remainder, re.MULTILINE)
    end = start + 1 + (match.start() if match else len(remainder))
    return GUIDE_TEXT[start:end]


def _guide_inventory_members(card_id: str) -> list[str]:
    """Return the inventory tokens listed in a card's canonical invocation."""
    block = _guide_card_block(card_id)
    lines = block.splitlines()
    start = next(
        i for i, line in enumerate(lines) if line.strip().startswith("- **Canonical invocation:**")
    )
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].strip().startswith("- **")),
        len(lines),
    )
    invocation = " ".join(lines[start:end])
    groups = re.findall(r"\(([^)]+)\)", invocation)
    assert groups, f"{card_id} canonical invocation must parenthesise the member list"
    return [token.strip("`") for token in groups[-1].split()]


def _plugin_paths(text: str) -> list[str]:
    """Extract ``.opencode/plugins/*.ts`` (or agents) paths from JSONC text."""
    return re.findall(r'"((?:\.opencode/plugins|\.opencode/agents)/[^"]+\.ts)"', text)


def _plugin_filenames(text: str) -> set[str]:
    """Return the basenames of every ``.opencode/plugins/*.ts`` reference."""
    return {Path(path).name for path in _plugin_paths(text)}


def _conftest_profiles(text: str) -> dict[str, tuple[int, int]]:
    """Parse Hypothesis profiles from ``conftest.py`` as name -> (examples, deadline)."""
    profiles: dict[str, tuple[int, int]] = {}
    pattern = re.compile(
        r'register_profile\(\s*"(\w+)"\s*,\s*max_examples=(\d+)\s*,\s*deadline=(\d+)'
    )
    for match in pattern.finditer(text):
        profiles[match.group(1)] = (int(match.group(2)), int(match.group(3)))
    return profiles


def _guide_profiles(text: str) -> dict[str, tuple[int, str]]:
    """Parse the guide's Hypothesis profile table rows."""
    start = text.index("### Hypothesis profiles")
    end = text.index("### Platform placement", start)
    section = text[start:end]
    profiles: dict[str, tuple[int, str]] = {}
    for line in section.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) >= 3 and cells[0].startswith("`"):
            profiles[cells[0].strip("`")] = (int(cells[1]), cells[2])
    return profiles


def _normalise(text: str) -> str:
    """Collapse all whitespace runs to single spaces."""
    return re.sub(r"\s+", " ", text)


# ---------------------------------------------------------------------------
# 1. Card completeness and ID well-formedness
# ---------------------------------------------------------------------------


class TestCardCompleteness:
    """Card IDs must be unique and well formed and carry required fields."""

    def test_card_ids_are_unique_and_well_formed(self) -> None:
        """Every card heading has a unique, namespaced dotted ID."""
        violations = _card_completeness_violations(_parse_cards(GUIDE_TEXT))
        assert violations == []

    def test_only_documented_underscore_id_exists(self) -> None:
        """The only non-conforming IDs are the two documented exceptions."""
        non_conforming = {
            card["id"]
            for card in _parse_cards(GUIDE_TEXT)
            if not _CARD_ID_PATTERN.match(card["id"])
        }
        assert non_conforming == _UNDERSCORE_ID_EXCEPTIONS

    def test_guide_declares_full_card_field_schema(self) -> None:
        """Section 8 still names all thirteen canonical card fields."""
        start = GUIDE_TEXT.index("**Card fields**")
        end = GUIDE_TEXT.index("### Session plugins", start)
        schema_block = GUIDE_TEXT[start:end]
        missing = [field for field in _SCHEMA_DECLARED_FIELDS if field not in schema_block]
        assert missing == []

    def test_duplicate_card_id_detected(self) -> None:
        """A synthetic duplicate card ID must be flagged."""
        synthetic = (
            "#### `make.dup`: One\n\n- **Purpose:** x\n\n#### `make.dup`: Two\n\n- **Purpose:** y\n"
        )
        violations = _card_completeness_violations(_parse_cards(synthetic))
        assert any("duplicate" in violation for violation in violations)

    def test_missing_required_field_detected(self) -> None:
        """A synthetic card missing a universal field must be flagged."""
        synthetic = "#### `make.broken`: Broken\n\n- **Purpose:** x\n"
        violations = _card_completeness_violations(_parse_cards(synthetic))
        assert violations


# ---------------------------------------------------------------------------
# 2. Thresholds and toggles
# ---------------------------------------------------------------------------


class TestThresholdsAndToggles:
    """gates.conf values must be documented verbatim in the guide."""

    def test_gates_conf_matches_guide_policy_table(self) -> None:
        """Every gates.conf key appears in the guide with the same value."""
        config = _parse_gates_conf(GATES_CONF.read_text(encoding="utf-8"))
        guide_values = _parse_guide_policy_table(GUIDE_TEXT)
        mismatches = [
            f"{key}: config={value} guide={guide_values.get(key)}"
            for key, value in config.items()
            if guide_values.get(key) != value
        ]
        assert mismatches == []

    def test_guide_mentions_suppression_reasons_toggle(self) -> None:
        """The guide must document the suppression-reasons toggle."""
        assert "CHECK_SUPPRESSION_REASONS" in GUIDE_TEXT

    def test_guide_documents_module_coverage_not_in_check(self) -> None:
        """The guide must state module-coverage is owned by test-coverage, not check."""
        assert "Per-module coverage ownership" in GUIDE_TEXT
        assert "not a `make check` member" in GUIDE_TEXT
        assert "must never consume a potentially stale `coverage.json`" in _normalise(GUIDE_TEXT)

    def test_undocumented_config_key_detected(self) -> None:
        """A config key absent from the guide table must be flagged."""
        config = "MAX_FLAGGED = 30\nCHECK_SUPPRESSION_REASONS = true\n"
        guide_table = (
            "## 5. Current Policy Values\n\n| Key | Value |\n|---|---|\n| `MAX_FLAGGED` | 30 |\n"
        )
        parsed = _parse_guide_policy_table(guide_table + "\n## 6. Phase Runbooks\n")
        missing = [key for key in _parse_gates_conf(config) if key not in parsed]
        assert missing == ["CHECK_SUPPRESSION_REASONS"]


# ---------------------------------------------------------------------------
# 3. Lefthook topology
# ---------------------------------------------------------------------------


class TestLefthookTopology:
    """The guide must document the exact Lefthook stage topology."""

    def test_precommit_topology(self) -> None:
        """Pre-commit is a piped five-stage pipeline with the documented modes."""
        data = _load_yaml(LEFTHOOK)
        assert _lefthook_violations(data) == []
        assert data["pre-commit"]["piped"] is True
        assert len(_lefthook_stage_names(data, "pre-commit")) == 5

    def test_prepush_topology(self) -> None:
        """Pre-push is piped with six stages and a single stdin consumer."""
        data = _load_yaml(LEFTHOOK)
        assert _lefthook_stage_names(data, "pre-push") == _PREPUSH_STAGES
        assert data["pre-push"]["piped"] is True
        assert _lefthook_stdin_consumers(data, "pre-push") == ["gitleaks-detect"]

    def test_guide_documents_hook_stage_ids(self) -> None:
        """Every hook stage ID appears in the guide's runbooks and cards."""
        missing = [
            f"hook.pre-commit.{stage}"
            for stage in _PRECOMMIT_STAGES
            if f"hook.pre-commit.{stage}" not in GUIDE_TEXT
        ]
        missing += [
            f"hook.pre-push.{stage}"
            for stage in _PREPUSH_STAGES
            if f"hook.pre-push.{stage}" not in GUIDE_TEXT
        ]
        assert missing == []

    def test_missing_stage_detected(self) -> None:
        """A synthetic Lefthook missing pytest-check must be flagged."""
        synthetic = _strict_yaml().load(
            "pre-commit:\n"
            "  piped: true\n"
            "  jobs:\n"
            "    - name: reject-partial-staging\n"
            "      run: echo hi\n"
            "pre-push:\n"
            "  piped: true\n"
            "  jobs:\n"
            "    - name: gitleaks-detect\n"
            "      run: gitleaks\n"
            "      use_stdin: true\n"
        )
        violations = _lefthook_violations(synthetic)
        assert violations


# ---------------------------------------------------------------------------
# 4. Make composites
# ---------------------------------------------------------------------------


class TestMakeComposites:
    """The guide must document exact Make composite prerequisite memberships."""

    def test_ratchets_membership(self) -> None:
        """Ratchets has six members: four ratchets and two hard gates."""
        expected = _makefile_prereqs("ratchets")
        assert expected == [
            "file-size",
            "suppression-ratchet",
            "suppression-reasons",
            "ruff-architecture",
            "typecheck-strict-ratchet",
            "semgrep-architecture",
        ]
        block = _guide_card_block("make.ratchets")
        assert "six members" in block
        assert all(member in block for member in expected)

    def test_test_coverage_membership(self) -> None:
        """test-coverage is test-coverage-report plus module-coverage."""
        expected = _makefile_prereqs("test-coverage")
        assert expected == ["test-coverage-report", "module-coverage"]
        block = _guide_card_block("make.test-coverage")
        assert all(member in block for member in expected)

    def test_ci_static_membership(self) -> None:
        """ci-static carries the full static-analysis lane."""
        expected = _makefile_prereqs("ci-static")
        assert expected == [
            "format-check",
            "lint",
            "typecheck-all",
            "bandit",
            "vulture",
            "complexity",
            "actionlint",
        ]
        block = _guide_card_block("make.ci-static")
        assert all(member in block for member in expected)

    def test_ci_quality_membership(self) -> None:
        """ci-quality carries the deterministic offline quality-gate inventory."""
        expected = _makefile_prereqs("ci-quality")
        assert expected == [
            "format-check",
            "lint",
            "typecheck-all",
            "bandit",
            "vulture",
            "complexity",
            "semgrep",
            "arch-check",
            "arch-check-dynamic",
            "import-linter",
            "coupling-check",
            "ratchets",
            "analyser-contract-tests",
            "deptry",
            "make-policy",
            "workflow-policy",
            "actionlint",
        ]
        block = _guide_card_block("make.ci-quality")
        assert all(member in block for member in expected)

    def test_ci_quality_inventory_matches_makefile_exactly(self) -> None:
        """The guide's documented ci-quality inventory equals the Makefile prereqs."""
        assert _guide_inventory_members("make.ci-quality") == _makefile_prereqs("ci-quality")

    def test_core_exclusion_manifest_is_literal_and_used(self) -> None:
        """The ordinary and coverage selectors exclude the manifest by exact path."""
        makefile = MAKEFILE.read_text(encoding="utf-8")
        assert "MUTATION_PROPERTY_FILES :=" in makefile
        manifest_start = makefile.index("MUTATION_PROPERTY_FILES :=")
        manifest_end = makefile.index("\n\n", manifest_start)
        manifest = makefile[manifest_start:manifest_end]
        kept = (
            "tests/test_property.py",
            "tests/test_property_policy.py",
            "tests/test_mutate_diff_files.py",
            "tests/test_mutation_policy.py",
        )
        deleted = (
            "tests/test_mutation_api_utils_mcp.py",
            "tests/test_mutation_final_api.py",
            "tests/test_mutation_final_rich_scraper.py",
            "tests/test_mutation_formatting.py",
            "tests/test_mutation_kill_api_threads.py",
            "tests/test_mutation_r3_api_rich.py",
            "tests/test_mutation_r3_runners.py",
            "tests/test_mutation_r3_threads_auth.py",
            "tests/test_mutation_runners_auth.py",
            "tests/test_mutation_threads_query.py",
            "tests/test_mutation_utils.py",
        )
        for path in kept:
            assert f"\t{path}" in manifest, f"manifest missing {path}"
        for path in deleted:
            assert f"\t{path}" not in manifest, f"manifest must not reference deleted {path}"
        assert "#" not in manifest.splitlines()[0]  # header comment precedes variable
        for target in ("\ntest:", "\ntest-coverage-report:"):
            start = makefile.index(target) + 1
            end = makefile.find("\n\n", start)
            recipe = makefile[start:end]
            assert "not integration" in recipe
            assert "$(addprefix --ignore=,$(MUTATION_PROPERTY_FILES))" in recipe
        assert "MUTATION_PROPERTY_FILES" in GUIDE_TEXT
        assert "never by glob" in GUIDE_TEXT

    def test_ci_trusted_membership(self) -> None:
        """ci-trusted is make ci plus fail-closed safety-gate."""
        expected = _makefile_prereqs("ci-trusted")
        assert expected == ["ci", "safety-gate"]
        block = _guide_card_block("make.ci-trusted")
        assert all(member in block for member in expected)

    def test_analyser_contract_tests_membership(self) -> None:
        """analyser-contract-tests depends on analyser-contract-validate."""
        expected = _makefile_prereqs("analyser-contract-tests")
        assert expected == ["analyser-contract-validate"]
        block = _guide_card_block("make.analyser-contract-tests")
        assert all(member in block for member in expected)

    def test_property_lane_membership(self) -> None:
        """Every property lane depends on test-property-policy and the Make source."""
        for target in ("test-property", "test-property-push", "test-property-ci"):
            assert _makefile_prereqs(target) == ["test-property-policy"]
        policy_block = _guide_card_block("make.test-property-policy")
        for lane in ("test-property", "test-property-push", "test-property-ci"):
            assert lane in policy_block
        assert "PROPERTY_TEST_FILES" in _guide_card_block("make.test-property")
        assert "override PROPERTY_TEST_FILES := tests/test_property.py" in MAKEFILE.read_text(
            encoding="utf-8"
        )

    def test_guide_states_check_is_static_only(self) -> None:
        """The guide must state make check is static-only without module-coverage."""
        block = _guide_card_block("make.check")
        assert "static" in _normalise(block)
        assert "module-coverage" not in _makefile_prereqs("check")
        assert "NOT a member" in block
        assert "not a `make check` member" in GUIDE_TEXT
        assert "must never consume a potentially stale `coverage.json`" in _normalise(GUIDE_TEXT)


# ---------------------------------------------------------------------------
# 5. Workflow inventory
# ---------------------------------------------------------------------------


class TestWorkflowInventory:
    """The guide must document every workflow file, job and policy condition."""

    def test_guide_documents_all_workflow_filenames(self) -> None:
        """All six workflow filenames appear in the guide."""
        missing = [name for name in _WORKFLOW_PREFIXES if name not in GUIDE_TEXT]
        assert missing == []

    def test_guide_documents_full_job_sets(self) -> None:
        """Every workflow job is documented by its stable card ID."""
        for filename, prefix in _WORKFLOW_PREFIXES.items():
            workflow = _load_yaml(WORKFLOWS / filename)
            stem = filename.removesuffix(".yml")
            for job_id in sorted(workflow["jobs"]):
                ref = f"{prefix}.{stem}.{job_id}"
                assert ref in GUIDE_TEXT, f"guide missing job reference {ref}"

    def test_guide_documents_safety_push_only(self) -> None:
        """Safety must be documented as push-only and the workflow must agree."""
        assert "push-only" in GUIDE_TEXT
        assert "on trusted pushes only" in GUIDE_TEXT
        ci = _load_yaml(WORKFLOWS / "ci.yml")
        safety_if = str(ci["jobs"]["safety"].get("if", ""))
        assert "github.event_name == 'push'" in safety_if

    def test_guide_documents_pr_only_jobs(self) -> None:
        """diff-coverage and mutation-diff are documented as PR-only."""
        assert "PR-only" in GUIDE_TEXT
        ci = _load_yaml(WORKFLOWS / "ci.yml")
        for job_id in ("diff-coverage", "mutation-diff"):
            condition = str(ci["jobs"][job_id].get("if", ""))
            assert "github.event_name == 'pull_request'" in condition

    def test_guide_documents_fuzz_blocking(self) -> None:
        """Fuzz status must be blocking, matching the workflow with no skip flag."""
        assert "BLOCKING" in GUIDE_TEXT
        assert "no `continue-on-error`" in _normalise(GUIDE_TEXT)
        ci = _load_yaml(WORKFLOWS / "ci.yml")
        assert "continue-on-error" not in ci["jobs"]["fuzz-status"]

    def test_guide_documents_hermetic_job(self) -> None:
        """The hermetic-integration CI job must be documented under the guard."""
        block = _guide_card_block("ci.ci.hermetic-integration")
        assert "make test-integration" in block
        assert "fail-closed network guard" in block
        assert "default-on" in _normalise(block)

    def test_guide_documents_windows_packaging_job(self) -> None:
        """The windows_packaging_smoke job must document the bounded commands."""
        block = _guide_card_block("ci.ci.windows_packaging_smoke")
        assert "windows-latest" in block
        assert "pxcli --version" in block
        assert "pxcli-mcp --help" in block
        assert "needs: [package]" in block or "needs" in block

    def test_guide_documents_repository_policy_job(self) -> None:
        """The repository-policy job must document the full ci-quality inventory."""
        block = _guide_card_block("ci.ci.repository-policy")
        normalised = _normalise(block)
        assert "make ci-quality" in block
        assert "uvx --from semgrep==1.171.0 semgrep --version" in normalised
        assert "uvx --from actionlint-py==1.7.12.24 actionlint --version" in normalised
        assert "warm" in normalised
        assert "no repository secrets" in block
        assert "30 min" in block

    def test_guide_documents_network_guard_default_on(self) -> None:
        """The fail-closed network guard must be documented as default-on."""
        assert "network guard" in GUIDE_TEXT
        assert "default-on" in _normalise(GUIDE_TEXT)
        assert "pytest_configure" in GUIDE_TEXT

    def test_missing_workflow_job_detected(self) -> None:
        """A workflow job absent from the guide must be flagged."""
        ci = _load_yaml(WORKFLOWS / "ci.yml")
        missing = [
            f"ci.ci.{job_id}"
            for job_id in sorted(ci["jobs"])
            if f"ci.ci.{job_id}" not in "ci.ci.static\nci.ci.test-coverage"
        ]
        assert missing


# ---------------------------------------------------------------------------
# 6. Plugins and npm separation
# ---------------------------------------------------------------------------


class TestPluginsAndNpm:
    """The guide must document the three plugin paths and check/audit split."""

    def test_guide_documents_three_plugin_paths(self) -> None:
        """All three registered plugin paths appear in the guide, and no others."""
        config_paths = _plugin_paths(OPCODE_CONFIG.read_text(encoding="utf-8"))
        assert len(config_paths) == 3
        missing = [path for path in config_paths if path not in GUIDE_TEXT]
        assert missing == []
        extra = _plugin_filenames(GUIDE_TEXT) - _plugin_filenames(
            OPCODE_CONFIG.read_text(encoding="utf-8")
        )
        assert extra == set()

    def test_guide_documents_check_and_audit_separation(self) -> None:
        """opencode-check and opencode-audit are documented as separate surfaces."""
        assert "opencode-check" in GUIDE_TEXT
        assert "opencode-audit" in GUIDE_TEXT
        assert "separately audits npm dependencies" in _normalise(GUIDE_TEXT)

    def test_extra_plugin_path_detected(self) -> None:
        """A synthetic guide referencing an extra plugin path must be flagged."""
        extra = 'const p = require(".opencode/plugins/phantom.ts");'
        assert ".opencode/plugins/phantom.ts" in _plugin_paths(extra)


# ---------------------------------------------------------------------------
# 7. Property profiles and mutation paths
# ---------------------------------------------------------------------------


class TestPropertyProfilesAndMutation:
    """Hypothesis profiles and mutation evidence paths must match sources."""

    def test_guide_profiles_match_conftest(self) -> None:
        """Guide profile table matches conftest.py for all four profiles."""
        expected = {
            name: (examples, f"{deadline} ms")
            for name, (examples, deadline) in _conftest_profiles(
                CONFTEST.read_text(encoding="utf-8")
            ).items()
        }
        actual = _guide_profiles(GUIDE_TEXT)
        assert expected == actual

    def test_guide_ci_profile_placement_python_313(self) -> None:
        """The ci profile is documented as Python 3.13 only in CI."""
        assert "property lane does not run on 3.12/3.14/macOS" in _normalise(GUIDE_TEXT)

    def test_guide_references_live_mutation_report(self) -> None:
        """The guide references the build/reports mutation report and live schema."""
        assert "build/reports/mutation-report.json" in GUIDE_TEXT
        assert "quality/schemas/mutation-report.json" in GUIDE_TEXT
        assert "the only live mutation schema" in _normalise(GUIDE_TEXT)

    def test_guide_omits_obsolete_mutation_paths(self) -> None:
        """No obsolete mutation paths are referenced as live policy."""
        for stale in (
            "quality/evidence/mutation-report.json",
            "mutation-report-v1.json",
            "mutation-waivers.toml",
        ):
            assert stale not in GUIDE_TEXT, f"obsolete path present: {stale}"

    def test_profile_mismatch_detected(self) -> None:
        """A profile value that drifts from conftest must be flagged."""
        conftest = _conftest_profiles(CONFTEST.read_text(encoding="utf-8"))
        guide = _guide_profiles(GUIDE_TEXT)
        mismatches = [
            name
            for name in conftest
            if guide.get(name) != (conftest[name][0], f"{conftest[name][1]} ms")
        ]
        assert mismatches == []


# ---------------------------------------------------------------------------
# 8. Stale phrase absence
# ---------------------------------------------------------------------------


class TestStalePhraseAbsence:
    """Literals from superseded guide revisions must be absent."""

    def test_stale_literals_absent(self) -> None:
        """Each known stale phrase must not appear in the guide."""
        present = [phrase for phrase in _STALE_PHRASES if phrase in GUIDE_TEXT]
        assert present == []

    def test_removed_schema_and_policy_engine_absent(self) -> None:
        """The deleted diff-coverage schema and coverage_policy engine are gone."""
        assert "quality/schemas/diff-coverage-v1.json" not in GUIDE_TEXT
        assert "coverage_policy.py" not in GUIDE_TEXT
        assert "scripts/coverage_policy" not in GUIDE_TEXT

    def test_continue_on_error_only_negated(self) -> None:
        """Every continue-on-error mention must be inside a negation."""
        normalised = _normalise(GUIDE_TEXT)
        occurrences = normalised.count("continue-on-error")
        negated = normalised.count("no `continue-on-error`")
        assert occurrences == negated

    def test_no_deadline_none_rows(self) -> None:
        """No profile row may carry a 'none' deadline."""
        for _, deadline in _guide_profiles(GUIDE_TEXT).values():
            assert deadline != "none"
        assert 'there is no "no deadline" profile' in GUIDE_TEXT


# ---------------------------------------------------------------------------
# 9. Inline surfaces
# ---------------------------------------------------------------------------


class TestInlineSurfaces:
    """The guide must document inline guards, fixers and boundary validations."""

    def test_inline_surfaces_documented(self) -> None:
        """All eight inline surfaces are covered by the guide."""
        assertions = [
            "Partial-staging guard" in GUIDE_TEXT,
            "block newly added `.env` files" in GUIDE_TEXT,
            "pre-commit-hooks" in GUIDE_TEXT,
            "make -n safety-gate | bash -n" in GUIDE_TEXT,
            "bash -n" in GUIDE_TEXT,
            "tests/test_workflow_configuration.py" in GUIDE_TEXT,
            "installs gitleaks 8.30.1" in GUIDE_TEXT,
            "version-agreement" in GUIDE_TEXT,
        ]
        assert all(assertions), [
            label
            for label, ok in zip(
                [
                    "partial-staging guard",
                    ".env block",
                    "pre-commit-hooks fixers",
                    "Make recipe shell-syntax",
                    "shell syntax",
                    "workflow-policy test",
                    "CI gitleaks install",
                    "publish version agreement",
                ],
                assertions,
                strict=True,
            )
            if not ok
        ]
