"""Direct tests for command runner orchestration helpers."""

import logging
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from perplexity_cli.command_runner import (
    run_auth_command,
    run_export_threads_command,
    run_logout_command,
    run_set_config_command,
    run_show_config_command,
)
from perplexity_cli.config.models import FeatureConfig, RateLimitConfig
from perplexity_cli.utils.exceptions import AuthenticationError, ConfigurationError


def test_run_auth_command_saves_token_and_cookies(capsys):
    """Auth runner saves the returned token and reports success."""
    mock_tm = Mock()
    mock_tm.token_path = Path("/tmp/token.json")

    with (
        patch("perplexity_cli.runners.auth.authenticate_sync") as mock_auth,
        patch("perplexity_cli.runners.auth.TokenManager", return_value=mock_tm),
        patch(
            "perplexity_cli.runners.auth.get_perplexity_base_url",
            return_value="https://www.perplexity.ai",
        ),
        patch("perplexity_cli.runners.auth.get_save_cookies_enabled", return_value=True),
    ):
        mock_auth.return_value = ("token-123", {"cf_clearance": "cookie-1"})

        run_auth_command(ctx_obj=None, port=9222)

    captured = capsys.readouterr()
    assert "[OK] Authentication successful!" in captured.out
    assert "[OK] Token saved to:" in captured.out
    assert "[OK] 1 cookies saved (including Cloudflare cookies)" in captured.out
    assert "Authenticating with Perplexity.ai..." in captured.out
    assert "[ERROR]" not in captured.out
    mock_tm.save_token.assert_called_once_with("token-123", cookies={"cf_clearance": "cookie-1"})


def test_run_logout_command_reports_no_credentials(capsys):
    """Logout runner exits early when there is nothing to clear."""
    mock_tm = Mock()
    mock_tm.token_exists.return_value = False

    with patch("perplexity_cli.runners.auth.TokenManager", return_value=mock_tm):
        run_logout_command()

    captured = capsys.readouterr()
    assert captured.out.strip() == "No stored credentials found."
    assert "[ERROR]" not in captured.out
    # Nothing to clear: token_exists() is the only token-manager interaction.
    mock_tm.token_exists.assert_called_once_with()
    mock_tm.save_token.assert_not_called()


def test_run_auth_command_handles_authentication_error(capsys):
    """Auth runner maps browser/auth failures to the user-facing auth path."""
    with (
        patch("perplexity_cli.runners.auth.authenticate_sync") as mock_auth,
        patch(
            "perplexity_cli.runners.auth.get_perplexity_base_url",
            return_value="https://www.perplexity.ai",
        ),
    ):
        mock_auth.side_effect = AuthenticationError("Chrome not found")

        with pytest.raises(SystemExit) as exc_info:
            run_auth_command(ctx_obj=None, port=9222)

    captured = capsys.readouterr()
    assert exc_info.value.code == 1
    assert "[ERROR] Authentication failed: Chrome not found" in captured.err
    assert "Troubleshooting:" in captured.err
    assert "[ERROR]" not in captured.out
    assert "Authentication successful" not in captured.out


def test_run_set_config_command_updates_setting(capsys):
    """Set-config runner persists the boolean feature value."""
    with (
        patch("perplexity_cli.runners.config.set_feature") as mock_set_feature,
        patch("perplexity_cli.runners.config.clear_feature_config_cache") as mock_clear_cache,
    ):
        run_set_config_command("debug_mode", "true")

    captured = capsys.readouterr()
    assert captured.out.startswith("[OK] Configuration updated: debug_mode = True\n")
    # Contextual contract message for enabling debug mode must also be emitted.
    assert "[INFO] Debug mode enabled." in captured.out
    assert "All commands will now log at DEBUG level." in captured.out
    assert "[ERROR]" not in captured.out
    mock_set_feature.assert_called_once_with("debug_mode", True)
    mock_clear_cache.assert_called_once()


def test_run_set_config_command_handles_configuration_error(capsys):
    """Set-config runner maps configuration failures to exit code 1."""
    logging.getLogger(
        "perplexity_cli"
    ).handlers.clear()  # drop leaked stderr handlers from earlier tests
    with patch("perplexity_cli.runners.config.set_feature") as mock_set_feature:
        mock_set_feature.side_effect = ConfigurationError("bad config")

        with pytest.raises(SystemExit) as exc_info:
            run_set_config_command("save_cookies", "true", output_format="human")

    captured = capsys.readouterr()
    assert exc_info.value.code == 1
    assert captured.err.strip() == "[ERROR] Failed to update configuration: bad config"
    assert "[ERROR]" not in captured.out


def test_run_show_config_command_displays_config_and_env_overrides(capsys, monkeypatch):
    """Show-config runner renders config model data and env overrides."""
    monkeypatch.setenv("PERPLEXITY_SAVE_COOKIES", "true")

    with (
        patch(
            "perplexity_cli.runners.config.get_feature_config",
            return_value=FeatureConfig(save_cookies=True, debug_mode=False),
        ),
        patch(
            "perplexity_cli.runners.config.get_feature_config_path",
            return_value=Path("/tmp/config.json"),
        ),
    ):
        run_show_config_command()

    captured = capsys.readouterr()
    assert "Perplexity CLI Configuration" in captured.out
    assert "Config file: /tmp/config.json" in captured.out
    assert "save_cookies: True" in captured.out
    assert "debug_mode:   False" in captured.out
    assert "PERPLEXITY_SAVE_COOKIES=true" in captured.out
    assert "[ERROR]" not in captured.out


def test_run_export_threads_command_forwards_filters_and_writes_csv(capsys):
    """Export runner passes options through to scraper and CSV writer."""
    mock_tm = Mock()
    mock_tm.load_token.return_value = ("token-123", {"cf_clearance": "cookie-1"})

    mock_cache_manager = Mock()

    mock_scraper = Mock()
    mock_scraper.scrape_all_threads = AsyncMock(return_value=[Mock(), Mock()])

    output_path = Path("/tmp/threads.csv")

    with (
        patch("perplexity_cli.runners.export.TokenManager", return_value=mock_tm),
        patch(
            "perplexity_cli.runners.export.get_rate_limiting_config",
            return_value=RateLimitConfig(
                enabled=False, requests_per_period=20, period_seconds=60.0
            ),
        ),
        patch(
            "perplexity_cli.runners.export.ThreadCacheManager",
            return_value=mock_cache_manager,
        ),
        patch(
            "perplexity_cli.runners.export.ThreadScraper", return_value=mock_scraper
        ) as mock_scraper_class,
        patch(
            "perplexity_cli.runners.export.write_threads_csv", return_value=output_path
        ) as mock_write_csv,
    ):
        run_export_threads_command(
            ctx_obj={"debug": False},
            from_date="2025-01-01",
            to_date="2025-01-31",
            output=output_path,
            force_refresh=True,
            clear_cache=False,
        )

    captured = capsys.readouterr()
    assert "[OK] Export complete" in captured.out
    assert "[ERROR]" not in captured.out
    mock_scraper_class.assert_called_once_with(
        token="token-123",
        cookies={"cf_clearance": "cookie-1"},
        rate_limiter=None,
        cache_manager=mock_cache_manager,
        force_refresh=True,
    )
    mock_scraper.scrape_all_threads.assert_awaited_once()
    assert mock_scraper.scrape_all_threads.await_args.kwargs["from_date"] == "2025-01-01"
    assert mock_scraper.scrape_all_threads.await_args.kwargs["to_date"] == "2025-01-31"
    assert callable(mock_scraper.scrape_all_threads.await_args.kwargs["progress_callback"])
    mock_write_csv.assert_called_once()


def test_run_export_threads_command_handles_invalid_date(capsys):
    """Export runner rejects invalid date input before scraping."""
    mock_tm = Mock()
    mock_tm.load_token.return_value = ("token-123", None)

    with (
        patch("perplexity_cli.runners.export.TokenManager", return_value=mock_tm),
        patch(
            "perplexity_cli.runners.export.get_rate_limiting_config",
            return_value=RateLimitConfig(
                enabled=False, requests_per_period=20, period_seconds=60.0
            ),
        ),
        patch("perplexity_cli.runners.export.ThreadCacheManager", return_value=Mock()),
        patch("dateutil.parser.parse", side_effect=ValueError("bad date")),
    ):
        with pytest.raises(SystemExit) as exc_info:
            run_export_threads_command(
                ctx_obj={"debug": False},
                from_date="bad-date",
                to_date=None,
                output=None,
                force_refresh=False,
                clear_cache=False,
            )

    captured = capsys.readouterr()
    assert exc_info.value.code == 1
    assert "[ERROR] Invalid date format: bad date" in captured.err
    assert "Please use YYYY-MM-DD format (e.g., 2025-12-23)" in captured.err
    assert "[ERROR]" not in captured.out
