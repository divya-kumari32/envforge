# tests/test_browser_webapp_kind.py
import json
from pathlib import Path
from envforge.core.runstore import RunStore
from envforge.core.orchestrator import Orchestrator
from envforge.core.ports import PortBroker
from envforge.core.status import StatusWriter
from envforge.core.exits import ExitCode
from envforge.phases.base import PhaseContext
from envforge.runtimes.local import LocalRuntime
from envforge.agents.fakes import FakeCodingAgent, FakeEvalAgent
from envforge.agents.base import EvalResult
from envforge.kinds.browser_webapp.kind import BrowserWebAppKind

NOW = "2026-06-22T00:00:00Z"


def test_full_kind_runs_end_to_end_with_fakes(tmp_path):
    rs = RunStore.create(tmp_path / "runs", "r", "browser_webapp", now=NOW)
    # generate_app writes index.html+server.py; function_tasks writes tasks+verifiers
    n = 3
    tj = json.dumps([{"id": f"task_{i}", "prompt": f"do {i}"} for i in range(n)])
    gen_files = {"index.html": "<h1>a</h1>", "server.py": "x=1"}
    task_files = {"function-tasks.json": tj}
    for i in range(n):
        task_files[f"verifiers/task_{i}.py"] = "def verify(u):\n    return True, 'ok'\n"
    coding = FakeCodingAgent([{"files": gen_files, "ok": True}, {"files": task_files, "ok": True}])
    eval_agent = FakeEvalAgent({f"task_{i}": EvalResult(f"task_{i}", passed=(i % 2 == 0)) for i in range(n)})

    kind = BrowserWebAppKind(coding, eval_agent, gen_model="g", eval_model="e",
                             docs_path=tmp_path / "docs", task_count=n)
    (tmp_path / "docs").mkdir()
    ctx = PhaseContext(
        runstore=rs, gateway=None,
        ports=PortBroker(tmp_path / "ports", start=8300, end=8360, is_free=lambda p: True),
        status=StatusWriter(rs.run_dir / "_status"), runtime=LocalRuntime(), config={}, now=lambda: NOW,
    )
    code = Orchestrator(rs, kind.phases(), kind.order(), ctx).run()
    assert code is ExitCode.OK
    assert rs.state["steps"]["score"]["result"]["total"] == n
    assert rs.state["steps"]["score"]["result"]["passed"] == 2  # tasks 0 and 2
