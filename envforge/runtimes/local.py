from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .base import CommandResult


class LocalRuntime:
    def prepare_env(self) -> None:
        return None

    def run(self, cmd: list[str], *, cwd: Path | None = None, timeout: float | None = None) -> CommandResult:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return CommandResult(proc.returncode, proc.stdout, proc.stderr)

    def free_gb(self, path: Path) -> float:
        usage = shutil.disk_usage(str(path))
        return usage.free / (1024 ** 3)
