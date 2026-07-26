# negative: properly logged exception
import logging

logger = logging.getLogger(__name__)
try:
    open("/tmp/nonexistent")
except OSError:
    logger.exception("Could not open file: %s", "/tmp/nonexistent")
