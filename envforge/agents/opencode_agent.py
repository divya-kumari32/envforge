# envforge/agents/opencode_agent.py
from __future__ import annotations

import subprocess
from pathlib import Path

from .base import CodingResult


class OpencodeAgent:
    def __init__(self, *, runner=subprocess.run):
        self._runner = runner

    def run(self, prompt: str, *, model: str, cwd: Path, timeout: float, log_path: Path) -> CodingResult:
        cmd = ["opencode", "run", "--model", model, prompt]
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "wb") as log:
            try:
                proc = self._runner(
                    cmd, cwd=str(cwd), stdout=log, stderr=subprocess.STDOUT, timeout=timeout
                )
            except subprocess.TimeoutExpired:
                log.write(f"\n[opencode] TIMEOUT after {timeout}s\n".encode())
                return CodingResult(ok=False, returncode=124, log_path=str(log_path))
        return CodingResult(ok=proc.returncode == 0, returncode=proc.returncode, log_path=str(log_path))
