# tests/test_openai_transport.py
import pytest
from envforge.models.openai_transport import OpenAITransport
from envforge.models.gateway import ModelSpec, ModelResponse
from envforge.models.errors import TransportError

SPEC = ModelSpec(provider="litellm", model="test/model", endpoints=["http://ep/v1"])


def test_successful_call_parses_text_and_cost():
    def fake_post(url, headers, payload):
        assert url == "http://ep/v1/chat/completions"
        assert payload["model"] == "test/model"
        return 200, {"choices": [{"message": {"content": "hello"}}],
                     "usage": {"prompt_tokens": 3, "completion_tokens": 7}}
    t = OpenAITransport("sk-key", http_post=fake_post)
    resp = t.call("http://ep/v1", SPEC, [{"role": "user", "content": "hi"}])
    assert isinstance(resp, ModelResponse) and resp.text == "hello" and resp.cost == 10


def test_non_2xx_raises_transport_error():
    def fake_post(url, headers, payload):
        return 503, {"error": "overloaded"}
    t = OpenAITransport("sk-key", http_post=fake_post)
    with pytest.raises(TransportError) as ei:
        t.call("http://ep/v1", SPEC, [])
    assert ei.value.status == 503
