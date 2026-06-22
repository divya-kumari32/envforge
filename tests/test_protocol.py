# tests/test_protocol.py
import json
import urllib.request
from pathlib import Path
import pytest
from envforge.kinds.browser_webapp.protocol import StateServer


def _req(method, url, data=None):
    body = json.dumps(data).encode() if data is not None else None
    r = urllib.request.Request(url, data=body, method=method,
                               headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=3) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


@pytest.fixture
def server(tmp_path: Path):
    (tmp_path / "index.html").write_text("<h1>app</h1>")
    s = StateServer(tmp_path, port=0)  # port 0 → OS picks a free port
    s.start()
    yield s
    s.stop()


def test_state_404_before_first_put(server):
    status, _ = _req("GET", f"{server.url}/api/state")
    assert status == 404


def test_put_then_get_roundtrip(server):
    status, _ = _req("PUT", f"{server.url}/api/state", {"count": 1})
    assert status == 204
    status, body = _req("GET", f"{server.url}/api/state")
    assert status == 200 and json.loads(body) == {"count": 1}


def test_reset_restores_seed(server):
    _req("PUT", f"{server.url}/api/state", {"count": 0})       # first PUT = seed
    _req("PUT", f"{server.url}/api/state", {"count": 9})       # mutate
    status, _ = _req("POST", f"{server.url}/api/reset")
    assert status == 200
    _, body = _req("GET", f"{server.url}/api/state")
    assert json.loads(body) == {"count": 0}


def test_static_file_served(server):
    status, body = _req("GET", f"{server.url}/index.html")
    assert status == 200 and b"<h1>app</h1>" in body
