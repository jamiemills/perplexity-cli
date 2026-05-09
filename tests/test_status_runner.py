"""Tests for the status command runner."""

from unittest.mock import Mock, patch

from perplexity_cli.runners.status import run_status_command


class TestRunStatusCommand:
    """Tests for run_status_command()."""

    @patch("perplexity_cli.auth.token_manager.TokenManager")
    def test_not_authenticated_human(self, mock_tm_class, capsys):
        """Human output shows not authenticated."""
        mock_tm = Mock()
        mock_tm.token_exists.return_value = False
        mock_tm_class.return_value = mock_tm

        run_status_command(verify=False)

        captured = capsys.readouterr()
        assert "Not authenticated" in captured.out

    @patch("perplexity_cli.auth.token_manager.TokenManager")
    def test_authenticated_human(self, mock_tm_class, capsys):
        """Human output shows authenticated status."""
        mock_tm = Mock()
        mock_tm.token_exists.return_value = True
        mock_tm.load_token.return_value = ("token-abc", {"cf": "val"})
        mock_token_path = Mock()
        mock_token_path.__str__ = Mock(return_value="/tmp/token.json")
        mock_token_path.stat.return_value = Mock(st_mtime=1700000000.0)
        mock_tm.token_path = mock_token_path
        mock_tm_class.return_value = mock_tm

        run_status_command(verify=False)

        captured = capsys.readouterr()
        assert "Authenticated" in captured.out

    @patch("perplexity_cli.auth.token_manager.TokenManager")
    def test_not_authenticated_json(self, mock_tm_class, capsys):
        """JSON output shows authenticated=False."""
        import json

        mock_tm = Mock()
        mock_tm.token_exists.return_value = False
        mock_tm.token_path = Mock(__str__=Mock(return_value="/tmp/token.json"))
        mock_tm_class.return_value = mock_tm

        run_status_command(verify=False, json_mode=True)

        envelope = json.loads(capsys.readouterr().out.strip())
        assert envelope["ok"] is True
        assert envelope["result"]["authenticated"] is False

    @patch("perplexity_cli.auth.token_manager.TokenManager")
    def test_authenticated_json(self, mock_tm_class, capsys):
        """JSON output shows authenticated=True with details."""
        import json

        mock_tm = Mock()
        mock_tm.token_exists.return_value = True
        mock_tm.load_token.return_value = ("token-abc", {"cf": "val"})
        mock_token_path = Mock()
        mock_token_path.__str__ = Mock(return_value="/tmp/token.json")
        mock_token_path.stat.return_value = Mock(st_mtime=1700000000.0)
        mock_tm.token_path = mock_token_path
        mock_tm_class.return_value = mock_tm

        run_status_command(verify=False, json_mode=True)

        envelope = json.loads(capsys.readouterr().out.strip())
        assert envelope["ok"] is True
        assert envelope["result"]["authenticated"] is True
        assert envelope["result"]["token_path"] == "/tmp/token.json"
        assert envelope["result"]["cookies_stored"] == 1
