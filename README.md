# envforge

A robust, **multi-model** pipeline that generates a web app from documentation,
then automatically generates and grades a suite of browser tasks against it —
designed to work reliably with **both Claude and open-source models** (most
public users run OS models, which are far less predictable than frontier APIs).

It is inspired by [webarena-infinity](https://github.com/web-arena-x/webarena-infinity)
but is a clean, from-scratch implementation whose entire design is built around
*surviving the ways real multi-model runs fail*: model outages, slow models,
malformed agent output, duplicate jobs, port collisions, mid-run crashes, and
output syncs that wipe in-progress state. Every termination is classified, every
run is durable, and every run is resumable.

---

## What it does

Given a directory of documentation for some web app, envforge runs a five-phase
state machine:

```
  generate_app  ──►  health_gate  ──►  generate_function_tasks  ──►  evaluate  ──►  score
  (coding agent      (app boots &       (coding agent writes N        (browser     (pass rate
   writes the app     serves the         tasks + verifier scripts)     agent runs   over the
   from the docs)     /api/state                                       each task)    suite)
                      protocol)
```

- **generate_app** — a coding agent (opencode) reads the docs and writes a runnable
  web app (`index.html`, `server.py`, `js/`, `css/`) that exposes a small
  `/api/state` protocol so its state can be seeded and inspected.
- **health_gate** — the app must actually boot and serve the protocol; a failure
  here stops the run cleanly instead of grading a broken app.
- **generate_function_tasks** — the coding agent writes `function-tasks.json`
  (N tasks at easy/medium/hard difficulty) plus a verifier script per task.
- **evaluate** — a browser agent (browser_use) drives a real Chromium through each
  task; the per-task verifier checks the resulting app state.
- **score** — aggregates pass/fail/timeout into a final pass rate.

The coding agent and the eval agent are both **swappable interfaces**, and all
model traffic goes through one gateway with budget caps and classified errors —
so the same pipeline runs against any OpenAI-compatible model: GLM, DeepSeek,
Claude, a local vLLM/Ollama model, etc. You select models by id at run time;
there is no model-specific code path.

---

## Entry point

The entry point is the **`envforge` command**, defined in
[`envforge/cli.py`](envforge/cli.py) and exposed as a console script via
`[project.scripts]` in `pyproject.toml`. Everything below is a subcommand of it
(`run`, `resume`, `status`, `clean`). The top of `cli.py` documents the full
`run` invocation with an explanation of every flag.

---

## Three ways to run it

### 1. Unit tests — zero external dependencies

The full state machine, gateway, locking, ports, and both agent interfaces are
covered by tests that use **fakes** (no models, no browser, no network):

```bash
uv venv && uv pip install -e ".[dev]"
uv run pytest -q
```

### 2. The `test` kind — full machine, still no models/browser

Exercises the real orchestrator, run-store, status writer, locking, and classified
exits end-to-end against the built-in model-free / browser-free kind:

```bash
uv run envforge run    --kind test --runs-root /tmp/ef-runs
uv run envforge status --run "$(ls /tmp/ef-runs | grep test | head -1)" --runs-root /tmp/ef-runs
```

### 3. A real `browser_webapp` run

envforge itself is plain Python — no container required. On any Linux/macOS box
you just need the real-run prerequisites installed:

**Prerequisites**

| Requirement | Why | Install |
|---|---|---|
| Python ≥ 3.12 | runtime | — |
| `browser` extra | browser_use + Playwright eval agent | `uv pip install -e ".[dev,browser]"` |
| Chromium | the eval agent drives a real browser | `playwright install chromium` |
| `opencode` CLI | the coding agent that writes the app + tasks | `npm install -g opencode-ai@latest` |
| An OpenAI-compatible endpoint | serves both models | vLLM / Ollama / LiteLLM / OpenAI / etc. |
| An opencode provider config | tells opencode how to reach your endpoint | see below |

**Configure opencode** so it can resolve your generation model. opencode reads a
provider config from `~/.config/opencode/opencode.json` (or the path in
`OPENCODE_CONFIG`). A generic, secret-free template is provided at
[`docs/opencode.example.json`](docs/opencode.example.json) — it defines an
OpenAI-compatible provider named `litellm` that reads its URL and key from the
environment. Copy it into place and add your model names:

```bash
mkdir -p ~/.config/opencode
cp docs/opencode.example.json ~/.config/opencode/opencode.json
# edit it to list the model id(s) your endpoint serves
```

**Run it** (see `envforge/cli.py` for the same, fully commented):

```bash
export OPENAI_BASE_URL="https://your-endpoint/v1"   # OpenAI-compatible base URL
export OPENAI_API_KEY="your-key"

envforge run \
  --kind browser_webapp \           # which pipeline (browser_webapp | test — see "Kinds" below)
  --docs       /path/to/app-docs \  # directory of docs the app is generated FROM (required)
  --runs-root  /tmp/ef-runs \       # PARENT dir for all runs; each run gets its own
                                    #   subdir <kind>-<timestamp>/ underneath (not a single file)
  --gen-model  litellm/<provider>/<model> \  # generation model for opencode: <provider>/<model>,
                                             #   where <provider> matches your opencode.json
  --eval-model <model-id> \         # eval model for browser_use; a model id your endpoint serves
  --task-count 24 \                 # how many tasks to GENERATE (every generated task is always
                                    #   graded — grading is never selective)
  --gen-timeout 14400               # per-phase coding-agent timeout, seconds (slow models need more)
```

Notes:
- `--gen-model` is passed to **opencode**, so it must be `<provider>/<model>` where
  `<provider>` matches a provider in your `opencode.json` (e.g. `litellm/...`).
- `--eval-model` is passed straight to **browser_use** via `OPENAI_BASE_URL`/
  `OPENAI_API_KEY`, so it is just a model id your endpoint accepts (no opencode
  config needed for it).
- `--gen-timeout` is the per-phase coding-agent ceiling in seconds. **Slow models
  need a generous value** — a large open-weights model can need 2h+ for a 24-task
  suite; the default is 3600s.
- opencode writes files into the nearest enclosing git repo, so the agent
  `git init`s the app directory automatically before generating into it.

> **Headless / sandbox note:** the eval agent passes `--no-sandbox` to Chromium
> (needed when running as root, e.g. inside a container). On a normal desktop this
> is harmless. If Chromium fails to launch, confirm `playwright install chromium`
> completed and that a headless Chromium can start on your machine.

### Choosing the generation agent (`--gen-agent`)

Generation runs through a swappable `CodingAgent`. Two are built in:

- **`opencode`** (default) — the opencode CLI, configured via `opencode.json` and
  `OPENAI_BASE_URL`/`OPENAI_API_KEY` (above).
- **`claude`** — the **Claude Code CLI** (`claude -p`). Point it at any model,
  including open-source ones, by setting `ANTHROPIC_BASE_URL` (and
  `ANTHROPIC_AUTH_TOKEN`) to an Anthropic-compatible endpoint — e.g. a proxy that
  serves an OS model over `/v1/messages`. `--gen-model` is then a model id that
  endpoint serves. Requires the `claude` CLI on `PATH`.

```bash
export ANTHROPIC_BASE_URL="https://your-anthropic-compatible-endpoint"
export ANTHROPIC_AUTH_TOKEN="your-key"

envforge run --kind browser_webapp --docs /path/to/app-docs --runs-root /tmp/ef-runs \
  --gen-agent claude --gen-model <model-the-endpoint-serves> \
  --eval-model <model-id> --task-count 24
```

The eval agent (browser_use) is unaffected — it always uses `OPENAI_BASE_URL`/
`OPENAI_API_KEY`. Only the generation step changes.

### Running in a container (optional)

envforge needs no container, but if you'd rather run it in one — e.g. on a shared
cluster — the recipe is generic:

1. Use any container image that bundles the real-run prerequisites above
   (Python ≥3.12, Node + opencode, Chromium).
2. Mount a persistent host directory and point `--runs-root` at it, so run
   outputs survive the container being destroyed.
3. Set `OPENAI_BASE_URL` / `OPENAI_API_KEY` and install the opencode provider
   config inside the container.
4. Run the same `envforge run ...` command shown above inside the container.

If your cluster uses a batch/job scheduler, wrap that command in a submission
script. Keep such scripts out of version control — they tend to hold
host/cluster/credential specifics that don't belong in the repo.

---

## Kinds

A *kind* is which pipeline `run` executes:

| Kind | What it does | Needs | Uses `--docs`/`--*-model`/`--task-count`? |
|---|---|---|---|
| `test` | Built-in, deterministic, **model-free and browser-free** phases that exercise the orchestrator / run-store / locking / ports / classified-exit machinery. | nothing | no — they're ignored |
| `browser_webapp` | The **real** pipeline: opencode generates the app + tasks, browser_use grades them against a live model endpoint. | `--docs`, models, an OpenAI-compatible endpoint, Chromium | yes |

## CLI

```
envforge run    --kind <test|browser_webapp> --runs-root <dir> [options]   # start a run
envforge resume --run <run_id> --runs-root <dir>                           # idempotent resume
envforge status --run <run_id> --runs-root <dir>                           # print durable STATUS.json
envforge clean  --run <run_id> --runs-root <dir> [--dry-run]               # tar-first safe cleanup
```

`--runs-root` is the **parent directory for all runs** — each run creates its own
`<kind>-<timestamp>/` subdirectory beneath it (it is not a single output file/dir
for one run), which is why it's a "root" rather than an "output path".

`run` options for `browser_webapp`: `--docs`, `--gen-model`, `--eval-model`,
`--task-count`, `--gen-timeout`, `--ports-dir`.

**Resume** needs no other flags: the per-run config (docs / models / task-count /
gen-timeout) is persisted to `<run_dir>/_config.json` at the first run, so
`envforge resume --run <id> --runs-root <dir>` reconstructs the kind exactly.

---

## What a run produces

Each run writes a self-contained, sync-survivable directory under `--runs-root`:

```
<runs-root>/browser_webapp-<timestamp>/
├── state.json          # the run-store: per-phase status + the final score
├── _config.json        # the exact config used (enables flag-free resume)
├── _status/
│   ├── STATUS.json      # latest snapshot (what `envforge status` prints)
│   └── activity.jsonl   # structured, append-only event log
├── app/                # the generated app
│   ├── index.html  server.py  js/  css/
│   ├── function-tasks.json    # the generated task suite
│   └── verifiers/             # one verifier script per task
├── logs/               # generate_app.log, generate_function_tasks.log (opencode output)
└── tasks/              # one subdir per task: the browser-eval trajectory (history.json)
```

The run-store / status live **outside** the synced `app/` dir on purpose, so a mid-run
output sync of the app cannot clobber the durable state.

### A real result (first clean end-to-end run)

The first full run — generating from a real app's documentation with an
open-weights coding model for generation and a reasoning model for evaluation —
scored **17/24 (70.8%)**: easy 8/8, medium 6/8, hard 3/8; all 7 failures were eval
timeouts on the harder multi-step tasks. `state.json` → `steps.score.result`:

```json
{ "total": 24, "passed": 17, "failed": 7, "timed_out": 7, "pass_rate": 0.708 }
```

---

## Core concepts (the robustness layer)

- **Run-store** — durable JSON state for a run, kept outside any synced directory.
- **Orchestrator** — advances ordered, idempotent phase steps; `resume` re-drives it.
- **Model gateway** — single entry point for all model calls; budget caps + fallback.
- **Run lock** — PID/host/heartbeat guard that refuses to start a duplicate job.
- **Port broker** — atomic port leases so concurrent runs never collide.
- **Status writer** — `STATUS.json` snapshot + structured `activity.jsonl`.
- **Classified exits** — every termination carries an `ExitCode` (e.g. `OK`,
  `DUPLICATE_JOB`, `BUDGET_EXCEEDED`, `EVAL_HARNESS_FAILURE`, `FATAL`), so a
  supervisor can tell "model was down" from "the app was broken" from "we crashed."

These exist because each maps to a real failure mode hit during live multi-model runs.

---

## Repository layout

```
envforge/
├── cli.py     the `envforge` entry point (run / resume / status / clean)
├── core/      orchestrator, run-store, status, exits, lock, ports   (domain-agnostic)
├── models/    gateway, budget, fallback, error classification, OpenAI transport
├── runtimes/  Runtime interface + portable LocalRuntime
├── agents/    CodingAgent (opencode) + EvalAgent (browser_use) interfaces, impls, fakes
├── phases/    phase interface + the built-in `test`-kind phases
└── kinds/
    └── browser_webapp/   /api/state protocol server, health gates, verifier runner,
                          and the generate/health/function-tasks/evaluate/score phases
docs/          design specs, implementation plans, opencode.example.json
tests/         unit tests (fakes only — no models/browser/network)
```

---

## Status

All code lives on **`main`**. Infra/cluster-specific job-submission scripts are
intentionally kept out of the repo (they hold host/credential specifics).

The robustness core and the `browser_webapp` kind (opencode + browser_use agents)
are complete and green, and the pipeline has produced its first clean end-to-end
score. Next up: the quality phases (audit loops, richer tasks, regression) and a
first-class cluster runtime adapter. See [`docs/`](docs/) for the specs and plans.
