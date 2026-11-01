# Webhooks

A workflow can tell another system that a run reached a stage, so the other system does not have to
poll. A webhook is a small, signed HTTPS notification. It says **that** something happened and
**which run**, nothing more; the receiver then pulls the run with its own token.

Webhooks are declared in the workflow YAML and delivered to the receiver you name there. A caller
cannot choose where notifications go. They are meant to be received with `@tuvl/client`
(`verifyWebhook`, `webhookHandler`), which is the supported way to verify one; the request format is
internal and may change.

## Turn it on

Delivery is off until the deployment enables it: set `TUVL_WEBHOOKS_ENABLED=true`. Without it nothing
is queued and nothing is sent, whatever the workflows declare.

## Declare a webhook

```yaml
spec:
  webhooks:
    - name: ops-pager
      url: ${OPS_WEBHOOK_URL}              # an environment reference, or an https:// literal
      secret: ${OPS_WEBHOOK_SECRET}        # at least 32 bytes; only an environment reference
      events: [completed, failed, waiting]
      stages: [classify]                   # also notify each time this agent finishes
```

| Field | |
|---|---|
| `name` | Unique in the workflow; shown in the delivery list |
| `url` | `${ENV}` (read when sent) or an `https://` URL without credentials |
| `secret` | `${ENV}` reference holding at least 32 bytes. It signs every call; it is never written in the YAML |
| `previous_secret` | `${ENV}` of the secret being replaced. While set, each call is signed with both (see Rotation) |
| `events` | `completed`, `failed`, `aborted`, `waiting` (a person or an approval is needed) |
| `stages` | Agent ids. One notification each time one of them finishes |
| `allow_private` | Permit an internal address or plain `http://` (a receiver inside your network). `tuvl lint project` warns |

A webhook must subscribe to something (`events` or `stages`). `tuvl lint project` checks the stage ids (V038).

## What is sent

One `POST` with a JSON body and a fixed set of headers (`Tuvl-Event`, `Tuvl-Delivery`, `Tuvl-Signature`,
`Content-Type`, `User-Agent`). The body names the run and what happened (workflow, run id, event type, the run's
journal position and, for a stage or a wait, the agent) and carries **no input, output or error text**. A
notification that reaches the wrong place discloses only that a run exists.

The receiver pulls the run: `GET /api/runs/{id}` (or the events from the journal position) with its own
token, so the usual scopes and tenant checks decide what it may read. A service token with `runs:read` is
enough.

## Security

- **No caller-chosen targets.** URLs come from the workflow and the environment.
- **Signed.** Each call carries an HMAC-SHA256 signature over its timestamp and body, with the
  webhook's secret. The client verifies it in constant time and rejects a timestamp more than five minutes
  from now, so a captured call cannot be replayed later.
- **Destination checks, twice.** `https` only, no credentials in the URL, no internal host names or
  numeric address tricks (`2130706433`, `0x7f.1`, IPv4-mapped IPv6, NAT64, 6to4). When sending, the name is
  resolved and refused if **any** address is loopback, private, link-local (including the cloud metadata
  address), carrier-grade NAT, multicast or reserved, then the connection goes to the address that was
  checked, so a second lookup cannot return something else.
- **No redirects, no proxies from the environment, no response body kept.** A `3xx` is a failure. A
  body of up to 16 KiB with a declared length is read and dropped, so the connection can be reused.
- **Connections are reused only for the same destination.** A kept-alive connection serves the same host
  name and checked address only; each notification is still resolved and checked before it is sent.
- **Fixed request.** Authors cannot add headers or change the body.
- **Nothing sensitive is stored.** The outbox holds the webhook's name and the event, not the URL or the
  secret; both are read from the current declaration when sending, so removing or rotating takes effect
  at once. A declaration that no longer exists drops its queued notifications.
- **Fails closed.** A secret shorter than 32 bytes, a refused URL or an internal address ends the
  notification (it is not retried); an unset environment variable is retried, since it can be fixed.
- **Contained.** A receiver that keeps failing is paused for five minutes after five failures.

## Delivery

At-least-once. A row is written with the journal event and sent by a background loop on each worker, so
nothing is lost between the event and the send. A non-2xx answer or a timeout (10 s) is retried with
backoff (10 s, 30 s, 2 min, 10 min, 30 min, 1 h, 3 h, 6 h), then marked dead. `410 Gone` marks it dead at
once. A receiver may see the same notification twice and should de-duplicate on its `id`. Order within a
run is by the journal position, not guaranteed on the wire.

`GET /api/runs/{id}/webhooks` lists a run's notifications with status, attempts and the last error (scope
`runs:read`, owner or admin). `POST /api/runs/{id}/webhooks/{delivery_id}/redeliver` sends one again
(`runs:control`).

## Receive with `@tuvl/client`

```ts
import { TuvlClient, webhookHandler } from "@tuvl/client";
const client = new TuvlClient({ baseUrl, token: serviceToken });

export const POST = webhookHandler({
  secrets: [process.env.OPS_WEBHOOK_SECRET!],
  onNotification: async (n) => {
    if (await seen(n.id)) return;                   // de-duplicate
    const run = await client.run(n.run_id).get();   // pull
    await notifyDevices(run);
  },
});
```

Answer quickly: the sender waits ten seconds. Do the work after acknowledging, or put it on a queue.
A phone should never hold the secret. Receive on your backend, verify, and push only the run id to the
device; the app then pulls the run with the user's own token.

## Rotation

Set `previous_secret` to the old secret's variable, put the new value in `secret`, and give receivers both
secrets. Calls are signed with both until you remove `previous_secret`.
