"""Logging configuration.

Thin wrapper around the standard ``logging`` module that:

* respects ``APP_LOG_LEVEL``
* produces ISO-8601 UTC timestamps
* includes the logger name and process id so we can correlate
  background pipeline tasks with API requests.

A single :func:`configure_logging` call is made from
:func:`app.main.create_app` at startup; modules should simply call
:func:`get_logger` and never reconfigure handlers themselves.
"""

from __future__ import annotations

import logging
import sys
from logging import Logger

from .config import settings

_CONFIGURED = False
_FORMAT = (
    "%(asctime)s | %(levelname)-7s | pid=%(process)d | %(name)s | %(message)s"
)


def configure_logging() -> None:
    """Initialize the root logger exactly once."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    root = logging.getLogger()
    root.setLevel(settings.app_log_level.upper())

    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(
        logging.Formatter(_FORMAT, datefmt="%Y-%m-%dT%H:%M:%S%z")
    )
    root.addHandler(handler)

    # Tone down chatty third-party libraries by default.
    for noisy in ("urllib3", "asyncio", "multipart"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _CONFIGURED = True


def get_logger(name: str) -> Logger:
    """Return a child logger named ``name``."""
    if not _CONFIGURED:
        configure_logging()
    return logging.getLogger(name)
