# tests/test_cli.py
import json
from pathlib import Path
import pytest
from envforge import cli
from envforge.core.exits import ExitCode

NOW = "2026-06-19T00:00:00Z"


def _args_run(runs_root: Path):
    ns = cli.build_parser().parse_args(
        ["run", "--kind", "demo", "--runs-root", str(runs_root), "--ports-dir", str(runs_root / "ports")]
    )
    return ns


def test_run_demo_completes_ok(tmp_path: Path):
    ns = _args_run(tmp_path)
    code = cli.cmd_run(ns, now=NOW, host="hostA", pid=123)
    assert code == int(ExitCode.OK)
    run_id = cli.build_run_id("demo", NOW)
    state = json.loads((tmp_path / run_id / "state.json").read_text())
    assert state["steps"]["eval"]["status"] == "done"
    assert state["exit"]["name"] == "OK"


def test_status_dir_outside_run_dir_has_status_json(tmp_path: Path):
    ns = _args_run(tmp_path)
    cli.cmd_run(ns, now=NOW, host="hostA", pid=123)
    run_id = cli.build_run_id("demo", NOW)
    # status lives under <run_dir>/_status, never inside a synced app dir
    assert (tmp_path / run_id / "_status" / "STATUS.json").exists()


def test_resume_is_idempotent(tmp_path: Path):
    ns = _args_run(tmp_path)
    cli.cmd_run(ns, now=NOW, host="hostA", pid=123)
    run_id = cli.build_run_id("demo", NOW)
    rns = cli.build_parser().parse_args(["resume", "--run", run_id, "--runs-root", str(tmp_path), "--ports-dir", str(tmp_path / "ports")])
    code = cli.cmd_resume(rns, now=NOW, host="hostA", pid=124)
    assert code == int(ExitCode.OK)


def test_duplicate_run_id_blocked_by_live_lock(tmp_path: Path):
    # Pre-write a live lock for the run, then resume from a different live pid → DUPLICATE_JOB
    ns = _args_run(tmp_path)
    cli.cmd_run(ns, now=NOW, host="hostA", pid=123)
    run_id = cli.build_run_id("demo", NOW)
    from envforge.core.lock import RunLock
    lock_path = tmp_path / run_id / "run.lock"
    RunLock(lock_path, pid=999, host="hostA", alive=lambda p: True).acquire(now=10_000.0)
    rns = cli.build_parser().parse_args(["resume", "--run", run_id, "--runs-root", str(tmp_path), "--ports-dir", str(tmp_path / "ports")])
    code = cli.cmd_resume(rns, now=NOW, host="hostA", pid=124, lock_now=10_001.0, alive=lambda p: True)
    assert code == int(ExitCode.DUPLICATE_JOB)


def test_main_dispatch_returns_int(tmp_path: Path):
    code = cli.main(["status", "--run", "missing", "--runs-root", str(tmp_path)])
    assert isinstance(code, int)
