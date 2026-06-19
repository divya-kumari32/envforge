from __future__ import annotations

import time
from typing import Callable

from .errors import ErrorCategory, classify_error

RETRYABLE: set[ErrorCategory] = {
    ErrorCategory.TIMEOUT,
    ErrorCategory.SERVER,
    ErrorCategory.TRANSPORT,
}


def with_retry(
    fn: Callable[[str], object],
    endpoints: list[str],
    *,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
    classify: Callable[[Exception], ErrorCategory] = classify_error,
):
    if not endpoints:
        raise ValueError("endpoints must be non-empty")
    last: Exception | None = None
    for attempt in range(max_attempts):
        endpoint = endpoints[attempt % len(endpoints)]
        try:
            return fn(endpoint)
        except Exception as exc:  # noqa: BLE001 — classify decides retryability
            category = classify(exc)
            last = exc
            if category not in RETRYABLE:
                raise
            if attempt + 1 < max_attempts:
                sleep(base_delay * (2 ** attempt))
    assert last is not None
    raise last
