# envforge/phases/demo.py
from __future__ import annotations

from ..core.exits import ExitCode
from .base import Phase, PhaseContext, PhaseResult


class GeneratePhase:
    name = "generate"

    def run(self, ctx: PhaseContext) -> PhaseResult:
        port = ctx.ports.lease(f"{ctx.runstore.run_id}:app")
        ctx.runstore.record_port("app", port)
        return PhaseResult.done(files=3, port=port)


class HealthPhase:
    name = "health"

    def run(self, ctx: PhaseContext) -> PhaseResult:
        if ctx.config.get("fail_health"):
            code, reason = ctx.config["fail_health"]
            return PhaseResult.fail(code, reason)
        return PhaseResult.done(healthy=True)


class EvalPhase:
    name = "eval"

    def run(self, ctx: PhaseContext) -> PhaseResult:
        if ctx.config.get("fail_eval"):
            code, reason = ctx.config["fail_eval"]
            return PhaseResult.fail(code, reason)
        return PhaseResult.done(passed=2, failed=1)


DEMO_PHASES: list[Phase] = [GeneratePhase(), HealthPhase(), EvalPhase()]
DEMO_ORDER: list[str] = [p.name for p in DEMO_PHASES]
