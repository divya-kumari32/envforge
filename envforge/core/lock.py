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
        pid = int(record.get("pid", -1))
        fresh = (now - float(record.get("heartbeat", 0))) <= self._ttl
        if not fresh:
            return False
        if record.get("host") == self._host:
            # Same host: we can directly probe the PID. A missing/invalid pid
            # (< 0) is never live — avoids os.kill(-1, ...) signalling everything.
            return pid >= 0 and self._alive(pid)
        # Different host (e.g. a shared filesystem across nodes): we cannot
        # probe the remote PID, so trust the heartbeat TTL alone. A fresh
        # heartbeat from another host means a live job → block as a duplicate.
        return True

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
