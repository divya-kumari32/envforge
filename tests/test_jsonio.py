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
