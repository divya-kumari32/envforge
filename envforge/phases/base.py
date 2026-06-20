# envforge/phases/base.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Protocol

from ..core.exits import ExitCode
from ..core.ports import PortBroker
from ..core.runstore import RunStore
from ..core.status import StatusWriter
from ..models.gateway import ModelGateway
from ..runtimes.base import Runtime


@dataclass
class PhaseResult:
    ok: bool
    result: dict = field(default_factory=dict)
    exit_code: ExitCode | None = None
    reason: str = ""

    @classmethod
    def done(cls, **result) -> "PhaseResult":
        return cls(ok=True, result=result)

    @classmethod
    def fail(cls, exit_code: ExitCode, reason: str) -> "PhaseResult":
        return cls(ok=False, exit_code=exit_code, reason=reason)


@dataclass
class PhaseContext:
    runstore: RunStore
    gateway: ModelGateway
    ports: PortBroker
    status: StatusWriter
    runtime: Runtime
    config: dict
    now: Callable[[], str]


class Phase(Protocol):
    name: str

    def run(self, ctx: PhaseContext) -> PhaseResult: ...
