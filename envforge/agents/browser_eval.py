# envforge/agents/browser_eval.py
from __future__ import annotations

import asyncio
from pathlib import Path

from ..kinds.browser_webapp.verifier import run_verifier
from .base import EvalResult


class EvalHarnessError(Exception):
    pass


def _is_retryable(exc: Exception) -> bool:
    return isinstance(exc, (ConnectionError, TimeoutError, OSError))


class BrowserUseEvalAgent:
    def __init__(
        self,
        llm,
        *,
        verifier_dir: Path,
        max_steps: int = 50,
        timeout: float = 300.0,
        max_restarts: int = 3,
        session_factory=None,
        agent_factory=None,
        sleep=asyncio.sleep,
    ):
        self._llm = llm
        self._verifier_dir = Path(verifier_dir)
        self._max_steps = max_steps
        self._timeout = timeout
        self._max_restarts = max_restarts
        self._session_factory = session_factory or self._default_session_factory
        self._agent_factory = agent_factory or self._default_agent_factory
        self._sleep = sleep
        self._session = None
        self._server_url: str | None = None

    @staticmethod
    def _default_session_factory():
        from browser_use import BrowserSession  # lazy import
        return BrowserSession(headless=True, keep_alive=True)

    @staticmethod
    def _default_agent_factory(*, task, llm, session, max_steps):
        from browser_use import Agent  # lazy import
        return Agent(task=task, llm=llm, browser_session=session, max_steps=max_steps)

    async def _start_session(self):
        self._session = self._session_factory()
        await self._session.start()

    async def setup(self, server_url: str) -> None:
        self._server_url = server_url
        await self._start_session()
        import urllib.error
        import urllib.request
        for _ in range(10):
            await self._sleep(1.0)
            try:
                with urllib.request.urlopen(f"{server_url}/api/state", timeout=2) as r:
                    if r.status == 200:
                        return
            except urllib.error.HTTPError:
                continue
            except Exception:
                continue
        # Seed never captured: tear down the session we started so a failed
        # setup never leaks a browser process, then signal the harness failure.
        await self.teardown()
        raise EvalHarnessError("seed state not captured: GET /api/state never returned 200")

    async def teardown(self) -> None:
        if self._session is not None:
            try:
                await self._session.kill()
            finally:
                self._session = None

    async def run(self, task_id: str, task: str, server_url: str, task_dir: Path) -> EvalResult:
        task_dir = Path(task_dir)
        task_dir.mkdir(parents=True, exist_ok=True)
        instruction = f"You are interacting with a web application at {server_url}. Your task: {task}"

        if self._session is None:
            await self._start_session()

        history = None
        attempts = 0
        while True:
            attempts += 1
            agent = self._agent_factory(
                task=instruction, llm=self._llm, session=self._session, max_steps=self._max_steps
            )
            try:
                history = await asyncio.wait_for(agent.run(), timeout=self._timeout)
                break
            except asyncio.TimeoutError:
                partial = getattr(agent, "history", None)
                if partial is not None:
                    try:
                        partial.save_to_file(str(task_dir / "history.json"))
                    except Exception:
                        pass
                return EvalResult(task_id=task_id, passed=False, timed_out=True)
            except Exception as exc:  # noqa: BLE001
                if _is_retryable(exc) and attempts <= self._max_restarts:
                    await self.teardown()
                    await self._start_session()
                    await self._sleep(1.0)
                    continue
                return EvalResult(task_id=task_id, passed=False, error=f"{type(exc).__name__}: {exc}")

        try:
            history.save_to_file(str(task_dir / "history.json"))
        except Exception:
            pass

        outcome = run_verifier(self._verifier_dir / f"{task_id}.py", server_url)
        return EvalResult(
            task_id=task_id,
            passed=outcome.passed,
            steps=len(getattr(history, "history", []) or []),
            timed_out=False,
        )
