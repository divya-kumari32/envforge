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
