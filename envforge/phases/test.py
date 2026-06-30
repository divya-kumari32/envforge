# envforge/phases/test.py
#
# The built-in "test" kind: deterministic, model-free, browser-free phases that
# exercise the full orchestrator / run-store / locking / ports / classified-exit
# machinery with NO external dependencies. Used by `envforge run --kind test`
# and by the unit tests. (Contrast: the "browser_webapp" kind runs the real
# opencode + browser_use agents against a live model endpoint.)
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


TEST_PHASES: list[Phase] = [GeneratePhase(), HealthPhase(), EvalPhase()]
TEST_ORDER: list[str] = [p.name for p in TEST_PHASES]
