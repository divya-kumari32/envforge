# tests/test_eval_score_phases.py
import json
from pathlib import Path
from envforge.core.runstore import RunStore, StepStatus
from envforge.core.ports import PortBroker
from envforge.core.status import StatusWriter
from envforge.core.exits import ExitCode
from envforge.phases.base import PhaseContext
from envforge.agents.fakes import FakeEvalAgent
from envforge.agents.base import EvalResult
from envforge.kinds.browser_webapp.phases.evaluate import EvaluatePhase
from envforge.kinds.browser_webapp.phases.score import ScorePhase

NOW = "2026-06-22T00:00:00Z"


def _ctx(tmp_path, rs):
    return PhaseContext(
        runstore=rs, gateway=None,
        ports=PortBroker(tmp_path / "ports", start=8200, end=8260, is_free=lambda p: True),
        status=StatusWriter(rs.run_dir / "_status"), runtime=None, config={}, now=lambda: NOW,
    )


def _seed_app_with_tasks(rs, n):
    app_dir = rs.run_dir / "app"; (app_dir / "verifiers").mkdir(parents=True)
    (app_dir / "index.html").write_text("<h1>a</h1>")
    tasks = [{"id": f"task_{i}", "prompt": f"do {i}"} for i in range(n)]
    (app_dir / "function-tasks.json").write_text(json.dumps(tasks))
    rs.set_step("generate_app", StepStatus.DONE, result={"app_dir": str(app_dir)}, now=NOW)
    rs.set_step("generate_function_tasks", StepStatus.DONE, result={"task_count": n}, now=NOW)
    return app_dir, tasks


def test_evaluate_runs_all_tasks(tmp_path):
    rs = RunStore.create(tmp_path / "runs", "r", "browser_webapp", now=NOW)
    _seed_app_with_tasks(rs, 3)
    fake = FakeEvalAgent({
        "task_0": EvalResult("task_0", passed=True),
        "task_1": EvalResult("task_1", passed=False),
        "task_2": EvalResult("task_2", passed=True),
    })
    res = EvaluatePhase(fake).run(_ctx(tmp_path, rs))
    assert res.ok and len(res.result["results"]) == 3 and fake.setup_called


def test_score_aggregates(tmp_path):
    rs = RunStore.create(tmp_path / "runs", "r", "browser_webapp", now=NOW)
    _seed_app_with_tasks(rs, 3)
    rs.set_step("evaluate", StepStatus.DONE, result={"results": [
        {"task_id": "task_0", "passed": True, "timed_out": False},
        {"task_id": "task_1", "passed": False, "timed_out": False},
        {"task_id": "task_2", "passed": True, "timed_out": False},
    ]}, now=NOW)
    res = ScorePhase().run(_ctx(tmp_path, rs))
    assert res.ok and res.result["passed"] == 2 and res.result["failed"] == 1
    status = json.loads((rs.run_dir / "_status" / "STATUS.json").read_text())
    assert status["passed"] == 2
