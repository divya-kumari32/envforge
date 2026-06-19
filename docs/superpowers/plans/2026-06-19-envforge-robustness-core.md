# envforge Robustness Core — Implementation Plan (Plan 1 of 4)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the domain-agnostic robustness core of envforge — a durable state-machine pipeline runner with a model gateway, budget caps, port leasing, duplicate-job locking, classified exits, and durable status — wired into a working `envforge` CLI that runs a full pipeline end-to-end against a built-in `demo` kind, entirely locally with no models or browsers.

**Architecture:** A thin `Orchestrator` advances ordered, idempotent phase steps recorded in a JSON `RunStore` that lives outside any synced directory. All model traffic flows through a `ModelGateway` that enforces per-role budget caps and retries/falls back on classified errors. A per-run lock (PID/host/heartbeat) prevents duplicate jobs; a port broker leases ports atomically. Every exit goes through one classified `finish()` path. Backends sit behind a `Runtime` interface (`LocalRuntime` here). A built-in `demo` kind exercises the whole machine with deterministic fake phases.

**Tech Stack:** Python ≥3.12, `uv` for packaging, `pytest` for tests. Standard library only for the core (no third-party runtime deps in Plan 1).

## Global Constraints

- Python **≥ 3.12** required (matches webarena-infinity); declared in `pyproject.toml`.
- Core (`envforge/core`, `envforge/models`, `envforge/runtimes`, `envforge/phases`) uses **standard library only** — no third-party runtime dependencies in this plan. `pytest` is a dev-only dependency.
- **No bare `sys.exit`** anywhere except the single CLI top-level handler; all termination flows through `finish()` / `EnvforgeExit`.
- **Run-store and status files live OUTSIDE any synced app directory** — under `<runs_root>/<run_id>/`.
- All on-disk JSON writes are **atomic**: write to a temp file in the same directory, then `os.replace`.
- Timestamps are ISO-8601 UTC strings; functions that stamp time accept an injectable `now` parameter for deterministic tests.
- Commit messages: imperative mood, no `Co-Authored-By` line.
- Package import root is `envforge`; tests live under `tests/` and import from `envforge`.

---

## File Structure

```
envforge/
├── pyproject.toml                  # package metadata, py>=3.12, pytest dev dep, console script
├── envforge/
│   ├── __init__.py
│   ├── core/
│   │   ├── __init__.py
│   │   ├── exits.py                # ExitCode, EnvforgeExit, finish()
│   │   ├── jsonio.py               # atomic_write_json / read_json (shared helper)
│   │   ├── runstore.py             # StepStatus, RunStore
│   │   ├── lock.py                 # RunLock, DuplicateJobError, pid_alive
│   │   ├── ports.py                # PortBroker
│   │   ├── status.py               # StatusWriter
│   │   └── orchestrator.py         # Orchestrator
│   ├── models/
│   │   ├── __init__.py
│   │   ├── errors.py               # ErrorCategory, classify_error
│   │   ├── budget.py               # BudgetLedger, BudgetExceeded
│   │   ├── fallback.py             # with_retry
│   │   └── gateway.py              # Transport, FakeTransport, ModelSpec, ModelGateway, ModelResponse
│   ├── runtimes/
│   │   ├── __init__.py
│   │   ├── base.py                 # Runtime protocol, CommandResult
│   │   └── local.py                # LocalRuntime
│   ├── phases/
│   │   ├── __init__.py
│   │   ├── base.py                 # PhaseResult, PhaseContext, Phase protocol
│   │   └── demo.py                 # demo kind phases (deterministic, model-free)
│   └── cli.py                      # argparse: run | resume | status | clean
└── tests/
    ├── __init__.py
    ├── test_exits.py
    ├── test_jsonio.py
    ├── test_runstore.py
    ├── test_lock.py
    ├── test_ports.py
    ├── test_status.py
    ├── test_errors.py
    ├── test_budget.py
    ├── test_fallback.py
    ├── test_gateway.py
    ├── test_local_runtime.py
    ├── test_orchestrator.py
    └── test_cli.py
```

---

## Task 1: Project scaffold & packaging

**Files:**
- Create: `envforge/pyproject.toml`
- Create: `envforge/envforge/__init__.py`
- Create: `envforge/envforge/core/__init__.py`
- Create: `envforge/envforge/models/__init__.py`
- Create: `envforge/envforge/runtimes/__init__.py`
- Create: `envforge/envforge/phases/__init__.py`
- Create: `envforge/tests/__init__.py`

**Interfaces:**
- Consumes: nothing.
- Produces: an installable package `envforge` and a working `pytest` invocation.

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "envforge"
version = "0.1.0"
description = "Multi-model pipeline for generating and evaluating webarena-style environments"
requires-python = ">=3.12"
dependencies = []

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[project.scripts]
envforge = "envforge.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["envforge"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Create empty package marker files**

Create each of these as empty files:
`envforge/envforge/__init__.py`, `envforge/envforge/core/__init__.py`, `envforge/envforge/models/__init__.py`, `envforge/envforge/runtimes/__init__.py`, `envforge/envforge/phases/__init__.py`, `envforge/tests/__init__.py`.

- [ ] **Step 3: Create the environment and install**

Run (from `envforge/`):
```bash
uv venv && uv pip install -e ".[dev]"
```
Expected: installs `envforge` editable + `pytest`, no errors.

- [ ] **Step 4: Verify pytest runs (collects zero tests)**

Run: `uv run pytest -q`
Expected: `no tests ran` (exit code 5 is acceptable here) — confirms collection works.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml envforge/ tests/
git commit -m "Scaffold envforge package and pytest"
```

---

## Task 2: Atomic JSON I/O helper

**Files:**
- Create: `envforge/envforge/core/jsonio.py`
- Test: `envforge/tests/test_jsonio.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `atomic_write_json(path: Path, data: object) -> None` — serializes `data` to `path` atomically (temp file in same dir + `os.replace`), creating parent dirs.
  - `read_json(path: Path) -> object` — reads and parses JSON from `path`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_jsonio.py
from pathlib import Path
from envforge.core.jsonio import atomic_write_json, read_json


def test_write_then_read_roundtrip(tmp_path: Path):
    p = tmp_path / "nested" / "state.json"
    atomic_write_json(p, {"a": 1, "b": [1, 2, 3]})
    assert read_json(p) == {"a": 1, "b": [1, 2, 3]}


def test_write_leaves_no_temp_files(tmp_path: Path):
    p = tmp_path / "state.json"
    atomic_write_json(p, {"x": 1})
    siblings = list(p.parent.iterdir())
    assert siblings == [p]


def test_overwrite_replaces_content(tmp_path: Path):
    p = tmp_path / "state.json"
    atomic_write_json(p, {"v": 1})
    atomic_write_json(p, {"v": 2})
    assert read_json(p) == {"v": 2}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_jsonio.py -v`
Expected: FAIL with `ModuleNotFoundError: envforge.core.jsonio`.

- [ ] **Step 3: Write minimal implementation**

```python
# envforge/core/jsonio.py
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def atomic_write_json(path: Path, data: object) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def read_json(path: Path) -> object:
    with open(path, encoding="utf-8") as f:
        return json.load(f)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_jsonio.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add envforge/core/jsonio.py tests/test_jsonio.py
git commit -m "Add atomic JSON I/O helper"
```

---

## Task 3: Classified exits

**Files:**
- Create: `envforge/envforge/core/exits.py`
- Test: `envforge/tests/test_exits.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `class ExitCode(IntEnum)` with members: `OK=0`, `BUDGET_EXCEEDED=10`, `TASKS_INVALID=11`, `APP_UNHEALTHY=12`, `EVAL_HARNESS_FAILURE=13`, `DUPLICATE_JOB=14`, `INTERRUPTED=15`, `FATAL=20`.
  - `class EnvforgeExit(Exception)` with attributes `.code: ExitCode` and `.reason: str`.
  - `def finish(code: ExitCode, reason: str) -> NoReturn` — raises `EnvforgeExit(code, reason)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_exits.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_exits.py -v`
Expected: FAIL with `ModuleNotFoundError: envforge.core.exits`.

- [ ] **Step 3: Write minimal implementation**

```python
# envforge/core/exits.py
from __future__ import annotations

from enum import IntEnum
from typing import NoReturn


class ExitCode(IntEnum):
    OK = 0
    BUDGET_EXCEEDED = 10
    TASKS_INVALID = 11
    APP_UNHEALTHY = 12
    EVAL_HARNESS_FAILURE = 13
    DUPLICATE_JOB = 14
    INTERRUPTED = 15
    FATAL = 20


class EnvforgeExit(Exception):
    def __init__(self, code: ExitCode, reason: str):
        super().__init__(f"[{code.name}] {reason}")
        self.code = code
        self.reason = reason


def finish(code: ExitCode, reason: str) -> NoReturn:
    raise EnvforgeExit(code, reason)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_exits.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add envforge/core/exits.py tests/test_exits.py
git commit -m "Add classified exit codes and finish()"
```

---

## Task 4: Run-store (durable state machine state)

**Files:**
- Create: `envforge/envforge/core/runstore.py`
- Test: `envforge/tests/test_runstore.py`

**Interfaces:**
- Consumes: `atomic_write_json`, `read_json` (Task 2); `ExitCode` (Task 3).
- Produces:
  - `class StepStatus(str, Enum)`: `PENDING="pending"`, `RUNNING="running"`, `DONE="done"`, `FAILED="failed"`.
  - `class RunStore`:
    - `RunStore.create(runs_root: Path, run_id: str, kind: str, *, now: str) -> RunStore` — creates `<runs_root>/<run_id>/state.json`.
    - `RunStore.load(runs_root: Path, run_id: str) -> RunStore` — loads existing.
    - `RunStore.exists(runs_root: Path, run_id: str) -> bool`.
    - `.run_dir -> Path`, `.run_id -> str`, `.kind -> str`.
    - `.set_step(name: str, status: StepStatus, *, result: dict | None = None, now: str) -> None`.
    - `.step_status(name: str) -> StepStatus` (returns `PENDING` if never set).
    - `.next_pending(order: list[str]) -> str | None` — first name in `order` whose status is not `DONE`.
    - `.set_exit(code: ExitCode, reason: str, *, now: str) -> None`.
    - `.exit_code -> ExitCode | None`.
    - `.record_port(name: str, port: int) -> None`, `.ports -> dict[str, int]`.
    - `.state -> dict` (deep copy of current state).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_runstore.py
from pathlib import Path
import pytest
from envforge.core.runstore import RunStore, StepStatus
from envforge.core.exits import ExitCode

NOW = "2026-06-19T00:00:00Z"


def test_create_persists_state(tmp_path: Path):
    rs = RunStore.create(tmp_path, "run-1", "demo", now=NOW)
    assert rs.run_id == "run-1"
    assert rs.kind == "demo"
    assert (tmp_path / "run-1" / "state.json").exists()
    assert RunStore.exists(tmp_path, "run-1")


def test_unset_step_is_pending(tmp_path: Path):
    rs = RunStore.create(tmp_path, "r", "demo", now=NOW)
    assert rs.step_status("generate") is StepStatus.PENDING


def test_set_step_survives_reload(tmp_path: Path):
    rs = RunStore.create(tmp_path, "r", "demo", now=NOW)
    rs.set_step("generate", StepStatus.DONE, result={"files": 3}, now=NOW)
    reloaded = RunStore.load(tmp_path, "r")
    assert reloaded.step_status("generate") is StepStatus.DONE
    assert reloaded.state["steps"]["generate"]["result"] == {"files": 3}


def test_next_pending_skips_done(tmp_path: Path):
    rs = RunStore.create(tmp_path, "r", "demo", now=NOW)
    order = ["generate", "health", "eval"]
    assert rs.next_pending(order) == "generate"
    rs.set_step("generate", StepStatus.DONE, now=NOW)
    assert rs.next_pending(order) == "health"
    rs.set_step("health", StepStatus.DONE, now=NOW)
    rs.set_step("eval", StepStatus.DONE, now=NOW)
    assert rs.next_pending(order) is None


def test_failed_step_is_still_next_pending(tmp_path: Path):
    rs = RunStore.create(tmp_path, "r", "demo", now=NOW)
    rs.set_step("generate", StepStatus.FAILED, now=NOW)
    assert rs.next_pending(["generate", "eval"]) == "generate"


def test_set_exit_records_code(tmp_path: Path):
    rs = RunStore.create(tmp_path, "r", "demo", now=NOW)
    rs.set_exit(ExitCode.BUDGET_EXCEEDED, "cap", now=NOW)
    reloaded = RunStore.load(tmp_path, "r")
    assert reloaded.exit_code is ExitCode.BUDGET_EXCEEDED


def test_record_port(tmp_path: Path):
    rs = RunStore.create(tmp_path, "r", "demo", now=NOW)
    rs.record_port("app", 8200)
    assert RunStore.load(tmp_path, "r").ports == {"app": 8200}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_runstore.py -v`
Expected: FAIL with `ModuleNotFoundError: envforge.core.runstore`.

- [ ] **Step 3: Write minimal implementation**

```python
# envforge/core/runstore.py
from __future__ import annotations

import copy
from enum import Enum
from pathlib import Path

from .exits import ExitCode
from .jsonio import atomic_write_json, read_json


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class RunStore:
    def __init__(self, run_dir: Path, state: dict):
        self._run_dir = Path(run_dir)
        self._state = state

    # ---- construction -----------------------------------------------------
    @staticmethod
    def _state_path(runs_root: Path, run_id: str) -> Path:
        return Path(runs_root) / run_id / "state.json"

    @classmethod
    def create(cls, runs_root: Path, run_id: str, kind: str, *, now: str) -> "RunStore":
        run_dir = Path(runs_root) / run_id
        state = {
            "run_id": run_id,
            "kind": kind,
            "created_at": now,
            "updated_at": now,
            "steps": {},
            "ports": {},
            "exit": None,
        }
        rs = cls(run_dir, state)
        rs._save(now)
        return rs

    @classmethod
    def load(cls, runs_root: Path, run_id: str) -> "RunStore":
        path = cls._state_path(runs_root, run_id)
        state = read_json(path)
        return cls(path.parent, state)

    @classmethod
    def exists(cls, runs_root: Path, run_id: str) -> bool:
        return cls._state_path(runs_root, run_id).exists()

    # ---- accessors --------------------------------------------------------
    @property
    def run_dir(self) -> Path:
        return self._run_dir

    @property
    def run_id(self) -> str:
        return self._state["run_id"]

    @property
    def kind(self) -> str:
        return self._state["kind"]

    @property
    def state(self) -> dict:
        return copy.deepcopy(self._state)

    @property
    def ports(self) -> dict:
        return dict(self._state["ports"])

    @property
    def exit_code(self) -> ExitCode | None:
        ex = self._state["exit"]
        return ExitCode(ex["code"]) if ex else None

    # ---- mutations --------------------------------------------------------
    def set_step(self, name: str, status: StepStatus, *, result: dict | None = None, now: str) -> None:
        step = self._state["steps"].setdefault(name, {})
        step["status"] = status.value
        if result is not None:
            step["result"] = result
        step["updated_at"] = now
        self._save(now)

    def step_status(self, name: str) -> StepStatus:
        step = self._state["steps"].get(name)
        return StepStatus(step["status"]) if step else StepStatus.PENDING

    def next_pending(self, order: list[str]) -> str | None:
        for name in order:
            if self.step_status(name) is not StepStatus.DONE:
                return name
        return None

    def set_exit(self, code: ExitCode, reason: str, *, now: str) -> None:
        self._state["exit"] = {"code": int(code), "name": code.name, "reason": reason}
        self._save(now)

    def record_port(self, name: str, port: int) -> None:
        self._state["ports"][name] = port
        self._save(self._state["updated_at"])

    # ---- persistence ------------------------------------------------------
    def _save(self, now: str) -> None:
        self._state["updated_at"] = now
        atomic_write_json(self._run_dir / "state.json", self._state)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_runstore.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add envforge/core/runstore.py tests/test_runstore.py
git commit -m "Add durable JSON run-store with step state machine"
```

---

## Task 5: Run lock (no-duplicate-job guard)

**Files:**
- Create: `envforge/envforge/core/lock.py`
- Test: `envforge/tests/test_lock.py`

**Interfaces:**
- Consumes: `atomic_write_json`, `read_json` (Task 2).
- Produces:
  - `def pid_alive(pid: int) -> bool` — default liveness probe via `os.kill(pid, 0)`.
  - `class DuplicateJobError(Exception)`.
  - `class RunLock`:
    - `RunLock(path: Path, *, pid: int, host: str, ttl_seconds: float = 90.0, alive=pid_alive)`.
    - `.acquire(now: float) -> None` — raises `DuplicateJobError` if a live lock by another process exists; otherwise (re)writes the lock. A lock is "live" iff same host **and** `alive(pid)` **and** `now - heartbeat <= ttl_seconds`.
    - `.heartbeat(now: float) -> None`.
    - `.release() -> None` — removes the lock file (idempotent).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_lock.py
from pathlib import Path
import pytest
from envforge.core.lock import RunLock, DuplicateJobError


def _lock(path, pid=111, host="hostA", ttl=90.0, alive=lambda p: True):
    return RunLock(path, pid=pid, host=host, ttl_seconds=ttl, alive=alive)


def test_acquire_on_fresh_path_succeeds(tmp_path: Path):
    lk = _lock(tmp_path / "run.lock")
    lk.acquire(now=1000.0)
    assert (tmp_path / "run.lock").exists()


def test_live_lock_by_other_pid_blocks(tmp_path: Path):
    p = tmp_path / "run.lock"
    _lock(p, pid=111).acquire(now=1000.0)
    other = _lock(p, pid=222, alive=lambda pid: True)
    with pytest.raises(DuplicateJobError):
        other.acquire(now=1005.0)


def test_stale_lock_dead_pid_is_reclaimed(tmp_path: Path):
    p = tmp_path / "run.lock"
    _lock(p, pid=111).acquire(now=1000.0)
    other = _lock(p, pid=222, alive=lambda pid: False)  # holder is dead
    other.acquire(now=1005.0)  # should NOT raise
    assert (tmp_path / "run.lock").exists()


def test_expired_heartbeat_is_reclaimed(tmp_path: Path):
    p = tmp_path / "run.lock"
    _lock(p, pid=111, ttl=30.0).acquire(now=1000.0)
    other = _lock(p, pid=222, ttl=30.0, alive=lambda pid: True)
    other.acquire(now=1100.0)  # 100s > 30s ttl → stale
    assert (tmp_path / "run.lock").exists()


def test_reacquire_same_pid_succeeds(tmp_path: Path):
    p = tmp_path / "run.lock"
    lk = _lock(p, pid=111)
    lk.acquire(now=1000.0)
    lk.acquire(now=1001.0)  # same process re-acquiring is fine


def test_release_then_acquire(tmp_path: Path):
    p = tmp_path / "run.lock"
    lk = _lock(p, pid=111)
    lk.acquire(now=1000.0)
    lk.release()
    assert not p.exists()
    _lock(p, pid=222).acquire(now=1001.0)  # free now
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_lock.py -v`
Expected: FAIL with `ModuleNotFoundError: envforge.core.lock`.

- [ ] **Step 3: Write minimal implementation**

```python
# envforge/core/lock.py
from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from .jsonio import atomic_write_json, read_json


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class DuplicateJobError(Exception):
    pass


class RunLock:
    def __init__(
        self,
        path: Path,
        *,
        pid: int,
        host: str,
        ttl_seconds: float = 90.0,
        alive: Callable[[int], bool] = pid_alive,
    ):
        self._path = Path(path)
        self._pid = pid
        self._host = host
        self._ttl = ttl_seconds
        self._alive = alive

    def _is_live(self, record: dict, now: float) -> bool:
        if record.get("host") != self._host:
            return False
        if not self._alive(int(record.get("pid", -1))):
            return False
        return (now - float(record.get("heartbeat", 0))) <= self._ttl

    def acquire(self, now: float) -> None:
        if self._path.exists():
            record = read_json(self._path)
            same_proc = record.get("pid") == self._pid and record.get("host") == self._host
            if not same_proc and self._is_live(record, now):
                raise DuplicateJobError(
                    f"run already held by pid={record.get('pid')} on {record.get('host')}"
                )
        self._write(now)

    def heartbeat(self, now: float) -> None:
        self._write(now)

    def release(self) -> None:
        try:
            self._path.unlink()
        except FileNotFoundError:
            pass

    def _write(self, now: float) -> None:
        atomic_write_json(
            self._path,
            {"pid": self._pid, "host": self._host, "heartbeat": now},
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_lock.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add envforge/core/lock.py tests/test_lock.py
git commit -m "Add run lock with PID/host/heartbeat duplicate-job guard"
```

---

## Task 6: Port broker (atomic port leasing)

**Files:**
- Create: `envforge/envforge/core/ports.py`
- Test: `envforge/tests/test_ports.py`

**Interfaces:**
- Consumes: nothing (uses stdlib `socket`, `os`).
- Produces:
  - `class NoPortAvailable(Exception)`.
  - `class PortBroker`:
    - `PortBroker(lease_dir: Path, *, start: int = 8200, end: int = 9000, is_free=<bind probe>)`.
    - `.lease(owner: str) -> int` — returns the lowest port in `[start, end)` that has no lease file **and** passes `is_free(port)`; atomically creates `<lease_dir>/<port>.lease` (via `O_CREAT|O_EXCL`) containing `owner`. Raises `NoPortAvailable` if none.
    - `.release(port: int) -> None` — removes the lease file (idempotent).
    - `is_free(port: int) -> bool` is injectable; the default attempts to bind `127.0.0.1:port`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ports.py
from pathlib import Path
import pytest
from envforge.core.ports import PortBroker, NoPortAvailable


def test_lease_returns_first_free_port(tmp_path: Path):
    b = PortBroker(tmp_path, start=8200, end=8210, is_free=lambda p: True)
    assert b.lease("app") == 8200


def test_two_leases_differ(tmp_path: Path):
    b = PortBroker(tmp_path, start=8200, end=8210, is_free=lambda p: True)
    a = b.lease("app")
    c = b.lease("clio")
    assert a != c and {a, c} == {8200, 8201}


def test_busy_port_is_skipped(tmp_path: Path):
    # 8200 is occupied by a non-envforge process
    b = PortBroker(tmp_path, start=8200, end=8210, is_free=lambda p: p != 8200)
    assert b.lease("app") == 8201


def test_exhaustion_raises(tmp_path: Path):
    b = PortBroker(tmp_path, start=8200, end=8201, is_free=lambda p: True)
    b.lease("a")
    with pytest.raises(NoPortAvailable):
        b.lease("b")


def test_release_frees_port(tmp_path: Path):
    b = PortBroker(tmp_path, start=8200, end=8201, is_free=lambda p: True)
    p = b.lease("a")
    b.release(p)
    assert b.lease("b") == 8200


def test_lease_file_records_owner(tmp_path: Path):
    b = PortBroker(tmp_path, start=8200, end=8210, is_free=lambda p: True)
    p = b.lease("worker-3")
    assert (tmp_path / f"{p}.lease").read_text().strip() == "worker-3"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ports.py -v`
Expected: FAIL with `ModuleNotFoundError: envforge.core.ports`.

- [ ] **Step 3: Write minimal implementation**

```python
# envforge/core/ports.py
from __future__ import annotations

import os
import socket
from pathlib import Path
from typing import Callable


class NoPortAvailable(Exception):
    pass


def _default_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


class PortBroker:
    def __init__(
        self,
        lease_dir: Path,
        *,
        start: int = 8200,
        end: int = 9000,
        is_free: Callable[[int], bool] = _default_is_free,
    ):
        self._dir = Path(lease_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._start = start
        self._end = end
        self._is_free = is_free

    def lease(self, owner: str) -> int:
        for port in range(self._start, self._end):
            lease_path = self._dir / f"{port}.lease"
            if lease_path.exists():
                continue
            if not self._is_free(port):
                continue
            try:
                fd = os.open(lease_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            except FileExistsError:
                continue  # lost a race with another leaser
            with os.fdopen(fd, "w") as f:
                f.write(owner)
            return port
        raise NoPortAvailable(f"no free port in [{self._start}, {self._end})")

    def release(self, port: int) -> None:
        try:
            (self._dir / f"{port}.lease").unlink()
        except FileNotFoundError:
            pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_ports.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add envforge/core/ports.py tests/test_ports.py
git commit -m "Add atomic port-lease broker"
```

---

## Task 7: Status writer (durable, sync-surviving, structured)

**Files:**
- Create: `envforge/envforge/core/status.py`
- Test: `envforge/tests/test_status.py`

**Interfaces:**
- Consumes: `atomic_write_json` (Task 2).
- Produces:
  - `class StatusWriter`:
    - `StatusWriter(status_dir: Path)` — `status_dir` is outside any synced app dir.
    - `.write_status(fields: dict, *, now: str) -> None` — atomically writes `<status_dir>/STATUS.json` (merges `fields` over prior, always stamps `updated_at`).
    - `.activity(event: str, *, now: str, **fields) -> None` — appends one JSON object per line to `<status_dir>/activity.jsonl` with keys `ts`, `event`, plus `fields`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_status.py
import json
from pathlib import Path
from envforge.core.status import StatusWriter

NOW = "2026-06-19T00:00:00Z"


def test_write_status_creates_file(tmp_path: Path):
    sw = StatusWriter(tmp_path)
    sw.write_status({"phase": "generate"}, now=NOW)
    data = json.loads((tmp_path / "STATUS.json").read_text())
    assert data["phase"] == "generate"
    assert data["updated_at"] == NOW


def test_write_status_merges(tmp_path: Path):
    sw = StatusWriter(tmp_path)
    sw.write_status({"phase": "generate", "run_id": "r"}, now=NOW)
    sw.write_status({"phase": "eval"}, now="2026-06-19T00:01:00Z")
    data = json.loads((tmp_path / "STATUS.json").read_text())
    assert data["phase"] == "eval"
    assert data["run_id"] == "r"  # preserved across merge


def test_activity_appends_json_lines(tmp_path: Path):
    sw = StatusWriter(tmp_path)
    sw.activity("phase_start", now=NOW, phase="generate")
    sw.activity("phase_done", now=NOW, phase="generate", files=3)
    lines = (tmp_path / "activity.jsonl").read_text().strip().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first == {"ts": NOW, "event": "phase_start", "phase": "generate"}
    assert json.loads(lines[1])["files"] == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_status.py -v`
Expected: FAIL with `ModuleNotFoundError: envforge.core.status`.

- [ ] **Step 3: Write minimal implementation**

```python
# envforge/core/status.py
from __future__ import annotations

import json
from pathlib import Path

from .jsonio import atomic_write_json


class StatusWriter:
    def __init__(self, status_dir: Path):
        self._dir = Path(status_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._status_path = self._dir / "STATUS.json"
        self._activity_path = self._dir / "activity.jsonl"
        self._status: dict = {}

    def write_status(self, fields: dict, *, now: str) -> None:
        self._status.update(fields)
        self._status["updated_at"] = now
        atomic_write_json(self._status_path, self._status)

    def activity(self, event: str, *, now: str, **fields) -> None:
        record = {"ts": now, "event": event, **fields}
        with open(self._activity_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, sort_keys=False) + "\n")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_status.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add envforge/core/status.py tests/test_status.py
git commit -m "Add durable structured status writer"
```

---

## Task 8: Model error classification

**Files:**
- Create: `envforge/envforge/models/errors.py`
- Test: `envforge/tests/test_errors.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `class ErrorCategory(str, Enum)`: `AUTH`, `BUDGET`, `TIMEOUT`, `SERVER`, `MALFORMED`, `TRANSPORT`, `UNKNOWN`.
  - `class TransportError(Exception)` with `.status: int | None` and `.message: str` — the gateway transport raises this on HTTP-style failures.
  - `def classify_error(exc: Exception) -> ErrorCategory` — maps a `TransportError` (by status/message) or generic exception to a category. Rules: status 401/403→`AUTH`; 402 or "budget"/"quota" in message→`BUDGET`; 408/504 or `TimeoutError`→`TIMEOUT`; 500/502/503→`SERVER`; `ValueError`/"json"/"parse" in message→`MALFORMED`; `ConnectionError`/`OSError`→`TRANSPORT`; else `UNKNOWN`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_errors.py
from envforge.models.errors import ErrorCategory, classify_error, TransportError


def test_auth_status():
    assert classify_error(TransportError("nope", status=401)) is ErrorCategory.AUTH


def test_budget_by_message():
    assert classify_error(TransportError("budget exceeded", status=400)) is ErrorCategory.BUDGET


def test_budget_by_status_402():
    assert classify_error(TransportError("payment required", status=402)) is ErrorCategory.BUDGET


def test_timeout_status_and_exc():
    assert classify_error(TransportError("slow", status=504)) is ErrorCategory.TIMEOUT
    assert classify_error(TimeoutError("timed out")) is ErrorCategory.TIMEOUT


def test_server_5xx():
    assert classify_error(TransportError("bad gateway", status=502)) is ErrorCategory.SERVER


def test_malformed():
    assert classify_error(ValueError("could not parse json")) is ErrorCategory.MALFORMED


def test_transport():
    assert classify_error(ConnectionError("reset")) is ErrorCategory.TRANSPORT


def test_unknown():
    assert classify_error(RuntimeError("???")) is ErrorCategory.UNKNOWN
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_errors.py -v`
Expected: FAIL with `ModuleNotFoundError: envforge.models.errors`.

- [ ] **Step 3: Write minimal implementation**

```python
# envforge/models/errors.py
from __future__ import annotations

from enum import Enum


class ErrorCategory(str, Enum):
    AUTH = "auth"
    BUDGET = "budget"
    TIMEOUT = "timeout"
    SERVER = "server"
    MALFORMED = "malformed"
    TRANSPORT = "transport"
    UNKNOWN = "unknown"


class TransportError(Exception):
    def __init__(self, message: str, *, status: int | None = None):
        super().__init__(message)
        self.status = status
        self.message = message


def classify_error(exc: Exception) -> ErrorCategory:
    msg = str(getattr(exc, "message", exc)).lower()
    status = getattr(exc, "status", None)

    if status in (401, 403):
        return ErrorCategory.AUTH
    if status == 402 or "budget" in msg or "quota" in msg:
        return ErrorCategory.BUDGET
    if status in (408, 504) or isinstance(exc, TimeoutError):
        return ErrorCategory.TIMEOUT
    if status in (500, 502, 503):
        return ErrorCategory.SERVER
    if isinstance(exc, ValueError) or "json" in msg or "parse" in msg:
        return ErrorCategory.MALFORMED
    if isinstance(exc, (ConnectionError, OSError)):
        return ErrorCategory.TRANSPORT
    return ErrorCategory.UNKNOWN
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_errors.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add envforge/models/errors.py tests/test_errors.py
git commit -m "Add model error classification"
```

---

## Task 9: Budget ledger with hard caps

**Files:**
- Create: `envforge/envforge/models/budget.py`
- Test: `envforge/tests/test_budget.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `class BudgetExceeded(Exception)` with `.role: str`, `.spent: float`, `.cap: float`.
  - `class BudgetLedger`:
    - `BudgetLedger(caps: dict[str, float | None])` — per-role caps; `None` = unlimited; missing role = unlimited.
    - `.record(role: str, cost: float) -> None` — adds cost; raises `BudgetExceeded` if it pushes the role's total over its cap (the cost is still recorded before raising).
    - `.spent(role: str | None = None) -> float` — role total, or grand total if `role is None`.
    - `.check(role: str) -> None` — raises `BudgetExceeded` if already at/over cap.
    - `.to_dict() -> dict` / `BudgetLedger.from_dict(d) -> BudgetLedger`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_budget.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_budget.py -v`
Expected: FAIL with `ModuleNotFoundError: envforge.models.budget`.

- [ ] **Step 3: Write minimal implementation**

```python
# envforge/models/budget.py
from __future__ import annotations


class BudgetExceeded(Exception):
    def __init__(self, role: str, spent: float, cap: float):
        super().__init__(f"budget for role '{role}' exceeded: {spent} > {cap}")
        self.role = role
        self.spent = spent
        self.cap = cap


class BudgetLedger:
    def __init__(self, caps: dict[str, float | None]):
        self._caps = dict(caps)
        self._spent: dict[str, float] = {}

    def record(self, role: str, cost: float) -> None:
        self._spent[role] = self._spent.get(role, 0.0) + cost
        self.check(role)

    def spent(self, role: str | None = None) -> float:
        if role is None:
            return sum(self._spent.values())
        return self._spent.get(role, 0.0)

    def check(self, role: str) -> None:
        cap = self._caps.get(role)
        if cap is not None and self._spent.get(role, 0.0) >= cap:
            raise BudgetExceeded(role, self._spent.get(role, 0.0), cap)

    def to_dict(self) -> dict:
        return {"caps": self._caps, "spent": self._spent}

    @classmethod
    def from_dict(cls, d: dict) -> "BudgetLedger":
        led = cls(d.get("caps", {}))
        led._spent = dict(d.get("spent", {}))
        return led
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_budget.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add envforge/models/budget.py tests/test_budget.py
git commit -m "Add budget ledger with per-role hard caps"
```

---

## Task 10: Retry/backoff/endpoint-swap

**Files:**
- Create: `envforge/envforge/models/fallback.py`
- Test: `envforge/tests/test_fallback.py`

**Interfaces:**
- Consumes: `ErrorCategory`, `classify_error` (Task 8).
- Produces:
  - `RETRYABLE: set[ErrorCategory]` = `{TIMEOUT, SERVER, TRANSPORT}`.
  - `def with_retry(fn, endpoints: list[str], *, max_attempts: int = 3, base_delay: float = 1.0, sleep=time.sleep, classify=classify_error)` — calls `fn(endpoint)` cycling through `endpoints`; on a retryable category, sleeps `base_delay * 2**attempt` and retries with the next endpoint (wrapping); on a non-retryable category, re-raises immediately; exhausting `max_attempts` re-raises the last exception. Returns `fn`'s result on success.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_fallback.py
import pytest
from envforge.models.fallback import with_retry, RETRYABLE
from envforge.models.errors import ErrorCategory, TransportError


def test_success_first_try():
    calls = []
    out = with_retry(lambda ep: calls.append(ep) or "ok", ["e1"], sleep=lambda s: None)
    assert out == "ok"
    assert calls == ["e1"]


def test_retries_then_succeeds_swapping_endpoints():
    seen = []

    def fn(ep):
        seen.append(ep)
        if len(seen) < 3:
            raise TransportError("503", status=503)
        return "ok"

    out = with_retry(fn, ["e1", "e2"], max_attempts=3, sleep=lambda s: None)
    assert out == "ok"
    assert seen == ["e1", "e2", "e1"]  # cycles endpoints


def test_non_retryable_raises_immediately():
    seen = []

    def fn(ep):
        seen.append(ep)
        raise TransportError("unauthorized", status=401)

    with pytest.raises(TransportError):
        with_retry(fn, ["e1", "e2"], max_attempts=3, sleep=lambda s: None)
    assert seen == ["e1"]  # no retry on AUTH


def test_exhausts_attempts_and_reraises():
    def fn(ep):
        raise TransportError("503", status=503)

    with pytest.raises(TransportError):
        with_retry(fn, ["e1"], max_attempts=2, sleep=lambda s: None)


def test_retryable_set():
    assert ErrorCategory.TIMEOUT in RETRYABLE
    assert ErrorCategory.AUTH not in RETRYABLE
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_fallback.py -v`
Expected: FAIL with `ModuleNotFoundError: envforge.models.fallback`.

- [ ] **Step 3: Write minimal implementation**

```python
# envforge/models/fallback.py
from __future__ import annotations

import time
from typing import Callable

from .errors import ErrorCategory, classify_error

RETRYABLE: set[ErrorCategory] = {
    ErrorCategory.TIMEOUT,
    ErrorCategory.SERVER,
    ErrorCategory.TRANSPORT,
}


def with_retry(
    fn: Callable[[str], object],
    endpoints: list[str],
    *,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
    classify: Callable[[Exception], ErrorCategory] = classify_error,
):
    if not endpoints:
        raise ValueError("endpoints must be non-empty")
    last: Exception | None = None
    for attempt in range(max_attempts):
        endpoint = endpoints[attempt % len(endpoints)]
        try:
            return fn(endpoint)
        except Exception as exc:  # noqa: BLE001 — classify decides retryability
            category = classify(exc)
            last = exc
            if category not in RETRYABLE:
                raise
            if attempt + 1 < max_attempts:
                sleep(base_delay * (2 ** attempt))
    assert last is not None
    raise last
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_fallback.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add envforge/models/fallback.py tests/test_fallback.py
git commit -m "Add retry/backoff/endpoint-swap helper"
```

---

## Task 11: Model gateway

**Files:**
- Create: `envforge/envforge/models/gateway.py`
- Test: `envforge/tests/test_gateway.py`

**Interfaces:**
- Consumes: `BudgetLedger`, `BudgetExceeded` (Task 9); `with_retry` (Task 10); `TransportError` (Task 8).
- Produces:
  - `@dataclass class ModelResponse`: `text: str`, `cost: float`, `raw: dict`.
  - `@dataclass class ModelSpec`: `provider: str`, `model: str`, `endpoints: list[str]`.
  - `class Transport(Protocol)`: `def call(self, endpoint: str, spec: ModelSpec, messages: list[dict], **kw) -> ModelResponse`.
  - `class FakeTransport`: constructed with a list of scripted responses/exceptions; raises/returns them in order; records `.calls`.
  - `class ModelGateway`:
    - `ModelGateway(role_specs: dict[str, ModelSpec], ledger: BudgetLedger, transport: Transport, *, sleep=time.sleep)`.
    - `.call(role: str, messages: list[dict], **kw) -> ModelResponse` — `ledger.check(role)` first (raises `BudgetExceeded`); then `with_retry` over `spec.endpoints` calling `transport.call`; on success `ledger.record(role, response.cost)` and return. Unknown role → `KeyError`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_gateway.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_gateway.py -v`
Expected: FAIL with `ModuleNotFoundError: envforge.models.gateway`.

- [ ] **Step 3: Write minimal implementation**

```python
# envforge/models/gateway.py
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Protocol

from .budget import BudgetLedger
from .fallback import with_retry


@dataclass
class ModelResponse:
    text: str
    cost: float
    raw: dict = field(default_factory=dict)


@dataclass
class ModelSpec:
    provider: str
    model: str
    endpoints: list[str]


class Transport(Protocol):
    def call(self, endpoint: str, spec: ModelSpec, messages: list[dict], **kw) -> ModelResponse:
        ...


class FakeTransport:
    """Test transport: replays scripted responses/exceptions in order."""

    def __init__(self, scripted: list):
        self._scripted = list(scripted)
        self.calls: list[dict] = []

    def call(self, endpoint: str, spec: ModelSpec, messages: list[dict], **kw) -> ModelResponse:
        self.calls.append({"endpoint": endpoint, "spec": spec, "messages": messages})
        item = self._scripted.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class ModelGateway:
    def __init__(
        self,
        role_specs: dict[str, ModelSpec],
        ledger: BudgetLedger,
        transport: Transport,
        *,
        sleep=time.sleep,
    ):
        self._specs = role_specs
        self._ledger = ledger
        self._transport = transport
        self._sleep = sleep

    def call(self, role: str, messages: list[dict], **kw) -> ModelResponse:
        spec = self._specs[role]  # KeyError on unknown role — intentional
        self._ledger.check(role)  # may raise BudgetExceeded before any spend

        def attempt(endpoint: str) -> ModelResponse:
            return self._transport.call(endpoint, spec, messages, **kw)

        resp = with_retry(attempt, spec.endpoints, sleep=self._sleep)
        self._ledger.record(role, resp.cost)
        return resp
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_gateway.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add envforge/models/gateway.py tests/test_gateway.py
git commit -m "Add model gateway over budget + fallback"
```

---

## Task 12: Runtime interface & LocalRuntime

**Files:**
- Create: `envforge/envforge/runtimes/base.py`
- Create: `envforge/envforge/runtimes/local.py`
- Test: `envforge/tests/test_local_runtime.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `@dataclass class CommandResult`: `returncode: int`, `stdout: str`, `stderr: str`.
  - `class Runtime(Protocol)`: `def prepare_env(self) -> None`; `def run(self, cmd: list[str], *, cwd: Path | None = None, timeout: float | None = None) -> CommandResult`; `def free_gb(self, path: Path) -> float`.
  - `class LocalRuntime`: implements `Runtime`. `prepare_env` is a no-op (host venv assumed). `run` uses `subprocess.run`. `free_gb` uses `shutil.disk_usage`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_local_runtime.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_local_runtime.py -v`
Expected: FAIL with `ModuleNotFoundError: envforge.runtimes.local`.

- [ ] **Step 3: Write minimal implementation**

```python
# envforge/runtimes/base.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


class Runtime(Protocol):
    def prepare_env(self) -> None: ...
    def run(self, cmd: list[str], *, cwd: Path | None = None, timeout: float | None = None) -> CommandResult: ...
    def free_gb(self, path: Path) -> float: ...
```

```python
# envforge/runtimes/local.py
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .base import CommandResult


class LocalRuntime:
    def prepare_env(self) -> None:
        return None

    def run(self, cmd: list[str], *, cwd: Path | None = None, timeout: float | None = None) -> CommandResult:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return CommandResult(proc.returncode, proc.stdout, proc.stderr)

    def free_gb(self, path: Path) -> float:
        usage = shutil.disk_usage(str(path))
        return usage.free / (1024 ** 3)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_local_runtime.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add envforge/runtimes/base.py envforge/runtimes/local.py tests/test_local_runtime.py
git commit -m "Add Runtime interface and LocalRuntime"
```

---

## Task 13: Phase interface & demo phases

**Files:**
- Create: `envforge/envforge/phases/base.py`
- Create: `envforge/envforge/phases/demo.py`
- Test: extended in Task 14 (orchestrator) — demo phases are exercised there.

**Interfaces:**
- Consumes: `ExitCode` (Task 3); `ModelGateway` (Task 11); `StatusWriter` (Task 7); `RunStore` (Task 4); `PortBroker` (Task 6); `Runtime` (Task 12).
- Produces:
  - `@dataclass class PhaseResult`: `ok: bool`; `result: dict = {}`; `exit_code: ExitCode | None = None`; `reason: str = ""`. Helpers: `PhaseResult.done(**result)`, `PhaseResult.fail(exit_code, reason)`.
  - `@dataclass class PhaseContext`: `runstore: RunStore`, `gateway: ModelGateway`, `ports: PortBroker`, `status: StatusWriter`, `runtime: Runtime`, `config: dict`, `now: Callable[[], str]`.
  - `class Phase(Protocol)`: attribute `name: str`; `def run(self, ctx: PhaseContext) -> PhaseResult`.
  - `class GeneratePhase`, `class HealthPhase`, `class EvalPhase`: deterministic demo phases. `GeneratePhase` leases a port named `"app"` and returns `done(files=3)`. `HealthPhase` returns `done(healthy=True)`. `EvalPhase` returns `done(passed=2, failed=1)`. A `FAIL_PHASE` env-style flag in `ctx.config` lets a phase be forced to fail for tests (`config["fail_eval"] = (ExitCode.EVAL_HARNESS_FAILURE, "forced")`).
  - `DEMO_PHASES: list[Phase]` = `[GeneratePhase(), HealthPhase(), EvalPhase()]` and `DEMO_ORDER: list[str]` = their names.

- [ ] **Step 1: Write `phases/base.py`**

```python
# envforge/phases/base.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Protocol

from ..core.exits import ExitCode
from ..core.ports import PortBroker
from ..core.runstore import RunStore
from ..core.status import StatusWriter
from ..models.gateway import ModelGateway
from ..runtimes.base import Runtime


@dataclass
class PhaseResult:
    ok: bool
    result: dict = field(default_factory=dict)
    exit_code: ExitCode | None = None
    reason: str = ""

    @classmethod
    def done(cls, **result) -> "PhaseResult":
        return cls(ok=True, result=result)

    @classmethod
    def fail(cls, exit_code: ExitCode, reason: str) -> "PhaseResult":
        return cls(ok=False, exit_code=exit_code, reason=reason)


@dataclass
class PhaseContext:
    runstore: RunStore
    gateway: ModelGateway
    ports: PortBroker
    status: StatusWriter
    runtime: Runtime
    config: dict
    now: Callable[[], str]


class Phase(Protocol):
    name: str

    def run(self, ctx: PhaseContext) -> PhaseResult: ...
```

- [ ] **Step 2: Write `phases/demo.py`**

```python
# envforge/phases/demo.py
from __future__ import annotations

from ..core.exits import ExitCode
from .base import Phase, PhaseContext, PhaseResult


class GeneratePhase:
    name = "generate"

    def run(self, ctx: PhaseContext) -> PhaseResult:
        port = ctx.ports.lease(f"{ctx.runstore.run_id}:app")
        ctx.runstore.record_port("app", port)
        return PhaseResult.done(files=3, port=port)


class HealthPhase:
    name = "health"

    def run(self, ctx: PhaseContext) -> PhaseResult:
        if ctx.config.get("fail_health"):
            code, reason = ctx.config["fail_health"]
            return PhaseResult.fail(code, reason)
        return PhaseResult.done(healthy=True)


class EvalPhase:
    name = "eval"

    def run(self, ctx: PhaseContext) -> PhaseResult:
        if ctx.config.get("fail_eval"):
            code, reason = ctx.config["fail_eval"]
            return PhaseResult.fail(code, reason)
        return PhaseResult.done(passed=2, failed=1)


DEMO_PHASES: list[Phase] = [GeneratePhase(), HealthPhase(), EvalPhase()]
DEMO_ORDER: list[str] = [p.name for p in DEMO_PHASES]
```

- [ ] **Step 3: Verify it imports**

Run: `uv run python -c "from envforge.phases.demo import DEMO_PHASES, DEMO_ORDER; print(DEMO_ORDER)"`
Expected: prints `['generate', 'health', 'eval']`.

- [ ] **Step 4: Commit**

```bash
git add envforge/phases/base.py envforge/phases/demo.py
git commit -m "Add phase interface and deterministic demo phases"
```

---

## Task 14: Orchestrator (the state machine)

**Files:**
- Create: `envforge/envforge/core/orchestrator.py`
- Test: `envforge/tests/test_orchestrator.py`

**Interfaces:**
- Consumes: `RunStore`, `StepStatus` (Task 4); `ExitCode`, `EnvforgeExit` (Task 3); `StatusWriter` (Task 7); `Phase`, `PhaseContext`, `PhaseResult` (Task 13).
- Produces:
  - `class Orchestrator`:
    - `Orchestrator(runstore: RunStore, phases: list[Phase], order: list[str], ctx: PhaseContext)`.
    - `.run() -> ExitCode` — iterate `order`; skip steps already `DONE` (idempotent resume); for each pending step: mark `RUNNING` + status + activity, call `phase.run(ctx)`; on `ok` → mark `DONE` (store `result`) + activity; on failure → mark `FAILED`, `runstore.set_exit(...)`, status, and return `result.exit_code`. After all steps `DONE`, `set_exit(OK, ...)`, status, return `ExitCode.OK`. A raised `EnvforgeExit` from inside a phase is caught → mark step `FAILED`, record that exit, return its code. Any other exception → mark `FAILED`, record `FATAL`, return `ExitCode.FATAL`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_orchestrator.py
from pathlib import Path
import pytest

from envforge.core.runstore import RunStore, StepStatus
from envforge.core.orchestrator import Orchestrator
from envforge.core.exits import ExitCode, EnvforgeExit
from envforge.core.ports import PortBroker
from envforge.core.status import StatusWriter
from envforge.models.gateway import ModelGateway, ModelSpec, FakeTransport
from envforge.models.budget import BudgetLedger
from envforge.runtimes.local import LocalRuntime
from envforge.phases.base import PhaseContext, PhaseResult
from envforge.phases.demo import DEMO_PHASES, DEMO_ORDER, GeneratePhase

NOW = "2026-06-19T00:00:00Z"


def _ctx(tmp_path: Path, runstore: RunStore, config: dict) -> PhaseContext:
    gw = ModelGateway({}, BudgetLedger({}), FakeTransport([]), sleep=lambda s: None)
    return PhaseContext(
        runstore=runstore,
        gateway=gw,
        ports=PortBroker(tmp_path / "ports", start=8200, end=8210, is_free=lambda p: True),
        status=StatusWriter(tmp_path / "status"),
        runtime=LocalRuntime(),
        config=config,
        now=lambda: NOW,
    )


def test_full_run_marks_all_done_and_returns_ok(tmp_path: Path):
    rs = RunStore.create(tmp_path / "runs", "r", "demo", now=NOW)
    orch = Orchestrator(rs, DEMO_PHASES, DEMO_ORDER, _ctx(tmp_path, rs, {}))
    code = orch.run()
    assert code is ExitCode.OK
    for name in DEMO_ORDER:
        assert rs.step_status(name) is StepStatus.DONE


def test_failed_phase_returns_classified_code(tmp_path: Path):
    rs = RunStore.create(tmp_path / "runs", "r", "demo", now=NOW)
    cfg = {"fail_eval": (ExitCode.EVAL_HARNESS_FAILURE, "forced")}
    orch = Orchestrator(rs, DEMO_PHASES, DEMO_ORDER, _ctx(tmp_path, rs, cfg))
    code = orch.run()
    assert code is ExitCode.EVAL_HARNESS_FAILURE
    assert rs.step_status("eval") is StepStatus.FAILED
    assert rs.step_status("generate") is StepStatus.DONE
    assert rs.exit_code is ExitCode.EVAL_HARNESS_FAILURE


def test_resume_skips_done_steps(tmp_path: Path):
    rs = RunStore.create(tmp_path / "runs", "r", "demo", now=NOW)
    rs.set_step("generate", StepStatus.DONE, result={"files": 3, "port": 8200}, now=NOW)

    class BoomGenerate(GeneratePhase):
        def run(self, ctx):  # would fail if called
            raise AssertionError("generate should have been skipped")

    phases = [BoomGenerate()] + DEMO_PHASES[1:]
    orch = Orchestrator(rs, phases, DEMO_ORDER, _ctx(tmp_path, rs, {}))
    assert orch.run() is ExitCode.OK


def test_envforge_exit_inside_phase_is_classified(tmp_path: Path):
    rs = RunStore.create(tmp_path / "runs", "r", "demo", now=NOW)

    class RaisingHealth:
        name = "health"

        def run(self, ctx):
            raise EnvforgeExit(ExitCode.APP_UNHEALTHY, "no boot")

    phases = [DEMO_PHASES[0], RaisingHealth(), DEMO_PHASES[2]]
    orch = Orchestrator(rs, phases, DEMO_ORDER, _ctx(tmp_path, rs, {}))
    assert orch.run() is ExitCode.APP_UNHEALTHY
    assert rs.step_status("health") is StepStatus.FAILED


def test_unexpected_exception_becomes_fatal(tmp_path: Path):
    rs = RunStore.create(tmp_path / "runs", "r", "demo", now=NOW)

    class BadHealth:
        name = "health"

        def run(self, ctx):
            raise RuntimeError("kaboom")

    phases = [DEMO_PHASES[0], BadHealth(), DEMO_PHASES[2]]
    orch = Orchestrator(rs, phases, DEMO_ORDER, _ctx(tmp_path, rs, {}))
    assert orch.run() is ExitCode.FATAL
    assert rs.exit_code is ExitCode.FATAL
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_orchestrator.py -v`
Expected: FAIL with `ModuleNotFoundError: envforge.core.orchestrator`.

- [ ] **Step 3: Write minimal implementation**

```python
# envforge/core/orchestrator.py
from __future__ import annotations

from ..phases.base import Phase, PhaseContext
from .exits import EnvforgeExit, ExitCode
from .runstore import RunStore, StepStatus
from .status import StatusWriter


class Orchestrator:
    def __init__(self, runstore: RunStore, phases: list[Phase], order: list[str], ctx: PhaseContext):
        self._rs = runstore
        self._by_name = {p.name: p for p in phases}
        self._order = order
        self._ctx = ctx
        self._status: StatusWriter = ctx.status

    def run(self) -> ExitCode:
        for name in self._order:
            if self._rs.step_status(name) is StepStatus.DONE:
                continue
            code = self._run_one(name)
            if code is not None:
                return code
        now = self._ctx.now()
        self._rs.set_exit(ExitCode.OK, "all phases complete", now=now)
        self._status.write_status({"phase": "done", "exit": "OK"}, now=now)
        return ExitCode.OK

    def _run_one(self, name: str) -> ExitCode | None:
        now = self._ctx.now()
        phase = self._by_name[name]
        self._rs.set_step(name, StepStatus.RUNNING, now=now)
        self._status.write_status({"phase": name, "step_status": "running"}, now=now)
        self._status.activity("phase_start", now=now, phase=name)
        try:
            result = phase.run(self._ctx)
        except EnvforgeExit as exc:
            return self._fail(name, exc.code, exc.reason)
        except Exception as exc:  # noqa: BLE001 — any phase crash is a classified FATAL
            return self._fail(name, ExitCode.FATAL, f"{type(exc).__name__}: {exc}")

        if result.ok:
            done_now = self._ctx.now()
            self._rs.set_step(name, StepStatus.DONE, result=result.result, now=done_now)
            self._status.activity("phase_done", now=done_now, phase=name, **result.result)
            return None
        return self._fail(name, result.exit_code or ExitCode.FATAL, result.reason)

    def _fail(self, name: str, code: ExitCode, reason: str) -> ExitCode:
        now = self._ctx.now()
        self._rs.set_step(name, StepStatus.FAILED, result={"reason": reason}, now=now)
        self._rs.set_exit(code, reason, now=now)
        self._status.write_status(
            {"phase": name, "step_status": "failed", "exit": code.name, "reason": reason}, now=now
        )
        self._status.activity("phase_failed", now=now, phase=name, exit=code.name, reason=reason)
        return code
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_orchestrator.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add envforge/core/orchestrator.py tests/test_orchestrator.py
git commit -m "Add orchestrator state machine with classified exits and resume"
```

---

## Task 15: CLI (run | resume | status | clean)

**Files:**
- Create: `envforge/envforge/cli.py`
- Test: `envforge/tests/test_cli.py`

**Interfaces:**
- Consumes: everything above. Builds the wiring: a run id, `RunStore`, `RunLock`, `PortBroker`, `StatusWriter`, `ModelGateway` (with `FakeTransport` for the demo kind), `LocalRuntime`, `DEMO_PHASES`/`DEMO_ORDER`, and `Orchestrator`.
- Produces:
  - `def build_run_id(kind: str, now: str) -> str` — `f"{kind}-{now-compacted}"` (deterministic given inputs; replace `:`/`-`/`T`/`Z`).
  - `def cmd_run(args, *, now, host, pid) -> int`, `def cmd_resume(...)`, `def cmd_status(...)`, `def cmd_clean(...)` — each returns an exit code int.
  - `def main(argv: list[str] | None = None) -> int` — argparse dispatch; the single place that maps `EnvforgeExit`/`ExitCode` to a process exit code and is the only `sys.exit` site (via `raise SystemExit(main())` under `__main__`).
- Note: for the demo kind, the gateway uses a `FakeTransport([])` and budget caps `{}` (unlimited) — the demo phases never call the model, so no scripted responses are needed.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli.py
import json
from pathlib import Path
import pytest
from envforge import cli
from envforge.core.exits import ExitCode

NOW = "2026-06-19T00:00:00Z"


def _args_run(runs_root: Path):
    ns = cli.build_parser().parse_args(
        ["run", "--kind", "demo", "--runs-root", str(runs_root), "--ports-dir", str(runs_root / "ports")]
    )
    return ns


def test_run_demo_completes_ok(tmp_path: Path):
    ns = _args_run(tmp_path)
    code = cli.cmd_run(ns, now=NOW, host="hostA", pid=123)
    assert code == int(ExitCode.OK)
    run_id = cli.build_run_id("demo", NOW)
    state = json.loads((tmp_path / run_id / "state.json").read_text())
    assert state["steps"]["eval"]["status"] == "done"
    assert state["exit"]["name"] == "OK"


def test_status_dir_outside_run_dir_has_status_json(tmp_path: Path):
    ns = _args_run(tmp_path)
    cli.cmd_run(ns, now=NOW, host="hostA", pid=123)
    run_id = cli.build_run_id("demo", NOW)
    # status lives under <run_dir>/_status, never inside a synced app dir
    assert (tmp_path / run_id / "_status" / "STATUS.json").exists()


def test_resume_is_idempotent(tmp_path: Path):
    ns = _args_run(tmp_path)
    cli.cmd_run(ns, now=NOW, host="hostA", pid=123)
    run_id = cli.build_run_id("demo", NOW)
    rns = cli.build_parser().parse_args(["resume", "--run", run_id, "--runs-root", str(tmp_path), "--ports-dir", str(tmp_path / "ports")])
    code = cli.cmd_resume(rns, now=NOW, host="hostA", pid=124)
    assert code == int(ExitCode.OK)


def test_duplicate_run_id_blocked_by_live_lock(tmp_path: Path):
    # Pre-write a live lock for the run, then resume from a different live pid → DUPLICATE_JOB
    ns = _args_run(tmp_path)
    cli.cmd_run(ns, now=NOW, host="hostA", pid=123)
    run_id = cli.build_run_id("demo", NOW)
    from envforge.core.lock import RunLock
    lock_path = tmp_path / run_id / "run.lock"
    RunLock(lock_path, pid=999, host="hostA", alive=lambda p: True).acquire(now=10_000.0)
    rns = cli.build_parser().parse_args(["resume", "--run", run_id, "--runs-root", str(tmp_path), "--ports-dir", str(tmp_path / "ports")])
    code = cli.cmd_resume(rns, now=NOW, host="hostA", pid=124, lock_now=10_001.0, alive=lambda p: True)
    assert code == int(ExitCode.DUPLICATE_JOB)


def test_main_dispatch_returns_int(tmp_path: Path):
    code = cli.main(["status", "--run", "missing", "--runs-root", str(tmp_path)])
    assert isinstance(code, int)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL with `ImportError`/`AttributeError` on `envforge.cli`.

- [ ] **Step 3: Write minimal implementation**

```python
# envforge/cli.py
from __future__ import annotations

import argparse
import datetime as _dt
import os
import socket
import sys
import tarfile
from pathlib import Path

from .core.exits import EnvforgeExit, ExitCode
from .core.lock import DuplicateJobError, RunLock, pid_alive
from .core.orchestrator import Orchestrator
from .core.ports import PortBroker
from .core.runstore import RunStore
from .core.status import StatusWriter
from .models.budget import BudgetLedger
from .models.gateway import FakeTransport, ModelGateway
from .phases.base import PhaseContext
from .phases.demo import DEMO_ORDER, DEMO_PHASES
from .runtimes.local import LocalRuntime


def _utcnow() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_run_id(kind: str, now: str) -> str:
    compact = now.replace(":", "").replace("-", "").replace("T", "-").replace("Z", "")
    return f"{kind}-{compact}"


# Registry maps a kind name to (phases, order). Only "demo" exists in Plan 1.
KINDS = {"demo": (DEMO_PHASES, DEMO_ORDER)}


def _build_orchestrator(runs_root: Path, run_id: str, kind: str, ports_dir: Path, now: str) -> tuple[Orchestrator, RunStore]:
    if RunStore.exists(runs_root, run_id):
        rs = RunStore.load(runs_root, run_id)
    else:
        rs = RunStore.create(runs_root, run_id, kind, now=now)
    phases, order = KINDS[rs.kind]
    status = StatusWriter(rs.run_dir / "_status")
    gateway = ModelGateway({}, BudgetLedger({}), FakeTransport([]), sleep=lambda s: None)
    ctx = PhaseContext(
        runstore=rs,
        gateway=gateway,
        ports=PortBroker(ports_dir),
        status=status,
        runtime=LocalRuntime(),
        config={},
        now=lambda: now,
    )
    return Orchestrator(rs, phases, order, ctx), rs


def _drive(runs_root: Path, run_id: str, kind: str, ports_dir: Path, *, now: str, host: str, pid: int, lock_now: float, alive) -> int:
    run_dir = Path(runs_root) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    lock = RunLock(run_dir / "run.lock", pid=pid, host=host, alive=alive)
    try:
        lock.acquire(now=lock_now)
    except DuplicateJobError:
        return int(ExitCode.DUPLICATE_JOB)
    try:
        orch, _rs = _build_orchestrator(runs_root, run_id, kind, ports_dir, now)
        return int(orch.run())
    except EnvforgeExit as exc:
        return int(exc.code)
    finally:
        lock.release()


def cmd_run(args, *, now: str | None = None, host: str | None = None, pid: int | None = None, lock_now: float | None = None, alive=pid_alive) -> int:
    now = now or _utcnow()
    run_id = build_run_id(args.kind, now)
    return _drive(
        Path(args.runs_root), run_id, args.kind, Path(args.ports_dir),
        now=now, host=host or socket.gethostname(), pid=pid or os.getpid(),
        lock_now=lock_now if lock_now is not None else 0.0, alive=alive,
    )


def cmd_resume(args, *, now: str | None = None, host: str | None = None, pid: int | None = None, lock_now: float | None = None, alive=pid_alive) -> int:
    now = now or _utcnow()
    if not RunStore.exists(Path(args.runs_root), args.run):
        print(f"no such run: {args.run}", file=sys.stderr)
        return int(ExitCode.FATAL)
    kind = RunStore.load(Path(args.runs_root), args.run).kind
    return _drive(
        Path(args.runs_root), args.run, kind, Path(args.ports_dir),
        now=now, host=host or socket.gethostname(), pid=pid or os.getpid(),
        lock_now=lock_now if lock_now is not None else 0.0, alive=alive,
    )


def cmd_status(args, **_kw) -> int:
    status_path = Path(args.runs_root) / args.run / "_status" / "STATUS.json"
    if not status_path.exists():
        print(f"no status for run: {args.run}", file=sys.stderr)
        return int(ExitCode.FATAL)
    print(status_path.read_text())
    return int(ExitCode.OK)


def cmd_clean(args, **_kw) -> int:
    run_dir = Path(args.runs_root) / args.run
    if not run_dir.exists():
        print(f"no such run: {args.run}", file=sys.stderr)
        return int(ExitCode.FATAL)
    if args.dry_run:
        print(f"[dry-run] would tar-then-remove {run_dir}")
        return int(ExitCode.OK)
    backup = run_dir.with_suffix(".tar.gz")
    with tarfile.open(backup, "w:gz") as tar:  # tar-first, never blind-delete
        tar.add(run_dir, arcname=run_dir.name)
    print(f"backed up to {backup} (left {run_dir} in place; remove manually)")
    return int(ExitCode.OK)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="envforge")
    sub = p.add_subparsers(dest="command", required=True)

    def add_common(sp):
        sp.add_argument("--runs-root", required=True)
        sp.add_argument("--ports-dir", default=None)

    r = sub.add_parser("run")
    r.add_argument("--kind", default="demo", choices=list(KINDS))
    add_common(r)
    r.set_defaults(func=cmd_run)

    rs = sub.add_parser("resume")
    rs.add_argument("--run", required=True)
    add_common(rs)
    rs.set_defaults(func=cmd_resume)

    st = sub.add_parser("status")
    st.add_argument("--run", required=True)
    st.add_argument("--runs-root", required=True)
    st.set_defaults(func=cmd_status)

    cl = sub.add_parser("clean")
    cl.add_argument("--run", required=True)
    cl.add_argument("--runs-root", required=True)
    cl.add_argument("--dry-run", action="store_true")
    cl.set_defaults(func=cmd_clean)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "ports_dir", None) is None and hasattr(args, "ports_dir"):
        args.ports_dir = str(Path(args.runs_root) / "_ports")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli.py -v`
Expected: 5 passed.

- [ ] **Step 5: Run the CLI end-to-end by hand**

Run:
```bash
uv run envforge run --kind demo --runs-root /tmp/ef-runs
uv run envforge status --run "$(ls /tmp/ef-runs | grep demo | head -1)" --runs-root /tmp/ef-runs
```
Expected: run exits 0; status prints a `STATUS.json` with `"phase": "done"`, `"exit": "OK"`.

- [ ] **Step 6: Commit**

```bash
git add envforge/cli.py tests/test_cli.py
git commit -m "Add envforge CLI: run/resume/status/clean over the demo kind"
```

---

## Task 16: Full-suite green + README

**Files:**
- Create: `envforge/README.md`
- Test: full suite.

**Interfaces:**
- Consumes: everything.
- Produces: a passing test suite and a short README documenting the CLI and the core concepts.

- [ ] **Step 1: Run the whole suite**

Run: `uv run pytest -q`
Expected: all tests pass (≈ 50+ across the modules), zero failures.

- [ ] **Step 2: Write `README.md`**

```markdown
# envforge

Multi-model pipeline for generating and evaluating webarena-style environments,
reliable with both Claude and open-source models.

This repository currently contains the **robustness core** (Plan 1): a durable
state-machine runner with a model gateway, budget caps, port leasing,
duplicate-job locking, classified exits, and durable status. A built-in `demo`
kind exercises the full machine with no models or browsers.

## Quickstart

```bash
uv venv && uv pip install -e ".[dev]"
uv run pytest -q
uv run envforge run --kind demo --runs-root /tmp/ef-runs
```

## Concepts

- **Run-store** — durable JSON state for a run, outside any synced directory.
- **Orchestrator** — advances ordered, idempotent phase steps; resume re-runs it.
- **Model gateway** — single entry for all model calls; budget caps + fallback.
- **Run lock** — PID/host/heartbeat guard against duplicate jobs.
- **Port broker** — atomic port leases (no collisions).
- **Classified exits** — every termination carries an `ExitCode`.

See `docs/superpowers/specs/` for the design and `docs/superpowers/plans/` for
the implementation plans.
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "Add README; robustness core complete and green"
```

---

## Self-Review

**1. Spec coverage** (against `2026-06-19-envforge-design.md`):
- §6 model gateway (selection/budget/fallback) → Tasks 8–11. ✓
- §7 orchestrator + run-store + lock + exits + status → Tasks 3,4,5,7,14. ✓
- §8 runtime backends (local; single-process setup is local no-op here, BlueVela deferred to Plan 4) → Task 12. ✓
- §9 browser kind, health gates → **deferred to Plan 2** (explicitly out of this plan's scope). ✓
- §12 issue mapping: #7 (status outside synced dir) → Task 15 uses `<run_dir>/_status`; #8–11 (budget) → Task 9; #12 (endpoint swap) → Task 10; #13 (dup jobs) → Task 5; #14 (ports) → Task 6; #16 (structured status) → Task 7. Remaining issues (#1–6 env setup, #2 browser, #3 health, #15 watcher, #17 ssh, #18 disk cleanup beyond the tar-first `clean`) → Plans 2/4. ✓ (no gap within this plan's stated scope)

**2. Placeholder scan:** No "TBD"/"handle edge cases"/"similar to"/"write tests for the above" — every code and test step contains complete content. ✓

**3. Type consistency:** `PhaseResult.done/fail`, `PhaseContext` fields, `ModelResponse(text,cost,raw)`, `ModelSpec(provider,model,endpoints)`, `StepStatus` values, `ExitCode` members, and `RunStore` method names are used identically in their defining tasks (4,11,13) and consuming tasks (14,15). `with_retry(fn, endpoints, ...)` signature matches its use in `ModelGateway.call`. ✓

---

## Out of scope (later plans)

- **Plan 2:** `agents/` (opencode `CodingAgent`, browser_use `EvalAgent`), `kinds/browser_webapp/` (`/api/state` protocol, 3 health gates), real `OpenAITransport`, the generate→eval vertical slice.
- **Plan 3:** function-task / audit / real-task / hardening / regression phases.
- **Plan 4:** `runtimes/bluevela.py` (LSF/enroot single-process setup), external status watcher.
