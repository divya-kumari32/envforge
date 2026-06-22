# envforge/kinds/browser_webapp/phases/generate_app.py
from __future__ import annotations

from pathlib import Path

from ....core.exits import ExitCode
from ....phases.base import PhaseContext, PhaseResult

_PROMPT = (Path(__file__).resolve().parents[1] / "prompts" / "generate_app.md").read_text()


class GenerateAppPhase:
    name = "generate_app"

    def __init__(self, coding_agent, *, model: str, docs_path: Path, timeout: float = 3600.0):
        self._agent = coding_agent
        self._model = model
        self._docs_path = Path(docs_path)
        self._timeout = timeout

    def run(self, ctx: PhaseContext) -> PhaseResult:
        app_dir = ctx.runstore.run_dir / "app"
        app_dir.mkdir(parents=True, exist_ok=True)
        prompt = f"{_PROMPT}\n\nDocumentation source: {self._docs_path}\n"
        log_path = ctx.runstore.run_dir / "logs" / "generate_app.log"
        result = self._agent.run(prompt, model=self._model, cwd=app_dir,
                                 timeout=self._timeout, log_path=log_path)
        if not result.ok:
            return PhaseResult.fail(ExitCode.TASKS_INVALID, f"generate_app agent failed (rc={result.returncode})")
        for f in ("index.html", "server.py"):
            p = app_dir / f
            if not p.exists() or p.stat().st_size == 0:
                return PhaseResult.fail(ExitCode.TASKS_INVALID, f"generated app missing/empty {f}")
        return PhaseResult.done(app_dir=str(app_dir))
