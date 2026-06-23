# envforge/kinds/browser_webapp/phases/evaluate.py
from __future__ import annotations

import asyncio
import json
import urllib.request
from dataclasses import asdict
from pathlib import Path

from ....agents.browser_eval import EvalHarnessError
from ....core.exits import ExitCode
from ....phases.base import PhaseContext, PhaseResult
from ..protocol import StateServer


def _reset_app_state(server_url: str) -> None:
    # Restore the captured seed state between tasks so task N never sees task
    # N-1's mutations. Tolerate any failure: a reset hiccup must not crash the
    # eval loop (we still attempt a reset before every task).
    try:
        req = urllib.request.Request(f"{server_url}/api/reset", data=b"", method="POST")
        with urllib.request.urlopen(req, timeout=5) as r:
            r.read()
    except Exception:
        pass


class EvaluatePhase:
    name = "evaluate"

    def __init__(self, eval_agent):
        self._eval_agent = eval_agent

    def run(self, ctx: PhaseContext) -> PhaseResult:
        app_dir = Path(ctx.runstore.state["steps"]["generate_app"]["result"]["app_dir"])
        if hasattr(self._eval_agent, "set_verifier_dir"):
            self._eval_agent.set_verifier_dir(app_dir / "verifiers")
        tasks = json.loads((app_dir / "function-tasks.json").read_text())
        owner = f"{ctx.runstore.run_id}:app"
        port = ctx.ports.lease(owner)
        ctx.runstore.record_port("app", port)
        server = StateServer(app_dir, port=port)
        server.start()
        try:
            results = asyncio.run(self._run_all(server.url, tasks, ctx.runstore.run_dir / "tasks"))
        except EvalHarnessError as exc:
            # The eval harness (browser setup / agent driving) failed in a way
            # that is not a fatal orchestrator bug — classify it as an eval
            # harness failure rather than letting it propagate to FATAL.
            return PhaseResult.fail(ExitCode.EVAL_HARNESS_FAILURE, f"eval harness failed: {exc}")
        finally:
            server.stop()
            ctx.ports.release(port)
        if not results:
            return PhaseResult.fail(ExitCode.EVAL_HARNESS_FAILURE, "eval produced zero results")
        return PhaseResult.done(results=[asdict(r) for r in results])

    async def _run_all(self, url, tasks, tasks_root):
        await self._eval_agent.setup(url)
        out = []
        try:
            for t in tasks:
                # Reset to the captured seed before each task so absolute-state
                # verifiers don't see mutations left over from a prior task.
                _reset_app_state(url)
                res = await self._eval_agent.run(t["id"], t["prompt"], url, tasks_root / t["id"])
                out.append(res)
        finally:
            await self._eval_agent.teardown()
        return out
