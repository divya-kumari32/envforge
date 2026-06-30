# envforge/cli.py
#
# Entry point for the `envforge` command (exposed via [project.scripts] in
# pyproject.toml). Subcommands: run | resume | status | clean.
#
# Real browser_webapp run — what each flag expects and does:
#
#   export OPENAI_BASE_URL="https://your-endpoint/v1"  # OpenAI-compatible base URL
#   export OPENAI_API_KEY="your-key"                   # key for that endpoint
#
# By default generation uses the opencode CLI. To use the Claude Code CLI instead
# (which can drive OS models via an Anthropic-compatible proxy), add
# `--gen-agent claude` and set ANTHROPIC_BASE_URL / ANTHROPIC_AUTH_TOKEN to that
# endpoint; --gen-model is then a model id that endpoint serves.
#
#   envforge run \
#     --kind browser_webapp \          # which pipeline to run (see the two kinds below):
#                                      #   browser_webapp = the real pipeline (opencode
#                                      #     generation + browser_use eval; needs --docs,
#                                      #     models, an endpoint, Chromium);
#                                      #   test = the built-in model-free / browser-free
#                                      #     kind that just exercises the orchestrator
#                                      #     machinery (ignores --docs/--*-model/--task-count)
#     --docs       /path/to/app-docs \ # dir of docs the app is generated FROM (required)
#     --runs-root  /tmp/ef-runs \      # PARENT dir holding all runs; each run gets its own
#                                      #   subdir <kind>-<timestamp>/ created underneath it
#     --gen-model  litellm/<provider>/<model> \  # generation model handed to opencode;
#                                      #   must be <provider>/<model> where <provider>
#                                      #   matches a provider in your opencode.json
#     --eval-model <model-id> \        # eval model handed to browser_use; any model id
#                                      #   your endpoint serves (no opencode config needed)
#     --task-count 24 \                # how many tasks to GENERATE. Grading is never
#                                      #   selective: every task that ends up in the suite
#                                      #   is graded — this only sets how many are created.
#     --gen-timeout 14400              # per-phase coding-agent timeout in seconds; slow
#                                      #   models need more (default 3600)
#
# resume needs none of the above: the first run persists them to
# <run_dir>/_config.json, so `envforge resume --run <id> --runs-root <dir>` is enough.
from __future__ import annotations

import argparse
import datetime as _dt
import os
import socket
import sys
import tarfile
import time
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
from .phases.test import TEST_ORDER, TEST_PHASES
from .runtimes.local import LocalRuntime
from .core.jsonio import atomic_write_json, read_json


def _utcnow() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_run_id(kind: str, now: str) -> str:
    compact = now.replace(":", "").replace("-", "").replace("T", "-").replace("Z", "")
    return f"{kind}-{compact}"


# Registry maps a kind name to (phases, order). "test" is the built-in
# model-free / browser-free kind (see envforge/phases/test.py).
KINDS = {"test": (TEST_PHASES, TEST_ORDER)}

# Kinds that build their phases dynamically from run args (real agents).
DYNAMIC_KINDS = ("browser_webapp",)


def _resolve_kind_config(run_dir: Path, args) -> dict:
    """Durable per-run kind config: written once at the initial run, reloaded on resume.

    This lets `resume` reconstruct a dynamic kind WITHOUT the user re-passing
    --docs/--gen-model/--eval-model/--task-count (the resume subparser has none of
    them). The config lives at <run_dir>/_config.json, outside any synced app dir.
    """
    config_path = run_dir / "_config.json"
    if config_path.exists():
        return read_json(config_path)
    docs = getattr(args, "docs", None) if args is not None else None
    if not docs:
        raise EnvforgeExit(ExitCode.FATAL, "browser_webapp requires --docs on the initial run")
    cfg = {
        "docs": str(docs),
        "gen_model": getattr(args, "gen_model", "litellm/your-coding-model"),
        "eval_model": getattr(args, "eval_model", "your-eval-model"),
        "task_count": getattr(args, "task_count", 24),
        "runs_root": str(getattr(args, "runs_root")),
        "gen_timeout": float(getattr(args, "gen_timeout", 3600.0) or 3600.0),
        "gen_agent": getattr(args, "gen_agent", "opencode") or "opencode",
    }
    atomic_write_json(config_path, cfg)
    return cfg


def _build_coding_agent(name: str):
    """Select the generation (coding) agent. Both implement the same CodingAgent
    interface, so the rest of the pipeline is identical regardless of choice."""
    if name == "claude":
        from .agents.claude_agent import ClaudeAgent  # uses the `claude` CLI
        return ClaudeAgent()
    from .agents.opencode_agent import OpencodeAgent
    return OpencodeAgent()


def _build_browser_webapp_kind(cfg: dict):
    from .agents.browser_eval import BrowserUseEvalAgent
    from .kinds.browser_webapp.kind import BrowserWebAppKind
    from browser_use.llm.openai.chat import ChatOpenAI  # lazy; only at real run time

    llm = ChatOpenAI(model=cfg["eval_model"],
                     base_url=os.environ["OPENAI_BASE_URL"],
                     api_key=os.environ["OPENAI_API_KEY"])
    coding = _build_coding_agent(cfg.get("gen_agent", "opencode"))
    # verifier_dir is rebound per-run inside EvaluatePhase via set_verifier_dir().
    eval_agent = BrowserUseEvalAgent(llm, verifier_dir=Path(cfg["runs_root"]))
    return BrowserWebAppKind(coding, eval_agent, gen_model=cfg["gen_model"],
                             eval_model=cfg["eval_model"], docs_path=Path(cfg["docs"]),
                             task_count=cfg["task_count"], gen_timeout=cfg.get("gen_timeout", 3600.0))


def _build_orchestrator(runs_root: Path, run_id: str, kind: str, ports_dir: Path, now: str, args=None) -> tuple[Orchestrator, RunStore]:
    if RunStore.exists(runs_root, run_id):
        rs = RunStore.load(runs_root, run_id)
    else:
        rs = RunStore.create(runs_root, run_id, kind, now=now)
    if rs.kind in DYNAMIC_KINDS:
        if rs.kind == "browser_webapp":
            cfg = _resolve_kind_config(rs.run_dir, args)
            built = _build_browser_webapp_kind(cfg)
            phases, order = built.phases(), built.order()
        else:  # pragma: no cover - defensive
            raise EnvforgeExit(ExitCode.FATAL, f"unbuildable dynamic kind: {rs.kind}")
    else:
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


def _drive(runs_root: Path, run_id: str, kind: str, ports_dir: Path, *, now: str, host: str, pid: int, lock_now: float, alive, args=None) -> int:
    run_dir = Path(runs_root) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    lock = RunLock(run_dir / "run.lock", pid=pid, host=host, alive=alive)
    try:
        lock.acquire(now=lock_now)
    except DuplicateJobError:
        return int(ExitCode.DUPLICATE_JOB)
    try:
        orch, _rs = _build_orchestrator(runs_root, run_id, kind, ports_dir, now, args=args)
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
        lock_now=lock_now if lock_now is not None else time.time(), alive=alive, args=args,
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
        lock_now=lock_now if lock_now is not None else time.time(), alive=alive, args=args,
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
        print(f"[dry-run] would tar-back-up {run_dir} (leaving it in place)")
        return int(ExitCode.OK)
    # Never overwrite an existing backup (cleanup-trap guard): pick a free name.
    backup = run_dir.with_suffix(".tar.gz")
    i = 1
    while backup.exists():
        backup = run_dir.parent / f"{run_dir.name}.tar.gz.{i}"
        i += 1
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
    r.add_argument("--kind", default="test", choices=list(KINDS) + list(DYNAMIC_KINDS),
                   help="which pipeline to run: 'test' (built-in, no models/browser) or 'browser_webapp' (real opencode + browser_use run)")
    r.add_argument("--docs", default=None,
                   help="directory of docs the app is generated FROM (required for browser_webapp)")
    r.add_argument("--gen-agent", default="opencode", choices=["opencode", "claude"],
                   help="coding agent for generation: 'opencode' (default) or 'claude' (Claude Code CLI; "
                        "point it at any model — incl. OS models — via ANTHROPIC_BASE_URL/ANTHROPIC_AUTH_TOKEN)")
    r.add_argument("--gen-model", default="litellm/your-coding-model",
                   help="generation model id; for opencode use <provider>/<model> from your opencode.json, "
                        "for claude use a model id your ANTHROPIC_BASE_URL endpoint serves")
    r.add_argument("--eval-model", default="your-eval-model",
                   help="eval model handed to browser_use; any model id your endpoint serves")
    r.add_argument("--task-count", type=int, default=24,
                   help="number of tasks to generate and grade (default 24)")
    r.add_argument("--gen-timeout", type=float, default=3600.0,
                   help="per-phase coding-agent (opencode) timeout in seconds for generate_app/function_tasks (default 3600; slow models need more)")
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
    if getattr(args, "ports_dir", None) is None:
        args.ports_dir = str(Path(args.runs_root) / "_ports")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
