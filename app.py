"""
Single generic process for the Distributed Food Delivery Monitor.

Which of the 4 roles this container plays is decided entirely by the
PROCESS_NAME environment variable (restaurant1 | restaurant2 | delivery1 | hub).
All four roles share this exact same code, per the project constitution.
"""
import os
import copy
import time
import queue
import threading
from functools import wraps

from flask import Flask, request, jsonify
import requests

from common.vector_clock import VectorClock, compare
from common import channels

PROCESS_NAME = os.environ.get("PROCESS_NAME", "hub")
USE_DOCKER = os.environ.get("USE_DOCKER", "false").lower() == "true"
PORT = int(os.environ.get("PORT", 5000))
# Artificial per-channel transit delay. Without this, messages are delivered
# faster than a snapshot can ever observe them, so every recorded channel
# state is trivially empty and the algorithm demonstrates nothing.
CHANNEL_DELAY_MS = int(os.environ.get("CHANNEL_DELAY_MS", 0))

if PROCESS_NAME not in channels.PROCESSES:
    raise SystemExit(f"Unknown PROCESS_NAME={PROCESS_NAME!r}")

app = Flask(__name__)

vc = VectorClock(PROCESS_NAME, channels.PROCESSES)

state_lock = threading.Lock()
state = {"orders": {}, "log": []}

# One outbound FIFO queue + one worker thread per OUTGOING channel.
# Application messages AND snapshot markers both traverse this queue, which is
# what actually enforces the FIFO property Chandy-Lamport depends on.
_out_queues = {c["id"]: queue.Queue() for c in channels.outgoing(PROCESS_NAME)}
_enqueue_locks = {c["id"]: threading.Lock() for c in channels.outgoing(PROCESS_NAME)}

snap_lock = threading.Lock()
snapshot = {
    "snapshot_id": None,
    "recording": False,
    "complete": False,
    "local_state": None,
    "channel_states": {},      # channel_id -> list[message] while/after recording
    "markers_received": set(),
}


# --------------------------------------------------------------------------- #
# Auth (in-memory, no DB)
# --------------------------------------------------------------------------- #
def require_auth(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        sender = request.headers.get("X-Process-Name")
        token = request.headers.get("X-Auth-Token")
        expected = channels.AUTH_TOKENS.get(sender)
        if not sender or not token or token != expected:
            return jsonify({"error": "unauthorized"}), 401
        return f(*args, **kwargs)
    return wrapper


def require_declared_channel(f):
    """FR-009: reject anything not arriving on a declared sender->me channel.

    Runs BEFORE any vector-clock merge or state mutation, so a rejected message
    leaves the receiver completely untouched.
    """
    @wraps(f)
    def wrapper(*args, **kwargs):
        sender = request.headers.get("X-Process-Name")
        body = request.get_json(force=True, silent=True) or {}
        claimed = body.get("channel_id")
        try:
            chan = channels.channel_to(sender, PROCESS_NAME)
        except ValueError:
            return jsonify({
                "error": "undeclared_channel",
                "detail": f"no channel {sender} -> {PROCESS_NAME}",
            }), 403
        if claimed != chan["id"]:
            return jsonify({
                "error": "channel_id_mismatch",
                "expected": chan["id"],
                "got": claimed,
            }), 403
        return f(*args, **kwargs)
    return wrapper


def auth_headers():
    return {
        "X-Process-Name": PROCESS_NAME,
        "X-Auth-Token": channels.AUTH_TOKENS[PROCESS_NAME],
    }


# --------------------------------------------------------------------------- #
# Logging helper
# --------------------------------------------------------------------------- #
def log_event(kind, detail, vc_snapshot):
    with state_lock:
        state["log"].append({
            "event": kind,          # internal | send | receive
            "detail": detail,
            "vc": vc_snapshot,
            "wall_time": time.time(),
        })


# --------------------------------------------------------------------------- #
# Messaging
# --------------------------------------------------------------------------- #
def _channel_worker(chan):
    """Drains one outgoing channel's queue strictly in enqueue order."""
    q = _out_queues[chan["id"]]
    dst_base = channels.base_url(chan["dst"], USE_DOCKER)
    while True:
        kind, body = q.get()
        if CHANNEL_DELAY_MS:
            time.sleep(CHANNEL_DELAY_MS / 1000.0)   # simulated transit time
        path = "/message" if kind == "app" else "/snapshot/marker"
        try:
            requests.post(dst_base + path, json=body, headers=auth_headers(), timeout=10)
        except requests.RequestException as e:
            log_event(f"{kind}-send-error", {"channel": chan["id"], "error": str(e)}, vc.snapshot())
        finally:
            q.task_done()


def send_message(dst, msg_type, payload):
    """Send event: increments own vector clock, then enqueues on the channel."""
    chan = channels.channel_to(PROCESS_NAME, dst)
    # tick + enqueue must be atomic so vector timestamps and wire order agree
    with _enqueue_locks[chan["id"]]:
        vc_snapshot = vc.tick()
        msg = {
            "channel_id": chan["id"],
            "from": PROCESS_NAME,
            "type": msg_type,
            "payload": payload,
            "vc": vc_snapshot,
        }
        log_event("send", {"channel": chan["id"], "type": msg_type, "payload": payload}, vc_snapshot)
        _out_queues[chan["id"]].put(("app", msg))


def send_marker(chan, snapshot_id):
    """Markers ride the SAME per-channel FIFO queue as application messages."""
    with _enqueue_locks[chan["id"]]:
        _out_queues[chan["id"]].put(
            ("marker", {"channel_id": chan["id"], "snapshot_id": snapshot_id})
        )


# --------------------------------------------------------------------------- #
# Business logic (per role) — triggered by receiving a message
# --------------------------------------------------------------------------- #
def handle_message(msg):
    mtype = msg["type"]
    payload = msg["payload"]
    order_id = payload.get("order_id")

    if mtype == "order_ready" and PROCESS_NAME == "hub":
        with state_lock:
            state["orders"][order_id] = {"status": "ready", "restaurant": msg["from"]}
        vc_snap = vc.tick()  # internal event: hub decides to assign a delivery partner
        log_event("internal", {"order_id": order_id, "action": "assign_delivery_decision"}, vc_snap)
        send_message("delivery1", "assign_delivery", {"order_id": order_id})
        send_message(msg["from"], "order_confirmed", {"order_id": order_id})

    elif mtype == "assign_delivery" and PROCESS_NAME == "delivery1":
        with state_lock:
            state["orders"][order_id] = {"status": "assigned"}

    elif mtype == "order_confirmed":
        with state_lock:
            if order_id in state["orders"]:
                state["orders"][order_id]["status"] = "confirmed"

    elif mtype == "picked_up" and PROCESS_NAME == "hub":
        with state_lock:
            state["orders"].setdefault(order_id, {})["status"] = "picked_up"

    elif mtype == "delivered" and PROCESS_NAME == "hub":
        with state_lock:
            state["orders"].setdefault(order_id, {})["status"] = "delivered"


# --------------------------------------------------------------------------- #
# Chandy-Lamport snapshot engine (generic — identical for every process)
# --------------------------------------------------------------------------- #
def _begin_recording(snapshot_id):
    with state_lock:
        # Deep copy, not dict(): a shallow copy shares the inner per-order
        # dicts with live state, so post-snapshot writes silently mutate the
        # "recorded" state and the snapshot is never actually frozen.
        orders_copy = copy.deepcopy(state["orders"])
    snapshot["snapshot_id"] = snapshot_id
    snapshot["local_state"] = {"vc": vc.snapshot(), "orders": orders_copy}
    snapshot["channel_states"] = {c["id"]: [] for c in channels.incoming(PROCESS_NAME)}
    snapshot["markers_received"] = set()
    snapshot["complete"] = False
    snapshot["recording"] = True


def initiate_snapshot():
    snapshot_id = f"snap-{PROCESS_NAME}-{int(time.time()*1000)}"
    with snap_lock:
        if snapshot["recording"]:
            return None
        _begin_recording(snapshot_id)
    for c in channels.outgoing(PROCESS_NAME):
        send_marker(c, snapshot_id)
    _check_complete()
    return snapshot_id


def receive_marker(channel_id, snapshot_id):
    first = False
    with snap_lock:
        if not snapshot["recording"]:
            first = True
            _begin_recording(snapshot_id)
            # Per Chandy-Lamport: the channel the marker arrived on records EMPTY.
            snapshot["channel_states"][channel_id] = []
        snapshot["markers_received"].add(channel_id)
    if first:
        for c in channels.outgoing(PROCESS_NAME):
            send_marker(c, snapshot_id)
    _check_complete()


def reset_snapshot():
    """Clear recording state so a second snapshot can be demonstrated."""
    with snap_lock:
        snapshot.update({
            "snapshot_id": None,
            "recording": False,
            "complete": False,
            "local_state": None,
            "channel_states": {},
            "markers_received": set(),
        })


def on_receive_message(msg):
    """Called for every application message BEFORE business logic runs."""
    channel_id = msg["channel_id"]
    with snap_lock:
        if (snapshot["recording"]
                and channel_id in snapshot["channel_states"]
                and channel_id not in snapshot["markers_received"]):
            snapshot["channel_states"][channel_id].append(msg)


def _check_complete():
    with snap_lock:
        incoming_ids = {c["id"] for c in channels.incoming(PROCESS_NAME)}
        if snapshot["recording"] and incoming_ids <= snapshot["markers_received"]:
            snapshot["complete"] = True


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
@app.get("/health")
def health():
    return jsonify({"process": PROCESS_NAME, "status": "ok"})


@app.get("/state")
def get_state():
    with state_lock:
        return jsonify({
            "process": PROCESS_NAME,
            "vector_clock": vc.snapshot(),
            "orders": state["orders"],
            "log": state["log"],
            "outbound_in_flight": {cid: q.qsize() for cid, q in _out_queues.items()},
        })


@app.post("/message")
@require_auth
@require_declared_channel
def receive_message():
    msg = request.get_json(force=True)
    on_receive_message(msg)              # snapshot bookkeeping first
    vc_snap = vc.merge(msg["vc"])        # receive event: merge + own increment
    log_event("receive", {"channel": msg["channel_id"], "type": msg["type"], "from": msg["from"]}, vc_snap)
    handle_message(msg)                  # then business logic (may itself send)
    return jsonify({"status": "received", "vc": vc_snap})


@app.post("/trigger/place_order")
def trigger_place_order():
    if PROCESS_NAME not in ("restaurant1", "restaurant2"):
        return jsonify({"error": f"{PROCESS_NAME} cannot place orders"}), 400
    body = request.get_json(force=True) or {}
    order_id = body.get("order_id", f"order-{int(time.time()*1000)}")
    vc_snap = vc.tick()  # internal event: order created locally
    with state_lock:
        state["orders"][order_id] = {"status": "created_local"}
    log_event("internal", {"order_id": order_id, "action": "order_created"}, vc_snap)
    send_message("hub", "order_ready", {"order_id": order_id})
    return jsonify({"order_id": order_id, "vc": vc_snap})


@app.post("/trigger/pickup")
def trigger_pickup():
    if PROCESS_NAME != "delivery1":
        return jsonify({"error": f"{PROCESS_NAME} cannot pick up orders"}), 400
    body = request.get_json(force=True) or {}
    order_id = body["order_id"]
    vc_snap = vc.tick()
    log_event("internal", {"order_id": order_id, "action": "picked_up_locally"}, vc_snap)
    send_message("hub", "picked_up", {"order_id": order_id})
    return jsonify({"order_id": order_id, "vc": vc_snap})


@app.post("/trigger/deliver")
def trigger_deliver():
    if PROCESS_NAME != "delivery1":
        return jsonify({"error": f"{PROCESS_NAME} cannot deliver orders"}), 400
    body = request.get_json(force=True) or {}
    order_id = body["order_id"]
    vc_snap = vc.tick()
    log_event("internal", {"order_id": order_id, "action": "delivered_locally"}, vc_snap)
    send_message("hub", "delivered", {"order_id": order_id})
    return jsonify({"order_id": order_id, "vc": vc_snap})


@app.post("/snapshot/start")
def start_snapshot():
    snapshot_id = initiate_snapshot()
    return jsonify({
        "started": snapshot_id is not None,
        "snapshot_id": snapshot_id,
        "process": PROCESS_NAME,
    })


@app.post("/snapshot/reset")
def reset_snapshot_endpoint():
    reset_snapshot()
    return jsonify({"status": "reset", "process": PROCESS_NAME})


@app.post("/snapshot/marker")
@require_auth
@require_declared_channel
def marker():
    body = request.get_json(force=True)
    receive_marker(body["channel_id"], body.get("snapshot_id"))
    return jsonify({"status": "marker-processed"})


@app.get("/snapshot/state")
def snapshot_state():
    with snap_lock:
        return jsonify({
            "process": PROCESS_NAME,
            "snapshot_id": snapshot["snapshot_id"],
            "recording": snapshot["recording"],
            "complete": snapshot["complete"],
            "local_state": snapshot["local_state"],
            "channel_states": snapshot["channel_states"],
            "markers_received": list(snapshot["markers_received"]),
        })


@app.get("/compare")
def compare_endpoint():
    """Utility: compare two vector clocks passed as query params (JSON-encoded)."""
    import json
    a = json.loads(request.args["a"])
    b = json.loads(request.args["b"])
    return jsonify({"result": compare(a, b)})


def start_channel_workers():
    for c in channels.outgoing(PROCESS_NAME):
        threading.Thread(target=_channel_worker, args=(c,), daemon=True).start()


start_channel_workers()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, threaded=True)
