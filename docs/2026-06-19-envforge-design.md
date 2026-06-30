# envforge — Design Spec

**Date:** 2026-06-19
**Status:** Design (approved in brainstorming; pending written-spec review)
**Repo name:** `envforge`
**Location:** `~/Documents/Pre-training exp/envforge/` — its own standalone git repository

---

## 1. Purpose

A standalone, from-scratch repo that **generates and evaluates webarena-style web-app
environments** for SFT/RL training data, and does so **reliably with both Claude and
open-source models**. OS models are less reliable than Claude, so the system is designed
so that a weak model either produces a working environment *or* exits cleanly with a
classified reason — it never hangs, never silently passes a broken environment, and never
loses progress.

(Working name was `arenaforge` during brainstorming; renamed to `envforge`.)

It is **inspired by, not copied from**, `webarena-infinity`. We reuse that project's
*proven contracts* (the `/api/state` environment protocol, the `AgentRunner` eval
interface, the phase flow) but rebuild the orchestration around a **durable state-machine
core** instead of a 2,439-line monolithic `pipeline.py`.

### Non-goals (YAGNI)

- No cross-machine job queue / SQS / Redis workers (webarena-infinity deliberately avoided
  cross-machine coordination; one environment = one pipeline run).
- No new environment HTTP protocol — reuse the proven `/api/state` contract verbatim.
- No GUI.
- No model *training* — generation + evaluation + the robustness core only.
- No additional environment kinds (SWE, search) *implemented* in this spec — but the
  architecture provides a clean seam for them (see §11).

---

## 2. Background: what we're designing against

This design is driven by **18 real failure modes** hit during live `webarena-infinity`
hardening runs (see the `project-hardening-issues-log` memory). Every one of them maps to a
named, testable component here (§12). The headline goals, drawn from those failures:

- Model abstraction + budget-aware fallback.
- Robust per-job port allocation (no collisions).
- Single-process environment setup (no venv / two-start splits).
- Durable status/activity that survives output syncs.
- No-duplicate-job / supervisor safety.
- OS-model output validation gates (the app actually boots and serves; the eval agent can
  actually observe and act).
- Clean, classified exits.
- Full resumability.

---

## 3. Key design decisions (settled in brainstorming)

| Decision | Choice | Rationale |
|---|---|---|
| Run target | **Infra-agnostic core + first-class adapters for BOTH local/public and an HPC cluster** | Most public users run OS models on generic machines; we also run on the cluster. |
| Generation agent | **opencode behind a swappable `CodingAgent` interface** | opencode is OS-model-proven; the Claude Agent SDK is unsupported/fragile with OS models (verified). |
| Eval rollout | **`browser_use` behind a swappable `EvalAgent` (AgentRunner-style) interface** | This is webarena-infinity's proven arrangement; coding agents don't browse natively. |
| Model abstraction | **One shared model gateway** that ALL model traffic flows through (gen + eval + audit) | Budget, caps, selection, and fallback live in one place; even black-box agents (opencode, browser_use) are covered by pointing them at the gateway endpoint. |
| Orchestration | **Phase state-machine + durable run-store** | Each of the 18 failures maps to a named component; resumability and supervision are first-class. |
| Env kinds | **Pluggable `EnvironmentKind` seam; browser-web-app is the only kind built now** | The core is already domain-agnostic; future SWE/search kinds plug in with zero core changes. |

### On "the Claude Agent SDK with any OS model"

We verified this against current docs: pointing the Claude Agent SDK at a LiteLLM
Anthropic-`/v1/messages` shim is *technically possible* (and is how the internal cluster config
works) but is **unsupported and fragile for OS models** — the SDK assumes Claude-trained
tool-use trajectories; weaker OS models emit malformed tool calls, loop, and have no
graceful recovery. Since reliable OS-model support is an explicit goal, generation uses
opencode (OS-first, proven), not the Agent SDK. Claude is still fully supported via the
same gateway.

---

## 4. Scope & build order

The spec describes the **full** target system. The implementation plan delivers it as a
**thin end-to-end vertical slice first**, then layers on the rest:

1. **Robustness core + one vertical slice.** model gateway · run-store · orchestrator ·
   port broker · lockfile · classified exits · durable status — wired through
   `generate → health-gate → eval → score` for **one environment, local backend, OS model**.
   Result: a working, testable multi-model pipeline.
2. **Quality phases.** function tasks, audit loop, real tasks, hardening rounds, final
   regression — each plugging into the already-hardened core.
3. **Cluster runtime adapter.** A batch scheduler + container runtime, behind the same `Runtime` interface.

---

## 5. Module layout

Small, single-purpose units. Domain-agnostic core; browser specifics isolated under a kind.

```
envforge/
├── core/                      # domain-agnostic orchestration
│   ├── orchestrator.py        # advances idempotent phase steps; the state machine
│   ├── runstore.py            # durable run state (JSON; SQLite if needed) OUTSIDE synced dir
│   ├── status.py              # STATUS.json + structured activity log (sync-surviving)
│   ├── exits.py               # classified EXIT_CODES; single finish() path
│   ├── lock.py                # per-run lockfile + PID/host/heartbeat (no dup jobs)
│   └── ports.py               # atomic port-lease broker (no collisions)
├── models/
│   ├── gateway.py             # one entry point for ALL model calls: gateway.call(role, ...)
│   ├── budget.py              # spend tracking + hard caps per role/run
│   └── fallback.py            # classify error → backoff → same-model endpoint swap
├── runtimes/
│   ├── base.py                # Runtime interface: prepare_env / run / sync_out / free_gb
│   ├── local.py               # laptop / generic Linux
│   └── cluster.py             # batch-scheduler/container adapter (single-process setup)
├── agents/
│   ├── base.py                # CodingAgent + EvalAgent interfaces (shared across kinds)
│   └── opencode.py            # OpencodeAgent (CodingAgent impl) — generic
├── kinds/
│   ├── base.py                # EnvironmentKind interface
│   └── browser_webapp/        # the only kind built now
│       ├── kind.py            # implements EnvironmentKind
│       ├── protocol.py        # /api/state contract + shared server base (reused verbatim)
│       ├── health.py          # the 3 health gates
│       ├── eval_agent.py      # BrowserUseAgent (EvalAgent impl)
│       └── phases/
│           ├── generate.py  func_tasks.py  audit.py
│           ├── real_tasks.py  harden.py  regression.py
├── config/                    # run config schema + examples (Claude profile, OS profile)
├── cli.py                     # envforge run | resume | status | clean
└── tests/
```

Each phase module is one **idempotent step** the orchestrator calls: it reads inputs from
the run-store, writes outputs + a classified result, and never knows about supervision,
ports, or budgets (those are injected). When a file grows large, that's a signal it's doing
too much — split it.

---

## 6. Model gateway (`models/`) — the reliability backbone

Every model call in the system — generation, audit, hardening, eval rollout — goes through
`gateway.call(role, ...)`. Nothing talks to LiteLLM / Anthropic / OpenAI directly.

- **Selection.** Roles (`gen`, `eval`, `audit`) map to model specs in config. One place to
  point at Claude *or* an OS model (vLLM / Ollama / LiteLLM). opencode and browser_use are
  configured to point at the gateway's endpoint, so even black-box agents are covered.
- **Budget (`budget.py`).** Tracks spend per run from response usage. **Hard cap** →
  raises `BudgetExceeded` → orchestrator does a clean classified exit (not a crash). Caps
  are per-role and per-run. Targets the recurring budget blowups (#8–#11).
- **Fallback (`fallback.py`).** Classify error (auth / budget / timeout / 5xx / malformed)
  → backoff + retry → same-model alternate endpoint if configured. Tier-1 per-request retry
  lives here, so all callers inherit it (covers #12).

---

## 7. Orchestrator + run-store (`core/`) — resumability & supervision

- **Run-store (`runstore.py`).** The single source of truth for a run: current phase,
  per-step status (`pending` / `running` / `done` / `failed`), classified results, port
  leases, budget ledger. Lives at `<runs_root>/<run_id>/state.json` **outside** any synced
  app dir (so an output sync can't wipe it — #7). **JSON-first** (human-readable, easy to
  debug, atomic via write-temp-then-rename); move to SQLite only if concurrency/contention
  ever demands it.
- **Orchestrator.** Computes the next not-`done` step from the run-store and runs it. Each
  step is **idempotent** — re-running a `done` step is a no-op; re-running a `failed` or
  interrupted step resumes cleanly. `resume` is simply "run the orchestrator again."
- **Lock (`lock.py`).** On start, acquire `<run_id>/run.lock` carrying PID + host +
  heartbeat. A live lock → refuse to start (no duplicate jobs, #13). A stale lock (dead PID
  / expired heartbeat) → reclaim. This is the supervisor-safety primitive — verifying a job
  is actually alive rather than grepping job names.
- **Exits (`exits.py`).** One `finish(code, reason)` path; enumerated codes (`OK`,
  `BUDGET_EXCEEDED`, `TASKS_INVALID`, `APP_UNHEALTHY`, `EVAL_HARNESS_FAILURE`, `FATAL`, …).
  No bare `sys.exit`.
- **Status (`status.py`).** Writes `STATUS.json` + a **structured** activity log (JSON
  lines, so monitors don't false-match eval-agent chatter — #16). Written to a durable
  location outside the synced dir; an external watcher tails it (no reliance on session-cron
  — #15).

---

## 8. Runtime backends (`runtimes/`) — single-process setup

`Runtime` interface: `prepare_env()`, `run(cmd)`, `sync_out()`, `free_gb()`. The interface
and the portable implementation live on `main`; the cluster-specific implementation lives only
on an infra-specific branch (see §16). The active runtime is selected by config, so `main`
never imports cluster-specific code.

- **local.py (on `main`).** venv/uv on the host; ports on localhost. The portable/public
  path — what every public user runs.
- **cluster.py (on the cluster branch only).** A **single container start** that sets up
  the venv *and* runs the pipeline in one process (kills the two-start venv-loss bug, #6); a
  preflight import check fails fast if deps are missing (#4); `sync_out` writes the app dir
  but **never** the run-store/status (those live outside it, #7); disk handling is
  **detect-only**, never auto-deletes backups (#18 and the cleanup-trap rule). The
  container/uv.lock/pyproject setup fixes (#1, #5) live here too, since they are
  container-specific.

---

## 9. Environment kind: browser web-app (`kinds/browser_webapp/`)

- **protocol.py.** Reuse the proven contract verbatim: `GET`/`PUT /api/state`,
  `POST /api/reset`, `GET /api/events` (SSE reset stream), static file serving. State-sync
  contract: browser PUTs full state on first load → server captures immutable `_seed_state`
  → browser PUTs on every mutation → verifiers read via GET → reset restores seed + emits
  SSE. Not reinventing what works.
- **eval_agent.py.** `BrowserUseAgent`, behind the shared `EvalAgent` interface
  (`setup` / `run` / `teardown`), driven by the eval model via the gateway.
- **phases/.** generate · func_tasks · audit · real_tasks · harden · regression, mirroring
  the proven phase flow but each as an idempotent orchestrator step.

### health.py — the OS-model safety net (3 gates, observe-only, never edits app code)

1. **Structural.** Required files exist; server imports.
2. **Boot + serve.** Server starts; `/api/state` reachable. The server is **restarted
   between** the endpoint check and the browser-load check, so a stale seed can't mask a
   broken-JS app (fixes the false-PASS, #3).
3. **Eval-agent liveness.** A tiny sanity rollout confirms the chosen eval agent + model can
   actually *observe and act* on the app before a full eval run is trusted.

On failure → re-invoke the **model** (via a fix prompt) to repair. **The pipeline itself
never patches app code** — only the model does. This preserves the "failures are research
data about model quality" invariant.

---

## 10. OS-model reliability strategy (the through-line)

OS models fail differently than Claude: malformed tool calls, empty / zero-task
generations, apps that don't boot, browser agents that stall. All defenses are native:

- **(a) Output validation gates** after every generative step: schema-check tasks /
  verifiers, require non-empty + parseable output.
- **(b) The 3 health gates** (§9).
- **(c) Eval-agent liveness** sanity rollout before full eval.
- **(d) Classified retries** via the gateway.
- **(e) A bounded repair loop**: re-invoke the model up to N times, then a clean classified
  exit.

A weak model that cannot produce a working environment exits **cleanly and labeled** — it
never hangs and never silently passes.

---

## 11. Environment-kind seam (future-proofing, not built now)

The domain-agnostic core (gateway, run-store, orchestrator, ports, lock, exits, status,
runtimes) does not care what a phase produces. An `EnvironmentKind` (`kinds/base.py`)
bundles the only domain-specific pieces:

```
EnvironmentKind:
    generation_phases() -> list[Phase]   # ordered idempotent steps to build env + tasks
    harness()                            # stand up / serve the env
    eval_agent()                         # the agent that attempts tasks
    verifier()                           # how a task is scored
    health_gates()                       # kind-specific validation gates
```

The orchestrator asks the active kind for its phase list and runs it through the same
machinery. `browser_webapp` is the only implementation in this spec. Future kinds (SWE:
repo + test-runner harness + coding eval agent + tests-pass verifier; search: tool harness +
answer-correctness verifier) plug in with **zero core changes** — each its own spec/plan.

---

## 12. Explicit mapping — every one of the 18 live failures → a named owner

| # | Live failure | Designed-against by |
|---|---|---|
| 1, 5 | dirty lock / pyproject desync | runtime `prepare_env` pins deps + preflight import |
| 2 | playwright missing | `EvalAgent` uses `browser_use` (same stack), behind interface |
| 3 | health false-PASS via stale seed | `health.py` restarts server between gates |
| 4 | `requests` under system python | preflight import gate, single venv |
| 6 | two-container-start venv loss | `cluster.py` single-process setup |
| 7 | sync `--delete` wiped STATUS | run-store / status live **outside** the synced dir |
| 8–11 | budget exhaustion (recurring) | `budget.py` hard caps → clean `BUDGET_EXCEEDED` exit |
| 12 | endpoint timeouts | `fallback.py` classify + backoff + endpoint swap |
| 13 | duplicate jobs | `lock.py` PID/host/heartbeat guard |
| 14 | port collision / Clio bleed | `ports.py` atomic lease broker |
| 15 | cron didn't fire | durable status file + external watcher, not session-cron |
| 16 | grep matched agent chatter | structured (JSON) activity log; tagged status lines |
| 17 | SSH blips | runtime retries on transient transport errors |
| 18 | disk / quota, cleanup trap | `free_gb` detect-only; standalone tar-first cleanup tool |

---

## 13. Testing strategy

TDD throughout. Core units (run-store, lock, ports, budget, exits, gateway fallback) are
pure Python and unit-tested locally — no cluster needed. Agents and runtimes are tested
behind their interfaces with fakes. One **end-to-end smoke test** (generate → eval a trivial
environment with a small local model) gates the vertical slice. Cluster-specific behavior
runs in the container, as today.

---

## 14. CLI surface

```
envforge run    --config <profile> --kind browser_webapp --docs <path>   # start a run
envforge resume --run <run_id>                                           # idempotent resume
envforge status --run <run_id>                                           # read durable status
envforge clean  --run <run_id> [--dry-run]                               # tar-first safe cleanup
```

Config profiles ship for at least two cases: a **Claude profile** and an **OS-model
profile** (e.g. a LiteLLM/vLLM endpoint), differing only in the `models/` section.

---

## 15. Resolved decisions & remaining open item

**Resolved at written-spec review:**
- **Repo name:** `envforge`.
- **Location / VCS:** `~/Documents/Pre-training exp/envforge/`, its own standalone git
  repository (separate from `webarena-infinity`).
- **Run-store format:** JSON-first (SQLite only if contention later demands it).

**Remaining open (can default at planning time):**
- Which small local OS model backs the end-to-end smoke test. Proposed default: a small
  instruct model served via LiteLLM/Ollama (e.g. a ~7B Qwen) — confirmable when we write the
  plan, since it only affects the smoke test, not the architecture.

---

## 16. Repository branch strategy

The repo is split so that `main` is **universal** — it runs for any user on any machine —
and cluster-specific infra is quarantined on its own branch.

### `main` — portable, works for everyone

Everything whose behavior is independent of where the pipeline runs:

- The robustness core (`core/`), model layer (`models/`), agents (`agents/`), and
  environment kinds (`kinds/`).
- **All exits/crashes caused by models, agents, or the generated app** — whether the model
  is an OS model *or* Claude. These are universal failure modes (budget exhaustion, invalid
  tasks, unhealthy app, eval-harness failure, duplicate job, malformed model output, …) and
  their classified exits, retries, fallback, and validation gates all live on `main`.
- The `Runtime` *interface* and the portable `runtimes/local.py`.

A public user clones `main`, points the model gateway at their endpoint (OS model or
Claude), and everything works. `main` never imports cluster-specific code.

### the cluster branch — infra-only, branched off `main`

Everything specific to the HPC cluster's batch-scheduler/container environment:

- `runtimes/cluster.py` (single container start, preflight import, sync-out rules).
- Container/`uv.lock`/`pyproject` setup fixes (#1, #5, #6) and container-specific exit codes.
- Cluster disk/quota handling beyond the portable `free_gb` detect-only logic.

The cluster branch tracks `main` (regularly merges `main` forward) and adds only the
runtime adapter and its cluster-specific concerns. Build order: Plans 1–3 land on `main`;
Plan 4 (the cluster adapter) lands on the cluster branch.

### Submission scripts are never committed

Job-submission scripts are **never** committed to the repository on any branch —
submission scripts are gitignored, not committed; they are written locally and `scp`'d to
the cluster. This matches the same convention. The repo therefore contains no submission
scripts; the cluster branch documents how to run, not the runnable job-submission scripts
themselves.
