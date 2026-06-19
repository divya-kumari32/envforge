from __future__ import annotations

import json
from pathlib import Path

from .jsonio import atomic_write_json, read_json


class StatusWriter:
    def __init__(self, status_dir: Path):
        self._dir = Path(status_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._status_path = self._dir / "STATUS.json"
        self._activity_path = self._dir / "activity.jsonl"
        self._status: dict = {}
        if self._status_path.exists():
            try:
                loaded = read_json(self._status_path)
                if isinstance(loaded, dict):
                    self._status = loaded
            except (ValueError, OSError):
                self._status = {}

    def write_status(self, fields: dict, *, now: str) -> None:
        self._status.update(fields)
        self._status["updated_at"] = now
        atomic_write_json(self._status_path, self._status)

    def activity(self, event: str, *, now: str, **fields) -> None:
        record = {"ts": now, "event": event, **fields}
        with open(self._activity_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, sort_keys=False) + "\n")
