# envforge Plan 2 — Browser Web-App Kind + Agents Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `browser_webapp` environment kind to envforge that generates a webarena-style web app, health-gates it, generates a ~24-task function suite + verifiers, runs a single browser-agent eval pass, and records a real pass/fail score — runnable via `envforge run --kind browser_webapp`.

**Architecture:** envforge-original code behind the Plan-1 interfaces. Two pluggable agents — `CodingAgent` (opencode subprocess) and `EvalAgent` (browser_use) — plus an `/api/state` protocol server, 3 health gates, and 5 idempotent phases driven by the existing `Orchestrator`. opencode/browser_use talk directly to the model endpoint; budget is enforced by the endpoint cap and surfaced via error classification. All third-party browser/model objects are dependency-injected so phases and the eval lifecycle are unit-testable with fakes (no real model/browser locally).

**Tech Stack:** Python ≥3.12, `uv`, `pytest`; new runtime deps `browser-use` and `playwright` (used only by the real `EvalAgent`; imported lazily so unit tests don't require them). `opencode` CLI is invoked as a subprocess (only in the real `CodingAgent`).

## Global Constraints

- Python **≥ 3.12**; package import root `envforge`; tests under `tests/`, import from `envforge`.
- **envforge-original code** — do NOT copy webarena-infinity source. Public libraries (`browser_use`, `playwright`, `opencode` CLI) are used directly; their imports are **lazy** (inside methods) so unit tests never import them.
- All model traffic for opencode/browser_use goes **directly to the endpoint** via `OPENAI_API_KEY`/`OPENAI_BASE_URL` (env) or an OpenAI-compatible `llm` adapter. Budget/quota errors are classified → `BUDGET_EXCEEDED` clean exit. envforge's own `ModelGateway` calls (health-fix prompts) use `openai_transport.py`.
- Every phase failure routes through a **classified `ExitCode`** (`APP_UNHEALTHY`, `TASKS_INVALID`, `EVAL_HARNESS_FAILURE`, `BUDGET_EXCEEDED`). No bare `sys.exit`.
- Third-party browser/model objects are **dependency-injected** (constructor params with real defaults) so logic is testable with fakes.
- Run tests with `env -u VIRTUAL_ENV uv run pytest …` for pristine output.
- Commit messages imperative, no `Co-Authored-By`.
- **Branch:** commit directly to `main` (per the amended branch policy — all code on main until the first real exp). **Submission scripts are gitignored, not committed.**

---

## File Structure

```
envforge/agents/
  __init__.py
  base.py             # CodingAgent/EvalAgent Protocols + CodingResult/EvalResult dataclasses
  fakes.py            # FakeCodingAgent, FakeEvalAgent (unit-test doubles)
  opencode_agent.py   # OpencodeAgent (CodingAgent via subprocess; injectable runner)
  browser_eval.py     # BrowserUseEvalAgent (EvalAgent via browser_use; injectable session/agent factories)
envforge/models/
  openai_transport.py # OpenAITransport (real Transport for envforge's OWN gateway calls)
envforge/kinds/
  __init__.py
  base.py             # EnvironmentKind Protocol
  browser_webapp/
    __init__.py
    protocol.py       # /api/state server (envforge-original)
    health.py         # structural / boot+serve / eval-liveness gates
    verifier.py       # load + run task verifier scripts
    kind.py           # BrowserWebAppKind: builds phases + order from agents/config
    prompts/
      generate_app.md  generate_function_tasks.md  fix_app_health.md
    phases/
      __init__.py
      generate_app.py  function_tasks.py  evaluate.py  score.py
envforge/cli.py       # MODIFY: register "browser_webapp" kind factory
tests/                # one test file per module above
```

The Plan-1 core (`Orchestrator`, `RunStore`, `RunLock`, `PortBroker`, `StatusWriter`, `ExitCode`/`EnvforgeExit`, `LocalRuntime`, `ModelGateway`/`BudgetLedger`/`fallback`, `PhaseContext`/`PhaseResult`/`Phase`) is reused unchanged.

---

## Task 1: Agent interfaces + fakes

**Files:**
- Create: `envforge/agents/__init__.py` (empty), `envforge/agents/base.py`, `envforge/agents/fakes.py`
- Test: `tests/test_agents_fakes.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `@dataclass CodingResult`: `ok: bool`, `returncode: int`, `log_path: str`.
  - `@dataclass EvalResult`: `task_id: str`, `passed: bool`, `steps: int = 0`, `elapsed: float = 0.0`, `timed_out: bool = False`, `error: str | None = None`.
  - `class CodingAgent(Protocol)`: `def run(self, prompt: str, *, model: str, cwd: Path, timeout: float, log_path: Path) -> CodingResult`.
  - `class EvalAgent(Protocol)`: `async def setup(self, server_url: str) -> None`; `async def run(self, task_id: str, task: str, server_url: str, task_dir: Path) -> EvalResult`; `async def teardown(self) -> None`.
  - `class FakeCodingAgent`: constructed with `responses: list[dict]` where each dict is `{"files": {relpath: content}, "ok": bool}`; each `run()` pops the next, writes its files under `cwd`, and returns a `CodingResult`. Records `.calls`.
  - `class FakeEvalAgent`: constructed with `results: dict[str, EvalResult]`; `run(task_id, …)` returns `results[task_id]`; `setup`/`teardown` are no-ops; records `.setup_called`/`.tasks_run`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_agents_fakes.py
import asyncio
from pathlib import Path
from envforge.agents.base import CodingResult, EvalResult
from envforge.agents.fakes import FakeCodingAgent, FakeEvalAgent


def test_fake_coding_agent_writes_files(tmp_path: Path):
    agent = FakeCodingAgent([{"files": {"index.html": "<h1>hi</h1>", "server.py": "x=1"}, "ok": True}])
    res = agent.run("build app", model="m", cwd=tmp_path, timeout=10, log_path=tmp_path / "log.txt")
    assert isinstance(res, CodingResult) and res.ok and res.returncode == 0
    assert (tmp_path / "index.html").read_text() == "<h1>hi</h1>"
    assert (tmp_path / "server.py").read_text() == "x=1"
    assert agent.calls[0]["model"] == "m"


def test_fake_coding_agent_consumes_responses_in_order(tmp_path: Path):
    agent = FakeCodingAgent([
        {"files": {"a.txt": "1"}, "ok": True},
        {"files": {"b.txt": "2"}, "ok": False},
    ])
    r1 = agent.run("p1", model="m", cwd=tmp_path, timeout=1, log_path=tmp_path / "l1")
    r2 = agent.run("p2", model="m", cwd=tmp_path, timeout=1, log_path=tmp_path / "l2")
    assert r1.ok and not r2.ok
    assert (tmp_path / "a.txt").exists() and (tmp_path / "b.txt").exists()


def test_fake_eval_agent_returns_scripted(tmp_path: Path):
    fake = FakeEvalAgent({"task_e1": EvalResult(task_id="task_e1", passed=True, steps=4)})

    async def go():
        await fake.setup("http://x")
        r = await fake.run("task_e1", "do thing", "http://x", tmp_path)
        await fake.teardown()
        return r

    r = asyncio.run(go())
    assert r.passed and r.steps == 4
    assert fake.setup_called and fake.tasks_run == ["task_e1"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `env -u VIRTUAL_ENV uv run pytest tests/test_agents_fakes.py -v`
Expected: FAIL — `ModuleNotFoundError: envforge.agents.base`.

- [ ] **Step 3: Write minimal implementation**

```python
# envforge/agents/base.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass
class CodingResult:
    ok: bool
    returncode: int
    log_path: str


@dataclass
class EvalResult:
    task_id: str
    passed: bool
    steps: int = 0
    elapsed: float = 0.0
    timed_out: bool = False
    error: str | None = None


class CodingAgent(Protocol):
    def run(self, prompt: str, *, model: str, cwd: Path, timeout: float, log_path: Path) -> CodingResult:
        ...


class EvalAgent(Protocol):
    async def setup(self, server_url: str) -> None: ...
    async def run(self, task_id: str, task: str, server_url: str, task_dir: Path) -> EvalResult: ...
    async def teardown(self) -> None: ...
```

```python
# envforge/agents/fakes.py
from __future__ import annotations

from pathlib import Path

from .base import CodingResult, EvalResult


class FakeCodingAgent:
    def __init__(self, responses: list[dict]):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def run(self, prompt: str, *, model: str, cwd: Path, timeout: float, log_path: Path) -> CodingResult:
        self.calls.append({"prompt": prompt, "model": model, "cwd": Path(cwd)})
        spec = self._responses.pop(0)
        for rel, content in spec.get("files", {}).items():
            target = Path(cwd) / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        Path(log_path).write_text("fake coding agent log\n", encoding="utf-8")
        ok = spec.get("ok", True)
        return CodingResult(ok=ok, returncode=0 if ok else 1, log_path=str(log_path))


class FakeEvalAgent:
    def __init__(self, results: dict[str, EvalResult]):
        self._results = dict(results)
        self.setup_called = False
        self.tasks_run: list[str] = []

    async def setup(self, server_url: str) -> None:
        self.setup_called = True

    async def run(self, task_id: str, task: str, server_url: str, task_dir: Path) -> EvalResult:
        self.tasks_run.append(task_id)
        return self._results[task_id]

    async def teardown(self) -> None:
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `env -u VIRTUAL_ENV uv run pytest tests/test_agents_fakes.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add envforge/agents/__init__.py envforge/agents/base.py envforge/agents/fakes.py tests/test_agents_fakes.py
git commit -m "Add CodingAgent/EvalAgent interfaces and test fakes"
```

---

## Task 2: EnvironmentKind interface

**Files:**
- Create: `envforge/kinds/__init__.py` (empty), `envforge/kinds/base.py`
- Test: `tests/test_kind_base.py`

**Interfaces:**
- Consumes: `Phase` (from `envforge.phases.base`, Plan 1).
- Produces: `class EnvironmentKind(Protocol)`: attribute `name: str`; `def phases(self) -> list[Phase]`; `def order(self) -> list[str]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_kind_base.py
from envforge.kinds.base import EnvironmentKind


class _DummyPhase:
    name = "p1"
    def run(self, ctx):  # pragma: no cover - not executed here
        ...


class _DummyKind:
    name = "dummy"
    def phases(self):
        return [_DummyPhase()]
    def order(self):
        return ["p1"]


def test_dummy_kind_satisfies_protocol():
    k: EnvironmentKind = _DummyKind()
    assert k.name == "dummy"
    assert [p.name for p in k.phases()] == k.order()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `env -u VIRTUAL_ENV uv run pytest tests/test_kind_base.py -v`
Expected: FAIL — `ModuleNotFoundError: envforge.kinds.base`.

- [ ] **Step 3: Write minimal implementation**

```python
# envforge/kinds/base.py
from __future__ import annotations

from typing import Protocol

from ..phases.base import Phase


class EnvironmentKind(Protocol):
    name: str

    def phases(self) -> list[Phase]: ...
    def order(self) -> list[str]: ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `env -u VIRTUAL_ENV uv run pytest tests/test_kind_base.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add envforge/kinds/__init__.py envforge/kinds/base.py tests/test_kind_base.py
git commit -m "Add EnvironmentKind protocol"
```

---

## Task 3: /api/state protocol server

**Files:**
- Create: `envforge/kinds/browser_webapp/__init__.py` (empty), `envforge/kinds/browser_webapp/protocol.py`
- Test: `tests/test_protocol.py`

**Interfaces:**
- Consumes: nothing (stdlib `http.server`, `threading`, `json`).
- Produces:
  - `class StateServer`: `StateServer(directory: Path, port: int)`; `.start()` (background thread), `.stop()`, `.url -> str`.
  - Endpoints: `GET /api/state` → 200 with current state JSON, or 404 if no state PUT yet; `PUT /api/state` (body = full state JSON) → captures `_seed_state` on first PUT, updates current state, 204; `POST /api/reset` → restores `_seed_state` as current, 200; static file serving for any other path from `directory`.

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `env -u VIRTUAL_ENV uv run pytest tests/test_protocol.py -v`
Expected: FAIL — `ModuleNotFoundError: envforge.kinds.browser_webapp.protocol`.

- [ ] **Step 3: Write minimal implementation**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `env -u VIRTUAL_ENV uv run pytest tests/test_protocol.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add envforge/kinds/browser_webapp/__init__.py envforge/kinds/browser_webapp/protocol.py tests/test_protocol.py
git commit -m "Add /api/state protocol server"
```

---

## Task 4: OpencodeAgent (CodingAgent via subprocess)

**Files:**
- Create: `envforge/agents/opencode_agent.py`
- Test: `tests/test_opencode_agent.py`

**Interfaces:**
- Consumes: `CodingResult` (Task 1).
- Produces:
  - `class OpencodeAgent`: `OpencodeAgent(*, runner=subprocess.run)`. `run(prompt, *, model, cwd, timeout, log_path) -> CodingResult` builds `["opencode", "run", "--model", model, prompt]`, invokes `runner(cmd, cwd=str(cwd), stdout=<log file>, stderr=STDOUT, timeout=timeout)`, writes combined output to `log_path`, returns `CodingResult(ok=returncode==0, returncode, str(log_path))`. On `subprocess.TimeoutExpired` → `CodingResult(ok=False, returncode=124, …)` and append a timeout note to the log. `runner` is injected for testing.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_opencode_agent.py
import subprocess
from pathlib import Path
from envforge.agents.opencode_agent import OpencodeAgent


def test_builds_command_and_succeeds(tmp_path: Path):
    captured = {}
    def fake_runner(cmd, cwd, stdout, stderr, timeout):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        stdout.write(b"generated ok\n")
        return subprocess.CompletedProcess(cmd, 0)
    agent = OpencodeAgent(runner=fake_runner)
    res = agent.run("make app", model="litellm/your-coding-model", cwd=tmp_path, timeout=30, log_path=tmp_path / "gen.log")
    assert res.ok and res.returncode == 0
    assert captured["cmd"] == ["opencode", "run", "--model", "litellm/your-coding-model", "make app"]
    assert captured["cwd"] == str(tmp_path)
    assert b"generated ok" in (tmp_path / "gen.log").read_bytes()


def test_nonzero_returncode_is_not_ok(tmp_path: Path):
    def fake_runner(cmd, cwd, stdout, stderr, timeout):
        stdout.write(b"boom\n")
        return subprocess.CompletedProcess(cmd, 2)
    agent = OpencodeAgent(runner=fake_runner)
    res = agent.run("p", model="m", cwd=tmp_path, timeout=30, log_path=tmp_path / "g.log")
    assert not res.ok and res.returncode == 2


def test_timeout_is_classified(tmp_path: Path):
    def fake_runner(cmd, cwd, stdout, stderr, timeout):
        raise subprocess.TimeoutExpired(cmd, timeout)
    agent = OpencodeAgent(runner=fake_runner)
    res = agent.run("p", model="m", cwd=tmp_path, timeout=5, log_path=tmp_path / "g.log")
    assert not res.ok and res.returncode == 124
    assert "timeout" in (tmp_path / "g.log").read_text().lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `env -u VIRTUAL_ENV uv run pytest tests/test_opencode_agent.py -v`
Expected: FAIL — `ModuleNotFoundError: envforge.agents.opencode_agent`.

- [ ] **Step 3: Write minimal implementation**

```python
# envforge/agents/opencode_agent.py
from __future__ import annotations

import subprocess
from pathlib import Path

from .base import CodingResult


class OpencodeAgent:
    def __init__(self, *, runner=subprocess.run):
        self._runner = runner

    def run(self, prompt: str, *, model: str, cwd: Path, timeout: float, log_path: Path) -> CodingResult:
        cmd = ["opencode", "run", "--model", model, prompt]
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "wb") as log:
            try:
                proc = self._runner(
                    cmd, cwd=str(cwd), stdout=log, stderr=subprocess.STDOUT, timeout=timeout
                )
            except subprocess.TimeoutExpired:
                log.write(f"\n[opencode] TIMEOUT after {timeout}s\n".encode())
                return CodingResult(ok=False, returncode=124, log_path=str(log_path))
        return CodingResult(ok=proc.returncode == 0, returncode=proc.returncode, log_path=str(log_path))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `env -u VIRTUAL_ENV uv run pytest tests/test_opencode_agent.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add envforge/agents/opencode_agent.py tests/test_opencode_agent.py
git commit -m "Add OpencodeAgent subprocess wrapper with classified timeout"
```

---

## Task 5: Verifier loader/runner

**Files:**
- Create: `envforge/kinds/browser_webapp/verifier.py`
- Test: `tests/test_verifier.py`

**Interfaces:**
- Consumes: nothing (stdlib `importlib.util`).
- Produces:
  - `@dataclass VerifyOutcome`: `passed: bool`, `detail: str`.
  - `def run_verifier(verifier_path: Path, server_url: str) -> VerifyOutcome` — loads the module at `verifier_path`, calls its `verify(server_url) -> tuple[bool, str]`, returns a `VerifyOutcome`. Any exception (missing `verify`, raise inside) → `VerifyOutcome(False, "<error>")` (never propagates).

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `env -u VIRTUAL_ENV uv run pytest tests/test_verifier.py -v`
Expected: FAIL — `ModuleNotFoundError: envforge.kinds.browser_webapp.verifier`.

- [ ] **Step 3: Write minimal implementation**

```python
# envforge/kinds/browser_webapp/verifier.py
from __future__ import annotations

import importlib.util
import uuid
from dataclasses import dataclass
from pathlib import Path


@dataclass
class VerifyOutcome:
    passed: bool
    detail: str


def run_verifier(verifier_path: Path, server_url: str) -> VerifyOutcome:
    try:
        spec = importlib.util.spec_from_file_location(f"verifier_{uuid.uuid4().hex}", verifier_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        verify = getattr(module, "verify", None)
        if verify is None:
            return VerifyOutcome(False, "verifier has no verify(server_url) function")
        passed, detail = verify(server_url)
        return VerifyOutcome(bool(passed), str(detail))
    except Exception as exc:  # noqa: BLE001 — a broken verifier must never crash eval
        return VerifyOutcome(False, f"{type(exc).__name__}: {exc}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `env -u VIRTUAL_ENV uv run pytest tests/test_verifier.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add envforge/kinds/browser_webapp/verifier.py tests/test_verifier.py
git commit -m "Add verifier loader/runner with crash isolation"
```

---

## Task 6: Health gates

**Files:**
- Create: `envforge/kinds/browser_webapp/health.py`
- Test: `tests/test_health.py`

**Interfaces:**
- Consumes: `StateServer` (Task 3); `EvalAgent` (Task 1); `PortBroker` (Plan 1).
- Produces:
  - `@dataclass HealthReport`: `ok: bool`, `gate: str`, `detail: str` (`gate` ∈ `structural`/`boot_serve`/`eval_liveness`/`all`).
  - `REQUIRED_FILES = ["index.html", "server.py"]`.
  - `def structural_gate(app_dir: Path) -> HealthReport` — all `REQUIRED_FILES` exist and non-empty.
  - `async def boot_serve_gate(app_dir: Path, port: int) -> HealthReport` — start a `StateServer` on `port`, PUT a probe state, GET it back 200; **restart the server** (stop+start a fresh instance) and confirm `GET /api/state` is 404 again (proving state is not persisted on disk — i.e. the app drives it), then stop. (This is the "restart between checks" guard.)
  - `async def eval_liveness_gate(eval_agent: EvalAgent, server_url: str) -> HealthReport` — `await eval_agent.setup(server_url)` then `await eval_agent.teardown()`; any exception → not-ok.
  - `async def run_all_gates(app_dir, *, port, eval_agent, server_url) -> HealthReport` — run gates in order, short-circuit on first failure, else `HealthReport(True, "all", "")`.

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `env -u VIRTUAL_ENV uv run pytest tests/test_health.py -v`
Expected: FAIL — `ModuleNotFoundError: envforge.kinds.browser_webapp.health`.

- [ ] **Step 3: Write minimal implementation**

```python
# envforge/kinds/browser_webapp/health.py
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from ...agents.base import EvalAgent
from .protocol import StateServer

REQUIRED_FILES = ["index.html", "server.py"]


@dataclass
class HealthReport:
    ok: bool
    gate: str
    detail: str


def structural_gate(app_dir: Path) -> HealthReport:
    for f in REQUIRED_FILES:
        p = Path(app_dir) / f
        if not p.exists():
            return HealthReport(False, "structural", f"missing required file: {f}")
        if p.stat().st_size == 0:
            return HealthReport(False, "structural", f"required file is empty: {f}")
    return HealthReport(True, "structural", "")


def _get_state_status(url: str) -> int:
    try:
        with urllib.request.urlopen(f"{url}/api/state", timeout=3) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def _put_state(url: str, data: object) -> None:
    body = json.dumps(data).encode()
    req = urllib.request.Request(f"{url}/api/state", data=body, method="PUT",
                                 headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=3).read()


async def boot_serve_gate(app_dir: Path, port: int) -> HealthReport:
    server = StateServer(Path(app_dir), port=port)
    server.start()
    try:
        _put_state(server.url, {"probe": 1})
        if _get_state_status(server.url) != 200:
            return HealthReport(False, "boot_serve", "GET /api/state did not return 200 after PUT")
    finally:
        server.stop()
    # Restart on a fresh server: state must NOT survive a restart (the app drives it,
    # so a stale on-disk seed cannot mask a broken-JS app).
    server2 = StateServer(Path(app_dir), port=port)
    server2.start()
    try:
        if _get_state_status(server2.url) != 404:
            return HealthReport(False, "boot_serve", "state unexpectedly persisted across restart")
    finally:
        server2.stop()
    return HealthReport(True, "boot_serve", "")


async def eval_liveness_gate(eval_agent: EvalAgent, server_url: str) -> HealthReport:
    try:
        await eval_agent.setup(server_url)
        await eval_agent.teardown()
    except Exception as exc:  # noqa: BLE001
        return HealthReport(False, "eval_liveness", f"{type(exc).__name__}: {exc}")
    return HealthReport(True, "eval_liveness", "")


async def run_all_gates(app_dir: Path, *, port: int, eval_agent: EvalAgent, server_url: str) -> HealthReport:
    rep = structural_gate(app_dir)
    if not rep.ok:
        return rep
    rep = await boot_serve_gate(app_dir, port)
    if not rep.ok:
        return rep
    rep = await eval_liveness_gate(eval_agent, server_url)
    if not rep.ok:
        return rep
    return HealthReport(True, "all", "")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `env -u VIRTUAL_ENV uv run pytest tests/test_health.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add envforge/kinds/browser_webapp/health.py tests/test_health.py
git commit -m "Add health gates: structural, boot+serve (restart between), eval-liveness"
```

---

## Task 7: BrowserUseEvalAgent (real eval agent, injectable)

**Files:**
- Create: `envforge/agents/browser_eval.py`
- Test: `tests/test_browser_eval.py`

**Interfaces:**
- Consumes: `EvalResult` (Task 1); `run_verifier`/`VerifyOutcome` (Task 5).
- Produces:
  - `class BrowserUseEvalAgent`: `BrowserUseEvalAgent(llm, *, verifier_dir: Path, max_steps=50, timeout=300, max_restarts=3, session_factory=None, agent_factory=None, sleep=asyncio.sleep)`. `session_factory()` returns a browser session object (lazily defaults to `browser_use.BrowserSession`); `agent_factory(task, llm, session, max_steps)` returns an agent object whose `await run()` returns a history with `.is_done()` and `.history`. Injecting these lets us test the lifecycle without a real browser.
  - Reliability behaviors (each tested): `setup` polls `GET /api/state` until 200 (≤10 tries) then raises `EvalHarnessError` if never ready; `run` enforces `timeout` (on timeout → `EvalResult(timed_out=True, passed=False)` after saving partial history); on a retryable session error during `run`, restart the session up to `max_restarts`; after the agent finishes, run the task's verifier (`<verifier_dir>/<task_id>.py`) to decide `passed`.
  - `class EvalHarnessError(Exception)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_browser_eval.py
import asyncio
from pathlib import Path
import pytest
from envforge.agents.browser_eval import BrowserUseEvalAgent, EvalHarnessError


class FakeSession:
    def __init__(self): self.started = self.killed = False
    async def start(self): self.started = True
    async def kill(self): self.killed = True


class FakeHistory:
    def __init__(self, done=True, steps=3):
        self._done, self.history = done, list(range(steps))
    def is_done(self): return self._done
    def save_to_file(self, p): Path(p).write_text("history")
    def screenshot_paths(self): return []


class FakeAgent:
    def __init__(self, history=None, raises=None, hang=False):
        self._history, self._raises, self._hang = history or FakeHistory(), raises, hang
        self.history = self._history
    async def run(self):
        if self._raises: raise self._raises
        if self._hang: await asyncio.sleep(10)
        return self._history


def _verifier_dir(tmp_path, task_id, passed):
    d = tmp_path / "verifiers"; d.mkdir(exist_ok=True)
    (d / f"{task_id}.py").write_text(f"def verify(u):\n    return {passed}, 'v'\n")
    return d


def test_run_passes_when_verifier_passes(tmp_path: Path):
    vd = _verifier_dir(tmp_path, "task_e1", True)
    agent = BrowserUseEvalAgent(
        llm=object(), verifier_dir=vd,
        session_factory=lambda: FakeSession(),
        agent_factory=lambda **kw: FakeAgent(FakeHistory(done=True, steps=5)),
        sleep=lambda s: asyncio.sleep(0),
    )
    async def go():
        return await agent.run("task_e1", "do x", "http://x", tmp_path / "t1")
    res = asyncio.run(go())
    assert res.passed and res.steps == 5 and not res.timed_out


def test_run_fails_when_verifier_fails(tmp_path: Path):
    vd = _verifier_dir(tmp_path, "task_e2", False)
    agent = BrowserUseEvalAgent(
        llm=object(), verifier_dir=vd,
        session_factory=lambda: FakeSession(),
        agent_factory=lambda **kw: FakeAgent(FakeHistory(done=True)),
        sleep=lambda s: asyncio.sleep(0),
    )
    res = asyncio.run(agent.run("task_e2", "do x", "http://x", tmp_path / "t2"))
    assert not res.passed


def test_run_timeout_sets_timed_out(tmp_path: Path):
    vd = _verifier_dir(tmp_path, "task_e3", True)
    agent = BrowserUseEvalAgent(
        llm=object(), verifier_dir=vd, timeout=0.05,
        session_factory=lambda: FakeSession(),
        agent_factory=lambda **kw: FakeAgent(hang=True),
        sleep=lambda s: asyncio.sleep(0),
    )
    res = asyncio.run(agent.run("task_e3", "do x", "http://x", tmp_path / "t3"))
    assert res.timed_out and not res.passed


def test_run_restarts_session_on_retryable_error(tmp_path: Path):
    vd = _verifier_dir(tmp_path, "task_e4", True)
    sessions = []
    def make_session():
        s = FakeSession(); sessions.append(s); return s
    calls = {"n": 0}
    def make_agent(**kw):
        calls["n"] += 1
        if calls["n"] == 1:
            return FakeAgent(raises=ConnectionError("CDP died"))
        return FakeAgent(FakeHistory(done=True))
    agent = BrowserUseEvalAgent(
        llm=object(), verifier_dir=vd, max_restarts=3,
        session_factory=make_session, agent_factory=make_agent,
        sleep=lambda s: asyncio.sleep(0),
    )
    res = asyncio.run(agent.run("task_e4", "do x", "http://x", tmp_path / "t4"))
    assert res.passed
    assert len(sessions) >= 2  # restarted at least once
```

- [ ] **Step 2: Run test to verify it fails**

Run: `env -u VIRTUAL_ENV uv run pytest tests/test_browser_eval.py -v`
Expected: FAIL — `ModuleNotFoundError: envforge.agents.browser_eval`.

- [ ] **Step 3: Write minimal implementation**

```python
# envforge/agents/browser_eval.py
from __future__ import annotations

import asyncio
from pathlib import Path

from ..kinds.browser_webapp.verifier import run_verifier
from .base import EvalResult


class EvalHarnessError(Exception):
    pass


def _is_retryable(exc: Exception) -> bool:
    return isinstance(exc, (ConnectionError, TimeoutError, OSError))


class BrowserUseEvalAgent:
    def __init__(
        self,
        llm,
        *,
        verifier_dir: Path,
        max_steps: int = 50,
        timeout: float = 300.0,
        max_restarts: int = 3,
        session_factory=None,
        agent_factory=None,
        sleep=asyncio.sleep,
    ):
        self._llm = llm
        self._verifier_dir = Path(verifier_dir)
        self._max_steps = max_steps
        self._timeout = timeout
        self._max_restarts = max_restarts
        self._session_factory = session_factory or self._default_session_factory
        self._agent_factory = agent_factory or self._default_agent_factory
        self._sleep = sleep
        self._session = None
        self._server_url: str | None = None

    @staticmethod
    def _default_session_factory():
        from browser_use import BrowserSession  # lazy import
        return BrowserSession(headless=True, keep_alive=True)

    @staticmethod
    def _default_agent_factory(*, task, llm, session, max_steps):
        from browser_use import Agent  # lazy import
        return Agent(task=task, llm=llm, browser_session=session, max_steps=max_steps)

    async def _start_session(self):
        self._session = self._session_factory()
        await self._session.start()

    async def setup(self, server_url: str) -> None:
        self._server_url = server_url
        await self._start_session()
        import urllib.error
        import urllib.request
        for _ in range(10):
            await self._sleep(1.0)
            try:
                with urllib.request.urlopen(f"{server_url}/api/state", timeout=2) as r:
                    if r.status == 200:
                        return
            except urllib.error.HTTPError:
                continue
            except Exception:
                continue
        raise EvalHarnessError("seed state not captured: GET /api/state never returned 200")

    async def teardown(self) -> None:
        if self._session is not None:
            try:
                await self._session.kill()
            finally:
                self._session = None

    async def run(self, task_id: str, task: str, server_url: str, task_dir: Path) -> EvalResult:
        task_dir = Path(task_dir)
        task_dir.mkdir(parents=True, exist_ok=True)
        instruction = f"You are interacting with a web application at {server_url}. Your task: {task}"

        history = None
        attempts = 0
        while True:
            attempts += 1
            agent = self._agent_factory(
                task=instruction, llm=self._llm, session=self._session, max_steps=self._max_steps
            )
            try:
                history = await asyncio.wait_for(agent.run(), timeout=self._timeout)
                break
            except asyncio.TimeoutError:
                partial = getattr(agent, "history", None)
                if partial is not None:
                    try:
                        partial.save_to_file(str(task_dir / "history.json"))
                    except Exception:
                        pass
                return EvalResult(task_id=task_id, passed=False, timed_out=True)
            except Exception as exc:  # noqa: BLE001
                if _is_retryable(exc) and attempts <= self._max_restarts:
                    await self.teardown()
                    await self._start_session()
                    await self._sleep(1.0)
                    continue
                return EvalResult(task_id=task_id, passed=False, error=f"{type(exc).__name__}: {exc}")

        try:
            history.save_to_file(str(task_dir / "history.json"))
        except Exception:
            pass

        outcome = run_verifier(self._verifier_dir / f"{task_id}.py", server_url)
        return EvalResult(
            task_id=task_id,
            passed=outcome.passed,
            steps=len(getattr(history, "history", []) or []),
            timed_out=False,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `env -u VIRTUAL_ENV uv run pytest tests/test_browser_eval.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add envforge/agents/browser_eval.py tests/test_browser_eval.py
git commit -m "Add BrowserUseEvalAgent with seed-poll, restart-retry, timeout, verifier scoring"
```

---

## Task 8: OpenAITransport (real gateway transport)

**Files:**
- Create: `envforge/models/openai_transport.py`
- Test: `tests/test_openai_transport.py`

**Interfaces:**
- Consumes: `ModelResponse`, `ModelSpec` (Plan 1 `models/gateway.py`); `TransportError` (Plan 1 `models/errors.py`).
- Produces:
  - `class OpenAITransport`: `OpenAITransport(api_key: str, *, http_post=None)`. `call(endpoint, spec, messages, **kw) -> ModelResponse` POSTs an OpenAI-compatible chat-completions request to `f"{endpoint}/chat/completions"` with `model=spec.model`; on a non-2xx response raises `TransportError(body, status=code)`; parses `choices[0].message.content` → text and `usage` → a coarse `cost` (sum of tokens; cost model is out of scope, use total tokens as the spend unit). `http_post` is injected for testing (defaults to a `urllib`-based POST).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_openai_transport.py
import pytest
from envforge.models.openai_transport import OpenAITransport
from envforge.models.gateway import ModelSpec, ModelResponse
from envforge.models.errors import TransportError

SPEC = ModelSpec(provider="litellm", model="litellm/your-coding-model", endpoints=["http://ep/v1"])


def test_successful_call_parses_text_and_cost():
    def fake_post(url, headers, payload):
        assert url == "http://ep/v1/chat/completions"
        assert payload["model"] == "litellm/your-coding-model"
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `env -u VIRTUAL_ENV uv run pytest tests/test_openai_transport.py -v`
Expected: FAIL — `ModuleNotFoundError: envforge.models.openai_transport`.

- [ ] **Step 3: Write minimal implementation**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `env -u VIRTUAL_ENV uv run pytest tests/test_openai_transport.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add envforge/models/openai_transport.py tests/test_openai_transport.py
git commit -m "Add OpenAITransport for envforge's own gateway calls"
```

---

## Task 9: generate_app + generate_function_tasks phases (+ prompts)

**Files:**
- Create: `envforge/kinds/browser_webapp/phases/__init__.py` (empty), `envforge/kinds/browser_webapp/phases/generate_app.py`, `envforge/kinds/browser_webapp/phases/function_tasks.py`, `envforge/kinds/browser_webapp/prompts/generate_app.md`, `envforge/kinds/browser_webapp/prompts/generate_function_tasks.md`
- Test: `tests/test_gen_phases.py`

**Interfaces:**
- Consumes: `PhaseResult`, `PhaseContext` (Plan 1 `phases/base.py`); `CodingAgent` (Task 1); `ExitCode` (Plan 1).
- Produces:
  - `class GenerateAppPhase`: `name="generate_app"`. `GenerateAppPhase(coding_agent, *, model, docs_path, app_dir_key="app_dir", timeout=3600)`. `run(ctx)`: builds the app dir at `ctx.runstore.run_dir / "app"`, reads the `generate_app.md` prompt, calls `coding_agent.run(prompt+docs context, model, cwd=app_dir, …)`, then output-validates that `index.html` and `server.py` exist non-empty. Stores `app_dir` in the result. Failure → `PhaseResult.fail(ExitCode.TASKS_INVALID, …)`.
  - `class GenerateFunctionTasksPhase`: `name="generate_function_tasks"`. `GenerateFunctionTasksPhase(coding_agent, *, model, expected_count=24, timeout=1800)`. `run(ctx)`: reads the app_dir from the `generate_app` step result, calls the agent with the `generate_function_tasks.md` prompt, then validates `function-tasks.json` parses to a list of `expected_count` task objects (each with `id`, `prompt`) and that a verifier file exists per task id under `<app_dir>/verifiers/`. Failure → `PhaseResult.fail(ExitCode.TASKS_INVALID, …)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_gen_phases.py
import json
from pathlib import Path
from envforge.core.runstore import RunStore, StepStatus
from envforge.core.exits import ExitCode
from envforge.phases.base import PhaseContext
from envforge.agents.fakes import FakeCodingAgent
from envforge.kinds.browser_webapp.phases.generate_app import GenerateAppPhase
from envforge.kinds.browser_webapp.phases.function_tasks import GenerateFunctionTasksPhase

NOW = "2026-06-22T00:00:00Z"


def _ctx(tmp_path, rs):
    return PhaseContext(runstore=rs, gateway=None, ports=None, status=None,
                        runtime=None, config={}, now=lambda: NOW)


def _tasks_json(n):
    return json.dumps([{"id": f"task_{i}", "prompt": f"do {i}"} for i in range(n)])


def test_generate_app_ok(tmp_path):
    rs = RunStore.create(tmp_path / "runs", "r", "browser_webapp", now=NOW)
    agent = FakeCodingAgent([{"files": {"index.html": "<h1>a</h1>", "server.py": "x=1"}, "ok": True}])
    phase = GenerateAppPhase(agent, model="m", docs_path=tmp_path / "docs")
    (tmp_path / "docs").mkdir()
    res = phase.run(_ctx(tmp_path, rs))
    assert res.ok and (Path(res.result["app_dir"]) / "index.html").exists()


def test_generate_app_fails_when_files_missing(tmp_path):
    rs = RunStore.create(tmp_path / "runs", "r", "browser_webapp", now=NOW)
    agent = FakeCodingAgent([{"files": {"index.html": "<h1>a</h1>"}, "ok": True}])  # no server.py
    (tmp_path / "docs").mkdir()
    res = GenerateAppPhase(agent, model="m", docs_path=tmp_path / "docs").run(_ctx(tmp_path, rs))
    assert not res.ok and res.exit_code is ExitCode.TASKS_INVALID


def test_generate_function_tasks_ok(tmp_path):
    rs = RunStore.create(tmp_path / "runs", "r", "browser_webapp", now=NOW)
    app_dir = rs.run_dir / "app"; (app_dir / "verifiers").mkdir(parents=True)
    rs.set_step("generate_app", StepStatus.DONE, result={"app_dir": str(app_dir)}, now=NOW)
    files = {"function-tasks.json": _tasks_json(24)}
    for i in range(24):
        files[f"verifiers/task_{i}.py"] = "def verify(u):\n    return True, 'ok'\n"
    agent = FakeCodingAgent([{"files": files, "ok": True}])
    res = GenerateFunctionTasksPhase(agent, model="m", expected_count=24).run(_ctx(tmp_path, rs))
    assert res.ok and res.result["task_count"] == 24


def test_generate_function_tasks_wrong_count_fails(tmp_path):
    rs = RunStore.create(tmp_path / "runs", "r", "browser_webapp", now=NOW)
    app_dir = rs.run_dir / "app"; (app_dir / "verifiers").mkdir(parents=True)
    rs.set_step("generate_app", StepStatus.DONE, result={"app_dir": str(app_dir)}, now=NOW)
    agent = FakeCodingAgent([{"files": {"function-tasks.json": _tasks_json(5)}, "ok": True}])
    res = GenerateFunctionTasksPhase(agent, model="m", expected_count=24).run(_ctx(tmp_path, rs))
    assert not res.ok and res.exit_code is ExitCode.TASKS_INVALID
```

- [ ] **Step 2: Run test to verify it fails**

Run: `env -u VIRTUAL_ENV uv run pytest tests/test_gen_phases.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Write the prompts**

`envforge/kinds/browser_webapp/prompts/generate_app.md`:
```markdown
Build a single-page web application in the current directory from the provided
documentation. Requirements:
- Entry point `index.html` plus `js/` and `css/` as needed.
- A `server.py` that serves static files AND implements the state protocol:
  GET /api/state (current state JSON; 404 before first PUT), PUT /api/state
  (full state; first PUT is captured as the immutable seed), POST /api/reset
  (restore seed), GET /api/events (SSE reset stream).
- On first load the browser must PUT its full initial state to /api/state.
- No native dialogs (alert/confirm/<select>); use custom JS-rendered widgets.
- Rich, realistic seed data.
```

`envforge/kinds/browser_webapp/prompts/generate_function_tasks.md`:
```markdown
Generate exactly 24 function-level tasks (8 easy, 8 medium, 8 hard) for the app
in the current directory. Write `function-tasks.json` as a JSON array; each task
object has: `id` (e.g. "task_e1"), `prompt` (instruction for a browser agent),
`difficulty` (easy|medium|hard). For each task write a verifier at
`verifiers/<id>.py` exporting `verify(server_url) -> (bool, str)` that reads
GET /api/state and checks the expected outcome (never interacts with the UI).
```

- [ ] **Step 4: Write the phases**

```python
# envforge/kinds/browser_webapp/phases/generate_app.py
from __future__ import annotations

from pathlib import Path

from ....core.exits import ExitCode
from ....phases.base import PhaseContext, PhaseResult

_PROMPT = (Path(__file__).resolve().parents[1] / "prompts" / "generate_app.md").read_text()


class GenerateAppPhase:
    name = "generate_app"

    def __init__(self, coding_agent, *, model: str, docs_path: Path, timeout: float = 3600.0):
        self._agent = coding_agent
        self._model = model
        self._docs_path = Path(docs_path)
        self._timeout = timeout

    def run(self, ctx: PhaseContext) -> PhaseResult:
        app_dir = ctx.runstore.run_dir / "app"
        app_dir.mkdir(parents=True, exist_ok=True)
        prompt = f"{_PROMPT}\n\nDocumentation source: {self._docs_path}\n"
        log_path = ctx.runstore.run_dir / "logs" / "generate_app.log"
        result = self._agent.run(prompt, model=self._model, cwd=app_dir,
                                 timeout=self._timeout, log_path=log_path)
        if not result.ok:
            return PhaseResult.fail(ExitCode.TASKS_INVALID, f"generate_app agent failed (rc={result.returncode})")
        for f in ("index.html", "server.py"):
            p = app_dir / f
            if not p.exists() or p.stat().st_size == 0:
                return PhaseResult.fail(ExitCode.TASKS_INVALID, f"generated app missing/empty {f}")
        return PhaseResult.done(app_dir=str(app_dir))
```

```python
# envforge/kinds/browser_webapp/phases/function_tasks.py
from __future__ import annotations

import json
from pathlib import Path

from ....core.exits import ExitCode
from ....phases.base import PhaseContext, PhaseResult

_PROMPT = (Path(__file__).resolve().parents[1] / "prompts" / "generate_function_tasks.md").read_text()


class GenerateFunctionTasksPhase:
    name = "generate_function_tasks"

    def __init__(self, coding_agent, *, model: str, expected_count: int = 24, timeout: float = 1800.0):
        self._agent = coding_agent
        self._model = model
        self._expected = expected_count
        self._timeout = timeout

    def run(self, ctx: PhaseContext) -> PhaseResult:
        app_dir = Path(ctx.runstore.state["steps"]["generate_app"]["result"]["app_dir"])
        log_path = ctx.runstore.run_dir / "logs" / "generate_function_tasks.log"
        result = self._agent.run(_PROMPT, model=self._model, cwd=app_dir,
                                 timeout=self._timeout, log_path=log_path)
        if not result.ok:
            return PhaseResult.fail(ExitCode.TASKS_INVALID, f"function-task gen failed (rc={result.returncode})")
        tasks_file = app_dir / "function-tasks.json"
        if not tasks_file.exists():
            return PhaseResult.fail(ExitCode.TASKS_INVALID, "function-tasks.json missing")
        try:
            tasks = json.loads(tasks_file.read_text())
        except json.JSONDecodeError as e:
            return PhaseResult.fail(ExitCode.TASKS_INVALID, f"function-tasks.json invalid JSON: {e}")
        if not isinstance(tasks, list) or len(tasks) != self._expected:
            return PhaseResult.fail(ExitCode.TASKS_INVALID,
                                    f"expected {self._expected} tasks, got {len(tasks) if isinstance(tasks, list) else 'non-list'}")
        for t in tasks:
            if "id" not in t or "prompt" not in t:
                return PhaseResult.fail(ExitCode.TASKS_INVALID, "task missing id/prompt")
            if not (app_dir / "verifiers" / f"{t['id']}.py").exists():
                return PhaseResult.fail(ExitCode.TASKS_INVALID, f"missing verifier for {t['id']}")
        return PhaseResult.done(task_count=len(tasks))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `env -u VIRTUAL_ENV uv run pytest tests/test_gen_phases.py -v`
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add envforge/kinds/browser_webapp/phases/__init__.py envforge/kinds/browser_webapp/phases/generate_app.py envforge/kinds/browser_webapp/phases/function_tasks.py envforge/kinds/browser_webapp/prompts/generate_app.md envforge/kinds/browser_webapp/prompts/generate_function_tasks.md tests/test_gen_phases.py
git commit -m "Add generate_app and generate_function_tasks phases with output validation"
```

---

## Task 10: evaluate + score phases

**Files:**
- Create: `envforge/kinds/browser_webapp/phases/evaluate.py`, `envforge/kinds/browser_webapp/phases/score.py`
- Test: `tests/test_eval_score_phases.py`

**Interfaces:**
- Consumes: `PhaseResult`/`PhaseContext` (Plan 1); `EvalAgent`/`EvalResult` (Task 1); `StateServer` (Task 3); `ExitCode` (Plan 1); `PortBroker` (Plan 1, via `ctx.ports`).
- Produces:
  - `class EvaluatePhase`: `name="evaluate"`. `EvaluatePhase(eval_agent, *, base_url_host="127.0.0.1")`. `run(ctx)`: read `app_dir` + tasks; lease a port via `ctx.ports.lease(f"{run_id}:app")`; start a `StateServer` on it; `await eval_agent.setup(url)`; for each task `await eval_agent.run(...)` saving `EvalResult`s; teardown + stop server + release port. If zero results produced → `PhaseResult.fail(ExitCode.EVAL_HARNESS_FAILURE, …)`. Stores per-task results list in `result["results"]`. (Uses `asyncio.run` internally since phases are sync.)
  - `class ScorePhase`: `name="score"`. `run(ctx)`: read the `evaluate` step results; compute `passed`/`failed`/`timed_out` counts + pass_rate; store in result and write a final status snapshot via `ctx.status`. Always `PhaseResult.done(...)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_eval_score_phases.py
import json
from pathlib import Path
from envforge.core.runstore import RunStore, StepStatus
from envforge.core.ports import PortBroker
from envforge.core.status import StatusWriter
from envforge.core.exits import ExitCode
from envforge.phases.base import PhaseContext
from envforge.agents.fakes import FakeEvalAgent
from envforge.agents.base import EvalResult
from envforge.kinds.browser_webapp.phases.evaluate import EvaluatePhase
from envforge.kinds.browser_webapp.phases.score import ScorePhase

NOW = "2026-06-22T00:00:00Z"


def _ctx(tmp_path, rs):
    return PhaseContext(
        runstore=rs, gateway=None,
        ports=PortBroker(tmp_path / "ports", start=8200, end=8260, is_free=lambda p: True),
        status=StatusWriter(rs.run_dir / "_status"), runtime=None, config={}, now=lambda: NOW,
    )


def _seed_app_with_tasks(rs, n):
    app_dir = rs.run_dir / "app"; (app_dir / "verifiers").mkdir(parents=True)
    (app_dir / "index.html").write_text("<h1>a</h1>")
    tasks = [{"id": f"task_{i}", "prompt": f"do {i}"} for i in range(n)]
    (app_dir / "function-tasks.json").write_text(json.dumps(tasks))
    rs.set_step("generate_app", StepStatus.DONE, result={"app_dir": str(app_dir)}, now=NOW)
    rs.set_step("generate_function_tasks", StepStatus.DONE, result={"task_count": n}, now=NOW)
    return app_dir, tasks


def test_evaluate_runs_all_tasks(tmp_path):
    rs = RunStore.create(tmp_path / "runs", "r", "browser_webapp", now=NOW)
    _seed_app_with_tasks(rs, 3)
    fake = FakeEvalAgent({
        "task_0": EvalResult("task_0", passed=True),
        "task_1": EvalResult("task_1", passed=False),
        "task_2": EvalResult("task_2", passed=True),
    })
    res = EvaluatePhase(fake).run(_ctx(tmp_path, rs))
    assert res.ok and len(res.result["results"]) == 3 and fake.setup_called


def test_score_aggregates(tmp_path):
    rs = RunStore.create(tmp_path / "runs", "r", "browser_webapp", now=NOW)
    _seed_app_with_tasks(rs, 3)
    rs.set_step("evaluate", StepStatus.DONE, result={"results": [
        {"task_id": "task_0", "passed": True, "timed_out": False},
        {"task_id": "task_1", "passed": False, "timed_out": False},
        {"task_id": "task_2", "passed": True, "timed_out": False},
    ]}, now=NOW)
    res = ScorePhase().run(_ctx(tmp_path, rs))
    assert res.ok and res.result["passed"] == 2 and res.result["failed"] == 1
    status = json.loads((rs.run_dir / "_status" / "STATUS.json").read_text())
    assert status["passed"] == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `env -u VIRTUAL_ENV uv run pytest tests/test_eval_score_phases.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

```python
# envforge/kinds/browser_webapp/phases/evaluate.py
from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from pathlib import Path

from ....core.exits import ExitCode
from ....phases.base import PhaseContext, PhaseResult
from ..protocol import StateServer


class EvaluatePhase:
    name = "evaluate"

    def __init__(self, eval_agent):
        self._eval_agent = eval_agent

    def run(self, ctx: PhaseContext) -> PhaseResult:
        app_dir = Path(ctx.runstore.state["steps"]["generate_app"]["result"]["app_dir"])
        tasks = json.loads((app_dir / "function-tasks.json").read_text())
        owner = f"{ctx.runstore.run_id}:app"
        port = ctx.ports.lease(owner)
        ctx.runstore.record_port("app", port)
        server = StateServer(app_dir, port=port)
        server.start()
        try:
            results = asyncio.run(self._run_all(server.url, tasks, ctx.runstore.run_dir / "tasks"))
        finally:
            server.stop()
            ctx.ports.release(port)
        if not results:
            return PhaseResult.fail(ExitCode.EVAL_HARNESS_FAILURE, "eval produced zero results")
        return PhaseResult.done(results=[asdict(r) for r in results])

    async def _run_all(self, url, tasks, tasks_root):
        await self._eval_agent.setup(url)
        out = []
        try:
            for t in tasks:
                res = await self._eval_agent.run(t["id"], t["prompt"], url, tasks_root / t["id"])
                out.append(res)
        finally:
            await self._eval_agent.teardown()
        return out
```

```python
# envforge/kinds/browser_webapp/phases/score.py
from __future__ import annotations

from ....phases.base import PhaseContext, PhaseResult


class ScorePhase:
    name = "score"

    def run(self, ctx: PhaseContext) -> PhaseResult:
        results = ctx.runstore.state["steps"]["evaluate"]["result"]["results"]
        total = len(results)
        passed = sum(1 for r in results if r.get("passed"))
        timed_out = sum(1 for r in results if r.get("timed_out"))
        failed = total - passed
        pass_rate = round(passed / total, 3) if total else 0.0
        summary = {"total": total, "passed": passed, "failed": failed,
                   "timed_out": timed_out, "pass_rate": pass_rate}
        ctx.status.write_status({"phase": "score", **summary}, now=ctx.now())
        return PhaseResult.done(**summary)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `env -u VIRTUAL_ENV uv run pytest tests/test_eval_score_phases.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add envforge/kinds/browser_webapp/phases/evaluate.py envforge/kinds/browser_webapp/phases/score.py tests/test_eval_score_phases.py
git commit -m "Add evaluate and score phases"
```

---

## Task 11: BrowserWebAppKind + CLI registration (integration)

**Files:**
- Create: `envforge/kinds/browser_webapp/kind.py`
- Modify: `envforge/cli.py` (register the `browser_webapp` kind; build agents from env/args)
- Test: `tests/test_browser_webapp_kind.py`

**Interfaces:**
- Consumes: all phases (Tasks 9–10); `CodingAgent`/`EvalAgent` (Task 1); `Orchestrator`/`PhaseContext` (Plan 1).
- Produces:
  - `class BrowserWebAppKind`: `name="browser_webapp"`. `BrowserWebAppKind(coding_agent, eval_agent, *, gen_model, eval_model, docs_path, task_count=24)`. `.phases()` returns `[GenerateAppPhase(coding_agent, model=gen_model, docs_path), HealthGatePhase(eval_agent), GenerateFunctionTasksPhase(coding_agent, model=gen_model, expected_count=task_count), EvaluatePhase(eval_agent), ScorePhase()]`; `.order()` returns their names.
  - A new `HealthGatePhase` (add to `phases/__init__.py` or a small `health_phase.py`): `name="health_gate"`; wraps `health.run_all_gates` over the app dir, leasing a port; on failure → `PhaseResult.fail(ExitCode.APP_UNHEALTHY, …)`. (Bounded model-driven repair is deferred to Plan 3; Plan 2 fails clean on unhealthy.)
  - `cli.py`: extend `KINDS`/dispatch so `--kind browser_webapp --docs <path>` builds `OpencodeAgent` + `BrowserUseEvalAgent` (real) and a `BrowserWebAppKind`, then runs the orchestrator. Keep `demo` working.

- [ ] **Step 1: Write the failing test (integration with fakes)**

```python
# tests/test_browser_webapp_kind.py
import json
from pathlib import Path
from envforge.core.runstore import RunStore
from envforge.core.orchestrator import Orchestrator
from envforge.core.ports import PortBroker
from envforge.core.status import StatusWriter
from envforge.core.exits import ExitCode
from envforge.phases.base import PhaseContext
from envforge.runtimes.local import LocalRuntime
from envforge.agents.fakes import FakeCodingAgent, FakeEvalAgent
from envforge.agents.base import EvalResult
from envforge.kinds.browser_webapp.kind import BrowserWebAppKind

NOW = "2026-06-22T00:00:00Z"


def test_full_kind_runs_end_to_end_with_fakes(tmp_path):
    rs = RunStore.create(tmp_path / "runs", "r", "browser_webapp", now=NOW)
    # generate_app writes index.html+server.py; function_tasks writes tasks+verifiers
    n = 3
    tj = json.dumps([{"id": f"task_{i}", "prompt": f"do {i}"} for i in range(n)])
    gen_files = {"index.html": "<h1>a</h1>", "server.py": "x=1"}
    task_files = {"function-tasks.json": tj}
    for i in range(n):
        task_files[f"verifiers/task_{i}.py"] = "def verify(u):\n    return True, 'ok'\n"
    coding = FakeCodingAgent([{"files": gen_files, "ok": True}, {"files": task_files, "ok": True}])
    eval_agent = FakeEvalAgent({f"task_{i}": EvalResult(f"task_{i}", passed=(i % 2 == 0)) for i in range(n)})

    kind = BrowserWebAppKind(coding, eval_agent, gen_model="g", eval_model="e",
                             docs_path=tmp_path / "docs", task_count=n)
    (tmp_path / "docs").mkdir()
    ctx = PhaseContext(
        runstore=rs, gateway=None,
        ports=PortBroker(tmp_path / "ports", start=8300, end=8360, is_free=lambda p: True),
        status=StatusWriter(rs.run_dir / "_status"), runtime=LocalRuntime(), config={}, now=lambda: NOW,
    )
    code = Orchestrator(rs, kind.phases(), kind.order(), ctx).run()
    assert code is ExitCode.OK
    assert rs.state["steps"]["score"]["result"]["total"] == n
    assert rs.state["steps"]["score"]["result"]["passed"] == 2  # tasks 0 and 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `env -u VIRTUAL_ENV uv run pytest tests/test_browser_webapp_kind.py -v`
Expected: FAIL — `ModuleNotFoundError: envforge.kinds.browser_webapp.kind`.

- [ ] **Step 3: Write the HealthGatePhase**

```python
# envforge/kinds/browser_webapp/phases/health_phase.py
from __future__ import annotations

import asyncio
from pathlib import Path

from ....core.exits import ExitCode
from ....phases.base import PhaseContext, PhaseResult
from ..health import run_all_gates
from ..protocol import StateServer


class HealthGatePhase:
    name = "health_gate"

    def __init__(self, eval_agent):
        self._eval_agent = eval_agent

    def run(self, ctx: PhaseContext) -> PhaseResult:
        app_dir = Path(ctx.runstore.state["steps"]["generate_app"]["result"]["app_dir"])
        port = ctx.ports.lease(f"{ctx.runstore.run_id}:health")
        server = StateServer(app_dir, port=port)
        server.start()
        try:
            report = asyncio.run(run_all_gates(
                app_dir, port=0, eval_agent=self._eval_agent, server_url=server.url))
        finally:
            server.stop()
            ctx.ports.release(port)
        if not report.ok:
            return PhaseResult.fail(ExitCode.APP_UNHEALTHY, f"{report.gate}: {report.detail}")
        return PhaseResult.done(healthy=True)
```

- [ ] **Step 4: Write the kind**

```python
# envforge/kinds/browser_webapp/kind.py
from __future__ import annotations

from pathlib import Path

from .phases.generate_app import GenerateAppPhase
from .phases.health_phase import HealthGatePhase
from .phases.function_tasks import GenerateFunctionTasksPhase
from .phases.evaluate import EvaluatePhase
from .phases.score import ScorePhase


class BrowserWebAppKind:
    name = "browser_webapp"

    def __init__(self, coding_agent, eval_agent, *, gen_model: str, eval_model: str,
                 docs_path: Path, task_count: int = 24):
        self._phases = [
            GenerateAppPhase(coding_agent, model=gen_model, docs_path=docs_path),
            HealthGatePhase(eval_agent),
            GenerateFunctionTasksPhase(coding_agent, model=gen_model, expected_count=task_count),
            EvaluatePhase(eval_agent),
            ScorePhase(),
        ]

    def phases(self):
        return list(self._phases)

    def order(self):
        return [p.name for p in self._phases]
```

- [ ] **Step 5: Wire the CLI** (modify `envforge/cli.py`)

Add near the top imports:
```python
from .agents.opencode_agent import OpencodeAgent
from .agents.browser_eval import BrowserUseEvalAgent
from .kinds.browser_webapp.kind import BrowserWebAppKind
```
Add a builder and extend dispatch (place after the existing `KINDS` definition):
```python
def _build_browser_webapp_kind(args):
    import os
    from browser_use.llm.openai.chat import ChatOpenAI  # lazy; only when actually running
    llm = ChatOpenAI(model=args.eval_model,
                     base_url=os.environ["OPENAI_BASE_URL"],
                     api_key=os.environ["OPENAI_API_KEY"])
    coding = OpencodeAgent()
    eval_agent = BrowserUseEvalAgent(llm, verifier_dir=Path(args.runs_root))  # verifier_dir set per-run inside evaluate
    return BrowserWebAppKind(coding, eval_agent, gen_model=args.gen_model,
                             eval_model=args.eval_model, docs_path=Path(args.docs),
                             task_count=args.task_count)
```
In `_build_orchestrator`, branch on `rs.kind`: for `demo` use `KINDS["demo"]`; for `browser_webapp` build the kind via `_build_browser_webapp_kind(args)` and use `kind.phases()/kind.order()`. Add the `run` subparser args: `--docs`, `--gen-model` (default `litellm/your-coding-model`), `--eval-model` (default `your-eval-model`), `--task-count` (default 24), and allow `--kind browser_webapp`.

> Note: the real `BrowserUseEvalAgent.verifier_dir` must point at the generated app's `verifiers/`. Since that path is only known after `generate_app`, have `EvaluatePhase`/`HealthGatePhase` pass the per-run verifier dir to the agent at call time, OR construct the eval agent inside the kind with a late-bound verifier dir. Implement by giving `BrowserUseEvalAgent` a `set_verifier_dir(path)` setter the evaluate phase calls with `app_dir/"verifiers"` before running. Add that one-line setter + a test.

- [ ] **Step 6: Add the late-bound verifier-dir setter + test**

Add to `BrowserUseEvalAgent`:
```python
    def set_verifier_dir(self, path: Path) -> None:
        self._verifier_dir = Path(path)
```
Add to `EvaluatePhase.run` (and `HealthGatePhase` not needed) right after computing `app_dir`:
```python
        if hasattr(self._eval_agent, "set_verifier_dir"):
            self._eval_agent.set_verifier_dir(app_dir / "verifiers")
```
Test (`tests/test_browser_eval.py`, append):
```python
def test_set_verifier_dir(tmp_path):
    from envforge.agents.browser_eval import BrowserUseEvalAgent
    a = BrowserUseEvalAgent(llm=object(), verifier_dir=tmp_path)
    a.set_verifier_dir(tmp_path / "v")
    assert a._verifier_dir == tmp_path / "v"
```

- [ ] **Step 7: Run tests + full suite**

Run: `env -u VIRTUAL_ENV uv run pytest tests/test_browser_webapp_kind.py tests/test_browser_eval.py -v`
Expected: kind integration + eval tests pass.
Run: `env -u VIRTUAL_ENV uv run pytest -q`
Expected: full suite green.

- [ ] **Step 8: Commit**

```bash
git add envforge/kinds/browser_webapp/kind.py envforge/kinds/browser_webapp/phases/health_phase.py envforge/agents/browser_eval.py envforge/cli.py tests/test_browser_webapp_kind.py tests/test_browser_eval.py
git commit -m "Assemble BrowserWebAppKind and register browser_webapp in the CLI"
```

---

## Task 12: Dependencies, README, full-suite green

**Files:**
- Modify: `envforge/pyproject.toml` (add optional `browser` extra: `browser-use`, `playwright`)
- Modify: `envforge/README.md` (document the browser_webapp kind + the cluster run recipe)
- Test: full suite.

**Interfaces:**
- Consumes: everything.
- Produces: a documented, installable browser extra and a green suite. The `browser` extra is optional so local unit tests (which use fakes + lazy imports) don't require it.

- [ ] **Step 1: Add the optional extra to `pyproject.toml`**

Under `[project.optional-dependencies]` add:
```toml
browser = ["browser-use>=0.11.9", "playwright>=1.40"]
```

- [ ] **Step 2: Document in README** (append a "browser_webapp kind" section)

```markdown
## browser_webapp kind (Plan 2)

Generates a web app, health-gates it, generates a 24-task function suite + verifiers,
runs a single browser_use eval pass, and scores it.

Local unit tests use fakes and need no models/browser. The real run needs the
`browser` extra and an OpenAI-compatible endpoint:

    uv pip install -e ".[dev,browser]"
    playwright install chromium
    export OPENAI_BASE_URL=<endpoint-url> OPENAI_API_KEY=<key>
    envforge run --kind browser_webapp --docs <docs-dir> --runs-root <dir> \
      --gen-model litellm/your-coding-model --eval-model your-eval-model

On the cluster this runs inside a prebuilt container image via a hand-written
job-submission script (not committed).
```

- [ ] **Step 3: Run the full suite**

Run: `env -u VIRTUAL_ENV uv run pytest -q`
Expected: all tests pass (Plan 1 + Plan 2).

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml README.md
git commit -m "Add optional browser extra and document the browser_webapp kind"
```

---

## Self-Review

**1. Spec coverage** (against `2026-06-22-envforge-plan2-browser-kind-design.md`):
- §3 module layout → Tasks 1–12 create every listed file. ✓
- §4 CodingAgent/EvalAgent → Tasks 1,4,7. ✓
- §5 reliability requirements → Task 7 tests (seed-poll raise, timeout→partial save, restart-on-retryable); 0/0 distinction → Task 10 EvaluatePhase (`EVAL_HARNESS_FAILURE`). ✓
- §6 protocol server → Task 3. ✓
- §7 phases (generate_app, health_gate, generate_function_tasks, evaluate, score) → Tasks 9,11,10. ✓
- §8 model traffic/budget → Task 8 (OpenAITransport for own calls); opencode/browser_use direct-to-endpoint wired in Task 11 CLI. ✓
- §10 testing (fakes local; integration cluster-gated) → fakes in Task 1; integration test with fakes in Task 11; the real cluster run is the post-implementation manual step. ✓

**2. Placeholder scan:** every code/test step has complete content; prompts are written out; no "TBD"/"similar to". The one prose note in Task 11 (verifier-dir late-binding) is resolved with concrete code in Steps 6. ✓

**3. Type consistency:** `CodingResult(ok,returncode,log_path)`, `EvalResult(task_id,passed,steps,elapsed,timed_out,error)`, `CodingAgent.run(...)` signature, `EvalAgent.setup/run/teardown`, `PhaseResult.done/fail`, `ExitCode` members, `StateServer(directory,port)/.url/.start/.stop`, `run_verifier→VerifyOutcome`, `ModelResponse/ModelSpec` are used identically across defining and consuming tasks. ✓

---

## Out of scope (later plans)

- **Plan 3:** audit-eval loops (2b/3b), real tasks (3a), hardening rounds (4), final regression (5); bounded model-driven health repair (Plan 2 fails clean on unhealthy).
- **Plan 4 / infra-specific branch (after first real exp):** batch-scheduler/container runtime adapter; the main/cluster branch split.
- **Deferred Plan-1 item now relevant:** when a phase makes a gateway call that can raise `BudgetExceeded`, translate it to `PhaseResult.fail(ExitCode.BUDGET_EXCEEDED, …)` (no Plan-2 phase calls the gateway yet, so not triggered here).
