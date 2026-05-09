"""Tests for the skill display command runner."""

from unittest.mock import patch

from perplexity_cli.runners.skill import run_show_skill_command


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
