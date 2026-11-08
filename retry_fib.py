"""Shared Fibonacci-ish backoff for TVibe clients (429/503).

Not used by the API server. NFA.
"""
from __future__ import annotations

import time
from typing import Callable, Optional, TypeVar

T = TypeVar("T")

# 1, 2, 3, 5, 8, 13 seconds (capped)
_FIB_SLEEPS = (1.0, 2.0, 3.0, 5.0, 8.0, 13.0)


def fib_sleep(attempt: int) -> float:
    """attempt is 0-based index into fib ladder."""
    if attempt < 0:
        attempt = 0
    if attempt >= len(_FIB_SLEEPS):
        return _FIB_SLEEPS[-1]
    return _FIB_SLEEPS[attempt]


def with_fib_retry(
    fn: Callable[[], T],
    *,
    retries: int = 4,
    retry_on: tuple = (429, 503, 502),
) -> T:
    """Call fn(); on httpx HTTPStatusError with retry_on codes, sleep fib and retry.

    fn should raise httpx.HTTPStatusError or return a response-like with .status_code,
    or raise httpx.TransportError (also retried lightly).
    """
    import httpx

    last: Optional[BaseException] = None
    for attempt in range(retries + 1):
        try:
            return fn()
        except httpx.HTTPStatusError as e:
            last = e
            code = e.response.status_code if e.response is not None else None
            if code not in retry_on or attempt >= retries:
                raise
            time.sleep(fib_sleep(attempt))
        except httpx.TransportError as e:
            last = e
            if attempt >= retries:
                raise
            time.sleep(fib_sleep(attempt))
    if last:
        raise last
    raise RuntimeError("with_fib_retry: exhausted")
