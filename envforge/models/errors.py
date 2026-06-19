from __future__ import annotations

from enum import Enum


class ErrorCategory(str, Enum):
    AUTH = "auth"
    BUDGET = "budget"
    TIMEOUT = "timeout"
    SERVER = "server"
    MALFORMED = "malformed"
    TRANSPORT = "transport"
    UNKNOWN = "unknown"


class TransportError(Exception):
    def __init__(self, message: str, *, status: int | None = None):
        super().__init__(message)
        self.status = status
        self.message = message


def classify_error(exc: Exception) -> ErrorCategory:
    msg = str(getattr(exc, "message", exc)).lower()
    status = getattr(exc, "status", None)

    if status in (401, 403):
        return ErrorCategory.AUTH
    if status == 402 or "budget" in msg or "quota" in msg:
        return ErrorCategory.BUDGET
    if status in (408, 504) or isinstance(exc, TimeoutError):
        return ErrorCategory.TIMEOUT
    if status in (500, 502, 503):
        return ErrorCategory.SERVER
    if isinstance(exc, ValueError) or "json" in msg or "parse" in msg:
        return ErrorCategory.MALFORMED
    if isinstance(exc, (ConnectionError, OSError)):
        return ErrorCategory.TRANSPORT
    return ErrorCategory.UNKNOWN
