# tests/test_claude_agent.py
import subprocess
from pathlib import Path
from envforge.agents.claude_agent import ClaudeAgent


def test_builds_claude_command_and_succeeds(tmp_path: Path):
    captured = {}
    def fake_runner(cmd, cwd, stdout, stderr, timeout):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        stdout.write(b"generated ok\n")
        return subprocess.CompletedProcess(cmd, 0)
    agent = ClaudeAgent(runner=fake_runner)
    res = agent.run("make app", model="my-os-model", cwd=tmp_path, timeout=30, log_path=tmp_path / "gen.log")
    assert res.ok and res.returncode == 0
    assert captured["cmd"] == ["claude", "-p", "make app", "--model", "my-os-model",
                               "--dangerously-skip-permissions"]
    assert captured["cwd"] == str(tmp_path)
    assert b"generated ok" in (tmp_path / "gen.log").read_bytes()


def test_extra_args_are_overridable(tmp_path: Path):
    captured = {}
    def fake_runner(cmd, cwd, stdout, stderr, timeout):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0)
    agent = ClaudeAgent(runner=fake_runner, extra_args=["--permission-mode", "acceptEdits"])
    agent.run("p", model="m", cwd=tmp_path, timeout=30, log_path=tmp_path / "g.log")
    assert captured["cmd"] == ["claude", "-p", "p", "--model", "m",
                               "--permission-mode", "acceptEdits"]


def test_nonzero_returncode_is_not_ok(tmp_path: Path):
    def fake_runner(cmd, cwd, stdout, stderr, timeout):
        stdout.write(b"boom\n")
        return subprocess.CompletedProcess(cmd, 2)
    agent = ClaudeAgent(runner=fake_runner)
    res = agent.run("p", model="m", cwd=tmp_path, timeout=30, log_path=tmp_path / "g.log")
    assert not res.ok and res.returncode == 2


def test_timeout_is_classified(tmp_path: Path):
    def fake_runner(cmd, cwd, stdout, stderr, timeout):
        raise subprocess.TimeoutExpired(cmd, timeout)
    agent = ClaudeAgent(runner=fake_runner)
    res = agent.run("p", model="m", cwd=tmp_path, timeout=5, log_path=tmp_path / "g.log")
    assert not res.ok and res.returncode == 124
    assert "timeout" in (tmp_path / "g.log").read_text().lower()


def test_creates_cwd_but_no_git_init(tmp_path: Path):
    # Unlike opencode, the Claude CLI writes relative to cwd, so the agent should
    # NOT create a .git repo; it just ensures the working dir exists.
    def fake_runner(cmd, cwd, stdout, stderr, timeout):
        stdout.write(b"ok\n")
        return subprocess.CompletedProcess(cmd, 0)
    target = tmp_path / "app"
    agent = ClaudeAgent(runner=fake_runner)
    agent.run("p", model="m", cwd=target, timeout=30, log_path=target / "g.log")
    assert target.exists()
    assert not (target / ".git").exists()
