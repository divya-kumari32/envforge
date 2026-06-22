# tests/test_health.py
import asyncio
from pathlib import Path
import pytest
from envforge.kinds.browser_webapp.health import (
    structural_gate, boot_serve_gate, eval_liveness_gate, HealthReport, REQUIRED_FILES,
)
from envforge.agents.fakes import FakeEvalAgent
from envforge.agents.base import EvalResult


def _good_app(tmp_path: Path) -> Path:
    for f in REQUIRED_FILES:
        (tmp_path / f).write_text("x")
    return tmp_path


def test_structural_passes_for_complete_app(tmp_path: Path):
    rep = structural_gate(_good_app(tmp_path))
    assert rep.ok and rep.gate == "structural"


def test_structural_fails_for_missing_file(tmp_path: Path):
    (tmp_path / "index.html").write_text("x")  # server.py missing
    rep = structural_gate(tmp_path)
    assert not rep.ok and "server.py" in rep.detail


def test_structural_fails_for_empty_file(tmp_path: Path):
    for f in REQUIRED_FILES:
        (tmp_path / f).write_text("")
    rep = structural_gate(tmp_path)
    assert not rep.ok


def test_boot_serve_gate_ok(tmp_path: Path):
    (tmp_path / "index.html").write_text("<h1>a</h1>")
    rep = asyncio.run(boot_serve_gate(tmp_path, port=0))
    assert rep.ok and rep.gate == "boot_serve"


def test_eval_liveness_ok(tmp_path: Path):
    fake = FakeEvalAgent({})
    rep = asyncio.run(eval_liveness_gate(fake, "http://x"))
    assert rep.ok and fake.setup_called


def test_eval_liveness_fail_when_setup_raises(tmp_path: Path):
    class BoomAgent(FakeEvalAgent):
        async def setup(self, server_url):
            raise RuntimeError("cannot observe")
    rep = asyncio.run(eval_liveness_gate(BoomAgent({}), "http://x"))
    assert not rep.ok and "cannot observe" in rep.detail


def test_boot_serve_gate_is_failsafe_on_transport_error(tmp_path, monkeypatch):
    # If talking to the app server raises (broken/slow server), the gate must
    # return a classified not-ok HealthReport, never propagate an exception.
    import envforge.kinds.browser_webapp.health as health_mod
    (tmp_path / "index.html").write_text("<h1>a</h1>")

    def boom(url, data):
        raise ConnectionError("server died")
    monkeypatch.setattr(health_mod, "_put_state", boom)

    rep = asyncio.run(health_mod.boot_serve_gate(tmp_path, port=0))
    assert not rep.ok and rep.gate == "boot_serve" and "server died" in rep.detail
