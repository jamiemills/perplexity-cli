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
