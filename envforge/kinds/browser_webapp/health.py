# envforge/kinds/browser_webapp/health.py
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from ...agents.base import EvalAgent
from .protocol import StateServer

REQUIRED_FILES = ["index.html", "server.py"]


@dataclass
class HealthReport:
    ok: bool
    gate: str
    detail: str


def structural_gate(app_dir: Path) -> HealthReport:
    for f in REQUIRED_FILES:
        p = Path(app_dir) / f
        if not p.exists():
            return HealthReport(False, "structural", f"missing required file: {f}")
        if p.stat().st_size == 0:
            return HealthReport(False, "structural", f"required file is empty: {f}")
    return HealthReport(True, "structural", "")


def _get_state_status(url: str) -> int:
    try:
        with urllib.request.urlopen(f"{url}/api/state", timeout=3) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def _put_state(url: str, data: object) -> None:
    body = json.dumps(data).encode()
    req = urllib.request.Request(f"{url}/api/state", data=body, method="PUT",
                                 headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=3).read()


async def boot_serve_gate(app_dir: Path, port: int) -> HealthReport:
    server = StateServer(Path(app_dir), port=port)
    server.start()
    try:
        _put_state(server.url, {"probe": 1})
        if _get_state_status(server.url) != 200:
            return HealthReport(False, "boot_serve", "GET /api/state did not return 200 after PUT")
    finally:
        server.stop()
    # Restart on a fresh server: state must NOT survive a restart (the app drives it,
    # so a stale on-disk seed cannot mask a broken-JS app).
    server2 = StateServer(Path(app_dir), port=port)
    server2.start()
    try:
        if _get_state_status(server2.url) != 404:
            return HealthReport(False, "boot_serve", "state unexpectedly persisted across restart")
    finally:
        server2.stop()
    return HealthReport(True, "boot_serve", "")


async def eval_liveness_gate(eval_agent: EvalAgent, server_url: str) -> HealthReport:
    try:
        await eval_agent.setup(server_url)
        await eval_agent.teardown()
    except Exception as exc:  # noqa: BLE001
        return HealthReport(False, "eval_liveness", f"{type(exc).__name__}: {exc}")
    return HealthReport(True, "eval_liveness", "")


async def run_all_gates(app_dir: Path, *, port: int, eval_agent: EvalAgent, server_url: str) -> HealthReport:
    rep = structural_gate(app_dir)
    if not rep.ok:
        return rep
    rep = await boot_serve_gate(app_dir, port)
    if not rep.ok:
        return rep
    rep = await eval_liveness_gate(eval_agent, server_url)
    if not rep.ok:
        return rep
    return HealthReport(True, "all", "")
