import pytest
from envforge.models.gateway import ModelGateway, ModelSpec, ModelResponse, FakeTransport
from envforge.models.budget import BudgetLedger, BudgetExceeded
from envforge.models.errors import TransportError

SPECS = {"gen": ModelSpec(provider="litellm", model="glm-5", endpoints=["e1", "e2"])}


def test_successful_call_records_cost():
    transport = FakeTransport([ModelResponse(text="hi", cost=2.0, raw={})])
    led = BudgetLedger({"gen": 10.0})
    gw = ModelGateway(SPECS, led, transport, sleep=lambda s: None)
    resp = gw.call("gen", [{"role": "user", "content": "x"}])
    assert resp.text == "hi"
    assert led.spent("gen") == 2.0
    assert transport.calls[0]["endpoint"] == "e1"


def test_retry_then_success_swaps_endpoint():
    transport = FakeTransport([
        TransportError("503", status=503),
        ModelResponse(text="ok", cost=1.0, raw={}),
    ])
    led = BudgetLedger({"gen": 10.0})
    gw = ModelGateway(SPECS, led, transport, sleep=lambda s: None)
    resp = gw.call("gen", [])
    assert resp.text == "ok"
    assert [c["endpoint"] for c in transport.calls] == ["e1", "e2"]


def test_budget_check_blocks_before_calling():
    transport = FakeTransport([ModelResponse(text="x", cost=1.0, raw={})])
    led = BudgetLedger({"gen": 5.0})
    led.record("gen", 5.0)  # already at cap
    gw = ModelGateway(SPECS, led, transport, sleep=lambda s: None)
    with pytest.raises(BudgetExceeded):
        gw.call("gen", [])
    assert transport.calls == []  # never hit the transport


def test_unknown_role_raises_keyerror():
    gw = ModelGateway(SPECS, BudgetLedger({}), FakeTransport([]), sleep=lambda s: None)
    with pytest.raises(KeyError):
        gw.call("nope", [])
