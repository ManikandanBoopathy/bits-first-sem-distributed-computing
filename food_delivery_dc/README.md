# Distributed Food Delivery System — Vector Clocks & Chandy-Lamport Snapshot

Lab Assignment 1, Distributed Computing (CCZG 526)

## What this is

4 independent Python processes talking only over TCP sockets (no shared
clock, no shared memory):

| Process           | Role                                             |
|--------------------|--------------------------------------------------|
| `OrderProcessor`   | Central component; places orders, initiates the global snapshot |
| `Restaurant1`      | Receives an order, "cooks", sends it to delivery  |
| `Restaurant2`      | Same, but slower — creates a genuine concurrent event with Restaurant1 |
| `DeliveryPartner`  | Picks up ready orders and confirms pickup to `OrderProcessor` |

Each process keeps its own **vector clock** (size 4) and timestamps every
internal / send / receive event. `OrderProcessor` triggers a
**Chandy-Lamport global snapshot** mid-flow, and each process's recorded
local state + channel states are written to `logs/snapshot_<name>.json`.

Files:
```
vector_clock.py      VectorClock class (tick, update, compare)
node.py              Process base class: sockets, events, Chandy-Lamport snapshot
config.py            process name -> (host, port) registry
order_processor.py   \
restaurant1.py        \  the 4 runnable processes
restaurant2.py        /
delivery_partner.py  /
run_demo.py          convenience runner (single machine) + post-run analysis
logs/                created at runtime: per-process .log + snapshot_*.json
```

---

## Option A — Run everything on ONE machine (quickest way to demo it)

Requires only Python 3 (no extra packages — pure standard library).

```bash
cd food_delivery_dc
python3 run_demo.py
```

This will:
1. Launch all 4 processes as subprocesses on `127.0.0.1` (ports 6000-6003, see `config.py`).
2. Let the order → cook → pickup → snapshot sequence run (~20 seconds).
3. Kill the processes, then automatically:
   - print a genuinely **concurrent event pair** (vector clocks compared),
   - print the full **captured global snapshot** (every process's local
     state + every channel's in-transit messages),
   - print a **consistency analysis** explaining why the cut is valid.

Per-process logs land in `logs/<Name>.log`; each process's snapshot is in
`logs/snapshot_<Name>.json`.

If you'd rather watch each process individually instead of the combined
runner, open 4 terminals **in this machine** and run, in any order:
```bash
python3 restaurant1.py
python3 restaurant2.py
python3 delivery_partner.py
python3 order_processor.py     # this one drives the scenario + snapshot
```
(`node.py` retries connecting for a few seconds, so start order doesn't
matter much — but start `order_processor.py` last so the others are
already listening.)

---

## Option B — Run on the actual cloud-lab nodes (real distributed processes)

This is what the assignment is really asking for: 4 processes on **different
machines/VMs**, not just 4 processes on one machine.

1. **Copy the whole `food_delivery_dc/` folder to each of your 4 nodes**
   (scp, git, shared volume — whatever your lab provides).

2. **Edit `config.py`** on every node so it lists the real IP address of
   each node instead of `127.0.0.1`, e.g.:
   ```python
   CONFIG = {
       "OrderProcessor":  ("10.0.0.11", 6000),
       "Restaurant1":     ("10.0.0.12", 6000),
       "Restaurant2":     ("10.0.0.13", 6000),
       "DeliveryPartner": ("10.0.0.14", 6000),
   }
   ```
   Every node needs the **same** `config.py` (same names → same IP\:port
   mapping) — that's how each process finds its peers.

3. Make sure the chosen ports are open between the nodes (check firewall /
   security-group rules on the cloud lab if connections get refused).

4. On each node, run **only its own script**:
   ```bash
   # on the Restaurant1 node
   python3 restaurant1.py

   # on the Restaurant2 node
   python3 restaurant2.py

   # on the DeliveryPartner node
   python3 delivery_partner.py

   # on the OrderProcessor node (run this one last)
   python3 order_processor.py
   ```
   Each process prints its own event log live to its terminal and to
   `logs/<name>.log` **on that node**.

5. After the run, collect `logs/snapshot_<name>.json` from all 4 nodes
   (scp them back to one place) and put them together — that combined set
   of 4 JSON files **is** your captured global snapshot, exactly like
   `run_demo.py` prints in Option A. You can adapt `run_demo.py`'s
   `load_snapshots()` / `analyze_consistency()` functions to read from a
   folder where you've copied all 4 files if you want the same automatic
   analysis.

No code changes are needed to move from Option A to Option B — only
`config.py`'s IP addresses change, because all networking already goes
through real TCP sockets rather than in-process calls.

---

## How to explain this in your report

- **Vector clocks**: point to any `.log` line — every event line already
  prints the vector clock at that moment (`VC=[...]`).
- **Internal / send / receive events**: labelled explicitly in the logs
  (`INTERNAL`, `SEND`, `RECEIVE`).
- **Concurrent events**: `run_demo.py` finds and prints one pair for you,
  using `VectorClock.compare()` (returns `"concurrent"` when neither clock
  is `<=` the other). In this scenario it's typically `OrderProcessor`
  placing Order#102 vs. `Restaurant1` receiving Order#101 — two events with
  no causal path between them.
- **Global snapshot**: each `snapshot_<name>.json` holds that process's
  recorded local state + vector clock, and the recorded state of every
  incoming channel (messages that were "in flight" when the marker
  arrived). With the timing built into this demo, `Restaurant2`'s channel
  typically comes back **empty** (its message hadn't been sent yet) while
  `Restaurant1 → DeliveryPartner` typically comes back **non-empty**
  (its `OrderReady` message was still in transit) — a nice contrast to
  discuss.
- **Consistency**: `run_demo.py`'s `analyze_consistency()` verifies that
  every in-transit message's send-time vector clock is `<=` the sender's
  recorded vector clock, and explains in prose why Chandy-Lamport
  guarantees this by construction.

## Notes / things you can extend for "additional features"

- Add a 5th process (e.g. a `PaymentService`) to exceed the minimum of 4.
- Run multiple snapshots and compare them.
- Visualize the vector clocks as a space-time diagram.
- Log all raw messages to a shared file, so you can draw the message
  sequence chart directly from it.
