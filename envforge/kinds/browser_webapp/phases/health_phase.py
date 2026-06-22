# envforge/kinds/browser_webapp/phases/health_phase.py
from __future__ import annotations

import asyncio
from pathlib import Path

from ....core.exits import ExitCode
from ....phases.base import PhaseContext, PhaseResult
from ..health import run_all_gates
from ..protocol import StateServer


class HealthGatePhase:
    name = "health_gate"

    def __init__(self, eval_agent):
        self._eval_agent = eval_agent

    def run(self, ctx: PhaseContext) -> PhaseResult:
        app_dir = Path(ctx.runstore.state["steps"]["generate_app"]["result"]["app_dir"])
        port = ctx.ports.lease(f"{ctx.runstore.run_id}:health")
        server = StateServer(app_dir, port=port)
        server.start()
        try:
            report = asyncio.run(run_all_gates(
                app_dir, port=0, eval_agent=self._eval_agent, server_url=server.url))
        finally:
            server.stop()
            ctx.ports.release(port)
        if not report.ok:
            return PhaseResult.fail(ExitCode.APP_UNHEALTHY, f"{report.gate}: {report.detail}")
        return PhaseResult.done(healthy=True)
