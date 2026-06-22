# envforge/models/openai_transport.py
from __future__ import annotations

import json
import urllib.request

from .errors import TransportError
from .gateway import ModelResponse, ModelSpec


def _default_http_post(url: str, headers: dict, payload: dict):
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            parsed = json.loads(e.read())
        except Exception:
            parsed = {"error": str(e)}
        return e.code, parsed


class OpenAITransport:
    def __init__(self, api_key: str, *, http_post=_default_http_post):
        self._api_key = api_key
        self._http_post = http_post

    def call(self, endpoint: str, spec: ModelSpec, messages: list[dict], **kw) -> ModelResponse:
        url = f"{endpoint}/chat/completions"
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        payload = {"model": spec.model, "messages": messages, **kw}
        status, data = self._http_post(url, headers, payload)
        if not (200 <= status < 300):
            raise TransportError(json.dumps(data), status=status)
        text = data["choices"][0]["message"].get("content") or ""
        usage = data.get("usage", {})
        cost = float(usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0))
        return ModelResponse(text=text, cost=cost, raw=data)
