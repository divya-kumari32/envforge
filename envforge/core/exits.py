from __future__ import annotations

from enum import IntEnum
from typing import NoReturn


class ExitCode(IntEnum):
    OK = 0
    BUDGET_EXCEEDED = 10
    TASKS_INVALID = 11
    APP_UNHEALTHY = 12
    EVAL_HARNESS_FAILURE = 13
    DUPLICATE_JOB = 14
    INTERRUPTED = 15
    FATAL = 20


class EnvforgeExit(Exception):
    def __init__(self, code: ExitCode, reason: str):
        super().__init__(f"[{code.name}] {reason}")
        self.code = code
        self.reason = reason


def finish(code: ExitCode, reason: str) -> NoReturn:
    raise EnvforgeExit(code, reason)
