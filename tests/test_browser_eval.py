# tests/test_browser_eval.py
import asyncio
from pathlib import Path
import pytest
from envforge.agents.browser_eval import BrowserUseEvalAgent, EvalHarnessError


class FakeSession:
    def __init__(self): self.started = self.killed = False
    async def start(self): self.started = True
    async def kill(self): self.killed = True


class FakeHistory:
    def __init__(self, done=True, steps=3):
        self._done, self.history = done, list(range(steps))
    def is_done(self): return self._done
    def save_to_file(self, p): Path(p).write_text("history")
    def screenshot_paths(self): return []


class FakeAgent:
    def __init__(self, history=None, raises=None, hang=False):
        self._history, self._raises, self._hang = history or FakeHistory(), raises, hang
        self.history = self._history
    async def run(self):
        if self._raises: raise self._raises
        if self._hang: await asyncio.sleep(10)
        return self._history


def _verifier_dir(tmp_path, task_id, passed):
    d = tmp_path / "verifiers"; d.mkdir(exist_ok=True)
    (d / f"{task_id}.py").write_text(f"def verify(u):\n    return {passed}, 'v'\n")
    return d


def test_run_passes_when_verifier_passes(tmp_path: Path):
    vd = _verifier_dir(tmp_path, "task_e1", True)
    agent = BrowserUseEvalAgent(
        llm=object(), verifier_dir=vd,
        session_factory=lambda: FakeSession(),
        agent_factory=lambda **kw: FakeAgent(FakeHistory(done=True, steps=5)),
        sleep=lambda s: asyncio.sleep(0),
    )
    async def go():
        return await agent.run("task_e1", "do x", "http://x", tmp_path / "t1")
    res = asyncio.run(go())
    assert res.passed and res.steps == 5 and not res.timed_out


def test_run_fails_when_verifier_fails(tmp_path: Path):
    vd = _verifier_dir(tmp_path, "task_e2", False)
    agent = BrowserUseEvalAgent(
        llm=object(), verifier_dir=vd,
        session_factory=lambda: FakeSession(),
        agent_factory=lambda **kw: FakeAgent(FakeHistory(done=True)),
        sleep=lambda s: asyncio.sleep(0),
    )
    res = asyncio.run(agent.run("task_e2", "do x", "http://x", tmp_path / "t2"))
    assert not res.passed


def test_run_timeout_sets_timed_out(tmp_path: Path):
    vd = _verifier_dir(tmp_path, "task_e3", True)
    agent = BrowserUseEvalAgent(
        llm=object(), verifier_dir=vd, timeout=0.05,
        session_factory=lambda: FakeSession(),
        agent_factory=lambda **kw: FakeAgent(hang=True),
        sleep=lambda s: asyncio.sleep(0),
    )
    res = asyncio.run(agent.run("task_e3", "do x", "http://x", tmp_path / "t3"))
    assert res.timed_out and not res.passed


def test_run_restarts_session_on_retryable_error(tmp_path: Path):
    vd = _verifier_dir(tmp_path, "task_e4", True)
    sessions = []
    def make_session():
        s = FakeSession(); sessions.append(s); return s
    calls = {"n": 0}
    def make_agent(**kw):
        calls["n"] += 1
        if calls["n"] == 1:
            return FakeAgent(raises=ConnectionError("CDP died"))
        return FakeAgent(FakeHistory(done=True))
    agent = BrowserUseEvalAgent(
        llm=object(), verifier_dir=vd, max_restarts=3,
        session_factory=make_session, agent_factory=make_agent,
        sleep=lambda s: asyncio.sleep(0),
    )
    res = asyncio.run(agent.run("task_e4", "do x", "http://x", tmp_path / "t4"))
    assert res.passed
    assert len(sessions) >= 2  # restarted at least once


def test_setup_tears_down_session_when_seed_never_ready(tmp_path: Path):
    # setup() must not leak a browser session if /api/state never returns 200.
    sess = FakeSession()
    agent = BrowserUseEvalAgent(
        llm=object(), verifier_dir=tmp_path,
        session_factory=lambda: sess,
        agent_factory=lambda **kw: FakeAgent(),
        sleep=lambda s: asyncio.sleep(0),
    )
    # No server running at this URL → GET /api/state always fails → EvalHarnessError.
    with pytest.raises(EvalHarnessError):
        asyncio.run(agent.setup("http://127.0.0.1:1"))
    assert sess.killed and agent._session is None  # torn down, not leaked


def test_set_verifier_dir(tmp_path):
    from envforge.agents.browser_eval import BrowserUseEvalAgent
    a = BrowserUseEvalAgent(llm=object(), verifier_dir=tmp_path)
    a.set_verifier_dir(tmp_path / "v")
    assert a._verifier_dir == tmp_path / "v"
