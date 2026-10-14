from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler

from config import get_settings


def setup_logging() -> None:
    s = get_settings()
    os.makedirs(s.log_dir, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if root.handlers:
        return

    fmt = logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")

    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(fmt)

    file_h = RotatingFileHandler(
        os.path.join(s.log_dir, "bot.log"),
        maxBytes=5_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    file_h.setLevel(logging.INFO)
    file_h.setFormatter(fmt)

    err_h = RotatingFileHandler(
        os.path.join(s.log_dir, "bot_errors.log"),
        maxBytes=5_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    err_h.setLevel(logging.ERROR)
    err_h.setFormatter(fmt)

    root.addHandler(console)
    root.addHandler(file_h)
    root.addHandler(err_h)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    logging.getLogger("aiogram").setLevel(logging.INFO)
