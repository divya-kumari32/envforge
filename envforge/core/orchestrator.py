# envforge/core/orchestrator.py
from __future__ import annotations

from ..phases.base import Phase, PhaseContext
from .exits import EnvforgeExit, ExitCode
from .runstore import RunStore, StepStatus
from .status import StatusWriter


class Orchestrator:
    def __init__(self, runstore: RunStore, phases: list[Phase], order: list[str], ctx: PhaseContext):
        self._rs = runstore
        self._by_name = {p.name: p for p in phases}
        self._order = order
        self._ctx = ctx
        self._status: StatusWriter = ctx.status

    def run(self) -> ExitCode:
        for name in self._order:
            if self._rs.step_status(name) is StepStatus.DONE:
                continue
            code = self._run_one(name)
            if code is not None:
                return code
        now = self._ctx.now()
        self._rs.set_exit(ExitCode.OK, "all phases complete", now=now)
        # step_status is explicitly cleared to "done" so the terminal snapshot
        # never reads exit=OK alongside a stale step_status=running.
        self._status.write_status({"phase": "done", "step_status": "done", "exit": "OK"}, now=now)
        return ExitCode.OK

    def _run_one(self, name: str) -> ExitCode | None:
        now = self._ctx.now()
        phase = self._by_name[name]
        self._rs.set_step(name, StepStatus.RUNNING, now=now)
        self._status.write_status({"phase": name, "step_status": "running"}, now=now)
        self._status.activity("phase_start", now=now, phase=name)
        try:
            result = phase.run(self._ctx)
        except EnvforgeExit as exc:
            return self._fail(name, exc.code, exc.reason)
        except Exception as exc:  # noqa: BLE001 — any phase crash is a classified FATAL
            return self._fail(name, ExitCode.FATAL, f"{type(exc).__name__}: {exc}")

        if result.ok:
            done_now = self._ctx.now()
            self._rs.set_step(name, StepStatus.DONE, result=result.result, now=done_now)
            self._status.activity("phase_done", now=done_now, phase=name, **result.result)
            return None
        return self._fail(name, result.exit_code or ExitCode.FATAL, result.reason)

    def _fail(self, name: str, code: ExitCode, reason: str) -> ExitCode:
        now = self._ctx.now()
        self._rs.set_step(name, StepStatus.FAILED, result={"reason": reason}, now=now)
        self._rs.set_exit(code, reason, now=now)
        self._status.write_status(
            {"phase": name, "step_status": "failed", "exit": code.name, "reason": reason}, now=now
        )
        self._status.activity("phase_failed", now=now, phase=name, exit=code.name, reason=reason)
        return code
