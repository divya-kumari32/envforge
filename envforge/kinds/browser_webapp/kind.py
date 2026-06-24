# envforge/kinds/browser_webapp/kind.py
from __future__ import annotations

from pathlib import Path

from .phases.generate_app import GenerateAppPhase
from .phases.health_phase import HealthGatePhase
from .phases.function_tasks import GenerateFunctionTasksPhase
from .phases.evaluate import EvaluatePhase
from .phases.score import ScorePhase


class BrowserWebAppKind:
    name = "browser_webapp"

    def __init__(self, coding_agent, eval_agent, *, gen_model: str, eval_model: str,
                 docs_path: Path, task_count: int = 24, gen_timeout: float = 3600.0):
        self._phases = [
            GenerateAppPhase(coding_agent, model=gen_model, docs_path=docs_path, timeout=gen_timeout),
            HealthGatePhase(eval_agent),
            GenerateFunctionTasksPhase(coding_agent, model=gen_model, expected_count=task_count,
                                       timeout=gen_timeout),
            EvaluatePhase(eval_agent),
            ScorePhase(),
        ]

    def phases(self):
        return list(self._phases)

    def order(self):
        return [p.name for p in self._phases]
