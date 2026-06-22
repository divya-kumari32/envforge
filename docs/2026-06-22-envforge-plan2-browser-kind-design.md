# envforge Plan 2 — Browser Web-App Kind + Agents + First Real Run (Design Spec)

**Date:** 2026-06-22
**Status:** Design (approved in brainstorming; pending written-spec review)
**Builds on:** Plan 1 (robustness core, merged to `main`) and the original design spec
`docs/2026-06-19-envforge-design.md`.
**Branch policy (amended 2026-06-22):** Until the pipeline runs a *proper real experiment*
end-to-end, **ALL code stays on `main`** — the `main`/`bluevela` split from the original
spec §16 is **deferred** until after the first successful real run. (Rationale: don't pay
branch-management overhead before the pipeline is proven.) The only standing exception is
unchanged: **`bsub` scripts are never committed** on any branch (gitignored, scp-only).
Plan 2 work is committed directly to `main`.

---

## 1. Purpose & scope

Plan 2 adds the first **data-producing** environment kind to envforge: it generates a
webarena-style web app, validates it boots and serves, generates a small set of function
tasks + verifiers, runs a single browser-agent evaluation pass, and records a real
pass/fail score. It works with both OS models and Claude via the proven direct-to-endpoint
model wiring.

**In scope (the first vertical slice):**
`generate_app → health_gate → generate_function_tasks → evaluate (single pass) → score`.

**Out of scope (deferred to Plan 3):** audit-eval loops (2b/3b), real tasks (3a),
hardening rounds (4), final regression (5). Deferred to Plan 4 / the `bluevela` branch: the
LSF/enroot runtime adapter.

The code is built and **unit-tested locally with fakes**; the first **real** generate→eval
run executes inside BlueVela's existing enroot image (§9).

## 2. Build approach (decided in brainstorming)

- **envforge-original code, not a copy** of webarena-infinity. Third-party *libraries*
  (`browser_use`, `playwright`, the `opencode` CLI) are public dependencies and are used
  directly — that is not "copying the repo." The wrapper/integration code is authored fresh
  for envforge's interfaces.
- **Proven-pattern-informed.** The hard-won reliability lessons from webarena-infinity's
  eval harness are encoded as explicit requirements + tests here (§5), so the fresh
  implementation has them by design rather than rediscovering the bugs.
- **Same process that delivered Plan 1:** writing-plans (with envforge-original reference
  code) → subagent-driven TDD → independent per-task review → final whole-branch review.

## 3. Module layout (new, all behind Plan-1 interfaces)

```
envforge/agents/
  base.py             # CodingAgent + EvalAgent Protocols (shared interfaces)
  opencode_agent.py   # CodingAgent: wraps `opencode run --model … <prompt>` (subprocess)
  browser_eval.py     # EvalAgent: wraps browser_use (lifecycle + reliability encoded)
  fakes.py            # FakeCodingAgent / FakeEvalAgent for local unit tests
envforge/models/
  openai_transport.py # real Transport (OpenAI-compatible client → LiteLLM) for OUR calls
envforge/kinds/
  base.py             # EnvironmentKind Protocol
  browser_webapp/
    kind.py           # implements EnvironmentKind; supplies phase list + order
    protocol.py       # /api/state server (envforge-original; the reused contract)
    health.py         # the 3 health gates
    prompts/          # generate-app.md, generate-function-tasks.md, fix-app-health.md
    phases/
      generate_app.py  function_tasks.py  evaluate.py  score.py
```

The Plan-1 core is reused **unchanged**: `Orchestrator`, `RunStore`, `RunLock`,
`PortBroker`, `StatusWriter`, `ExitCode`/`EnvforgeExit`, `Runtime`/`LocalRuntime`,
`ModelGateway`/`BudgetLedger`/`fallback`. The kind only supplies its `phases` + `order`.

## 4. Agents

### CodingAgent (`agents/base.py`, `opencode_agent.py`)
- Interface: `run(prompt: str, *, model: str, cwd: Path, timeout: float, log_path: Path) -> CodingResult`
  where `CodingResult` carries `returncode`, a captured-log path, and `ok`.
- `OpencodeAgent` runs `opencode run --model <model> <augmented_prompt>` as a subprocess in
  `cwd`, stdout/stderr → `log_path`, with a classified timeout (→ a phase failure, never a
  hang). Augmentation (dir constraint, inlined docs/CLAUDE-style context) is built by the
  calling phase, not the agent.
- Reads `OPENAI_API_KEY` / `OPENAI_BASE_URL` from the environment to reach LiteLLM.
- `FakeCodingAgent` (in `fakes.py`) writes canned files into `cwd` and returns a scripted
  result — lets every phase be unit-tested with no real model.

### EvalAgent (`agents/base.py`, `browser_eval.py`)
- Interface (AgentRunner-shaped): `async setup(server_url)`, `async run(task, server_url, task_dir) -> EvalResult`, `async teardown()`.
- `BrowserUseEvalAgent` wraps `browser_use.Agent` + `BrowserSession`, driven by an
  OpenAI-compatible `llm` adapter pointed at LiteLLM.
- `FakeEvalAgent` returns scripted `EvalResult`s for local tests.

## 5. Encoded eval-harness reliability requirements (the proven lessons)

These are **mandatory requirements with tests** in the implementation plan — they are how we
get reliability without copying source:

1. **Seed-state polling:** after first page load, poll `GET /api/state` (up to ~10s) until
   200 before trusting the env; fail classified if never ready.
2. **Browser restart + retry:** on CDP/resource/transport errors during `setup` or `run`,
   kill and restart the browser session (bounded retries) before giving up.
3. **Per-task timeout with partial save:** each task runs under a timeout; on timeout, save
   partial trajectory/history and record a timeout outcome (never hang).
4. **Trajectory artifacts:** write history + screenshots under the task dir for every task.
5. **0/0 distinction:** if a full eval returns zero usable results, classify it
   (`EVAL_HARNESS_FAILURE`) and exit cleanly rather than silently scoring 0.

## 6. Protocol server (`kinds/browser_webapp/protocol.py`)

envforge-original implementation of the proven contract: `GET /api/state`,
`PUT /api/state`, `POST /api/reset` (restores seed + SSE event), `GET /api/events` (SSE),
and static file serving. State-sync contract: browser PUTs full state on first load →
server captures immutable `_seed_state` → browser PUTs on each mutation → verifiers read via
GET → reset restores seed. The generate-app prompt **requires** generated apps to implement
this contract; a shared reference server in the kind documents/serves it.

## 7. Phases (each an idempotent orchestrator step; each failure → a classified exit)

1. **generate_app** — CodingAgent builds the app (HTML/CSS/JS + `server.py` implementing the
   protocol) from a docs path, using the gen model. Output-validation gate (required files
   exist, non-empty). Failure → `TASKS_INVALID`-class generation failure.
2. **health_gate** — three gates (`health.py`): (a) **structural** (files present, server
   imports); (b) **boot+serve** (server starts; `/api/state` reachable; **server restarted
   between** the endpoint check and the browser-load check so a stale seed can't mask a
   broken-JS app); (c) **eval-agent liveness** (a tiny rollout confirms the eval agent+model
   can observe+act). On failure → re-invoke the model via `fix-app-health.md` (bounded N
   attempts), then `APP_UNHEALTHY`. The pipeline never edits app code.
3. **generate_function_tasks** — CodingAgent generates a **full ~24-task suite (8 easy / 8
   medium / 8 hard)** as `function-tasks.json` + verifier scripts (each
   `verify(server_url)->(bool,str)`). Output-validate (parseable, expected count, verifier
   files present). Failure → `TASKS_INVALID`.
4. **evaluate** — Runtime starts the app server; PortBroker leases the port; the EvalAgent
   runs each task once (single pass). Per-task results + trajectories saved. Eval-harness
   failure → `EVAL_HARNESS_FAILURE`.
5. **score** — aggregate pass/fail/timeout into the run-store + a final status snapshot.

## 8. Model traffic & budget (decided)

opencode and browser_use talk **directly** to the LiteLLM (OpenAI-compatible) endpoint via
env vars / the `llm` adapter. Budget is enforced by the endpoint/key cap; budget/quota
errors are classified by `models/errors.py` → `BUDGET_EXCEEDED` clean exit (via the existing
fallback). envforge's in-process `ModelGateway` + the new `openai_transport.py` handle only
envforge's **own** direct calls (health-gate fix prompts, optional task validation). A
note for completeness: `BudgetExceeded` is not currently an `EnvforgeExit` — phases that
make gateway calls must translate it to `PhaseResult.fail(BUDGET_EXCEEDED, …)` (this is the
deferred Plan-1 item now in scope here).

## 9. First real run (BlueVela, manual)

- **Image:** reuse the existing `webarena.sqsh` enroot image (already has opencode +
  browser_use + playwright + node).
- **Code:** clone/scp envforge `main` into the container. `LocalRuntime` works as-is inside
  the container (subprocess + localhost); the full Plan-4 LSF adapter is NOT required for a
  manual run.
- **Invocation:** a **hand-written bsub, never committed** (gitignored `*.bsub`), runs
  `envforge run --kind browser_webapp --docs <user-manuals subdir> --runs-root <mounted dir>`.
- **Models:** `aws/glm-5` (generation, via opencode) + `deepseek-v32-az` (eval, via
  browser_use), over the IBM LiteLLM endpoint. Confirmable; these match the proven combo.
- **Docs source:** a small `user-manuals/` subdir (~40–80 files).
- **Output:** run-store + status under a mounted results dir, outside any synced app dir.

## 10. Testing strategy

- **Local unit tests (no model/browser):** every phase tested with `FakeCodingAgent` /
  `FakeEvalAgent`; `protocol.py` tested with real HTTP against a localhost instance; health
  gates tested against a known-good and known-broken fake app; output-validation gates
  tested with malformed inputs.
- **Reliability tests:** the §5 requirements each get a test (seed-state-never-ready →
  classified; injected CDP error → restart; task timeout → partial save + timeout outcome;
  zero results → `EVAL_HARNESS_FAILURE`).
- **Integration (BV-gated):** one end-to-end real run, executed in the enroot container, not
  in local CI.

## 11. Resolved decisions (written-spec review)

- **Models:** `aws/glm-5` (generation via opencode) + `deepseek-v32-az` (eval via
  browser_use), over IBM LiteLLM — the proven combo. Configurable, but this is the default.
- **Function-task suite:** full ~24 tasks (8 easy / 8 medium / 8 hard) for the first slice.
- **Docs source:** chosen at run time — when we reach the BV run, list `user-manuals/`
  subdirs with ~40–80 files (read-only SSH) and recommend one for the user to pick.
