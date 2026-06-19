import pytest
from envforge.models.budget import BudgetLedger, BudgetExceeded


def test_record_accumulates():
    led = BudgetLedger({"gen": 10.0})
    led.record("gen", 3.0)
    led.record("gen", 2.0)
    assert led.spent("gen") == 5.0


def test_grand_total():
    led = BudgetLedger({"gen": None, "eval": None})
    led.record("gen", 1.0)
    led.record("eval", 2.5)
    assert led.spent() == 3.5


def test_cap_exceeded_raises_and_records():
    led = BudgetLedger({"gen": 5.0})
    with pytest.raises(BudgetExceeded) as ei:
        led.record("gen", 6.0)
    assert ei.value.role == "gen"
    assert led.spent("gen") == 6.0  # cost recorded before raising


def test_unlimited_role_never_raises():
    led = BudgetLedger({"gen": None})
    led.record("gen", 1e9)  # no raise


def test_check_before_call():
    led = BudgetLedger({"eval": 5.0})
    led.record("eval", 5.0)
    with pytest.raises(BudgetExceeded):
        led.check("eval")


def test_roundtrip_dict():
    led = BudgetLedger({"gen": 5.0})
    led.record("gen", 2.0)
    again = BudgetLedger.from_dict(led.to_dict())
    assert again.spent("gen") == 2.0
    with pytest.raises(BudgetExceeded):
        again.record("gen", 4.0)
