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
