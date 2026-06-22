# envforge/agents/fakes.py
from __future__ import annotations

from pathlib import Path

from .base import CodingResult, EvalResult


class FakeCodingAgent:
    def __init__(self, responses: list[dict]):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def run(self, prompt: str, *, model: str, cwd: Path, timeout: float, log_path: Path) -> CodingResult:
        self.calls.append({"prompt": prompt, "model": model, "cwd": Path(cwd)})
        spec = self._responses.pop(0)
        for rel, content in spec.get("files", {}).items():
            target = Path(cwd) / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        Path(log_path).write_text("fake coding agent log\n", encoding="utf-8")
        ok = spec.get("ok", True)
        return CodingResult(ok=ok, returncode=0 if ok else 1, log_path=str(log_path))


class FakeEvalAgent:
    def __init__(self, results: dict[str, EvalResult]):
        self._results = dict(results)
        self.setup_called = False
        self.tasks_run: list[str] = []

    async def setup(self, server_url: str) -> None:
        self.setup_called = True

    async def run(self, task_id: str, task: str, server_url: str, task_dir: Path) -> EvalResult:
        self.tasks_run.append(task_id)
        return self._results[task_id]

    async def teardown(self) -> None:
        return None
