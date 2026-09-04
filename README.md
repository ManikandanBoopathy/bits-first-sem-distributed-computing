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

## Run it — locally, no Docker (quick dev loop)
```bash
pip install -r requirements.txt
PROCESS_NAME=hub          PORT=5000 python app.py &
PROCESS_NAME=restaurant1  PORT=5001 python app.py &
PROCESS_NAME=restaurant2  PORT=5002 python app.py &
PROCESS_NAME=delivery1    PORT=5003 python app.py &
python demo.py
```

## Run the Streamlit dashboard

With the four Flask processes running, start the visualization in another terminal:

```bash
streamlit run dashboard.py
```

Open `http://localhost:8501`. The dashboard polls each process's `/health`, `/state`,
and `/snapshot/state` endpoints. Use **Demo preview** in the sidebar to view the
visual design without starting the backend processes, or use **Start global snapshot**
to initiate Chandy-Lamport recording at the hub while running live.

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
*by construction*, given FIFO channels (enforced here via a per-process
send-lock that serializes outbound messages):

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

In our test run, all 4 `/snapshot/state` endpoints reported `complete: true`
with empty channel states for every channel — meaning by the time the
snapshot ran, all in-flight order messages had already been fully
processed, and the recorded local states line up with the final order
statuses (`confirmed` at restaurants, `assigned` at delivery1, `delivered`
at hub). This is itself evidence of a valid, consistent cut: the union of
all recorded local + channel states neither creates nor drops any message.

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
