import pytest
from envforge.core.exits import ExitCode, EnvforgeExit, finish


def test_exit_codes_are_stable():
    assert ExitCode.OK == 0
    assert ExitCode.BUDGET_EXCEEDED == 10
    assert ExitCode.FATAL == 20


def test_finish_raises_classified_exit():
    with pytest.raises(EnvforgeExit) as ei:
        finish(ExitCode.BUDGET_EXCEEDED, "cap hit")
    assert ei.value.code is ExitCode.BUDGET_EXCEEDED
    assert ei.value.reason == "cap hit"


def test_exit_str_includes_code_and_reason():
    err = EnvforgeExit(ExitCode.FATAL, "boom")
    assert "FATAL" in str(err) and "boom" in str(err)
