from __future__ import annotations

import logging

from . import config


def get_logger(name: str = "cricket") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s", "%H:%M:%S")

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    logger.addHandler(console)

    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(config.LOG_DIR / "pipeline.log", encoding="utf-8")
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)
    return logger
