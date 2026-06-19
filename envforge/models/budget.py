from __future__ import annotations


class BudgetExceeded(Exception):
    def __init__(self, role: str, spent: float, cap: float):
        super().__init__(f"budget for role '{role}' exceeded: {spent} >= {cap}")
        self.role = role
        self.spent = spent
        self.cap = cap


class BudgetLedger:
    def __init__(self, caps: dict[str, float | None]):
        self._caps = dict(caps)
        self._spent: dict[str, float] = {}

    def record(self, role: str, cost: float) -> None:
        # Record the cost first (so an over-cap charge is always accounted for),
        # then raise only when the total has gone strictly OVER the cap. Note
        # this is `>`, not `>=`: landing exactly on the cap is allowed by
        # record(), while check() (>=) treats at-cap as already exhausted.
        self._spent[role] = self._spent.get(role, 0.0) + cost
        cap = self._caps.get(role)
        if cap is not None and self._spent[role] > cap:
            raise BudgetExceeded(role, self._spent[role], cap)

    def spent(self, role: str | None = None) -> float:
        if role is None:
            return sum(self._spent.values())
        return self._spent.get(role, 0.0)

    def check(self, role: str) -> None:
        cap = self._caps.get(role)
        if cap is not None and self._spent.get(role, 0.0) >= cap:
            raise BudgetExceeded(role, self._spent.get(role, 0.0), cap)

    def to_dict(self) -> dict:
        return {"caps": self._caps, "spent": self._spent}

    @classmethod
    def from_dict(cls, d: dict) -> "BudgetLedger":
        led = cls(d.get("caps", {}))
        led._spent = dict(d.get("spent", {}))
        return led
