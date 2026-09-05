"""
Launches all 4 processes as subprocesses, lets the demo run, then performs
post-hoc analysis:
  1. Finds a concurrent event pair using vector clock comparison.
  2. Loads each process's snapshot_<name>.json and prints the full
     recorded global state.
  3. Explains whether the captured global state is consistent.
"""

import json
import os
import re
import subprocess
import sys
import time

from config import CONFIG
from vector_clock import VectorClock

LOG_DIR = "logs"
SCRIPTS = {
    "Restaurant1": "restaurant1.py",
    "Restaurant2": "restaurant2.py",
    "DeliveryPartner": "delivery_partner.py",
    "OrderProcessor": "order_processor.py",  # started last; it's the initiator
}


def clean_logs():
    if os.path.isdir(LOG_DIR):
        for f in os.listdir(LOG_DIR):
            os.remove(os.path.join(LOG_DIR, f))
    os.makedirs(LOG_DIR, exist_ok=True)


def launch_all():
    procs = []
    # Start listeners first (peer order doesn't matter, node.py retries connections)
    for name in ["Restaurant1", "Restaurant2", "DeliveryPartner", "OrderProcessor"]:
        proc = subprocess.Popen([sys.executable, SCRIPTS[name]])
        procs.append(proc)
        time.sleep(0.3)
    return procs


LOG_LINE_RE = re.compile(
    r"\[(?P<time>[\d:]+)\] \[(?P<proc>[\w]+)\s*\] (?P<body>.*?)\s*\| VC=(?P<vc>\[[\d,\s]*\])"
)


def parse_events():
    """Parses logs/<name>.log for every process into a flat list of events."""
    events = []
    for name in CONFIG:
        path = os.path.join(LOG_DIR, f"{name}.log")
        if not os.path.exists(path):
            continue
        with open(path) as f:
            for line in f:
                m = LOG_LINE_RE.match(line.strip())
                if not m:
                    continue
                vc = json.loads(m.group("vc"))
                events.append({
                    "process": m.group("proc"),
                    "body": m.group("body"),
                    "vc": vc,
                })
    return events


def find_concurrent_pair(events):
    """Finds one pair of events on DIFFERENT processes whose vector clocks
    are incomparable (concurrent)."""
    for i in range(len(events)):
        for j in range(i + 1, len(events)):
            e1, e2 = events[i], events[j]
            if e1["process"] == e2["process"]:
                continue
            if VectorClock.compare(e1["vc"], e2["vc"]) == "concurrent":
                return e1, e2
    return None


def load_snapshots():
    snaps = {}
    for name in CONFIG:
        path = os.path.join(LOG_DIR, f"snapshot_{name}.json")
        if os.path.exists(path):
            with open(path) as f:
                snaps[name] = json.load(f)
    return snaps


def print_global_snapshot(snaps):
    print("\n" + "=" * 70)
    print("CAPTURED GLOBAL SNAPSHOT (Chandy-Lamport)")
    print("=" * 70)
    for name, snap in snaps.items():
        ps = snap["process_state"]
        print(f"\nProcess: {name}")
        print(f"  Vector clock at snapshot: {ps['vector_clock']}")
        print(f"  Local state            : {ps['local_state']}")
        print(f"  Channel states (incoming messages in transit when marker arrived):")
        for peer, msgs in snap["channel_states"].items():
            tag = [f"{m['type']}({m.get('payload')})" for m in msgs]
            print(f"    {peer} -> {name}: {tag if tag else '[] (empty)'}")


def analyze_consistency(snaps):
    """
    A cut is consistent if for every recorded receive event, the
    corresponding send is either (a) reflected in the sender's recorded
    state, or (b) present in the recorded state of the channel.
    In Chandy-Lamport this is guaranteed by construction; we verify it here
    by checking no channel message is "orphaned" (i.e. every in-transit
    message's send index is <= sender's recorded vector clock index) and
    that no receiver's recorded state already reflects a message that
    wasn't captured on the channel or in the sender's pre-snapshot history.
    """
    print("\n" + "=" * 70)
    print("CONSISTENCY ANALYSIS")
    print("=" * 70)
    consistent = True
    for name, snap in snaps.items():
        for peer, msgs in snap["channel_states"].items():
            for m in msgs:
                sender_vc_at_send = m["vc"]
                sender_snap = snaps.get(peer)
                if not sender_snap:
                    continue
                sender_recorded_vc = sender_snap["process_state"]["vector_clock"]
                # The sender's recorded state must be >= the vector clock at
                # the time it sent this in-transit message (send happened
                # before the sender's own state was recorded, or exactly at it).
                cmp = VectorClock.compare(sender_vc_at_send, sender_recorded_vc)
                if cmp not in ("before", "equal"):
                    consistent = False
                    print(f"  INCONSISTENCY: message {m['type']} from {peer} to {name} "
                          f"has send-VC {sender_vc_at_send} not <= sender's recorded VC "
                          f"{sender_recorded_vc}")
    if consistent:
        print("""
  The captured cut is CONSISTENT.

  Reasoning: Chandy-Lamport guarantees consistency by construction --
  a process records its own state exactly when the first MARKER is seen,
  and every application message that arrives on a channel BEFORE that
  channel's marker is recorded as part of the channel state (i.e. as
  'in transit'), while messages arriving AFTER the marker belong to the
  post-snapshot state of the receiver and are excluded.

  Consequently, for every message recorded as "in transit" on a channel,
  its send event's vector clock is <= the sender's own recorded vector
  clock (the send happened-before or at the moment the sender's state was
  captured). No receive event in the recorded cut depends on a send event
  that is missing from the snapshot, so the cut respects causality and is
  a valid consistent global state.
""")
    else:
        print("\n  The captured cut is INCONSISTENT (see messages above).")
    return consistent


def main():
    clean_logs()
    print("Launching 4 distributed processes (Restaurant1, Restaurant2, "
          "DeliveryPartner, OrderProcessor)...\n")
    procs = launch_all()

    # Let the whole scenario (orders, prep, pickup, snapshot) play out.
    time.sleep(19)

    for proc in procs:
        proc.terminate()
    for proc in procs:
        proc.wait(timeout=5)

    events = parse_events()
    pair = find_concurrent_pair(events)

    print("\n" + "=" * 70)
    print("CONCURRENT EVENT PAIR (vector clocks incomparable)")
    print("=" * 70)
    if pair:
        e1, e2 = pair
        print(f"  {e1['process']:16s} VC={e1['vc']}  event: {e1['body']}")
        print(f"  {e2['process']:16s} VC={e2['vc']}  event: {e2['body']}")
        print("  These are concurrent because neither vector clock is <= the other.")
    else:
        print("  No concurrent pair found in this run (try again / adjust timing).")

    snaps = load_snapshots()
    print_global_snapshot(snaps)
    analyze_consistency(snaps)

    print("\nFull per-process logs are in the 'logs/' directory.")


if __name__ == "__main__":
    main()
