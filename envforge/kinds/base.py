# envforge/kinds/base.py
from __future__ import annotations

from typing import Protocol

from ..phases.base import Phase


class EnvironmentKind(Protocol):
    name: str

    def phases(self) -> list[Phase]: ...
    def order(self) -> list[str]: ...
