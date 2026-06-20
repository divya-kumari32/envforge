# envforge

Multi-model pipeline for generating and evaluating webarena-style environments,
reliable with both Claude and open-source models.

This repository currently contains the **robustness core** (Plan 1): a durable
state-machine runner with a model gateway, budget caps, port leasing,
duplicate-job locking, classified exits, and durable status. A built-in `demo`
kind exercises the full machine with no models or browsers.

## Quickstart

```bash
uv venv && uv pip install -e ".[dev]"
uv run pytest -q
uv run envforge run --kind demo --runs-root /tmp/ef-runs
uv run envforge status --run "$(ls /tmp/ef-runs | grep demo | head -1)" --runs-root /tmp/ef-runs
```

(If a conda base env is active, prefix commands with `env -u VIRTUAL_ENV` so
`uv` targets the project `.venv`.)

## Concepts

- **Run-store** — durable JSON state for a run, outside any synced directory.
- **Orchestrator** — advances ordered, idempotent phase steps; resume re-runs it.
- **Model gateway** — single entry for all model calls; budget caps + fallback.
- **Run lock** — PID/host/heartbeat guard against duplicate jobs.
- **Port broker** — atomic port leases (no collisions).
- **Status writer** — `STATUS.json` snapshot + structured `activity.jsonl`, kept
  outside the synced app dir so it survives output syncs.
- **Classified exits** — every termination carries an `ExitCode`.

## CLI

```
envforge run    --kind demo --runs-root <dir> [--ports-dir <dir>]   # start a run
envforge resume --run <run_id> --runs-root <dir>                    # idempotent resume
envforge status --run <run_id> --runs-root <dir>                    # read durable status
envforge clean  --run <run_id> --runs-root <dir> [--dry-run]        # tar-first safe cleanup
```

## Repository layout

- `envforge/core/` — orchestrator, run-store, status, exits, lock, ports (domain-agnostic).
- `envforge/models/` — gateway, budget, fallback, error classification.
- `envforge/runtimes/` — `Runtime` interface + portable `LocalRuntime`.
- `envforge/phases/` — phase interface + the built-in `demo` phases.
- `docs/` — the design spec and the implementation plans.

## Branches

`main` is portable and works for everyone (OS models or Claude). IBM/BlueVela
LSF/enroot specifics live on a separate `bluevela` branch (future work). LSF
`bsub` scripts are never committed on any branch.

## Status

Plan 1 (robustness core) is complete and green. Future plans: the browser
web-app environment kind + agents (opencode / browser_use), the quality phases
(function/real tasks, audit, hardening, regression), and the BlueVela runtime
adapter. See `docs/` for the spec and plans.
