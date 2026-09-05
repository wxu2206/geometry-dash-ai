"""Application logging setup that avoids duplicate handlers."""

from __future__ import annotations

import logging
from pathlib import Path


def configure_logging(level: str = "INFO", log_file: Path | None = None) -> logging.Logger:
    """Configure and return the project logger."""
    logger = logging.getLogger("geometry_dash_ai")
    logger.handlers.clear()
    logger.setLevel(level.upper())
    logger.propagate = False
    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )
    handler: logging.Handler
    if log_file is None:
        handler = logging.StreamHandler()
    else:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(log_file, encoding="utf-8")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger

