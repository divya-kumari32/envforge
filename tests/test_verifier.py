# tests/test_verifier.py
from pathlib import Path
from envforge.kinds.browser_webapp.verifier import run_verifier, VerifyOutcome


def _write(p: Path, body: str) -> Path:
    p.write_text(body, encoding="utf-8")
    return p


def test_passing_verifier(tmp_path: Path):
    v = _write(tmp_path / "task_e1.py", "def verify(server_url):\n    return True, 'ok'\n")
    out = run_verifier(v, "http://x")
    assert isinstance(out, VerifyOutcome) and out.passed and out.detail == "ok"


def test_failing_verifier(tmp_path: Path):
    v = _write(tmp_path / "task_e2.py", "def verify(server_url):\n    return False, 'nope'\n")
    out = run_verifier(v, "http://x")
    assert not out.passed and out.detail == "nope"


def test_verifier_exception_is_caught(tmp_path: Path):
    v = _write(tmp_path / "task_e3.py", "def verify(server_url):\n    raise ValueError('bad')\n")
    out = run_verifier(v, "http://x")
    assert not out.passed and "bad" in out.detail


def test_missing_verify_function(tmp_path: Path):
    v = _write(tmp_path / "task_e4.py", "x = 1\n")
    out = run_verifier(v, "http://x")
    assert not out.passed and "verify" in out.detail.lower()
