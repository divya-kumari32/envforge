# envforge/cli.py
from __future__ import annotations

import argparse
import datetime as _dt
import os
import socket
import sys
import tarfile
from pathlib import Path

from .core.exits import EnvforgeExit, ExitCode
from .core.lock import DuplicateJobError, RunLock, pid_alive
from .core.orchestrator import Orchestrator
from .core.ports import PortBroker
from .core.runstore import RunStore
from .core.status import StatusWriter
from .models.budget import BudgetLedger
from .models.gateway import FakeTransport, ModelGateway
from .phases.base import PhaseContext
from .phases.demo import DEMO_ORDER, DEMO_PHASES
from .runtimes.local import LocalRuntime


def _utcnow() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_run_id(kind: str, now: str) -> str:
    compact = now.replace(":", "").replace("-", "").replace("T", "-").replace("Z", "")
    return f"{kind}-{compact}"


# Registry maps a kind name to (phases, order). Only "demo" exists in Plan 1.
KINDS = {"demo": (DEMO_PHASES, DEMO_ORDER)}


def _build_orchestrator(runs_root: Path, run_id: str, kind: str, ports_dir: Path, now: str) -> tuple[Orchestrator, RunStore]:
    if RunStore.exists(runs_root, run_id):
        rs = RunStore.load(runs_root, run_id)
    else:
        rs = RunStore.create(runs_root, run_id, kind, now=now)
    phases, order = KINDS[rs.kind]
    status = StatusWriter(rs.run_dir / "_status")
    gateway = ModelGateway({}, BudgetLedger({}), FakeTransport([]), sleep=lambda s: None)
    ctx = PhaseContext(
        runstore=rs,
        gateway=gateway,
        ports=PortBroker(ports_dir),
        status=status,
        runtime=LocalRuntime(),
        config={},
        now=lambda: now,
    )
    return Orchestrator(rs, phases, order, ctx), rs


def _drive(runs_root: Path, run_id: str, kind: str, ports_dir: Path, *, now: str, host: str, pid: int, lock_now: float, alive) -> int:
    run_dir = Path(runs_root) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    lock = RunLock(run_dir / "run.lock", pid=pid, host=host, alive=alive)
    try:
        lock.acquire(now=lock_now)
    except DuplicateJobError:
        return int(ExitCode.DUPLICATE_JOB)
    try:
        orch, _rs = _build_orchestrator(runs_root, run_id, kind, ports_dir, now)
        return int(orch.run())
    except EnvforgeExit as exc:
        return int(exc.code)
    finally:
        lock.release()


def cmd_run(args, *, now: str | None = None, host: str | None = None, pid: int | None = None, lock_now: float | None = None, alive=pid_alive) -> int:
    now = now or _utcnow()
    run_id = build_run_id(args.kind, now)
    return _drive(
        Path(args.runs_root), run_id, args.kind, Path(args.ports_dir),
        now=now, host=host or socket.gethostname(), pid=pid or os.getpid(),
        lock_now=lock_now if lock_now is not None else 0.0, alive=alive,
    )


def cmd_resume(args, *, now: str | None = None, host: str | None = None, pid: int | None = None, lock_now: float | None = None, alive=pid_alive) -> int:
    now = now or _utcnow()
    if not RunStore.exists(Path(args.runs_root), args.run):
        print(f"no such run: {args.run}", file=sys.stderr)
        return int(ExitCode.FATAL)
    kind = RunStore.load(Path(args.runs_root), args.run).kind
    return _drive(
        Path(args.runs_root), args.run, kind, Path(args.ports_dir),
        now=now, host=host or socket.gethostname(), pid=pid or os.getpid(),
        lock_now=lock_now if lock_now is not None else 0.0, alive=alive,
    )


def cmd_status(args, **_kw) -> int:
    status_path = Path(args.runs_root) / args.run / "_status" / "STATUS.json"
    if not status_path.exists():
        print(f"no status for run: {args.run}", file=sys.stderr)
        return int(ExitCode.FATAL)
    print(status_path.read_text())
    return int(ExitCode.OK)


def cmd_clean(args, **_kw) -> int:
    run_dir = Path(args.runs_root) / args.run
    if not run_dir.exists():
        print(f"no such run: {args.run}", file=sys.stderr)
        return int(ExitCode.FATAL)
    if args.dry_run:
        print(f"[dry-run] would tar-then-remove {run_dir}")
        return int(ExitCode.OK)
    backup = run_dir.with_suffix(".tar.gz")
    with tarfile.open(backup, "w:gz") as tar:  # tar-first, never blind-delete
        tar.add(run_dir, arcname=run_dir.name)
    print(f"backed up to {backup} (left {run_dir} in place; remove manually)")
    return int(ExitCode.OK)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="envforge")
    sub = p.add_subparsers(dest="command", required=True)

    def add_common(sp):
        sp.add_argument("--runs-root", required=True)
        sp.add_argument("--ports-dir", default=None)

    r = sub.add_parser("run")
    r.add_argument("--kind", default="demo", choices=list(KINDS))
    add_common(r)
    r.set_defaults(func=cmd_run)

    rs = sub.add_parser("resume")
    rs.add_argument("--run", required=True)
    add_common(rs)
    rs.set_defaults(func=cmd_resume)

    st = sub.add_parser("status")
    st.add_argument("--run", required=True)
    st.add_argument("--runs-root", required=True)
    st.set_defaults(func=cmd_status)

    cl = sub.add_parser("clean")
    cl.add_argument("--run", required=True)
    cl.add_argument("--runs-root", required=True)
    cl.add_argument("--dry-run", action="store_true")
    cl.set_defaults(func=cmd_clean)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "ports_dir", None) is None and hasattr(args, "ports_dir"):
        args.ports_dir = str(Path(args.runs_root) / "_ports")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
