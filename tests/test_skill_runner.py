"""Tests for the skill display command runner."""

import json
from unittest.mock import patch

from perplexity_cli.runners.skill import (
    _load_skill_content,
    _resolve_ctx_flags,
    run_show_skill_command,
)


class TestRunShowSkillCommand:
    """Tests for run_show_skill_command()."""

    def test_echoes_skill_content_when_file_exists(self, capsys):
        """Test that skill.md content is echoed when the resource exists."""
        mock_path = patch(
            "perplexity_cli.runners.skill.files",
        )
        with mock_path as mock_files:
            mock_files.return_value.joinpath.return_value.read_text.return_value = (
                "# My Skill\nSome content"
            )

            run_show_skill_command()

        captured = capsys.readouterr()
        assert captured.out.strip() == "# My Skill\nSome content"

    def test_echoes_fallback_on_file_not_found(self, capsys):
        """Test that a fallback message is echoed when FileNotFoundError is raised."""
        with patch("perplexity_cli.runners.skill.files") as mock_files:
            mock_files.return_value.joinpath.return_value.read_text.side_effect = (
                FileNotFoundError()
            )

            run_show_skill_command()

        captured = capsys.readouterr()
        assert "Agent Skill definition not available" in captured.out

    def test_echoes_fallback_on_attribute_error(self, capsys):
        """Test that a fallback message is echoed when AttributeError is raised."""
        with patch("perplexity_cli.runners.skill.files") as mock_files:
            mock_files.return_value.joinpath.return_value.read_text.side_effect = AttributeError()

            run_show_skill_command()

        captured = capsys.readouterr()
        assert "Agent Skill definition not available" in captured.out
        assert "perplexity-cli --help" in captured.out


class TestSkillMdContent:
    """Tests that verify skill.md content reflects v0.7.0 changes."""

    @staticmethod
    def _read_skill_md() -> str:
        """Read the actual skill.md resource file."""
        from importlib.resources import files

        return files("perplexity_cli").joinpath("resources", "skill.md").read_text(encoding="utf-8")

    def test_references_new_command_names(self):
        """skill.md must reference the v0.7.0 command names."""
        content = self._read_skill_md()
        for cmd in [
            "pxcli auth login",
            "pxcli auth logout",
            "pxcli auth status",
            "pxcli config set",
            "pxcli config show",
            "pxcli style set",
            "pxcli style show",
            "pxcli style clear",
            "pxcli threads export",
            "pxcli skill show",
        ]:
            assert cmd in content, f"Expected command '{cmd}' not found in skill.md"

    def test_references_envelope_format(self):
        """skill.md must reference the new JSON envelope fields."""
        content = self._read_skill_md()
        for field in [".ok", ".result", ".meta"]:
            assert field in content, f"Expected field '{field}' not found in skill.md"
        # Must not contain old format_version
        assert "format_version" not in content, (
            "skill.md still references removed format_version field"
        )

    def test_references_exit_codes(self):
        """skill.md must document exit codes."""
        content = self._read_skill_md()
        for code_desc in [
            "Authentication required",
            "Transient error",
            "Validation error",
        ]:
            assert code_desc in content, (
                f"Expected exit code description '{code_desc}' not found in skill.md"
            )


class TestSkillRunnerMutationKillers:
    """Mutation-killing tests for skill runner edge cases."""

    def test_load_skill_content_fallback_exact_string(self):
        with patch("perplexity_cli.runners.skill.files") as mock_files:
            mock_files.return_value.joinpath.return_value.read_text.side_effect = (
                FileNotFoundError()
            )
            result = _load_skill_content()

        assert result == (
            "Agent Skill definition not available. "
            "Run 'perplexity-cli --help' for usage information."
        )

    def test_load_skill_content_returns_file_content(self):
        with patch("perplexity_cli.runners.skill.files") as mock_files:
            mock_files.return_value.joinpath.return_value.read_text.return_value = "# Skill"
            result = _load_skill_content()

        assert result == "# Skill"

    def test_resolve_ctx_flags_json_mode_true(self):
        with patch("perplexity_cli.runners.skill.click.get_current_context", return_value=None):
            output_format, include_schema = _resolve_ctx_flags(json_mode=True)

        assert output_format == "json"
        assert include_schema == "no_schema"

    def test_resolve_ctx_flags_json_mode_false(self):
        with patch("perplexity_cli.runners.skill.click.get_current_context", return_value=None):
            output_format, include_schema = _resolve_ctx_flags(json_mode=False)

        assert output_format == "human"
        assert include_schema == "no_schema"

    def test_resolve_ctx_flags_json_mode_none_no_ctx(self):
        with patch("perplexity_cli.runners.skill.click.get_current_context", return_value=None):
            output_format, include_schema = _resolve_ctx_flags(json_mode=None)

        assert output_format == "human"
        assert include_schema == "no_schema"

    def test_resolve_ctx_flags_schema_from_ctx(self):
        from unittest.mock import Mock

        mock_ctx = Mock()
        mock_ctx.obj = {"json": False, "schema": True}
        with patch("perplexity_cli.runners.skill.click.get_current_context", return_value=mock_ctx):
            output_format, include_schema = _resolve_ctx_flags(json_mode=None)

        assert output_format == "human"
        assert include_schema == "with_schema"

    def test_run_show_skill_json_output(self, capsys):
        with patch("perplexity_cli.runners.skill.files") as mock_files:
            mock_files.return_value.joinpath.return_value.read_text.return_value = "# Skill MD"
            run_show_skill_command(json_mode=True)

        envelope = json.loads(capsys.readouterr().out.strip())
        assert envelope["ok"] is True
        assert envelope["command"] == "pxcli skill show"
        assert envelope["result"]["skill_md"] == "# Skill MD"

    def test_run_show_skill_human_output_exact(self, capsys):
        with patch("perplexity_cli.runners.skill.files") as mock_files:
            mock_files.return_value.joinpath.return_value.read_text.return_value = "exact content"
            run_show_skill_command(json_mode=False)

        assert capsys.readouterr().out == "exact content\n"
