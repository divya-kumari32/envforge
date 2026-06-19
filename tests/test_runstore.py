# tests/test_runstore.py
from pathlib import Path
import pytest
from envforge.core.runstore import RunStore, StepStatus
from envforge.core.exits import ExitCode

NOW = "2026-06-19T00:00:00Z"


def test_create_persists_state(tmp_path: Path):
    rs = RunStore.create(tmp_path, "run-1", "demo", now=NOW)
    assert rs.run_id == "run-1"
    assert rs.kind == "demo"
    assert (tmp_path / "run-1" / "state.json").exists()
    assert RunStore.exists(tmp_path, "run-1")


def test_unset_step_is_pending(tmp_path: Path):
    rs = RunStore.create(tmp_path, "r", "demo", now=NOW)
    assert rs.step_status("generate") is StepStatus.PENDING


def test_set_step_survives_reload(tmp_path: Path):
    rs = RunStore.create(tmp_path, "r", "demo", now=NOW)
    rs.set_step("generate", StepStatus.DONE, result={"files": 3}, now=NOW)
    reloaded = RunStore.load(tmp_path, "r")
    assert reloaded.step_status("generate") is StepStatus.DONE
    assert reloaded.state["steps"]["generate"]["result"] == {"files": 3}


def test_next_pending_skips_done(tmp_path: Path):
    rs = RunStore.create(tmp_path, "r", "demo", now=NOW)
    order = ["generate", "health", "eval"]
    assert rs.next_pending(order) == "generate"
    rs.set_step("generate", StepStatus.DONE, now=NOW)
    assert rs.next_pending(order) == "health"
    rs.set_step("health", StepStatus.DONE, now=NOW)
    rs.set_step("eval", StepStatus.DONE, now=NOW)
    assert rs.next_pending(order) is None


def test_failed_step_is_still_next_pending(tmp_path: Path):
    rs = RunStore.create(tmp_path, "r", "demo", now=NOW)
    rs.set_step("generate", StepStatus.FAILED, now=NOW)
    assert rs.next_pending(["generate", "eval"]) == "generate"


def test_set_exit_records_code(tmp_path: Path):
    rs = RunStore.create(tmp_path, "r", "demo", now=NOW)
    rs.set_exit(ExitCode.BUDGET_EXCEEDED, "cap", now=NOW)
    reloaded = RunStore.load(tmp_path, "r")
    assert reloaded.exit_code is ExitCode.BUDGET_EXCEEDED


def test_record_port(tmp_path: Path):
    rs = RunStore.create(tmp_path, "r", "demo", now=NOW)
    rs.record_port("app", 8200)
    assert RunStore.load(tmp_path, "r").ports == {"app": 8200}


def test_state_is_deep_copy(tmp_path: Path):
    rs = RunStore.create(tmp_path, "r", "demo", now=NOW)
    snapshot = rs.state
    snapshot["kind"] = "corrupted"
    snapshot["steps"]["generate"] = {"status": "done"}
    assert rs.kind == "demo"
    assert rs.step_status("generate") is StepStatus.PENDING
