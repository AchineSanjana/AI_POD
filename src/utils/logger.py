"""Small shared logging setup so every module logs consistently."""

import logging
import sys


def get_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    """Return a configured logger.

    Usage:
        from src.utils.logger import get_logger
        logger = get_logger(__name__)
    """
    logger = logging.getLogger(name)

    if not logger.handlers:  # avoid duplicate handlers on reimport
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(level)

    return logger
