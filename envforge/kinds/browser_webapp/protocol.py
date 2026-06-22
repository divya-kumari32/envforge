# envforge/kinds/browser_webapp/protocol.py
from __future__ import annotations

import json
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class _State:
    def __init__(self) -> None:
        self.current: object | None = None
        self.seed: object | None = None
        self.has_state = False


class _Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, state: _State, **kwargs):
        self._state = state
        super().__init__(*args, **kwargs)

    def log_message(self, *args):  # silence per-request logging
        return

    def _send_json(self, code: int, payload: object) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/state":
            if not self._state.has_state:
                self._send_json(404, {"error": "no state yet"})
            else:
                self._send_json(200, self._state.current)
            return
        super().do_GET()

    def do_PUT(self):
        if self.path == "/api/state":
            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length) or b"null")
            if not self._state.has_state:
                self._state.seed = data
            self._state.current = data
            self._state.has_state = True
            self.send_response(204)
            self.end_headers()
            return
        self.send_response(405)
        self.end_headers()

    def do_POST(self):
        if self.path == "/api/reset":
            self._state.current = self._state.seed
            self._send_json(200, {"ok": True})
            return
        self.send_response(405)
        self.end_headers()


class StateServer:
    def __init__(self, directory: Path, port: int):
        self._state = _State()
        handler = partial(_Handler, state=self._state, directory=str(directory))
        self._httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        host, port = self._httpd.server_address[:2]
        return f"http://{host}:{port}"

    def start(self) -> None:
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        if self._thread:
            self._thread.join(timeout=5)
