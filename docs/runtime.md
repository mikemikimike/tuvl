# Runtime and journal

tuvl 2.0 runs every workflow on a **durable runner**: one deterministic loop that walks the graph,
invokes engines and records everything. There is no master process — any worker can continue any
run, because run state lives in Postgres, not in worker memory.

## Storage

| Table (`tuvl_system_` prefix) | Contents |
|---|---|
| `runs` | id, workflow name + content hash, status, trigger (`http`, `api`, `schedule`, `mcp`, `child`, `child:<agent>:<item>` for a `map` item, `dev`), principal, tenant, parent run, current agent, lease owner + expiry, tokens used, output, error |
| `run_events` | The **journal**: append-only `(run_id, seq)` events with type, agent, payload, tokens and latency |
| `run_checkpoints` | The context after each completed agent — the resume state |
| `approvals` | Open human forms and tool-call approvals: run, agent, kind, payload, required group, expiry |
| `run_deltas` | The **live draft** of an agent's answer while it is still being written: text pieces and resets, written in batches by the worker and read by the event stream. Not part of the journal. Rows stay for a minute after the run ends (a client may still be reading the last pieces) and a sweep then removes them; a run that never finished loses them after a day |

On boot tuvl builds the indexes on the vector store, and `run_deltas (created_at)` for the draft sweep, including the partial indexes agent memory
uses (by `memory_key` and by `step`). They are built with
`CREATE INDEX CONCURRENTLY IF NOT EXISTS`, so upgrading a deployment with a large table does not block writes. One process builds them (an
advisory lock; the others skip) and an index an interrupted build left invalid is rebuilt.

Statuses: `queued`, `running`, `waiting_human`, `waiting_approval`, `paused`, `completed`, `failed`,
`aborted`, `compensated` (`compensating` while compensators run).

## Lifecycle

1. **Trigger** — HTTP route, `POST /api/workflows/{name}/runs`, schedule, MCP or a parent loop. The
   principal is verified, the input validated against `trigger.input`, and a run is queued.
2. **Sync path** (HTTP): the receiving process claims the run and executes it inline. If it ends
   within `trigger.http.sync_timeout` (default 30 s) the response is the end's `status`/`body`;
   otherwise `202` with `{ run_id, status_url, events_url, … }`, and the run keeps going.
3. **Async path:** workers claim queued runs with `SELECT … FOR UPDATE SKIP LOCKED` and hold a
   heartbeat-renewed **lease**.
4. **Per agent:** `agent_started` → engine → output validation → `agent_completed` + signal →
   checkpoint → route. The step's database writes commit in the same transaction as its checkpoint.
5. **Pause** (human form, tool approval, breakpoint, supervisor or operator): checkpoint, set the
   status, release the lease. A decision or resume re-queues the run; any worker continues from the
   last checkpoint.
6. **End:** `run_completed` with the end name and response; compensation if the end has
   `rollback: true`.

### Roles

`tuvl serve app --role all | api | worker` (Helm: `split: true`):

- `all` serves HTTP and executes the queue (default);
- `api` serves HTTP and only executes synchronous requests inline;
- `worker` executes the queue (and serves `/health`).

`--concurrency` bounds runs per process.

## Crash recovery

An expired lease returns a run to `queued`; the next claimer resumes from the last checkpoint and
re-executes the in-flight agent. Per-agent semantics are **at-least-once**, made safe by:

- `tool: db` on the primary datasource — writes commit with the checkpoint (exactly-once);
- `tool: http` — `idempotency: auto` sends a stable `Idempotency-Key`;
- `code` — `ctx.idempotency_key`, and `ctx.db` writes commit with the checkpoint;
- MCP and other external calls — at-least-once; give write/destructive ones a `compensate` (V015).

A human agent's idempotency key counts finished steps, so it is stable across suspend and resume.

## Transactions

| `spec.transaction` | Semantics | Constraints |
|---|---|---|
| `per_agent` (default) | Each agent's writes commit with its checkpoint. Cross-agent atomicity comes from compensation | — |
| `per_run` | One transaction for the whole run, each step in a savepoint; committed with the run's end, rolled back on failure. No checkpoints — a crash reruns the run | No `human`, approvals or async triggers; sync only (V021) |

## Compensation

Reaching an end with `rollback: true`, an unhandled `error`, or an abort runs the `compensate` agent
of every **completed** agent that declares one, in **reverse completion order**. Each compensator
receives the original agent's inputs and outputs. A failing compensator makes the run `failed`
(`compensation_failed`); the rest still run. Success ends as `compensated`.

## Journal events

Every event: `{ run_id, seq, ts, type, agent_id, engine, tokens, latency_ms, payload }`.

`run_queued` · `run_started` · `agent_started` · `agent_completed` · `signal` · `llm_turn` ·
`tool_call` · `tool_result` · `map_started` · `map_item` · `map_finished` · `parallel_started` · `parallel_branch` · `parallel_finished` ·
`memory_recalled` · `memory_written` · `memory_compacted` · `decision` · `judge_verdict` · `approval_requested` ·
`approval_decided` · `paused` · `resumed` · `checkpoint` · `compensation_started` ·
`compensation_completed` · `run_completed` · `run_failed` · `run_aborted`

Read them with `GET /api/runs/{id}/events` (SSE: replay, then live), `tuvl follow run`, the Insight
Runs page, or `RunHandle.events()` in `@tuvl/client`. Checkpoints keep real values (they are the
resume state); secure fields are redacted on export.

## Replay and fixtures

The journal is the recording. **Replay** re-executes a run's graph but serves `llm`, `loop`, decide
model, `tool` and judge results from recorded events. `tuvl pin run <run_id>` (or 📌 in Insight)
exports a run to `tests/fixtures/<workflow>/<name>.journal.json`; a `Test` with `replay:` then runs
with zero tokens, and `tuvl replay runs <fixture>` fails if the end or output differ. Insight's
**Change engine** check replays fixtures with only the changed agent live.

## Operator control

`POST /api/runs/{id}/pause | resume | abort | steer` (scope `runs:control`). Control is read by the
runner between agents and loop iterations, under the run's lock, so it works across workers. In dev
mode, Insight breakpoints and step mode pause runs through the same mechanism.

## Production server and shutdown

`tuvl serve app` starts uvicorn and *replaces* the `tuvl` process with it, so in a
container uvicorn is PID 1 and receives SIGTERM itself. On SIGTERM it stops taking requests and lets open
ones finish for `--graceful-timeout` seconds (20), then the runtime stops claiming runs and waits
`--drain-timeout` seconds (20) for the running ones. A run still going is interrupted, not failed: its
lease expires and another worker resumes it from the last checkpoint. `terminationGracePeriodSeconds` in the
chart (60) must exceed the sum, and a `preStop` pause lets the load balancer stop sending traffic first.

Behind an ingress, `--forwarded-allow-ips` (`forwardedAllowIps` in the chart) names the proxies whose
`X-Forwarded-For` is trusted, so `--allow-host` and the logs see the real client. Leave it empty to trust
only `127.0.0.1`; `*` trusts every sender and lets a client spoof its address. `--limit-max-requests`
restarts a worker after that many requests. The `Server` response header is off.

The chart runs the pod as a non-root user with no privilege escalation, every capability dropped and the
runtime-default seccomp profile (`securityContext` in `values.yaml`). `readOnlyRootFilesystem` is off by
default because some admin features write under `/app`; turn it on once yours do not (a writable `/tmp` is
mounted when it is on).

## Scheduler

`trigger.schedule` (cron, UTC) enqueues one run per slot across all workers, guarded by a Postgres
advisory lock. A slot missed while every process was down is skipped; there is no catch-up.

```yaml
trigger:
  schedule:
    cron: "0 9 * * 1-5"
    enabled: true            # false pauses it and keeps the settings
    input: { report: daily } # every scheduled run starts with this; checked against trigger.input
```

A bare cron string (`schedule: "0 9 * * 1-5"`) is the same schedule with no input. Scheduled runs have
no caller, so a workflow whose `trigger.input` has required fields needs them in `input`.
`tuvl lint project` reports a mismatch (V019). The schedule is read at boot; in dev the server reloads
when the YAML changes.

## Multi-tenant mode

When the project is locked to `multi_tenant`, the run tables carry a `tenant_id` column and every
run belongs to one tenant:

- **Starting a run needs a tenant.** An HTTP or API run takes it from the caller's token (`tenant`
  claim); code that starts runs binds it with `tuvl.tenancy.tenant_scope()`. A run started with no
  tenant is refused (`MissingTenantContextError`) unless `TUVL_REQUIRE_TENANT_CONTEXT=false`.
- **Workers execute a run under its tenant.** The tenant is bound while the run executes, so its
  `db` calls, logs, journal rows and child runs carry it, and the runtime engine sets
  `app.current_tenant_id` for row-level security (`tuvl generate rls`).
- **Callers reach only their own tenant's runs.** Reads, the event stream, export, pause/resume/abort,
  the run list and approvals are filtered by tenant, whatever scopes the caller holds, `iam:admin`
  and `runs:control` included. Another tenant's run answers `404`.
- **Scheduled workflows list their tenants.** A scheduled run has no request to take a tenant from:

  ```yaml
  trigger:
    schedule: "0 6 * * *"
    tenants: [acme, globex]
  ```

  Each slot enqueues one run per tenant (trigger `schedule:<slot>:<tenant>`), once, across all
  workers. A scheduled workflow with no `tenants` is not scheduled in multi-tenant mode (the
  runtime logs `workflow.schedule_needs_tenants`); in single-tenant mode `tenants` is ignored.
- **Upgrading.** A database first booted in multi-tenant mode by an earlier build lacks the column;
  the runtime adds it at boot (`ALTER TABLE … ADD COLUMN IF NOT EXISTS`, default `default_tenant`).
