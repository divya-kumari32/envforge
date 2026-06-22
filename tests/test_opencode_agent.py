# tests/test_opencode_agent.py
import subprocess
from pathlib import Path
from envforge.agents.opencode_agent import OpencodeAgent


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
