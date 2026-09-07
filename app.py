"""
Single generic process for the Distributed Food Delivery Monitor.

Which of the 4 roles this container plays is decided entirely by the
PROCESS_NAME environment variable (restaurant1 | restaurant2 | delivery1 | hub).
All four roles share this exact same code, per the project constitution.
"""
import copy
import os
import queue
import time
import threading
from functools import wraps

from flask import Flask, request, jsonify, render_template
import requests

from common.vector_clock import VectorClock, compare
from common import channels

PROCESS_NAME = os.environ.get("PROCESS_NAME", "hub")
USE_DOCKER = os.environ.get("USE_DOCKER", "false").lower() == "true"
PORT = int(os.environ.get("PORT", 5000))
# Default artificial transit delay for this process's OUTGOING channels. The
# dashboard raises it at runtime (via /config) on one link so that a snapshot
# can actually observe messages in transit.
DEFAULT_CHANNEL_DELAY_MS = int(os.environ.get("CHANNEL_DELAY_MS", 0))

if PROCESS_NAME not in channels.PROCESSES:
    raise SystemExit(f"Unknown PROCESS_NAME={PROCESS_NAME!r}")

app = Flask(__name__)

vc = VectorClock(PROCESS_NAME, channels.PROCESSES)

OUTGOING = channels.outgoing(PROCESS_NAME)
INCOMING = channels.incoming(PROCESS_NAME)
CHANNEL_BY_ID = {c["id"]: c for c in channels.CHANNELS}


def _fresh_counters():
    return (
        {c["id"]: 0 for c in OUTGOING},   # messages sent per outgoing channel
        {c["id"]: 0 for c in INCOMING},   # messages received per incoming channel
    )


state_lock = threading.Lock()
_sent, _received = _fresh_counters()
state = {"orders": {}, "log": [], "sent": _sent, "received": _received}

send_lock = threading.Lock()  # serializes tick + enqueue -> vector order == wire order

snap_lock = threading.Lock()
snapshot = {
    "recording": False,
    "complete": False,
    "local_state": None,
    "channel_states": {},      # channel_id -> list[message] while/after recording
    "markers_received": set(),
    "started_at": None,
}

config_lock = threading.Lock()
config = {"channel_delay_ms": DEFAULT_CHANNEL_DELAY_MS}


def channel_delay_ms():
    with config_lock:
        return config["channel_delay_ms"]


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


def auth_headers():
    return {
        "X-Process-Name": PROCESS_NAME,
        "X-Auth-Token": channels.AUTH_TOKENS[PROCESS_NAME],
    }


def _incoming_channel_for(sender, channel_id):
    """Return the declared channel if `sender -> me` matches `channel_id`, else None."""
    chan = CHANNEL_BY_ID.get(channel_id)
    if not chan or chan["src"] != sender or chan["dst"] != PROCESS_NAME:
        return None
    return chan


# --------------------------------------------------------------------------- #
# Logging helper
# --------------------------------------------------------------------------- #
def log_event(kind, detail, vc_snapshot):
    with state_lock:
        state["log"].append({
            "event": kind,          # internal | send | receive | snapshot | marker-send | marker-receive
            "detail": detail,
            "vc": vc_snapshot,
            "wall_time": time.time(),
        })


# --------------------------------------------------------------------------- #
# Transport: one FIFO queue + worker per OUTGOING channel
# --------------------------------------------------------------------------- #
# Application messages AND snapshot markers traverse the same queue. That is
# what actually gives each channel the FIFO property Chandy-Lamport relies on:
# a marker can never overtake a message that was enqueued before it.
_out_queues = {c["id"]: queue.Queue() for c in OUTGOING}
_in_flight = {c["id"]: 0 for c in OUTGOING}
_in_flight_lock = threading.Lock()


def _enqueue(channel_id, kind, body):
    with _in_flight_lock:
        _in_flight[channel_id] += 1
    _out_queues[channel_id].put((kind, body))


def _channel_worker(chan):
    q = _out_queues[chan["id"]]
    dst_base = channels.base_url(chan["dst"], USE_DOCKER)
    while True:
        kind, body = q.get()
        delay = channel_delay_ms()
        if delay:
            time.sleep(delay / 1000.0)   # simulated transit time
        path = "/message" if kind == "app" else "/snapshot/marker"
        try:
            requests.post(dst_base + path, json=body, headers=auth_headers(), timeout=10)
        except requests.RequestException as e:
            log_event(f"{kind}-send-error", {"channel": chan["id"], "error": str(e)}, vc.snapshot())
        finally:
            with _in_flight_lock:
                _in_flight[chan["id"]] -= 1
            q.task_done()


def start_channel_workers():
    for c in OUTGOING:
        threading.Thread(target=_channel_worker, args=(c,), daemon=True).start()


def in_flight_counts():
    with _in_flight_lock:
        return dict(_in_flight)


# --------------------------------------------------------------------------- #
# Messaging
# --------------------------------------------------------------------------- #
def send_message(dst, msg_type, payload):
    """Send event: increments own vector clock, then enqueues on the FIFO channel."""
    chan = channels.channel_to(PROCESS_NAME, dst)
    with send_lock:  # tick + enqueue are atomic -> timestamps agree with wire order
        vc_snapshot = vc.tick()
        msg = {
            "channel_id": chan["id"],
            "from": PROCESS_NAME,
            "to": dst,
            "type": msg_type,
            "payload": payload,
            "vc": vc_snapshot,
        }
        with state_lock:
            state["sent"][chan["id"]] += 1
        log_event("send", {"channel": chan["id"], "to": dst, "type": msg_type, "payload": payload}, vc_snapshot)
        _enqueue(chan["id"], "app", msg)


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
        with state_lock:
            state["orders"][order_id]["status"] = "assigned"
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
def _snapshot_in_progress_locked():
    return snapshot["recording"] and not snapshot["complete"]


def _begin_recording_locked():
    """Caller holds snap_lock. Freeze local state (deep copy) and open every incoming channel."""
    with state_lock:
        local_state = {
            "vc": vc.snapshot(),
            "orders": copy.deepcopy(state["orders"]),
            "sent": dict(state["sent"]),          # per outgoing channel, at the cut
            "received": dict(state["received"]),  # per incoming channel, at the cut
        }
    snapshot.update({
        "recording": True,
        "complete": False,
        "local_state": local_state,
        "channel_states": {c["id"]: [] for c in INCOMING},
        "markers_received": set(),
        "started_at": time.time(),
    })
    return local_state["vc"]


def _record_and_broadcast(trigger, marker_channel=None):
    """Record local state and push a marker on every outgoing channel.

    Holding send_lock makes "record state, then send markers" atomic with
    respect to application sends: every message this process sent before the
    cut is already ahead of the marker in its channel queue, and nothing sent
    after the cut can slip in front of it.
    """
    with send_lock:
        with snap_lock:
            if _snapshot_in_progress_locked():
                if marker_channel:
                    snapshot["markers_received"].add(marker_channel)
                return False
            vc_now = _begin_recording_locked()
            if marker_channel:
                # Per Chandy-Lamport: the channel the first marker arrived on records EMPTY.
                snapshot["markers_received"].add(marker_channel)
        log_event("snapshot", {"action": "local_state_recorded", "trigger": trigger}, vc_now)
        for c in OUTGOING:
            log_event("marker-send", {"channel": c["id"], "to": c["dst"]}, vc_now)
            _enqueue(c["id"], "marker", {"channel_id": c["id"], "type": "marker"})
    return True


def initiate_snapshot():
    started = _record_and_broadcast("initiator")
    _check_complete()
    return started


def receive_marker(channel_id):
    with snap_lock:
        first = not _snapshot_in_progress_locked()
    log_event("marker-receive", {"channel": channel_id, "first": first}, vc.snapshot())
    if first:
        _record_and_broadcast(f"first marker on {channel_id}", marker_channel=channel_id)
    else:
        with snap_lock:
            snapshot["markers_received"].add(channel_id)
    _check_complete()


def on_receive_message(msg):
    """Snapshot + counter bookkeeping for every application message, atomically.

    Runs BEFORE business logic. Holding snap_lock across the channel-state
    decision, the received counter and the clock merge means a concurrently
    starting snapshot sees either all of this message's effects or none.
    """
    channel_id = msg["channel_id"]
    with snap_lock:
        if (_snapshot_in_progress_locked()
                and channel_id in snapshot["channel_states"]
                and channel_id not in snapshot["markers_received"]):
            snapshot["channel_states"][channel_id].append(msg)
        with state_lock:
            state["received"][channel_id] += 1
        return vc.merge(msg["vc"])  # receive event: merge + own increment


def _check_complete():
    with snap_lock:
        incoming_ids = {c["id"] for c in INCOMING}
        if snapshot["recording"] and incoming_ids <= snapshot["markers_received"]:
            snapshot["complete"] = True


def snapshot_view():
    with snap_lock:
        return {
            "process": PROCESS_NAME,
            "recording": snapshot["recording"],
            "complete": snapshot["complete"],
            "local_state": snapshot["local_state"],
            "channel_states": snapshot["channel_states"],
            "markers_received": sorted(snapshot["markers_received"]),
            "started_at": snapshot["started_at"],
        }


# --------------------------------------------------------------------------- #
# Routes — process API
# --------------------------------------------------------------------------- #
@app.get("/")
def dashboard():
    return render_template("dashboard.html")


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
            "sent": state["sent"],
            "received": state["received"],
            "in_flight": in_flight_counts(),
            "channel_delay_ms": channel_delay_ms(),
        })


@app.get("/config")
def get_config():
    return jsonify({"process": PROCESS_NAME, "channel_delay_ms": channel_delay_ms()})


@app.post("/config")
def set_config():
    """Tune this process's outgoing transit delay (used by the dashboard demo)."""
    body = request.get_json(force=True, silent=True) or {}
    try:
        delay = int(body.get("channel_delay_ms", channel_delay_ms()))
    except (TypeError, ValueError):
        return jsonify({"error": "channel_delay_ms must be an integer"}), 400
    if delay < 0 or delay > 60000:
        return jsonify({"error": "channel_delay_ms must be between 0 and 60000"}), 400
    with config_lock:
        config["channel_delay_ms"] = delay
    return jsonify({"process": PROCESS_NAME, "channel_delay_ms": delay})


@app.post("/reset")
def reset_process_state():
    """Reset one process for a repeatable teaching/demo run."""
    sent, received = _fresh_counters()
    with state_lock:
        state["orders"] = {}
        state["log"] = []
        state["sent"] = sent
        state["received"] = received
    with vc._lock:
        vc.clock = {process: 0 for process in vc.processes}
    with snap_lock:
        snapshot.update({
            "recording": False,
            "complete": False,
            "local_state": None,
            "channel_states": {},
            "markers_received": set(),
            "started_at": None,
        })
    with config_lock:
        config["channel_delay_ms"] = DEFAULT_CHANNEL_DELAY_MS
    return jsonify({"reset": True, "process": PROCESS_NAME})


@app.post("/message")
@require_auth
def receive_message():
    msg = request.get_json(force=True, silent=True) or {}
    sender = request.headers.get("X-Process-Name")
    chan = _incoming_channel_for(sender, msg.get("channel_id"))
    if chan is None or msg.get("from") != sender or not isinstance(msg.get("vc"), dict) or "type" not in msg:
        return jsonify({"error": "invalid channel or message"}), 400
    msg.setdefault("payload", {})
    vc_snap = on_receive_message(msg)        # snapshot bookkeeping + receive event
    log_event("receive", {
        "channel": chan["id"], "type": msg["type"], "from": sender,
        "payload": msg["payload"], "vc_sent": msg["vc"],
    }, vc_snap)
    handle_message(msg)                      # then business logic (may itself send)
    return jsonify({"status": "received", "vc": vc_snap})


@app.post("/trigger/place_order")
def trigger_place_order():
    if PROCESS_NAME not in ("restaurant1", "restaurant2"):
        return jsonify({"error": f"{PROCESS_NAME} cannot place orders"}), 400
    body = request.get_json(force=True, silent=True) or {}
    order_id = body.get("order_id") or f"order-{int(time.time()*1000)}"
    vc_snap = vc.tick()  # internal event: order created locally
    with state_lock:
        state["orders"][order_id] = {"status": "created_local"}
    log_event("internal", {"order_id": order_id, "action": "order_created"}, vc_snap)
    send_message("hub", "order_ready", {"order_id": order_id})
    return jsonify({"order_id": order_id, "vc": vc_snap})


def _delivery_trigger(action, msg_type):
    if PROCESS_NAME != "delivery1":
        return jsonify({"error": f"{PROCESS_NAME} cannot {action.replace('_', ' ')} orders"}), 400
    body = request.get_json(force=True, silent=True) or {}
    order_id = body.get("order_id")
    if not order_id:
        return jsonify({"error": "order_id is required"}), 400
    vc_snap = vc.tick()
    log_event("internal", {"order_id": order_id, "action": f"{action}_locally"}, vc_snap)
    with state_lock:
        state["orders"].setdefault(order_id, {})["status"] = action
    send_message("hub", msg_type, {"order_id": order_id})
    return jsonify({"order_id": order_id, "vc": vc_snap})


@app.post("/trigger/pickup")
def trigger_pickup():
    return _delivery_trigger("picked_up", "picked_up")


@app.post("/trigger/deliver")
def trigger_deliver():
    return _delivery_trigger("delivered", "delivered")


@app.post("/snapshot/start")
def start_snapshot():
    started = initiate_snapshot()
    return jsonify({"started": started, "process": PROCESS_NAME})


@app.post("/snapshot/marker")
@require_auth
def marker():
    body = request.get_json(force=True, silent=True) or {}
    sender = request.headers.get("X-Process-Name")
    chan = _incoming_channel_for(sender, body.get("channel_id"))
    if chan is None:
        return jsonify({"error": "invalid channel for marker"}), 400
    receive_marker(chan["id"])
    return jsonify({"status": "marker-processed"})


@app.get("/snapshot/state")
def snapshot_state():
    return jsonify(snapshot_view())


@app.get("/compare")
def compare_endpoint():
    """Utility: compare two vector clocks passed as query params (JSON-encoded)."""
    import json
    a = json.loads(request.args["a"])
    b = json.loads(request.args["b"])
    return jsonify({"result": compare(a, b)})


# --------------------------------------------------------------------------- #
# Routes — dashboard API (served by whichever process hosts the UI, i.e. hub)
# --------------------------------------------------------------------------- #
SCENARIO_ORDERS = [("restaurant1", "order-101"), ("restaurant2", "order-102")]
SCENARIO_TRANSIT_DELAY_MS = 1800   # applied to delivery1 -> hub while the snapshot runs


def _url(process, path):
    return channels.base_url(process, USE_DOCKER) + path


def _fetch_json(process, path, timeout=2):
    response = requests.get(_url(process, path), timeout=timeout)
    response.raise_for_status()
    return response.json()


def check_consistency(snapshots):
    """Verify the cut: for every channel, sent@src == received@dst + in-transit.

    `sent`/`received` are the per-channel counters frozen in each local state,
    and in-transit is the recorded channel state at the receiver. If this holds
    on every channel, no message is lost or duplicated by the cut.
    """
    checks = []
    consistent = True
    for chan in channels.CHANNELS:
        src = snapshots.get(chan["src"]) or {}
        dst = snapshots.get(chan["dst"]) or {}
        src_state, dst_state = src.get("local_state"), dst.get("local_state")
        if not (src.get("complete") and dst.get("complete") and src_state and dst_state):
            return {"verified": False, "consistent": False, "checks": []}
        sent = src_state.get("sent", {}).get(chan["id"], 0)
        received = dst_state.get("received", {}).get(chan["id"], 0)
        in_transit = len((dst.get("channel_states") or {}).get(chan["id"], []))
        ok = sent == received + in_transit
        consistent = consistent and ok
        checks.append({
            "channel": chan["id"], "src": chan["src"], "dst": chan["dst"],
            "sent": sent, "received": received, "in_transit": in_transit, "ok": ok,
        })
    return {"verified": True, "consistent": consistent, "checks": checks}


def find_concurrent_pair(processes):
    """Pick a pair of concurrent events from different processes (prefer the two order creations)."""
    events = []
    for process in processes:
        for index, event in enumerate(process.get("log", [])):
            events.append({**event, "process": process["process"], "index": index})
    creations = [e for e in events if e.get("detail", {}).get("action") == "order_created"]
    candidates = [creations, events] if creations else [events]
    for pool in candidates:
        for i, first in enumerate(pool):
            for second in pool[i + 1:]:
                if first["process"] == second["process"]:
                    continue
                if compare(first.get("vc", {}), second.get("vc", {})) == "concurrent":
                    return {"first": first, "second": second}
    return None


@app.get("/api/dashboard")
def dashboard_data():
    """Return a browser-friendly view of the whole distributed system."""
    processes = []
    all_orders = {}
    snapshots = {}

    for process in channels.PROCESSES:
        process_data = {"process": process, "status": "offline", "orders": {}, "log": []}
        try:
            state_data = _fetch_json(process, "/state")
            process_data.update({
                "status": "online",
                "vector_clock": state_data.get("vector_clock", {}),
                "orders": state_data.get("orders", {}),
                "log": state_data.get("log", []),
                "in_flight": state_data.get("in_flight", {}),
                "channel_delay_ms": state_data.get("channel_delay_ms", 0),
            })
            for order_id, order in state_data.get("orders", {}).items():
                all_orders.setdefault(order_id, {})[process] = order.get("status")
            snapshots[process] = _fetch_json(process, "/snapshot/state")
        except (requests.RequestException, ValueError) as error:
            process_data["error"] = str(error)
            snapshots[process] = None
        processes.append(process_data)

    complete = [s for s in snapshots.values() if s and s.get("complete")]
    in_progress = [s for s in snapshots.values() if s and s.get("recording") and not s.get("complete")]
    all_complete = len(complete) == len(channels.PROCESSES)
    consistency = check_consistency(snapshots) if all_complete else {"verified": False, "consistent": False, "checks": []}
    snapshot_data = {
        "complete": all_complete,
        "recording": bool(in_progress),
        "processes": snapshots,
        "consistent": consistency["consistent"],
        "consistency": consistency,
    }

    recent_events = sorted(
        ({**event, "process": p["process"]} for p in processes for event in p.get("log", [])),
        key=lambda event: event.get("wall_time", 0),
        reverse=True,
    )[:20]

    return jsonify({
        "process": PROCESS_NAME,
        "processes": processes,
        "orders": all_orders,
        "events": recent_events,
        "snapshot": snapshot_data,
        "concurrency": find_concurrent_pair(processes),
        "channels": channels.CHANNELS,
    })


@app.post("/api/orders")
def dashboard_place_order():
    body = request.get_json(force=True, silent=True) or {}
    restaurant = body.get("restaurant", "restaurant1")
    order_id = body.get("order_id") or f"order-{int(time.time() * 1000)}"
    if restaurant not in ("restaurant1", "restaurant2"):
        return jsonify({"error": "a valid restaurant is required"}), 400
    try:
        response = requests.post(_url(restaurant, "/trigger/place_order"), json={"order_id": order_id}, timeout=5)
        return jsonify(response.json()), response.status_code
    except requests.RequestException as error:
        return jsonify({"error": str(error)}), 502


def reset_all_processes():
    results = {}
    for process in channels.PROCESSES:
        try:
            response = requests.post(_url(process, "/reset"), timeout=3)
            results[process] = response.ok
        except requests.RequestException:
            results[process] = False
    return {"reset": all(results.values()), "processes": results}


@app.post("/api/reset")
def dashboard_reset():
    return jsonify(reset_all_processes())


@app.post("/api/snapshot")
def dashboard_snapshot():
    """Plain snapshot: hub initiates right now, whatever the system is doing."""
    try:
        response = requests.post(_url("hub", "/snapshot/start"), timeout=5)
        return jsonify(response.json()), response.status_code
    except requests.RequestException as error:
        return jsonify({"error": str(error)}), 502


@app.post("/api/scenario/start")
def scenario_start():
    """Phase 1 of the classroom demo: reset, then both restaurants place orders concurrently."""
    reset = reset_all_processes()
    if not reset["reset"]:
        offline = [p for p, ok in reset["processes"].items() if not ok]
        return jsonify({"error": f"processes not reachable: {', '.join(offline)}", **reset}), 503

    def place(restaurant, order_id):
        try:
            requests.post(_url(restaurant, "/trigger/place_order"), json={"order_id": order_id}, timeout=5)
        except requests.RequestException:
            pass

    threads = [threading.Thread(target=place, args=order, daemon=True) for order in SCENARIO_ORDERS]
    for thread in threads:
        thread.start()
    return jsonify({"started": True, "orders": [order_id for _, order_id in SCENARIO_ORDERS]}), 202


@app.post("/api/scenario/snapshot")
def scenario_snapshot():
    """Phase 2: slow delivery1 -> hub, fire pickup + deliver, and let hub initiate the snapshot.

    Because the delivery messages are still travelling on d1_hub when hub records
    its state, they end up in hub's recorded channel state instead of any local
    state — exactly the case Chandy-Lamport's channel recording exists for.
    """
    body = request.get_json(force=True, silent=True) or {}
    delay = int(body.get("delay_ms", SCENARIO_TRANSIT_DELAY_MS))

    def run():
        try:
            orders = list(_fetch_json("hub", "/state", timeout=5).get("orders", {}))
            requests.post(_url("delivery1", "/config"), json={"channel_delay_ms": delay}, timeout=5)
            for order_id in orders:
                requests.post(_url("delivery1", "/trigger/pickup"), json={"order_id": order_id}, timeout=5)
                requests.post(_url("delivery1", "/trigger/deliver"), json={"order_id": order_id}, timeout=5)
            requests.post(_url("hub", "/snapshot/start"), timeout=5)
            deadline = time.time() + 60
            while time.time() < deadline:
                time.sleep(0.5)
                states = [_fetch_json(p, "/snapshot/state", timeout=5) for p in channels.PROCESSES]
                if all(s.get("complete") for s in states):
                    break
        except (requests.RequestException, ValueError):
            pass
        finally:
            try:
                requests.post(_url("delivery1", "/config"), json={"channel_delay_ms": DEFAULT_CHANNEL_DELAY_MS}, timeout=5)
            except requests.RequestException:
                pass

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"started": True, "slowed_channel": "d1_hub", "delay_ms": delay}), 202


start_channel_workers()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, threaded=True)
