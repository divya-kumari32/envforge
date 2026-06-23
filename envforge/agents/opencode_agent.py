# envforge/agents/opencode_agent.py
from __future__ import annotations

import os
import signal
import subprocess
from pathlib import Path

from .base import CodingResult


def _default_runner(cmd, *, cwd, stdout, stderr, timeout):
    # Launch opencode in its own process group so that on timeout we can kill
    # the entire child tree, not just the direct child. opencode spawns its own
    # subprocesses; subprocess.run(timeout=...) would only SIGKILL the direct
    # child and orphan the rest on the 3600s generate timeout.
    proc = subprocess.Popen(
        cmd, cwd=cwd, stdout=stdout, stderr=stderr, start_new_session=True
    )
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()
        proc.wait()
        raise
    return subprocess.CompletedProcess(cmd, proc.returncode)


class OpencodeAgent:
    def __init__(self, *, runner=_default_runner):
        self._runner = runner

    def run(self, prompt: str, *, model: str, cwd: Path, timeout: float, log_path: Path) -> CodingResult:
        # opencode anchors its project root — and therefore where it writes files —
        # to the nearest enclosing git repository, NOT the process cwd. If cwd is
        # not inside a git repo, opencode writes files into some other repo entirely.
        # Make cwd its own git project so generated files land here.
        cwd_path = Path(cwd)
        if not (cwd_path / ".git").exists():
            subprocess.run(["git", "init", "-q"], cwd=str(cwd_path),
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
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
