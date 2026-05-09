"""Tests for logging utilities."""

import logging
import tempfile
from pathlib import Path

from perplexity_cli.utils.logging import (
    get_logger,
    redact_mapping_keys,
    redact_path,
    redact_response_text,
    redact_text,
    redact_url,
    setup_logging,
)


class TestLoggingSetup:
    """Test logging setup and configuration."""

    def test_setup_logging_default_level(self):
        """Test logging setup with default level."""
        logger = setup_logging()
        assert logger.level == logging.WARNING

    def test_setup_logging_verbose(self):
        """Test logging setup with verbose flag."""
        logger = setup_logging(verbose=True)
        assert logger.level == logging.INFO

    def test_setup_logging_debug(self):
        """Test logging setup with debug flag."""
        logger = setup_logging(debug=True)
        assert logger.level == logging.DEBUG

    def test_setup_logging_with_file(self):
        """Test logging setup with log file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "test.log"
            logger = setup_logging(log_file=log_file)
            assert logger.level == logging.WARNING
            # File handler is added, but file is created when first log message is written
            # Log something to ensure file is created
            logger.info("Test message")
            assert log_file.exists() is True

    def test_get_logger(self):
        """Test getting logger instance."""
        logger = get_logger()
        assert isinstance(logger, logging.Logger)
        assert logger.name == "perplexity_cli"

    def test_get_logger_with_name(self):
        """Test getting logger with custom name."""
        logger = get_logger("test_module")
        assert logger.name == "perplexity_cli.test_module"


class TestLogRedaction:
    """Test logging redaction helpers."""

    def test_redact_path_keeps_only_filename(self):
        assert redact_path("/Users/example/secrets/token.json") == "<redacted>/token.json"

    def test_redact_text_hides_content(self):
        redacted = redact_text("very sensitive query text")
        assert "sensitive" not in redacted
        assert redacted.startswith("<redacted:")

    def test_redact_url_hides_path_and_query(self):
        redacted = redact_url("https://example.com/secret/path?token=abc")
        assert redacted == "https://example.com/<redacted>"

    def test_redact_mapping_keys_hides_cookie_names(self):
        redacted = redact_mapping_keys({"cf_clearance": "x", "csrftoken": "y"})
        assert redacted == "<redacted:2 keys>"

    def test_redact_response_text_hides_body(self):
        redacted = redact_response_text('{"token":"secret"}')
        assert "secret" not in redacted
