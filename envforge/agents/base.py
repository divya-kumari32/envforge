# envforge/agents/base.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass
class CodingResult:
    ok: bool
    returncode: int
    log_path: str


@dataclass
class EvalResult:
    task_id: str
    passed: bool
    steps: int = 0
    elapsed: float = 0.0
    timed_out: bool = False
    error: str | None = None


class CodingAgent(Protocol):
    def run(self, prompt: str, *, model: str, cwd: Path, timeout: float, log_path: Path) -> CodingResult:
        ...


class EvalAgent(Protocol):
    async def setup(self, server_url: str) -> None: ...
    async def run(self, task_id: str, task: str, server_url: str, task_dir: Path) -> EvalResult: ...
    async def teardown(self) -> None: ...
