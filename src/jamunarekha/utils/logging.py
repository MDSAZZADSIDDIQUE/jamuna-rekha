"""Console + file logging shared by every entry point."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

_FMT = "%(asctime)s %(levelname)-7s %(name)-28s %(message)s"
_DATEFMT = "%H:%M:%S"


def get_logger(name: str, log_dir: Path | str | None = None) -> logging.Logger:
    """Return a configured logger, optionally also writing to ``log_dir``.

    Handlers are attached once per name, so repeated calls in a notebook do not
    produce duplicated lines.
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(logging.Formatter(_FMT, datefmt=_DATEFMT))
    logger.addHandler(stream)

    if log_dir is not None:
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_dir / f"{name.replace('.', '_')}.log", encoding="utf-8")
        file_handler.setFormatter(logging.Formatter(_FMT, datefmt=_DATEFMT))
        logger.addHandler(file_handler)

    logger.propagate = False
    return logger
