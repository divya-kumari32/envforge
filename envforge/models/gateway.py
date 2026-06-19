from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Protocol

from .budget import BudgetLedger
from .fallback import with_retry


@dataclass
class ModelResponse:
    text: str
    cost: float
    raw: dict = field(default_factory=dict)


@dataclass
class ModelSpec:
    provider: str
    model: str
    endpoints: list[str]


class Transport(Protocol):
    def call(self, endpoint: str, spec: ModelSpec, messages: list[dict], **kw) -> ModelResponse:
        ...


class FakeTransport:
    """Test transport: replays scripted responses/exceptions in order."""

    def __init__(self, scripted: list):
        self._scripted = list(scripted)
        self.calls: list[dict] = []

    def call(self, endpoint: str, spec: ModelSpec, messages: list[dict], **kw) -> ModelResponse:
        self.calls.append({"endpoint": endpoint, "spec": spec, "messages": messages})
        item = self._scripted.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class ModelGateway:
    def __init__(
        self,
        role_specs: dict[str, ModelSpec],
        ledger: BudgetLedger,
        transport: Transport,
        *,
        sleep=time.sleep,
    ):
        self._specs = role_specs
        self._ledger = ledger
        self._transport = transport
        self._sleep = sleep

    def call(self, role: str, messages: list[dict], **kw) -> ModelResponse:
        spec = self._specs[role]  # KeyError on unknown role — intentional
        self._ledger.check(role)  # may raise BudgetExceeded before any spend

        def attempt(endpoint: str) -> ModelResponse:
            return self._transport.call(endpoint, spec, messages, **kw)

        resp = with_retry(attempt, spec.endpoints, sleep=self._sleep)
        self._ledger.record(role, resp.cost)
        return resp
