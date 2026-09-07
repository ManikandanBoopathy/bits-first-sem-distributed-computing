# Distributed Food Delivery Monitor
CCZG 526 — Lab Assignment I (Vector Clocks + Chandy-Lamport Global Snapshot)

Built following Spec-Driven Development (SDD) — see `.specify/memory/constitution.md`
and `specs/001-distributed-food-delivery-monitor/` for the constitution, spec, plan,
and tasks that drove this implementation.

## What this is
Four independent Flask processes — `restaurant1`, `restaurant2`, `delivery1`, `hub` —
communicate purely over HTTP, each keeping its own in-memory Vector Clock. The system
demonstrates internal/send/receive events, a genuine pair of concurrent events, and a
full Chandy-Lamport global snapshot (process states + channel states).

## Run it — Docker (recommended, matches the "everyone runs the same code" requirement)
```bash
docker compose up --build
```
Wait for all 4 containers to report "Running on http://0.0.0.0:5000", then in another
terminal:
```bash
pip install -r requirements.txt   # only need `requests` on the host
python demo.py --docker
```
Open http://localhost:5000/ for the classroom dashboard. Nothing in it is
simulated client-side: it replays the four processes' *real* event logs as a
space-time diagram (dots = events with their vector timestamps, arrows =
messages paired per FIFO channel) and drives a real Chandy-Lamport snapshot:

1. **Start** — resets all four processes, then `restaurant1` and `restaurant2`
   place `order-101` / `order-102` concurrently. The hub assigns delivery and
   confirms. The replay pauses once the system is quiet; the two `order_created`
   events are highlighted as *concurrent* (incomparable vector clocks).
2. **Capture Global Snapshot** — slows the `delivery1 → hub` channel
   (`POST /config {"channel_delay_ms": …}` on delivery1), fires `PICKED_UP` /
   `DELIVERED` for both orders, and has the hub initiate the snapshot while those
   four messages are still travelling. They therefore show up in the hub's
   recorded **channel state** for `d1_hub`, not in any process state. A purple
   dashed line joins the four recorded local states — the actual cut.
3. The results panel shows every recorded process state, every channel state,
   and a verified consistency check: for each channel,
   `sent@sender-cut == received@receiver-cut + in-transit`.

Messages and markers share one FIFO queue per outgoing channel inside each
process; set `CHANNEL_DELAY_MS=<ms>` in a process's environment to add transit
latency to all of its outgoing channels (default `0`).

## Run it — locally, no Docker (quick dev loop)
```bash
pip install -r requirements.txt
PROCESS_NAME=hub          PORT=5000 python app.py &
PROCESS_NAME=restaurant1  PORT=5001 python app.py &
PROCESS_NAME=restaurant2  PORT=5002 python app.py &
PROCESS_NAME=delivery1    PORT=5003 python app.py &
python demo.py
```

`demo.py` will:
1. Wait for all 4 processes to be healthy.
2. Fire `restaurant1` and `restaurant2` order placements concurrently.
3. Run the delivery lifecycle (assign → pickup → deliver) through `hub`.
4. Print both orders' vector clocks and explicitly `compare()` them —
   expected result: **`concurrent`**, since neither restaurant's send event
   happened-before the other's.
5. Print every process's full event log (internal / send / receive, each
   tagged with its vector timestamp).
6. Trigger a Chandy-Lamport snapshot from `hub` and print + save
   (`global_snapshot.json`) the assembled global state.

## Why the captured global state is consistent
The Chandy-Lamport algorithm guarantees the captured cut is consistent
*by construction*, given FIFO channels (enforced here by one outbound FIFO
queue + worker per channel, which application messages and markers share; the
"record local state, then enqueue markers" step is atomic with respect to sends):

- Every process records its own local state **exactly once** — either when
  it initiates the snapshot, or upon receiving the *first* marker on any
  incoming channel.
- For each incoming channel, the process records every application message
  that arrives **after** its own local snapshot but **before** the marker
  on that specific channel. Once the marker arrives, that channel's
  recording is frozen.
- Because channels are FIFO, a marker on a channel guarantees no
  pre-snapshot message from that channel can arrive after it — so nothing
  is missed and nothing is double-counted.
- Consequently, no message appears "received" by a process's recorded state
  without also appearing either (a) in some channel's recorded state, or
  (b) already reflected in the sender's recorded local state as sent
  before its own snapshot. This is exactly the definition of a consistent
  cut.

In the dashboard run, all 4 `/snapshot/state` endpoints report
`complete: true`; the hub's recorded local state still shows both orders as
`assigned`, delivery1's shows them `delivered`, and the hub's channel state for
`d1_hub` holds exactly the four `PICKED_UP`/`DELIVERED` messages that bridge the
two. Every other channel is empty. The per-channel check
`sent@sender-cut == received@receiver-cut + in-transit` holds on all six
channels (e.g. `d1_hub: 4 == 0 + 4`), so the union of recorded local + channel
states neither creates nor drops any message — a consistent cut. `demo.py`
(with no added latency) reaches the same conclusion with all channels empty.

## Project layout
```
common/vector_clock.py   VectorClock class + compare()
common/channels.py       static topology, ports, in-memory auth tokens
app.py                   single Flask app, role selected by PROCESS_NAME
demo.py                  host-side test/demo orchestration
Dockerfile               one image for all 4 roles
docker-compose.yml       4 services from that one image
.specify/                Spec Kit constitution
specs/.../spec.md         feature spec
specs/.../plan.md         architecture + sequence diagrams (Mermaid)
specs/.../tasks.md        task checklist
```
