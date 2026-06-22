# envforge/kinds/browser_webapp/phases/function_tasks.py
from __future__ import annotations

import json
from pathlib import Path

from ....core.exits import ExitCode
from ....phases.base import PhaseContext, PhaseResult

_PROMPT = (Path(__file__).resolve().parents[1] / "prompts" / "generate_function_tasks.md").read_text()


class GenerateFunctionTasksPhase:
    name = "generate_function_tasks"

    def __init__(self, coding_agent, *, model: str, expected_count: int = 24, timeout: float = 1800.0):
        self._agent = coding_agent
        self._model = model
        self._expected = expected_count
        self._timeout = timeout

    def run(self, ctx: PhaseContext) -> PhaseResult:
        app_dir = Path(ctx.runstore.state["steps"]["generate_app"]["result"]["app_dir"])
        log_path = ctx.runstore.run_dir / "logs" / "generate_function_tasks.log"
        result = self._agent.run(_PROMPT, model=self._model, cwd=app_dir,
                                 timeout=self._timeout, log_path=log_path)
        if not result.ok:
            return PhaseResult.fail(ExitCode.TASKS_INVALID, f"function-task gen failed (rc={result.returncode})")
        tasks_file = app_dir / "function-tasks.json"
        if not tasks_file.exists():
            return PhaseResult.fail(ExitCode.TASKS_INVALID, "function-tasks.json missing")
        try:
            tasks = json.loads(tasks_file.read_text())
        except json.JSONDecodeError as e:
            return PhaseResult.fail(ExitCode.TASKS_INVALID, f"function-tasks.json invalid JSON: {e}")
        if not isinstance(tasks, list) or len(tasks) != self._expected:
            return PhaseResult.fail(ExitCode.TASKS_INVALID,
                                    f"expected {self._expected} tasks, got {len(tasks) if isinstance(tasks, list) else 'non-list'}")
        for t in tasks:
            if "id" not in t or "prompt" not in t:
                return PhaseResult.fail(ExitCode.TASKS_INVALID, "task missing id/prompt")
            if not (app_dir / "verifiers" / f"{t['id']}.py").exists():
                return PhaseResult.fail(ExitCode.TASKS_INVALID, f"missing verifier for {t['id']}")
        return PhaseResult.done(task_count=len(tasks))
