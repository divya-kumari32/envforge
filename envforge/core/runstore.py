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
