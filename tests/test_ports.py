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
