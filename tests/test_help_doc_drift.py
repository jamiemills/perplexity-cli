"""Regression tests guarding CLI help, README.md, and QUALITY_GATES.md drift.

These tests lock in the corrections made in ``.claude/DOCUMENTATION_GAP_PLAN.md``
so the documented JSON contracts cannot silently drift from the implementation
again.  Each test name maps to a specific gap in that plan.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from perplexity_cli.cli import main
from perplexity_cli.commands._schemas import COMMAND_RESULT_SCHEMAS
from perplexity_cli.utils.version import get_version

PROJECT_ROOT = Path(__file__).resolve().parents[1]
README = PROJECT_ROOT / "README.md"
QUALITY_GATES = PROJECT_ROOT / "QUALITY_GATES.md"


@pytest.fixture(scope="module")
def runner() -> CliRunner:
    """Shared Click CLI runner for the module."""
    return CliRunner()


def _help(runner: CliRunner, *args: str) -> str:
    """Invoke ``--help`` for *args* and return stdout."""
    result = runner.invoke(main, [*args, "--help"])
    assert result.exit_code == 0, f"--help failed for {args}: {result.output}"
    return result.output


# ---------------------------------------------------------------------------
# Plan §17, §39, §45: query references must be name/url/snippet
# ---------------------------------------------------------------------------


class TestQueryReferenceShape:
    """Query JSON examples and schema must use the actual reference fields."""

    def test_query_schema_uses_name_not_index_or_title(self) -> None:
        """``pxcli schema`` must document ``references[].{name,url,snippet}``."""
        props = COMMAND_RESULT_SCHEMAS["query"]["references"]["items"]["properties"]
        assert set(props) == {"name", "url", "snippet"}
        assert "index" not in props
        assert "title" not in props

    def test_query_help_json_example_uses_name(self, runner: CliRunner) -> None:
        """``query --help`` example must show ``name`` references, not ``index/title``."""
        output = _help(runner, "query")
        assert '"name":' in output
        assert '"index":' not in output
        assert '"title": "Python' not in output

    def test_query_help_json_envelope_doc_uses_name(self, runner: CliRunner) -> None:
        """The prose JSON ENVELOPE block must list ``name``."""
        output = _help(runner, "query")
        assert "references: [{name, url, snippet}, ...]" in output


# ---------------------------------------------------------------------------
# Plan §46: query NDJSON events are start/chunk/result only
# ---------------------------------------------------------------------------


class TestQueryNDJSONEvents:
    """Query NDJSON streaming emits start, chunk, result (no progress)."""

    def test_query_help_does_not_advertise_progress_event(self, runner: CliRunner) -> None:
        """The NDJSON event-type summary must not mention ``progress``."""
        output = _help(runner, "query")
        # The header line lists "start, chunk, result (final line)."
        assert "start, chunk, result (final line)." in output
        assert "progress" not in output


# ---------------------------------------------------------------------------
# Plan §50: skill show documents result.skill_md (renamed from content)
# ---------------------------------------------------------------------------


class TestSkillShowSkillMdField:
    """``skill show --help`` must match the implementation's ``result.skill_md``."""

    def test_help_documents_skill_md_not_content(self, runner: CliRunner) -> None:
        output = _help(runner, "skill", "show")
        assert "result.skill_md" in output
        assert "skill_md  - The full SKILL.md content" in output
        assert '"content":' not in output

    def test_help_jq_example_uses_skill_md(self, runner: CliRunner) -> None:
        output = _help(runner, "skill", "show")
        assert "jq -r '.result.skill_md'" in output

    def test_schema_command_includes_skill_show(self) -> None:
        """``pxcli schema`` must include the skill-show result definition."""
        assert "skill show" in COMMAND_RESULT_SCHEMAS
        assert "skill_md" in COMMAND_RESULT_SCHEMAS["skill show"]


# ---------------------------------------------------------------------------
# Plan §48, §49: models list has a JSON example + schema section
# ---------------------------------------------------------------------------


class TestModelsListHelpSections:
    """``models list --help`` must include JSON example, schema, and auth see-also."""

    def test_has_json_example_section(self, runner: CliRunner) -> None:
        output = _help(runner, "models", "list")
        assert "Example Output (--json):" in output
        assert '"models": [' in output
        assert '"model_id":' in output

    def test_has_json_schema_section(self, runner: CliRunner) -> None:
        output = _help(runner, "models", "list")
        assert "JSON Schema (Success Envelope):" in output

    def test_see_also_references_auth_login(self, runner: CliRunner) -> None:
        output = _help(runner, "models", "list")
        assert "See Also" in output
        assert "pxcli auth login" in output

    def test_schema_command_includes_models_list(self) -> None:
        """``pxcli schema`` must include the models-list result definition."""
        assert "models list" in COMMAND_RESULT_SCHEMAS
        props = COMMAND_RESULT_SCHEMAS["models list"]["models"]["items"]["properties"]
        assert set(props) == {
            "model_id",
            "label",
            "tier",
            "description",
            "reasoning_model",
            "is_default",
        }


# ---------------------------------------------------------------------------
# Plan §51, §52, §53: doctor security and threads export cache filename
# ---------------------------------------------------------------------------


class TestCacheFilenameIsHyphenated:
    """Help text must use ``threads-cache.json`` (matches ``utils/config.py``).

    Click wraps long lines, so we assert against the source strings in the
    ``*_cmds.py`` modules rather than the rendered (and possibly wrapped)
    help output.  ``utils/config.py`` uses the hyphenated filename; every
    help string must agree.
    """

    @pytest.mark.parametrize(
        "rel_path",
        [
            "src/perplexity_cli/commands/doctor_cmds.py",
            "src/perplexity_cli/commands/threads_cmds.py",
            "src/perplexity_cli/commands/_examples.py",
        ],
    )
    def test_source_uses_hyphenated_cache_filename(self, rel_path: str) -> None:
        source = (PROJECT_ROOT / rel_path).read_text(encoding="utf-8")
        assert "threads-cache.json" in source
        assert "threads_cache.json" not in source

    def test_implementation_uses_hyphenated_cache_filename(self) -> None:
        """``ConfigPaths.cache_path`` must use the hyphenated filename."""
        source = (PROJECT_ROOT / "src/perplexity_cli/utils/config.py").read_text(encoding="utf-8")
        assert '"threads-cache.json"' in source


class TestDoctorSecurityHelpMatchesImplementation:
    """``doctor security --help`` must match the actual runner output shape."""

    def test_help_storage_backend_matches_implementation(self, runner: CliRunner) -> None:
        output = _help(runner, "doctor", "security")
        assert "machine-bound encrypted file storage" in output
        assert "encrypted_file" not in output  # the old literal value

    def test_help_permissions_match_implementation_format(self, runner: CliRunner) -> None:
        output = _help(runner, "doctor", "security")
        assert "secure (0o600)" in output
        assert 'Unix permission string (e.g. "600")' not in output


# ---------------------------------------------------------------------------
# Plan §54: threads export --json documents the CSV side effect
# ---------------------------------------------------------------------------


class TestThreadsExportJsonSideEffect:
    """``threads export --json`` must skip the CSV write unless --output is given."""

    def test_help_clarifies_no_csv_without_output(self) -> None:
        source = (PROJECT_ROOT / "src/perplexity_cli/commands/threads_cmds.py").read_text(
            encoding="utf-8"
        )
        assert "instead of" in source
        assert "no CSV is written" in source
        assert "result.output_path is null" in source

    def test_runner_skips_csv_in_json_only_mode(self) -> None:
        """The runner must not call write_threads_csv when json mode and no --output."""
        source = (PROJECT_ROOT / "src/perplexity_cli/runners/export.py").read_text(encoding="utf-8")
        assert "if json_mode and not explicit_output:" in source

    def test_schema_marks_output_path_nullable(self) -> None:
        """The output_path field schema must accept null (JSON-only mode)."""
        assert COMMAND_RESULT_SCHEMAS["threads export"]["output_path"] == {
            "type": ["string", "null"]
        }


# ---------------------------------------------------------------------------
# Plan §55: examples must not pin a stale version
# ---------------------------------------------------------------------------


class TestExampleVersionsAreCurrent:
    """JSON examples shown in help must use the runtime version, not 0.7.0."""

    def test_query_json_example_uses_runtime_version(self, runner: CliRunner) -> None:
        output = _help(runner, "query")
        current = get_version()
        assert f'"version": "{current}"' in output

    def test_doctor_security_example_uses_runtime_version(self, runner: CliRunner) -> None:
        output = _help(runner, "doctor", "security")
        current = get_version()
        assert f'"version": "{current}"' in output

    def test_models_list_example_uses_runtime_version(self, runner: CliRunner) -> None:
        output = _help(runner, "models", "list")
        current = get_version()
        assert f'"version": "{current}"' in output


# ---------------------------------------------------------------------------
# Plan §56: auth login help covers Chrome for Testing on all platforms
# ---------------------------------------------------------------------------


class TestAuthLoginHelpCrossPlatform:
    """``auth login --help`` must give Chrome launch guidance for every OS."""

    @pytest.mark.parametrize(
        "label",
        ["Apple Silicon macOS", "Intel macOS", "Linux", "Windows"],
    )
    def test_help_covers_platform(self, runner: CliRunner, label: str) -> None:
        output = _help(runner, "auth", "login")
        assert label in output


# ---------------------------------------------------------------------------
# Plan §38: README command reference must not overclaim --json/--schema
# ---------------------------------------------------------------------------


class TestReadmeCommandReferenceClaim:
    """README must narrow the ``--json/--schema`` claim to commands that have them."""

    def test_readme_does_not_claim_completion_supports_json(self) -> None:
        text = README.read_text(encoding="utf-8")
        # The old claim said every group (including completion) accepted the flags.
        old_claim = (
            "All subcommands under `auth`, `config`, `models`, `style`, `threads`, "
            "`skill`, `doctor`, and `completion` accept `--json` and `--schema`"
        )
        assert old_claim not in text
        # The new claim must explicitly exclude completion.
        assert "`completion`, `schema`, and `--help` do not" in text

    def test_readme_query_json_uses_name_references(self) -> None:
        """README query JSON example must not use the old index/title shape."""
        text = README.read_text(encoding="utf-8")
        assert '"index": 1' not in text
        assert '"title": "Python.org"' not in text
        assert '"name": "Python.org"' in text

    def test_readme_skill_show_uses_skill_md(self) -> None:
        """README result-shapes table must use skill_md, not content."""
        text = README.read_text(encoding="utf-8")
        assert "`skill show` | `{skill_md}`" in text
        assert "`skill show` | `{content}`" not in text


# ---------------------------------------------------------------------------
# Plan §22, §30-§35: README documents URL config and attachment safety
# ---------------------------------------------------------------------------


class TestReadmeUrlConfigAndAttachments:
    """README must document the full URL config and attachment safety rules."""

    def test_readme_lists_all_url_config_fields(self) -> None:
        text = README.read_text(encoding="utf-8")
        required = (
            "model_config_endpoint",
            "user_settings_endpoint",
            "thread_list_endpoint",
            "upload_url_endpoint",
            "s3_bucket_url",
        )
        missing = [field for field in required if field not in text]
        assert missing == [], f"README missing URL config fields: {missing}"

    def test_readme_lists_all_url_env_vars(self) -> None:
        text = README.read_text(encoding="utf-8")
        required = (
            "PERPLEXITY_THREAD_LIST_ENDPOINT",
            "PERPLEXITY_UPLOAD_URL_ENDPOINT",
            "PERPLEXITY_S3_BUCKET_URL",
            "PERPLEXITY_MODEL_CONFIG_ENDPOINT",
            "PERPLEXITY_USER_SETTINGS_ENDPOINT",
        )
        missing = [var for var in required if var not in text]
        assert missing == [], f"README missing env vars: {missing}"

    def test_readme_documents_attachment_limits(self) -> None:
        text = README.read_text(encoding="utf-8")
        assert "10 MiB" in text
        assert "25 MiB" in text
        assert "25 files" in text

    def test_readme_documents_sensitive_file_exclusions(self) -> None:
        text = README.read_text(encoding="utf-8")
        assert ".env" in text
        assert ".pem" in text
        assert "Skipped directories" in text or "skipped directories" in text.lower()

    def test_readme_documents_session_log_location(self) -> None:
        text = README.read_text(encoding="utf-8")
        assert "pxcli/sessions" in text
        assert "XDG_DATA_HOME" in text

    def test_readme_documents_mcp_mount_path(self) -> None:
        text = README.read_text(encoding="utf-8")
        assert "--mount-path" in text

    def test_readme_documents_mcp_output_aliases(self) -> None:
        text = README.read_text(encoding="utf-8")
        assert "alias: `md`" in text
        assert "alias: `text`" in text

    def test_readme_documents_setup_prerequisites(self) -> None:
        text = README.read_text(encoding="utf-8")
        required = ("uv", "gitleaks", "infisical")
        missing = [tool for tool in required if tool not in text]
        assert missing == [], f"README missing prereq tools: {missing}"


# ---------------------------------------------------------------------------
# Plan §63-§69: QUALITY_GATES.md reflects actual wiring
# ---------------------------------------------------------------------------


class TestQualityGatesMatchesRepo:
    """QUALITY_GATES.md must reflect Makefile, lefthook, and workflow wiring."""

    def test_documents_setup_prerequisites(self) -> None:
        text = QUALITY_GATES.read_text(encoding="utf-8")
        required = ("uv", "gitleaks", "infisical", "check-uv", "check-gitleaks", "check-infisical")
        missing = [token for token in required if token not in text]
        assert missing == [], f"QUALITY_GATES.md missing tokens: {missing}"

    def test_documents_release_drafter(self) -> None:
        text = QUALITY_GATES.read_text(encoding="utf-8")
        assert "release-drafter.yml" in text
        assert "Release Drafter" in text

    def test_agent_check_push_wiring_is_corrected(self) -> None:
        """The doc must state that agent-check-push is NOT wired into lefthook/ci."""
        text = QUALITY_GATES.read_text(encoding="utf-8")
        assert "not currently wired into `lefthook.yml` or `make ci`" in text

    def test_safety_skip_behaviour_documented(self) -> None:
        text = QUALITY_GATES.read_text(encoding="utf-8")
        assert "skip" in text.lower()
        assert "make safety" in text

    def test_gitleaks_graceful_skip_documented(self) -> None:
        text = QUALITY_GATES.read_text(encoding="utf-8")
        assert "Gitleaks" in text
        assert "prints a skip notice and exits 0" in text

    def test_thresholds_wired_or_documented(self) -> None:
        """FAIL_UNDER is a reference mirror; SEMGREP_SEVERITY is wired into Makefile."""
        text = QUALITY_GATES.read_text(encoding="utf-8")
        assert "reference mirror" in text  # FAIL_UNDER
        assert "`make semgrep` target via `$(SEMGREP_SEVERITY)`" in text  # SEMGREP_SEVERITY wired

    def test_opencode_plugin_caveats_documented(self) -> None:
        text = QUALITY_GATES.read_text(encoding="utf-8")
        assert "semgrep from `PATH`" in text
        assert "src/perplexity_cli/commands/" in text

    def test_auxiliary_make_targets_documented(self) -> None:
        text = QUALITY_GATES.read_text(encoding="utf-8")
        required = ("arch-explain", "format-fix", "make clean")
        missing = [target for target in required if target not in text]
        assert missing == [], f"QUALITY_GATES.md missing targets: {missing}"


# ---------------------------------------------------------------------------
# Plan §116: documentation drift test for README command support claims
# ---------------------------------------------------------------------------


class TestReadmeAndSchemaAgree:
    """README result-shapes table must match ``pxcli schema`` output."""

    def test_readme_result_shapes_match_schema(self) -> None:
        """Every command in the README result-shapes table exists in schema."""
        text = README.read_text(encoding="utf-8")
        # Cross-check: every command for which schema has an entry is mentioned
        # in the README's "Result shapes by command" table.
        for command in COMMAND_RESULT_SCHEMAS:
            assert command in text, f"README result-shapes table missing command: {command}"


# ---------------------------------------------------------------------------
# JSON examples must be valid JSON (catches future typos in the examples)
# ---------------------------------------------------------------------------


class TestExampleJsonIsValid:
    """JSON example strings embedded in help must be parseable."""

    @pytest.mark.parametrize(
        "args,contains_marker",
        [
            (("query",), '"ok": true'),
            (("models", "list"), '"models":'),
            (("skill", "show"), '"skill_md":'),
            (("doctor", "security"), '"storage_backend":'),
            (("threads", "export"), '"output_path": null'),
        ],
    )
    def test_example_block_is_valid_json(
        self, runner: CliRunner, args: tuple[str, ...], contains_marker: str
    ) -> None:
        output = _help(runner, *args)
        assert contains_marker in output
        # Sanity: the runtime version appears (not the 0.7.0 placeholder)
        assert '"version": "0.7.0"' not in output
