# positive: fstring in logger call
import logging

logger = logging.getLogger(__name__)
logger.info(f"Processing {item}")
logger.error(f"Failed: {name}", exc_info=True)
