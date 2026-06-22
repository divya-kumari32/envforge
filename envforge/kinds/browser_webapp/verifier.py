# envforge/kinds/browser_webapp/verifier.py
from __future__ import annotations

import importlib.util
import uuid
from dataclasses import dataclass
from pathlib import Path


@dataclass
class VerifyOutcome:
    passed: bool
    detail: str


def run_verifier(verifier_path: Path, server_url: str) -> VerifyOutcome:
    try:
        spec = importlib.util.spec_from_file_location(f"verifier_{uuid.uuid4().hex}", verifier_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        verify = getattr(module, "verify", None)
        if verify is None:
            return VerifyOutcome(False, "verifier has no verify(server_url) function")
        passed, detail = verify(server_url)
        return VerifyOutcome(bool(passed), str(detail))
    except Exception as exc:  # noqa: BLE001 — a broken verifier must never crash eval
        return VerifyOutcome(False, f"{type(exc).__name__}: {exc}")
