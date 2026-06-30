# envforge/agents/claude_agent.py
from __future__ import annotations

import subprocess
from pathlib import Path

from .base import CodingResult
from .opencode_agent import _default_runner


class ClaudeAgent:
    """CodingAgent backed by the Claude Code CLI (`claude -p ...`).

    Mirrors OpencodeAgent's interface and reuses its process-group timeout
    runner, so a generation phase can use either coding agent interchangeably
    (selected by `--gen-agent`).

    It can drive ANY model the CLI is pointed at — including open-source models —
    by setting `ANTHROPIC_BASE_URL` (and `ANTHROPIC_AUTH_TOKEN`) to an
    Anthropic-compatible endpoint, e.g. a proxy that exposes an OS model over
    `/v1/messages` (LiteLLM and similar can do this). `--gen-model` is then the
    model id that endpoint serves. envforge does not set those env vars itself;
    they come from the environment, exactly like opencode's OPENAI_* vars.

    Unlike opencode (which anchors writes to the nearest git repo), the Claude
    CLI writes relative to its process cwd, so no `git init` is needed — we just
    ensure cwd exists and launch there.
    """

    def __init__(self, *, runner=_default_runner, extra_args: list[str] | None = None):
        self._runner = runner
        # Headless, non-interactive generation: skip the interactive permission
        # prompts so the agent can create/edit files on its own. Overridable for
        # callers that want to scope tools/permissions differently.
        self._extra_args = (
            list(extra_args) if extra_args is not None else ["--dangerously-skip-permissions"]
        )

    def run(self, prompt: str, *, model: str, cwd: Path, timeout: float, log_path: Path) -> CodingResult:
        cwd_path = Path(cwd)
        cwd_path.mkdir(parents=True, exist_ok=True)
        cmd = ["claude", "-p", prompt, "--model", model, *self._extra_args]
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "wb") as log:
            try:
                proc = self._runner(
                    cmd, cwd=str(cwd), stdout=log, stderr=subprocess.STDOUT, timeout=timeout
                )
            except subprocess.TimeoutExpired:
                log.write(f"\n[claude] TIMEOUT after {timeout}s\n".encode())
                return CodingResult(ok=False, returncode=124, log_path=str(log_path))
        return CodingResult(ok=proc.returncode == 0, returncode=proc.returncode, log_path=str(log_path))
