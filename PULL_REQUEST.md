# Fix snapshot correctness: FIFO markers, frozen state, channel validation

## Summary

Five defects in the Chandy-Lamport implementation, found by running the system
rather than reading it. Four of the five produce **wrong output with no error**,
which is the failure mode that matters most here — the recorded global snapshot
is the graded artifact, and it was quietly incorrect.

Also adds the demo scenario that captures messages **in transit**, satisfying
the assignment requirement to show the state of each process *and each
communication channel*.

| # | Defect | Severity | Symptom |
|---|--------|----------|---------|
| 1 | Recorded local state not frozen (shallow copy) | Critical | Snapshot mutates after being taken |
| 2 | Markers bypass FIFO ordering | Critical | Marker can overtake an application message |
| 3 | Undeclared channels accepted | High | Forged vector clock merged into a live process |
| 4 | Channel states always empty | High | Snapshot demonstrates nothing |
| 5 | Snapshot can only run once | Medium | No second snapshot without restarting all processes |

---

## Issue 1 — Recorded local state was never actually frozen

**Severity:** Critical · **File:** `app.py` · **Commit:** `fix(snapshot): freeze recorded local state with a deep copy`

### Problem

`_begin_recording()` copied the order table with `dict()`:

```python
orders_copy = dict(state["orders"])
```

`dict()` is a **shallow** copy. The outer dict is new, but the inner per-order
dicts are the *same objects* still referenced by live process state. Every
order transition occurring after the snapshot retroactively rewrote the
"recorded" state.

### Reproduction

Snapshot taken while `order-C`'s `order_ready` was still in transit to hub.
`restaurant1` reported:

```json
{
  "orders": { "order-C": { "status": "confirmed" } },
  "vc": { "delivery1": 0, "hub": 0, "restaurant1": 2, "restaurant2": 0 }
}
```

`status: confirmed` requires receiving `order_confirmed` from hub. But hub's
clock component is `0` — restaurant1 has never received anything from hub. The
state is causally impossible. It was written *after* the snapshot, through the
shared reference.

### Fix

```python
orders_copy = copy.deepcopy(state["orders"])
```

### After

```json
{
  "orders": { "order-C": { "status": "created_local" } },
  "vc": { "delivery1": 0, "hub": 0, "restaurant1": 2, "restaurant2": 0 }
}
```

`created_local` at `restaurant1:2` — the state immediately after the internal
create event and the send tick. Internally consistent.

> **Why this one mattered most:** nothing crashed and no test failed. The
> snapshot was simply wrong, and would have been reported as correct.

---

## Issue 2 — Markers could overtake application messages

**Severity:** Critical · **File:** `app.py` · **Commit:** `fix(transport): route markers through per-channel FIFO queues`

### Problem

Chandy-Lamport's correctness rests entirely on FIFO channels. The
implementation claimed to provide this via a global `send_lock`:

```python
def send_message(dst, msg_type, payload):
    with send_lock:               # serializes application messages
        ...
        requests.post(url, json=msg, ...)

def send_marker(chan):            # no lock, different endpoint
    requests.post(url, json={"channel_id": chan["id"]}, ...)
```

`send_marker()` never took the lock and posted to `/snapshot/marker` rather
than `/message`. Two independent HTTP requests to a `threaded=True` Flask
server have no ordering guarantee, so a marker could arrive ahead of an
application message dispatched before it. When that happens the message is
lost from the cut: too late for the sender's recorded state, and the receiver
has already closed that channel's recording.

A second, related problem: `send_message()` blocked on `requests.post`, and
`handle_message()` dispatched downstream sends *synchronously inside the
receive handler*. This produced a deeply nested synchronous cascade
(`hub → r1 → hub → …`) that survived only because Flask runs `threaded=True`,
and it drove channel occupancy to effectively zero — which masked this bug
entirely (see Issue 4).

### Fix

One FIFO queue and one worker thread per outgoing channel. Markers and
application messages share the queue, so ordering is structural rather than
incidental:

```python
_out_queues = {c["id"]: queue.Queue() for c in channels.outgoing(PROCESS_NAME)}

def send_message(dst, msg_type, payload):
    with _enqueue_locks[chan["id"]]:      # tick + enqueue atomic
        vc_snapshot = vc.tick()
        _out_queues[chan["id"]].put(("app", msg))

def send_marker(chan, snapshot_id):
    with _enqueue_locks[chan["id"]]:
        _out_queues[chan["id"]].put(("marker", {...}))   # same queue
```

The tick and the enqueue are atomic together, so vector timestamps and wire
order always agree. Sends are now asynchronous, which also removes the nested
cascade.

---

## Issue 3 — Undeclared channels were accepted and corrupted the vector clock

**Severity:** High · **File:** `app.py` · **Commit:** `fix(auth): reject undeclared channels before touching receiver state`

### Problem

`require_auth` validated the bearer token, but never checked that a declared
channel exists from the sender to this process, nor that the claimed
`channel_id` matched. Spec 002 US4 scenario 2 requires both.

### Reproduction

`delivery1 → restaurant1`. No such channel exists in `common/channels.py`:

```bash
curl -XPOST localhost:5001/message \
  -H "X-Process-Name: delivery1" -H "X-Auth-Token: tok-delivery1" \
  -d '{"channel_id":"d1_r1","from":"delivery1","type":"order_confirmed",
       "payload":{"order_id":"x"},"vc":{"delivery1":99}}'
```

```
200 {"status":"received","vc":{"delivery1":99,"hub":7,"restaurant1":4,"restaurant2":2}}
```

Accepted. `restaurant1`'s clock now carries `delivery1: 99` — a value it has no
causal basis for. Every subsequent `compare()` involving `restaurant1` is
meaningless.

### Fix

`@require_declared_channel`, applied to `/message` and `/snapshot/marker`,
running *before* any vector-clock merge or state mutation:

```python
try:
    chan = channels.channel_to(sender, PROCESS_NAME)
except ValueError:
    return jsonify({"error": "undeclared_channel", ...}), 403
if claimed != chan["id"]:
    return jsonify({"error": "channel_id_mismatch",
                    "expected": chan["id"], "got": claimed}), 403
```

### After

| Case | Response |
|------|----------|
| `delivery1 → restaurant1` (no channel) | `403 undeclared_channel` |
| `restaurant1 → hub` claiming `d1_hub` | `403 channel_id_mismatch, expected r1_hub` |
| Valid sender, wrong token | `401 unauthorized` |

Receiver vector clock verified unchanged in all three cases.

---

## Issue 4 — Every recorded channel state was empty

**Severity:** High · **Files:** `app.py`, `demo.py` · **Commits:** `fix(transport): …`, `test(demo): capture a snapshot with messages in transit`

### Problem

Because sends were synchronous and `demo.py` snapshotted a quiesced system,
every run produced:

```
--- snapshot @ hub ---
  channel_states: {'d1_hub': [], 'r1_hub': [], 'r2_hub': []}
```

The assignment requires showing the state of each process **and each
communication channel**. An all-empty result demonstrates the algorithm ran,
not that it works — the interesting half of Chandy-Lamport is exactly the
in-transit messages.

### Fix

`CHANNEL_DELAY_MS` on the queue workers makes transit an observable state, and
`scenario_b()` in `demo.py` fires the snapshot 300ms after placing orders,
while `order_ready` is still on the wire.

```bash
CHANNEL_DELAY_MS=2000 PROCESS_NAME=hub PORT=5000 python app.py &   # ×4
python demo.py --scenario-b
```

### After

```
--- snapshot @ restaurant1 ---
  local_state:  orders {order-C: created_local}   vc {restaurant1: 2}
  channel_states: {hub_r1: []}

--- snapshot @ hub ---
  local_state:  orders {}                          vc {all zeros}
  channel_states:
    r1_hub: [ order_ready(order-C)  vc {restaurant1: 2} ]
    r2_hub: [ order_ready(order-D)  vc {restaurant2: 2} ]

>>> messages captured in transit: 2
```

### Consistency argument this enables

The message recorded in `r1_hub` carries `vc = {restaurant1: 2}`.
`restaurant1`'s recorded local state carries **the same timestamp**, and hub's
recorded local state has no trace of the order. So the message is:

- **sent** — reflected in the sender's recorded state
- **not received** — absent from the receiver's recorded state
- **in the channel** — present in `r1_hub`'s recorded state

Nothing appears received-but-never-sent, and nothing sent is lost. That is
precisely the definition of a consistent cut, now demonstrated with evidence
rather than asserted from an empty result.

---

## Issue 5 — A snapshot could only ever run once

**Severity:** Medium · **File:** `app.py` · **Commit:** `feat(snapshot): add snapshot_id and /snapshot/reset`

### Problem

`recording` was set `True` and never cleared:

```bash
curl -XPOST localhost:5000/snapshot/start
{"process":"hub","started":false}
```

A second snapshot required restarting all four processes — awkward in a live
demonstration where a grader may ask to see it again.

### Fix

`POST /snapshot/reset`, plus a `snapshot_id` threaded through
start → marker → state so successive rounds are distinguishable.

```bash
curl -XPOST localhost:5000/snapshot/reset
{"process":"hub","status":"reset"}

curl -XPOST localhost:5000/snapshot/start
{"process":"hub","snapshot_id":"snap-hub-1788605081740","started":true}
```

---

## Verification

All checks run against the final commit, four processes on localhost:5000–5003.

| Check | Result |
|-------|--------|
| Scenario A — full order lifecycle, all 4 processes healthy | Pass |
| Concurrency — `compare(A, B)` on independent restaurant placements | `concurrent` |
| Event log — internal / send / receive present, 4-component timestamps | Pass |
| Scenario B — snapshot with messages in transit | 2 messages captured |
| Recorded state internally consistent with recorded channel contents | Pass |
| Undeclared channel rejected | `403` |
| `channel_id` mismatch rejected | `403` |
| Invalid token rejected | `401` |
| Receiver vector clock unchanged after each rejection | Pass |
| Reset then re-snapshot | `started: true` |

```bash
# reproduce
CHANNEL_DELAY_MS=2000 PROCESS_NAME=hub         PORT=5000 python app.py &
CHANNEL_DELAY_MS=2000 PROCESS_NAME=restaurant1 PORT=5001 python app.py &
CHANNEL_DELAY_MS=2000 PROCESS_NAME=restaurant2 PORT=5002 python app.py &
CHANNEL_DELAY_MS=2000 PROCESS_NAME=delivery1   PORT=5003 python app.py &
python demo.py                 # scenario A then B
python demo.py --scenario-b    # scenario B only, clean boot
```

Artifacts written: `global_snapshot.json`, `global_snapshot_in_transit.json`.

---

## Not in this PR

Tracked separately:

- `tests/` — pytest suite for vector clocks, FIFO under load (SC-005), auth rejection (SC-006)
- `PEERS` env var so processes can run across real cloud-lab nodes rather than one host
- `GROUP-<N>.pdf` submission document and the recorded demonstration

## Checklist

- [x] All five defects reproduced before fixing
- [x] Each fix verified independently
- [x] Non-empty channel state demonstrated
- [x] No new dependencies (`flask`, `requests` only)
- [x] Backward compatible — `CHANNEL_DELAY_MS` defaults to `0`
- [ ] Reviewed by a second group member
