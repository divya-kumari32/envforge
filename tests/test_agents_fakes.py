# tests/test_agents_fakes.py
import asyncio
from pathlib import Path
from envforge.agents.base import CodingResult, EvalResult
from envforge.agents.fakes import FakeCodingAgent, FakeEvalAgent


def test_fake_coding_agent_writes_files(tmp_path: Path):
    agent = FakeCodingAgent([{"files": {"index.html": "<h1>hi</h1>", "server.py": "x=1"}, "ok": True}])
    res = agent.run("build app", model="m", cwd=tmp_path, timeout=10, log_path=tmp_path / "log.txt")
    assert isinstance(res, CodingResult) and res.ok and res.returncode == 0
    assert (tmp_path / "index.html").read_text() == "<h1>hi</h1>"
    assert (tmp_path / "server.py").read_text() == "x=1"
    assert agent.calls[0]["model"] == "m"


def test_fake_coding_agent_consumes_responses_in_order(tmp_path: Path):
    agent = FakeCodingAgent([
        {"files": {"a.txt": "1"}, "ok": True},
        {"files": {"b.txt": "2"}, "ok": False},
    ])
    r1 = agent.run("p1", model="m", cwd=tmp_path, timeout=1, log_path=tmp_path / "l1")
    r2 = agent.run("p2", model="m", cwd=tmp_path, timeout=1, log_path=tmp_path / "l2")
    assert r1.ok and not r2.ok
    assert (tmp_path / "a.txt").exists() and (tmp_path / "b.txt").exists()


def test_fake_eval_agent_returns_scripted(tmp_path: Path):
    fake = FakeEvalAgent({"task_e1": EvalResult(task_id="task_e1", passed=True, steps=4)})

    async def go():
        await fake.setup("http://x")
        r = await fake.run("task_e1", "do thing", "http://x", tmp_path)
        await fake.teardown()
        return r

    r = asyncio.run(go())
    assert r.passed and r.steps == 4
    assert fake.setup_called and fake.tasks_run == ["task_e1"]
