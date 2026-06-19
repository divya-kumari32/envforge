from pathlib import Path
from envforge.runtimes.local import LocalRuntime
from envforge.runtimes.base import CommandResult


def test_run_echo_captures_stdout():
    rt = LocalRuntime()
    res = rt.run(["python", "-c", "print('hello')"])
    assert isinstance(res, CommandResult)
    assert res.returncode == 0
    assert "hello" in res.stdout


def test_run_nonzero_returncode():
    rt = LocalRuntime()
    res = rt.run(["python", "-c", "import sys; sys.exit(3)"])
    assert res.returncode == 3


def test_free_gb_is_positive(tmp_path: Path):
    rt = LocalRuntime()
    assert rt.free_gb(tmp_path) > 0


def test_prepare_env_is_noop():
    LocalRuntime().prepare_env()  # must not raise
