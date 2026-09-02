# Data Model: Distributed Food Delivery System

## Process

Represents one independent runtime: `restaurant1`, `restaurant2`, `delivery1`,
or `hub`.

| Field | Type | Rules |
|---|---|---|
| process_name | identifier | Must be one of the four configured process names |
| role | enum | restaurant, delivery partner, or hub |
| vector_clock | map | Contains exactly one non-negative component per process |
| orders | map | Process-local order projections only |
| event_log | ordered list | Append-only for the process lifetime |
| auth_token | secret value | Static in-memory token associated with process name |

## Order

Represents a delivery request and its local projections at participating
processes.

| Field | Type | Rules |
|---|---|---|
| order_id | identifier | Required and unique within a demonstration |
| restaurant | process name | Must be restaurant1 or restaurant2 |
| delivery_partner | process name | Must be delivery1 once assigned |
| status | enum | created_local, ready, assigned, confirmed, picked_up, delivered |

Valid lifecycle transitions are `created_local -> ready -> assigned`, with
restaurant confirmation recorded alongside assignment, then
`assigned -> picked_up -> delivered`. Duplicate updates are idempotent and
invalid backwards transitions are rejected or ignored without a second business
transition.

## Message Envelope

Represents an application message or snapshot marker sent on one declared
channel.

| Field | Type | Rules |
|---|---|---|
| message_id | identifier | Unique per outbound application message or marker |
| channel_id | identifier | Must match the configured source and destination |
| from | process name | Must equal the authenticated sender |
| to | process name | Must equal the configured channel destination |
| type | enum | order_ready, order_confirmed, assign_delivery, picked_up, delivered, marker |
| payload | object | Contains order_id for application order messages; marker carries snapshot_id |
| vc | map | Four-component vector timestamp for application events |
| snapshot_id | identifier | Required for marker messages and snapshot bookkeeping |

Receivers validate required fields, channel direction, message type, sender
identity, and token before merging the vector clock. A previously accepted
`message_id` is acknowledged without reapplying business logic.

## Event Log Entry

| Field | Type | Rules |
|---|---|---|
| event | enum | internal, send, receive, or diagnostic error |
| detail | object | Identifies action, order, channel, or message |
| vc | map | Four-component timestamp captured at the event |

## Directed Channel

A configured source-to-destination path. The six channels are:

- `r1_hub`: restaurant1 -> hub, `order_ready`
- `r2_hub`: restaurant2 -> hub, `order_ready`
- `hub_r1`: hub -> restaurant1, `order_confirmed`
- `hub_r2`: hub -> restaurant2, `order_confirmed`
- `hub_d1`: hub -> delivery1, `assign_delivery`
- `d1_hub`: delivery1 -> hub, `picked_up` or `delivered`

Each channel has an ordered outbound send path and an in-memory set/list of
message IDs used for deduplication and snapshot recording.

## Global Snapshot

| Field | Type | Rules |
|---|---|---|
| snapshot_id | identifier | Identifies one hub-initiated run |
| status | enum | idle, recording, complete |
| local_state | object per process | Captured once, containing vector clock and order projection |
| channel_states | list per incoming channel | Messages after local capture and before that channel's marker |
| markers_received | set | Each incoming channel marker counted at most once |
| complete | boolean | True only after every incoming marker is received |

The snapshot engine records local state on hub initiation or the first marker,
marks the first-marker channel empty, starts recording other incoming channels,
forwards markers once, and freezes each channel after its marker arrives.
