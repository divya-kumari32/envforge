# tests/test_opencode_agent.py
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
import pytest
from envforge.agents.opencode_agent import OpencodeAgent, _default_runner


def test_builds_command_and_succeeds(tmp_path: Path):
    captured = {}
    def fake_runner(cmd, cwd, stdout, stderr, timeout):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        stdout.write(b"generated ok\n")
        return subprocess.CompletedProcess(cmd, 0)
    agent = OpencodeAgent(runner=fake_runner)
    res = agent.run("make app", model="aws/glm-5", cwd=tmp_path, timeout=30, log_path=tmp_path / "gen.log")
    assert res.ok and res.returncode == 0
    assert captured["cmd"] == ["opencode", "run", "--model", "aws/glm-5", "make app"]
    assert captured["cwd"] == str(tmp_path)
    assert b"generated ok" in (tmp_path / "gen.log").read_bytes()


def test_nonzero_returncode_is_not_ok(tmp_path: Path):
    def fake_runner(cmd, cwd, stdout, stderr, timeout):
        stdout.write(b"boom\n")
        return subprocess.CompletedProcess(cmd, 2)
    agent = OpencodeAgent(runner=fake_runner)
    res = agent.run("p", model="m", cwd=tmp_path, timeout=30, log_path=tmp_path / "g.log")
    assert not res.ok and res.returncode == 2


def test_timeout_is_classified(tmp_path: Path):
    def fake_runner(cmd, cwd, stdout, stderr, timeout):
        raise subprocess.TimeoutExpired(cmd, timeout)
    agent = OpencodeAgent(runner=fake_runner)
    res = agent.run("p", model="m", cwd=tmp_path, timeout=5, log_path=tmp_path / "g.log")
    assert not res.ok and res.returncode == 124
    assert "timeout" in (tmp_path / "g.log").read_text().lower()


def test_default_runner_kills_child_process_group_on_timeout(tmp_path: Path):
    # The default runner must launch the child in its own process group and, on
    # timeout, SIGKILL the whole group so opencode's grandchildren are not
    # orphaned. We spawn a parent that forks a long-lived grandchild and writes
    # the grandchild PID to a file; after the timeout fires the grandchild must
    # be dead too.
    pidfile = tmp_path / "grandchild.pid"
    script = (
        "import os, sys, time\n"
        "pid = os.fork()\n"
        "if pid == 0:\n"  # grandchild
        "    time.sleep(30)\n"
        "    sys.exit(0)\n"
        f"open({str(pidfile)!r}, 'w').write(str(pid))\n"
        "time.sleep(30)\n"
    )
    with open(tmp_path / "out.log", "wb") as log:
        with pytest.raises(subprocess.TimeoutExpired):
            _default_runner(
                [sys.executable, "-c", script],
                cwd=str(tmp_path), stdout=log, stderr=subprocess.STDOUT, timeout=1.0,
            )
    # Give the kill a moment to propagate, then confirm the grandchild is gone.
    for _ in range(50):
        if pidfile.exists():
            break
        time.sleep(0.05)
    gc_pid = int(pidfile.read_text())
    time.sleep(0.3)
    with pytest.raises(ProcessLookupError):
        os.kill(gc_pid, 0)  # raises if the process no longer exists


def test_run_initializes_git_repo_in_cwd(tmp_path):
    # opencode anchors file writes to a git root, so the agent must make cwd a
    # git project before invoking opencode (else files land outside cwd).
    def fake_runner(cmd, cwd, stdout, stderr, timeout):
        stdout.write(b"ok\n")
        return subprocess.CompletedProcess(cmd, 0)
    agent = OpencodeAgent(runner=fake_runner)
    assert not (tmp_path / ".git").exists()
    agent.run("p", model="m", cwd=tmp_path, timeout=30, log_path=tmp_path / "g.log")
    assert (tmp_path / ".git").exists()  # cwd is now a git project
