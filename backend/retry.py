"""Retry policies for calls to external services (exponential backoff with jitter)."""

import logging

import httpx
from tenacity import (
    AsyncRetrying,
    RetryCallState,
    retry_if_exception,
    stop_after_attempt,
    stop_after_delay,
    wait_random_exponential,
)

logger = logging.getLogger(__name__)

RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


class RetryableHTTPError(Exception):
    def __init__(self, response: httpx.Response) -> None:
        super().__init__(f"HTTP {response.status_code} from {response.request.url.host}")
        self.response = response


def _is_transient(exc: BaseException) -> bool:
    return isinstance(exc, (httpx.TransportError, RetryableHTTPError))


def _log_retry(state: RetryCallState) -> None:
    exc = state.outcome.exception() if state.outcome else None
    logger.warning("Retrying after attempt %d failed: %r", state.attempt_number, exc)


def http_retry(attempts: int = 3, max_seconds: float = 10.0) -> AsyncRetrying:
    """Usage: `async for attempt in http_retry(): with attempt: ...`"""
    return AsyncRetrying(
        retry=retry_if_exception(_is_transient),
        stop=stop_after_attempt(attempts) | stop_after_delay(max_seconds),
        wait=wait_random_exponential(multiplier=0.25, max=4),
        before_sleep=_log_retry,
        reraise=True,
    )


def raise_for_retryable(response: httpx.Response) -> None:
    """Raise RetryableHTTPError for transient statuses, HTTPStatusError for other failures."""
    if response.status_code in RETRYABLE_STATUS:
        raise RetryableHTTPError(response)
    response.raise_for_status()
