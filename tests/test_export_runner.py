"""Tests for the export threads command runner."""

import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from perplexity_cli.runners.export import run_export_threads_command


class TestRunExportThreadsCommand:
    """Tests for run_export_threads_command()."""

    @patch("perplexity_cli.auth.token_manager.TokenManager")
    def test_not_authenticated_human(self, mock_tm_class, capsys):
        """Human output shows not authenticated error."""
        mock_tm = Mock()
        mock_tm.load_token.return_value = (None, None)
        mock_tm_class.return_value = mock_tm

        with pytest.raises(SystemExit) as exc_info:
            run_export_threads_command(
                ctx_obj={},
                from_date=None,
                to_date=None,
                output=None,
                force_refresh=False,
                clear_cache=False,
            )

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Not authenticated" in captured.err

    @patch("perplexity_cli.auth.token_manager.TokenManager")
    def test_not_authenticated_json(self, mock_tm_class, capsys):
        """JSON output shows error envelope when not authenticated."""
        mock_tm = Mock()
        mock_tm.load_token.return_value = (None, None)
        mock_tm_class.return_value = mock_tm

        with pytest.raises(SystemExit):
            run_export_threads_command(
                ctx_obj={"json": True},
                from_date=None,
                to_date=None,
                output=None,
                force_refresh=False,
                clear_cache=False,
            )

        envelope = json.loads(capsys.readouterr().out.strip())
        assert envelope["ok"] is False
        assert envelope["command"] == "pxcli threads export"

    @patch("perplexity_cli.threads.exporter.write_threads_csv")
    @patch("perplexity_cli.runners.export.run_async")
    @patch("perplexity_cli.utils.config.get_rate_limiting_config")
    @patch("perplexity_cli.threads.cache_manager.ThreadCacheManager")
    @patch("perplexity_cli.threads.scraper.ThreadScraper")
    @patch("perplexity_cli.auth.token_manager.TokenManager")
    def test_success_human(
        self,
        mock_tm_class,
        mock_scraper_class,
        mock_cm_class,
        mock_rate_config,
        mock_run_async,
        mock_write_csv,
        capsys,
    ):
        """Human output shows export complete."""
        mock_tm = Mock()
        mock_tm.load_token.return_value = ("token", {})
        mock_tm_class.return_value = mock_tm

        mock_rate_config.return_value = Mock(enabled=False)
        mock_run_async.return_value = [
            {"title": "Thread 1", "created_at": "2025-01-01", "url": "https://perplexity.ai/t/1"}
        ]
        mock_write_csv.return_value = Path("/tmp/threads.csv")

        run_export_threads_command(
            ctx_obj={},
            from_date=None,
            to_date=None,
            output=None,
            force_refresh=False,
            clear_cache=False,
        )

        captured = capsys.readouterr()
        assert "Export complete" in captured.out

    @patch("perplexity_cli.threads.exporter.write_threads_csv")
    @patch("perplexity_cli.runners.export.run_async")
    @patch("perplexity_cli.utils.config.get_rate_limiting_config")
    @patch("perplexity_cli.threads.cache_manager.ThreadCacheManager")
    @patch("perplexity_cli.threads.scraper.ThreadScraper")
    @patch("perplexity_cli.auth.token_manager.TokenManager")
    def test_success_json(
        self,
        mock_tm_class,
        mock_scraper_class,
        mock_cm_class,
        mock_rate_config,
        mock_run_async,
        mock_write_csv,
        capsys,
    ):
        """JSON output shows success envelope with thread data."""
        mock_tm = Mock()
        mock_tm.load_token.return_value = ("token", {})
        mock_tm_class.return_value = mock_tm

        mock_rate_config.return_value = Mock(enabled=False)
        mock_run_async.return_value = [
            {"title": "Thread 1", "created_at": "2025-01-01", "url": "https://perplexity.ai/t/1"}
        ]
        mock_write_csv.return_value = Path("/tmp/threads.csv")

        run_export_threads_command(
            ctx_obj={"json": True},
            from_date=None,
            to_date=None,
            output=None,
            force_refresh=False,
            clear_cache=False,
        )

        envelope = json.loads(capsys.readouterr().out.strip())
        assert envelope["ok"] is True
        assert envelope["command"] == "pxcli threads export"
        assert envelope["result"]["total"] == 1
        assert len(envelope["result"]["threads"]) == 1
