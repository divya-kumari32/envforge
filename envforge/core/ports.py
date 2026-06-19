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
