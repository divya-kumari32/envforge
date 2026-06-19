from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


class Runtime(Protocol):
    def prepare_env(self) -> None: ...
    def run(self, cmd: list[str], *, cwd: Path | None = None, timeout: float | None = None) -> CommandResult: ...
    def free_gb(self, path: Path) -> float: ...
