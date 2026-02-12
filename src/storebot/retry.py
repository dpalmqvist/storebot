"""Retry decorator with exponential backoff for transient network errors."""

import functools
import logging
import time

import requests
import zeep.exceptions

logger = logging.getLogger(__name__)


def _is_retryable(exc: Exception) -> bool:
    """Determine if an exception is transient and worth retrying."""
    if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
        return True
    if isinstance(exc, zeep.exceptions.TransportError):
        status_code = getattr(exc, "status_code", None)
        return status_code is not None and status_code >= 500
    if isinstance(exc, requests.HTTPError):
        response = getattr(exc, "response", None)
        return response is not None and response.status_code >= 500
    return False


def retry_on_transient(max_retries: int = 3, base_delay: float = 1.0):
    """Decorator that retries a function on transient network errors.

    Uses exponential backoff: base_delay * 2^attempt (1s, 2s, 4s by default).
    Only retries on ConnectionError, Timeout, and 5xx TransportError/HTTPError.
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    last_exc = exc
                    if attempt < max_retries and _is_retryable(exc):
                        delay = base_delay * (2**attempt)
                        logger.warning(
                            "Transient error in %s (attempt %d/%d), retrying in %.1fs: %s",
                            func.__name__,
                            attempt + 1,
                            max_retries + 1,
                            delay,
                            exc,
                        )
                        time.sleep(delay)
                    else:
                        raise
            raise last_exc  # pragma: no cover

        return wrapper

    return decorator
