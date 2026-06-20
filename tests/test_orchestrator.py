# tests/test_orchestrator.py
from pathlib import Path
import pytest

from envforge.core.runstore import RunStore, StepStatus
from envforge.core.orchestrator import Orchestrator
from envforge.core.exits import ExitCode, EnvforgeExit
from envforge.core.ports import PortBroker
from envforge.core.status import StatusWriter
from envforge.models.gateway import ModelGateway, ModelSpec, FakeTransport
from envforge.models.budget import BudgetLedger
from envforge.runtimes.local import LocalRuntime
from envforge.phases.base import PhaseContext, PhaseResult
from envforge.phases.demo import DEMO_PHASES, DEMO_ORDER, GeneratePhase

NOW = "2026-06-19T00:00:00Z"


def _ctx(tmp_path: Path, runstore: RunStore, config: dict) -> PhaseContext:
    gw = ModelGateway({}, BudgetLedger({}), FakeTransport([]), sleep=lambda s: None)
    return PhaseContext(
        runstore=runstore,
        gateway=gw,
        ports=PortBroker(tmp_path / "ports", start=8200, end=8210, is_free=lambda p: True),
        status=StatusWriter(tmp_path / "status"),
        runtime=LocalRuntime(),
        config=config,
        now=lambda: NOW,
    )


def test_full_run_marks_all_done_and_returns_ok(tmp_path: Path):
    rs = RunStore.create(tmp_path / "runs", "r", "demo", now=NOW)
    orch = Orchestrator(rs, DEMO_PHASES, DEMO_ORDER, _ctx(tmp_path, rs, {}))
    code = orch.run()
    assert code is ExitCode.OK
    for name in DEMO_ORDER:
        assert rs.step_status(name) is StepStatus.DONE


def test_failed_phase_returns_classified_code(tmp_path: Path):
    rs = RunStore.create(tmp_path / "runs", "r", "demo", now=NOW)
    cfg = {"fail_eval": (ExitCode.EVAL_HARNESS_FAILURE, "forced")}
    orch = Orchestrator(rs, DEMO_PHASES, DEMO_ORDER, _ctx(tmp_path, rs, cfg))
    code = orch.run()
    assert code is ExitCode.EVAL_HARNESS_FAILURE
    assert rs.step_status("eval") is StepStatus.FAILED
    assert rs.step_status("generate") is StepStatus.DONE
    assert rs.exit_code is ExitCode.EVAL_HARNESS_FAILURE


def test_resume_skips_done_steps(tmp_path: Path):
    rs = RunStore.create(tmp_path / "runs", "r", "demo", now=NOW)
    rs.set_step("generate", StepStatus.DONE, result={"files": 3, "port": 8200}, now=NOW)

    class BoomGenerate(GeneratePhase):
        def run(self, ctx):  # would fail if called
            raise AssertionError("generate should have been skipped")

    phases = [BoomGenerate()] + DEMO_PHASES[1:]
    orch = Orchestrator(rs, phases, DEMO_ORDER, _ctx(tmp_path, rs, {}))
    assert orch.run() is ExitCode.OK


def test_envforge_exit_inside_phase_is_classified(tmp_path: Path):
    rs = RunStore.create(tmp_path / "runs", "r", "demo", now=NOW)

    class RaisingHealth:
        name = "health"

        def run(self, ctx):
            raise EnvforgeExit(ExitCode.APP_UNHEALTHY, "no boot")

    phases = [DEMO_PHASES[0], RaisingHealth(), DEMO_PHASES[2]]
    orch = Orchestrator(rs, phases, DEMO_ORDER, _ctx(tmp_path, rs, {}))
    assert orch.run() is ExitCode.APP_UNHEALTHY
    assert rs.step_status("health") is StepStatus.FAILED


def test_unexpected_exception_becomes_fatal(tmp_path: Path):
    rs = RunStore.create(tmp_path / "runs", "r", "demo", now=NOW)

    class BadHealth:
        name = "health"

        def run(self, ctx):
            raise RuntimeError("kaboom")

    phases = [DEMO_PHASES[0], BadHealth(), DEMO_PHASES[2]]
    orch = Orchestrator(rs, phases, DEMO_ORDER, _ctx(tmp_path, rs, {}))
    assert orch.run() is ExitCode.FATAL
    assert rs.exit_code is ExitCode.FATAL
