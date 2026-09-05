"""
Orchestration script — run this from the HOST (not inside a container) once
all 4 processes are up, either locally (`python app.py` x4 on different
ports) or via `docker compose up`.

Usage:
    python demo.py            # talk to localhost:5000-5003
    python demo.py --docker   # talk to docker-compose mapped ports (same by default)
"""
import sys
import time
import json
import threading

import requests

sys.path.insert(0, ".")
from common import channels
from common.vector_clock import compare

USE_DOCKER = "--docker" in sys.argv


def url(process, path):
    return channels.base_url(process, USE_DOCKER) + path


def wait_for_health(timeout=20):
    deadline = time.time() + timeout
    for p in channels.PROCESSES:
        while time.time() < deadline:
            try:
                r = requests.get(url(p, "/health"), timeout=2)
                if r.ok:
                    break
            except requests.RequestException:
                pass
            time.sleep(0.5)
        else:
            raise SystemExit(f"{p} never became healthy")
    print("[ok] all 4 processes are healthy\n")


def place_order(process, order_id):
    r = requests.post(url(process, "/trigger/place_order"), json={"order_id": order_id}, timeout=5)
    r.raise_for_status()
    return r.json()


def get_state(process):
    return requests.get(url(process, "/state"), timeout=5).json()


def get_snapshot_state(process):
    return requests.get(url(process, "/snapshot/state"), timeout=5).json()


def main():
    wait_for_health()

    print("=== Step 1: two restaurants place orders CONCURRENTLY ===")
    results = {}

    def place(proc, oid):
        results[proc] = place_order(proc, oid)

    t1 = threading.Thread(target=place, args=("restaurant1", "order-A"))
    t2 = threading.Thread(target=place, args=("restaurant2", "order-B"))
    t1.start(); t2.start()
    t1.join(); t2.join()
    print("restaurant1 order_ready vc:", results["restaurant1"]["vc"])
    print("restaurant2 order_ready vc:", results["restaurant2"]["vc"])

    time.sleep(1.5)  # let hub/delivery process everything

    print("\n=== Step 2: delivery lifecycle ===")
    hub_state = get_state("hub")
    assigned_orders = [oid for oid, o in hub_state["orders"].items() if o.get("status") in ("assigned", "ready")]
    print("hub sees orders:", hub_state["orders"])
    for oid in list(hub_state["orders"].keys()):
        requests.post(url("delivery1", "/trigger/pickup"), json={"order_id": oid}, timeout=5)
        time.sleep(0.2)
        requests.post(url("delivery1", "/trigger/deliver"), json={"order_id": oid}, timeout=5)
    time.sleep(1)

    print("\n=== Step 3: prove concurrency with vector clocks ===")
    print("A =", results["restaurant1"]["vc"])
    print("B =", results["restaurant2"]["vc"])
    print("compare(A, B) =>", compare(results["restaurant1"]["vc"], results["restaurant2"]["vc"]))

    print("\n=== Step 4: print full event log per process ===")
    for p in channels.PROCESSES:
        st = get_state(p)
        print(f"\n--- {p} --- vc={st['vector_clock']}")
        for entry in st["log"]:
            print(" ", entry["event"], entry["detail"], "vc=", entry["vc"])

    print("\n=== Step 5: trigger Chandy-Lamport global snapshot (initiator = hub) ===")
    requests.post(url("hub", "/snapshot/start"), timeout=5)
    time.sleep(1.5)

    print("\n=== Step 6: assemble global snapshot ===")
    global_snapshot = {}
    for p in channels.PROCESSES:
        global_snapshot[p] = get_snapshot_state(p)
        print(f"\n--- snapshot @ {p} --- complete={global_snapshot[p]['complete']}")
        print("  local_state:", global_snapshot[p]["local_state"])
        print("  channel_states:", global_snapshot[p]["channel_states"])

    with open("global_snapshot.json", "w") as f:
        json.dump(global_snapshot, f, indent=2)
    print("\n[ok] wrote global_snapshot.json")

    scenario_b()


def scenario_b():
    """Snapshot taken WHILE messages are still in transit.

    Requires the processes to be started with CHANNEL_DELAY_MS set (e.g. 2000),
    otherwise messages are delivered too fast to ever be caught in a channel.
    """
    print("\n\n=== Scenario B: snapshot with messages IN TRANSIT ===")
    for p in channels.PROCESSES:
        requests.post(url(p, "/snapshot/reset"), timeout=5)
    print("[ok] snapshot state reset on all 4 processes")

    requests.post(url("restaurant1", "/trigger/place_order"),
                  json={"order_id": "order-C"}, timeout=5)
    requests.post(url("restaurant2", "/trigger/place_order"),
                  json={"order_id": "order-D"}, timeout=5)
    print("[ok] order-C and order-D placed; messages now in transit")

    time.sleep(0.3)   # short enough that transit is still in progress
    r = requests.post(url("hub", "/snapshot/start"), timeout=5).json()
    print(f"[ok] hub initiated snapshot {r['snapshot_id']} mid-flight")

    time.sleep(12)    # let all markers finish propagating

    captured = {}
    total_in_channels = 0
    for p in channels.PROCESSES:
        s = get_snapshot_state(p)
        captured[p] = s
        nonempty = {k: v for k, v in s["channel_states"].items() if v}
        total_in_channels += sum(len(v) for v in s["channel_states"].values())
        print(f"\n--- snapshot @ {p} --- complete={s['complete']}")
        print("  local_state:", s["local_state"])
        print("  channel_states (non-empty only):", nonempty or "{}")

    print(f"\n>>> messages captured in transit: {total_in_channels}")
    if total_in_channels == 0:
        print(">>> WARNING: channels empty. Start processes with CHANNEL_DELAY_MS=2000.")
    else:
        print(">>> Channel state is non-empty — this is the evidence the")
        print(">>> assignment asks for: state of each process AND channel.")

    with open("global_snapshot_in_transit.json", "w") as f:
        json.dump(captured, f, indent=2)
    print("[ok] wrote global_snapshot_in_transit.json")


if __name__ == "__main__":
    if "--scenario-b" in sys.argv:
        wait_for_health()
        scenario_b()
    else:
        main()
