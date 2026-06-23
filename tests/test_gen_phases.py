# tests/test_gen_phases.py
import json
from pathlib import Path
from envforge.core.runstore import RunStore, StepStatus
from envforge.core.exits import ExitCode
from envforge.phases.base import PhaseContext
from envforge.agents.fakes import FakeCodingAgent
from envforge.kinds.browser_webapp.phases.generate_app import GenerateAppPhase
from envforge.kinds.browser_webapp.phases.function_tasks import GenerateFunctionTasksPhase

NOW = "2026-06-22T00:00:00Z"


def _ctx(tmp_path, rs):
    return PhaseContext(runstore=rs, gateway=None, ports=None, status=None,
                        runtime=None, config={}, now=lambda: NOW)


def _tasks_json(n):
    return json.dumps([{"id": f"task_{i}", "prompt": f"do {i}"} for i in range(n)])


def test_generate_app_ok(tmp_path):
    rs = RunStore.create(tmp_path / "runs", "r", "browser_webapp", now=NOW)
    agent = FakeCodingAgent([{"files": {"index.html": "<h1>a</h1>", "server.py": "x=1"}, "ok": True}])
    phase = GenerateAppPhase(agent, model="m", docs_path=tmp_path / "docs")
    (tmp_path / "docs").mkdir()
    res = phase.run(_ctx(tmp_path, rs))
    assert res.ok and (Path(res.result["app_dir"]) / "index.html").exists()


def test_generate_app_fails_when_files_missing(tmp_path):
    rs = RunStore.create(tmp_path / "runs", "r", "browser_webapp", now=NOW)
    agent = FakeCodingAgent([{"files": {"index.html": "<h1>a</h1>"}, "ok": True}])  # no server.py
    (tmp_path / "docs").mkdir()
    res = GenerateAppPhase(agent, model="m", docs_path=tmp_path / "docs").run(_ctx(tmp_path, rs))
    assert not res.ok and res.exit_code is ExitCode.TASKS_INVALID


def test_generate_function_tasks_ok(tmp_path):
    rs = RunStore.create(tmp_path / "runs", "r", "browser_webapp", now=NOW)
    app_dir = rs.run_dir / "app"; (app_dir / "verifiers").mkdir(parents=True)
    rs.set_step("generate_app", StepStatus.DONE, result={"app_dir": str(app_dir)}, now=NOW)
    files = {"function-tasks.json": _tasks_json(24)}
    for i in range(24):
        files[f"verifiers/task_{i}.py"] = "def verify(u):\n    return True, 'ok'\n"
    agent = FakeCodingAgent([{"files": files, "ok": True}])
    res = GenerateFunctionTasksPhase(agent, model="m", expected_count=24).run(_ctx(tmp_path, rs))
    assert res.ok and res.result["task_count"] == 24


def test_generate_function_tasks_wrong_count_fails(tmp_path):
    rs = RunStore.create(tmp_path / "runs", "r", "browser_webapp", now=NOW)
    app_dir = rs.run_dir / "app"; (app_dir / "verifiers").mkdir(parents=True)
    rs.set_step("generate_app", StepStatus.DONE, result={"app_dir": str(app_dir)}, now=NOW)
    agent = FakeCodingAgent([{"files": {"function-tasks.json": _tasks_json(5)}, "ok": True}])
    res = GenerateFunctionTasksPhase(agent, model="m", expected_count=24).run(_ctx(tmp_path, rs))
    assert not res.ok and res.exit_code is ExitCode.TASKS_INVALID


def test_generate_app_stages_docs_then_cleans_up(tmp_path):
    # Docs must be staged under the agent cwd (so the agent can read them with a
    # relative path), then removed so they aren't part of the generated app.
    rs = RunStore.create(tmp_path / "runs", "r", "browser_webapp", now=NOW)
    docs = tmp_path / "docs"; docs.mkdir()
    (docs / "guide.md").write_text("how payments work")

    saw_staged = {}

    class DocAwareFake(FakeCodingAgent):
        def run(self, prompt, *, model, cwd, timeout, log_path):
            staged = Path(cwd) / "_source_docs" / "guide.md"
            saw_staged["present"] = staged.exists()
            saw_staged["relative_in_prompt"] = "./_source_docs/" in prompt
            return super().run(prompt, model=model, cwd=cwd, timeout=timeout, log_path=log_path)

    agent = DocAwareFake([{"files": {"index.html": "<h1>a</h1>", "server.py": "x=1"}, "ok": True}])
    res = GenerateAppPhase(agent, model="m", docs_path=docs).run(_ctx(tmp_path, rs))
    assert res.ok
    assert saw_staged["present"] and saw_staged["relative_in_prompt"]  # staged + referenced relatively
    assert not (Path(res.result["app_dir"]) / "_source_docs").exists()  # cleaned up


def test_generate_app_fails_when_docs_path_missing(tmp_path):
    rs = RunStore.create(tmp_path / "runs", "r", "browser_webapp", now=NOW)
    agent = FakeCodingAgent([{"files": {"index.html": "x", "server.py": "y"}, "ok": True}])
    res = GenerateAppPhase(agent, model="m", docs_path=tmp_path / "nope").run(_ctx(tmp_path, rs))
    assert not res.ok and res.exit_code is ExitCode.TASKS_INVALID
