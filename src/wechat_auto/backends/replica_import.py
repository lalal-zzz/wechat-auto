"""Contain the optional adapter's import-time stream/logging side effects."""

import importlib
import io
import logging
import sys
from contextlib import redirect_stderr, redirect_stdout
from threading import RLock

_IMPORT_LOCK = RLock()


def replica_module(name: str = 'wechatauto'):
    """Load before starting stdio; never let vendor initialization own stdout."""
    with _IMPORT_LOCK:
        if name in sys.modules:
            return sys.modules[name]
        root = logging.getLogger()
        handlers, level = root.handlers[:], root.level
        levels = {key: logger.level for key, logger in logging.Logger.manager.loggerDict.items()
                  if isinstance(logger, logging.Logger)}
        try:
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                return importlib.import_module(name)
        finally:
            root.handlers[:] = handlers
            root.setLevel(level)
            for key, prior in levels.items():
                logging.getLogger(key).setLevel(prior)
