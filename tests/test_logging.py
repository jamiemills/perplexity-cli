"""Tests for logging utilities."""

import logging
import tempfile
from pathlib import Path

import pytest

from perplexity_cli.utils.logging import get_logger, setup_logging


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

