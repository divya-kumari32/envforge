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

## browser_webapp kind (Plan 2)

Generates a web app, health-gates it, generates a 24-task function suite + verifiers,
runs a single browser_use eval pass, and scores it.

Local unit tests use fakes and need no models/browser. The real run needs the
`browser` extra and an OpenAI-compatible endpoint:

```bash
uv pip install -e ".[dev,browser]"
playwright install chromium
export OPENAI_BASE_URL=<litellm-url> OPENAI_API_KEY=<key>
envforge run --kind browser_webapp --docs <docs-dir> --runs-root <dir> \
  --gen-model aws/glm-5 --eval-model deepseek-v32-az
```

On BlueVela this runs inside the existing enroot image via a hand-written bsub
(never committed). Per-run config (docs/models/task-count) is persisted to
`<run_dir>/_config.json`, so `envforge resume --run <id> --runs-root <dir>`
continues without re-passing those flags.

## Repository layout

- `envforge/core/` — orchestrator, run-store, status, exits, lock, ports (domain-agnostic).
- `envforge/models/` — gateway, budget, fallback, error classification, OpenAI transport.
- `envforge/runtimes/` — `Runtime` interface + portable `LocalRuntime`.
- `envforge/agents/` — CodingAgent (opencode) + EvalAgent (browser_use) interfaces, impls, fakes.
- `envforge/phases/` — phase interface + the built-in `demo` phases.
- `envforge/kinds/browser_webapp/` — the `/api/state` protocol server, health gates, verifier
  runner, and the generate/health/function-tasks/evaluate/score phases.
- `docs/` — the design specs and the implementation plans.

## Branches

Until the pipeline runs a proper real experiment end-to-end, **all code stays on
`main`** (the eventual portable-`main` / IBM-`bluevela` split is deferred until
then). LSF `bsub` scripts are never committed on any branch.

## Status

Plan 1 (robustness core) and Plan 2 (the `browser_webapp` kind + opencode/browser_use
agents) are complete and green. Next: the first real run on BlueVela, then the
quality phases (audit loops, real tasks, hardening, regression) and the BlueVela
runtime adapter. See `docs/` for the specs and plans.
