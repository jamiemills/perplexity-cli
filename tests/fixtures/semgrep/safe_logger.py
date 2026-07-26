# negative: no credential keywords in logger format string
import logging

logger = logging.getLogger(__name__)
logger.info("Processing request %s", request_id)
