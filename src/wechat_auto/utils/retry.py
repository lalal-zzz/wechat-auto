"""Retry decorator for handling transient UI failures."""

from __future__ import annotations

import functools
import logging
import time
from typing import TypeVar, Callable, Any

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


def retry_on_failure(
    max_retries: int = 3,
    delay: float = 1.0,
    exceptions: tuple = (Exception,),
    on_retry: Callable[[Exception, int], None] | None = None,
) -> Callable[[F], F]:
    """Decorator to retry a function on failure.

    Args:
        max_retries: Maximum number of attempts.
        delay: Delay between retries in seconds.
        exceptions: Tuple of exception types to catch.
        on_retry: Optional callback(exception, attempt_number).
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(1, max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    logger.warning(
                        "[Retry] %s attempt %d/%d failed: %s",
                        func.__name__,
                        attempt,
                        max_retries,
                        exc,
                    )
                    if on_retry:
                        on_retry(exc, attempt)
                    if attempt < max_retries:
                        time.sleep(delay)
            raise last_exc  # type: ignore[misc]

        return wrapper  # type: ignore[return-value]

    return decorator
