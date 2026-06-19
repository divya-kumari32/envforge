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
