# positive: credential keywords in logger format string
import logging

logger = logging.getLogger(__name__)
logger.info("Using api key: %s", some_key)
