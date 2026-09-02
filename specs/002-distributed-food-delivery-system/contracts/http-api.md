# HTTP Interface Contract

All processes expose JSON endpoints. Process-to-process endpoints require the
static bearer identity headers defined by the shared configuration. Invalid
authentication, sender claims, channel claims, message types, or malformed
payloads return `401` or `400` and MUST NOT change receiver state.

## Public inspection and triggers

| Method | Path | Request | Response |
|---|---|---|---|
| GET | `/health` | None | `{process, status}` |
| GET | `/state` | None | `{process, vector_clock, orders, log}` |
| POST | `/trigger/place_order` | `{order_id}`; restaurant only | `{order_id, vc}` |
| POST | `/trigger/pickup` | `{order_id}`; delivery1 only | `{order_id, vc}` |
| POST | `/trigger/deliver` | `{order_id}`; delivery1 only | `{order_id, vc}` |
| POST | `/snapshot/start` | None; hub initiates | `{snapshot_id, started, process}` |
| GET | `/snapshot/state` | None | `{process, snapshot_id, recording, complete, local_state, channel_states, markers_received}` |
| GET | `/compare` | Query parameters `a` and `b` as vector-clock JSON | `{result}` |

Role-inappropriate trigger requests return `400`. A missing order or invalid
state transition returns `400` without a valid event transition.

## Application message

`POST /message` requires the authenticated sender identity and carries:

```json
{
  "message_id": "message-123",
  "channel_id": "r1_hub",
  "from": "restaurant1",
  "to": "hub",
  "type": "order_ready",
  "payload": {"order_id": "order-A"},
  "vc": {"delivery1": 0, "hub": 0, "restaurant1": 2, "restaurant2": 0}
}
```

An accepted first delivery returns `200` with receive status and the merged
vector clock. A repeated `message_id` returns an idempotent acknowledgement and
does not append a second receive event or mutate order state.

## Snapshot marker

`POST /snapshot/marker` requires authenticated sender identity and carries a
snapshot ID plus the channel ID:

```json
{
  "snapshot_id": "snapshot-1",
  "channel_id": "hub_r1",
  "type": "marker"
}
```

The receiver records the marker once for the matching incoming channel. The
first marker starts local recording and is not recorded as an in-transit
application message; later markers close their corresponding channel.
