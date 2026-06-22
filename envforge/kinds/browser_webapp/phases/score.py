# envforge/kinds/browser_webapp/phases/score.py
from __future__ import annotations

from ....phases.base import PhaseContext, PhaseResult


class ScorePhase:
    name = "score"

    def run(self, ctx: PhaseContext) -> PhaseResult:
        results = ctx.runstore.state["steps"]["evaluate"]["result"]["results"]
        total = len(results)
        passed = sum(1 for r in results if r.get("passed"))
        timed_out = sum(1 for r in results if r.get("timed_out"))
        failed = total - passed
        pass_rate = round(passed / total, 3) if total else 0.0
        summary = {"total": total, "passed": passed, "failed": failed,
                   "timed_out": timed_out, "pass_rate": pass_rate}
        ctx.status.write_status({"phase": "score", **summary}, now=ctx.now())
        return PhaseResult.done(**summary)
