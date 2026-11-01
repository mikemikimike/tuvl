# Developer telemetry

An optional way for a team to see what every developer on a project is doing, and to see it from their own Insight.
When it is on, each development action is shared through a **collector** your team runs: ideas imported, specs created,
approved or sent back, tasks derived, each coding-agent attempt, branches, commits and pull requests, gate results,
reviews, ships, and one `cli.command` event per command. The same collector lets each developer read the team's events
back (the Audit page's **Team** view, the **Team activity** section of a task, and who built each branch).

It is off by default and **development only**: nothing here reaches production (`tuvl ship` refuses the config file and
the outbox, check V027). It carries the same events the local [audit ledger](cli.md) records (ids, hashes and short details,
never file contents, prompts or secrets); the ledger remains the record and the collector gets a copy.

## Turn it on

| Where | How |
|---|---|
| At `tuvl init` | answer the "Developer telemetry" question, or pass `--dev-telemetry https://collector.example.com` |
| Later, in a terminal | `tuvl set dev-telemetry https://collector.example.com` (`--off` stops it) |
| Later, in Insight | Settings → Developer telemetry |

This writes `.tuvl/dev-telemetry.yaml`. **Commit it** so everyone on the project uses the same collector:

```yaml
kind: DevTelemetry
version: tuvl/v2
telemetry:
  enabled: true
  server: https://collector.example.com
  token_env: TUVL_DEV_TELEMETRY_TOKEN   # optional override of your registered token (CI, a shared runner)
  identity: initials                    # what events say about you: initials | full (name and email)
  commands: true                        # one event per command, without its arguments
```

## Register once, with a token of your own

Each developer registers at the collector with the team's join code (ask whoever runs the collector):

```bash
tuvl register developer          # asks for your name, email (defaults: your git ones) and the join code
tuvl check dev-telemetry         # the collector tells you who it thinks you are
```

The collector answers with a token that is **yours**: it sends your events and reads the team's. It is kept in your own
config folder (`~/.config/tuvl/dev-telemetry.json`, or `$TUVL_HOME`), readable only by you, never in the project and never in
git; `TUVL_DEV_TELEMETRY_TOKEN` (or the variable named by `token_env`) overrides it. `tuvl set dev-telemetry --rotate-token` gets a new one (the old stops working) and `--forget` removes it
from the machine; an admin can revoke it at the collector. Insight → Settings → Developer telemetry does the same steps.

`tuvl show dev-telemetry` says whether it is on, who you are there, how many events are waiting and when the last delivery
happened. `tuvl list team-activity` prints what the team did (`--actor`, `--entity`, `--kind`, `-n`).

## What is sent, and how

- **Never in the way.** Each event is appended to `.tuvl/audit/outbox.queue` first and sent in the background in batches of up
  to 100 (at the end of a command, or within a second in a long-running `tuvl dev`). If the collector is down, or you have
  no token yet, events stay queued and go with the next command; a command never fails or waits long because of telemetry.
  The queue keeps the newest 5,000.
- **Who.** The collector decides who an event is from by the token. Where tuvl gets *you*: the initials you gave at
  `tuvl init`, and the name and email from `git config user.name` / `user.email` (shown in Settings → Developer telemetry and
  by `tuvl show dev-telemetry`, and the defaults when you register). `identity: initials` sends your initials only and also
  takes your name and email out of the event's text (an approval's detail names the approver); `full` adds the git name and
  email. What an event claims about its actor is never trusted. Your local ledger keeps everything.
- **Where from.** Every batch says which tuvl version, the project id and name, the current git branch and a hash of the host name.
- **Safe transport.** https only (plain http is accepted for `localhost` to try a collector), no credentials in the URL, no
  redirects, no proxies, a few seconds' timeout.
- **What it is.** The events are what each developer's tuvl reports about itself: visibility for the team, not tamper-proof
  evidence. For an audit, rely on what the git host and CI record.

## The collector contract

Any server can be the collector. [Tuvl Flightlog](https://github.com/tuvl-io/flightlog) is the collector we provide: self-hosted, Apache 2.0, SQLite or PostgreSQL, with
retention, export, forwarding to a SIEM and a terminal-only admin. It comes in two builds of the same contract: a small
Python service (the smallest surface; it stores only token hashes), and a tuvl project with the same contract on tuvl's own
tokens and run journal (it needs PostgreSQL and Redis, and keeps a registration's token in the run record). All paths are under `<server>/v1`; everything except `/register` carries
`Authorization: Bearer <token>`.

| | |
|---|---|
| `POST /register` | `{name, email, team_code}` → `{"token": "…", "developer": {name, email, team}}` |
| `GET /me` | `{name, email, team}` of the token's owner (401 when the token is not known) |
| `POST /token/rotate` | `{"token": "…"}`: a new token for the caller; the old one stops working |
| `POST /dev-events` | `{"schema": "tuvl.dev-events/1", "sender": {tuvl, project, name, host, branch}, "events": [...]}`; answer any 2xx to accept the batch, anything else leaves it queued. Delivery is at-least-once: de-duplicate on `event.id` (a ULID) |
| `GET /team/events` | `{"events": [...]}` newest first for the caller's team, with `developer: {name}` on each: filters `project`, `actor`, `entity`, `kind`, `before` (an event id), `limit` |

An event: `{"id", "ts", "kind", "command", "actor": {"initials"}, "entities": [...], "result", "detail", "refs"}`. Kinds are the
audit kinds (`idea.imported`, `spec.approved`, `tasks.derived`, `task.attempt`, `task.failed`, `branch.created`, `pr.opened`,
`gate.result`, `ship.packaged` …) plus `cli.command` (`refs`: `exit_code`, `seconds`).

## A company's own certificate authority

If the collector's certificate is signed by a private CA, set `TUVL_DEV_TELEMETRY_CA` (or `SSL_CERT_FILE`) to the CA bundle on each
developer's machine.
