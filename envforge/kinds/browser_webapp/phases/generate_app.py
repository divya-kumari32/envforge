# envforge/kinds/browser_webapp/phases/generate_app.py
from __future__ import annotations

import shutil
from pathlib import Path

from ....core.exits import ExitCode
from ....phases.base import PhaseContext, PhaseResult

_PROMPT = (Path(__file__).resolve().parents[1] / "prompts" / "generate_app.md").read_text()

# Docs are staged here, INSIDE the agent's working dir, so the coding agent can
# read them with a relative path. Coding agents (e.g. opencode) refuse to read
# absolute paths outside their cwd ("external directory"), so pointing at the
# original docs location silently yields an empty app. Removed after generation.
_STAGED_DOCS_DIR = "_source_docs"


class GenerateAppPhase:
    name = "generate_app"

    def __init__(self, coding_agent, *, model: str, docs_path: Path, timeout: float = 3600.0):
        self._agent = coding_agent
        self._model = model
        self._docs_path = Path(docs_path)
        self._timeout = timeout

    def run(self, ctx: PhaseContext) -> PhaseResult:
        if not self._docs_path.exists():
            return PhaseResult.fail(ExitCode.TASKS_INVALID, f"docs path does not exist: {self._docs_path}")
        app_dir = ctx.runstore.run_dir / "app"
        app_dir.mkdir(parents=True, exist_ok=True)

        # Stage docs under the agent's cwd so they are readable via a relative path.
        staged = app_dir / _STAGED_DOCS_DIR
        if staged.exists():
            shutil.rmtree(staged)
        shutil.copytree(self._docs_path, staged)

        prompt = (
            f"{_PROMPT}\n\n"
            f"The source documentation is in ./{_STAGED_DOCS_DIR}/ (a directory of files in the\n"
            f"current working directory) — read it to understand the domain. Build the app in the\n"
            f"current directory. Do NOT modify, serve, or reference ./{_STAGED_DOCS_DIR}/ from the app.\n"
        )
        log_path = ctx.runstore.run_dir / "logs" / "generate_app.log"
        result = self._agent.run(prompt, model=self._model, cwd=app_dir,
                                 timeout=self._timeout, log_path=log_path)

        # Remove the staged docs so they are not part of the generated app.
        shutil.rmtree(staged, ignore_errors=True)

        if not result.ok:
            return PhaseResult.fail(ExitCode.TASKS_INVALID, f"generate_app agent failed (rc={result.returncode})")
        for f in ("index.html", "server.py"):
            p = app_dir / f
            if not p.exists() or p.stat().st_size == 0:
                return PhaseResult.fail(ExitCode.TASKS_INVALID, f"generated app missing/empty {f}")
        return PhaseResult.done(app_dir=str(app_dir))
