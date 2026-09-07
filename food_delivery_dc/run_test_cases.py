"""
Acceptance-test runner for the four-process food-delivery demo.

Run from this directory:
    python run_test_cases.py

The runner exercises the current TCP implementation and reports which requested
behaviors are implemented. TC1-TC3 use the existing role scripts. TC4-TC6
also probe the transport/application boundaries and are reported as FAIL when
an expected contract is not implemented yet.
"""

import json
import os
import re
import socket
import subprocess
import sys
import time
from contextlib import closing

from config import CONFIG
from vector_clock import VectorClock

LOG_DIR = "logs"
PROCESS_ORDER = ["Restaurant1", "Restaurant2", "DeliveryPartner", "OrderProcessor"]
SCRIPTS = {
    "Restaurant1": "restaurant1.py",
    "Restaurant2": "restaurant2.py",
    "DeliveryPartner": "delivery_partner.py",
    "OrderProcessor": "order_processor.py",
}
LOG_LINE_RE = re.compile(
    r"\[(?P<time>[\d:]+)\] \[(?P<proc>[\w]+)\s*\] "
    r"(?P<body>.*?)\s*\| VC=(?P<vc>\[[\d,\s]*\])"
)


def clean_logs():
    os.makedirs(LOG_DIR, exist_ok=True)
    for filename in os.listdir(LOG_DIR):
        path = os.path.join(LOG_DIR, filename)
        if os.path.isfile(path):
            os.remove(path)


def launch_processes():
    processes = []
    for name in PROCESS_ORDER:
        process = subprocess.Popen(
            [sys.executable, SCRIPTS[name]],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        processes.append(process)
        time.sleep(0.3)
    return processes


def stop_processes(processes):
    for process in processes:
        if process.poll() is None:
            process.terminate()
    for process in processes:
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)


def wait_for_logs(timeout=22):
    deadline = time.time() + timeout
    required = [os.path.join(LOG_DIR, f"{name}.log") for name in CONFIG]
    while time.time() < deadline:
        if all(os.path.exists(path) for path in required):
            return True
        time.sleep(0.2)
    return False


def read_logs():
    logs = {}
    for name in CONFIG:
        path = os.path.join(LOG_DIR, f"{name}.log")
        try:
            with open(path, encoding="utf-8") as handle:
                logs[name] = handle.read()
        except FileNotFoundError:
            logs[name] = ""
    return logs


def parse_events(logs):
    events = []
    for content in logs.values():
        for line in content.splitlines():
            match = LOG_LINE_RE.match(line.strip())
            if match:
                events.append({
                    "process": match.group("proc"),
                    "body": match.group("body"),
                    "vc": json.loads(match.group("vc")),
                })
    return events


def result(name, passed, detail):
    status = "PASS" if passed else "FAIL"
    print(f"[{status}] {name}: {detail}")
    return passed


def test_tc1(logs):
    combined = "\n".join(logs.values())
    has_order = "NewOrder" in combined
    has_ready = "OrderReady" in combined
    has_pickup = "PickedUp" in combined
    has_delivery_status = "DELIVERED" in combined
    return result(
        "TC1 Normal Order Flow",
        has_order and has_ready and has_pickup and has_delivery_status,
        "requires NewOrder, OrderReady, PickedUp, and DELIVERED state; "
        f"observed delivery status={has_delivery_status}",
    )


def test_tc2(events):
    candidates = [
        event for event in events
        if "Customer places Order#" in event["body"]
    ]
    pair = None
    for index, first in enumerate(candidates):
        for second in candidates[index + 1:]:
            if first["process"] != second["process"] and VectorClock.compare(
                first["vc"], second["vc"]
            ) == "concurrent":
                pair = first, second
                break
        if pair:
            break
    detail = "two incomparable order-creation vector clocks found" if pair else "no concurrent order-creation pair found"
    return result("TC2 Simultaneous Order Creation", pair is not None, detail)


def load_snapshots():
    snapshots = {}
    for name in CONFIG:
        path = os.path.join(LOG_DIR, f"snapshot_{name}.json")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as handle:
                snapshots[name] = json.load(handle)
    return snapshots


def test_tc3():
    snapshots = load_snapshots()
    complete = len(snapshots) == len(CONFIG)
    transit = [
        message
        for snapshot in snapshots.values()
        for messages in snapshot.get("channel_states", {}).values()
        for message in messages
    ]
    has_transit = bool(transit)
    detail = f"snapshots={len(snapshots)}/{len(CONFIG)}, in_transit_messages={len(transit)}"
    return result("TC3 Snapshot During Message Transit", complete and has_transit, detail)


def send_raw_json(host, port, payload):
    with closing(socket.create_connection((host, port), timeout=3)) as connection:
        connection.sendall(payload)
        connection.shutdown(socket.SHUT_WR)
        return connection.recv(4096)


def test_tc4():
    host, port = CONFIG["Restaurant1"]
    try:
        response = send_raw_json(host, port, b"not-json\n")
    except (ConnectionError, OSError, ValueError) as error:
        return result("TC4 Invalid or Malformed Input", False, f"connection closed without HTTP 400 ({error})")
    return result("TC4 Invalid or Malformed Input", False, f"TCP response={response!r}; HTTP 400 contract is unavailable")


def test_tc5():
    return result(
        "TC5 Message Sent to Closed Process",
        False,
        "role scripts do not expose a controlled send/error endpoint; retry/error behavior needs an explicit test hook",
    )


def test_tc6(logs):
    duplicate_marker = "duplicate"
    passed = duplicate_marker in "\n".join(logs.values()).lower()
    return result(
        "TC6 Repeated Delivery Update",
        passed,
        "duplicate update was detected" if passed else "no duplicate-message detection is implemented",
    )


def main():
    clean_logs()
    print("Launching four food_delivery_dc processes...\n")
    processes = launch_processes()
    try:
        if not wait_for_logs():
            print("[FAIL] Process startup: log files were not created")
            return 1
        # The existing scenario completes its snapshot in approximately 12 seconds.
        time.sleep(19)
        logs = read_logs()
        events = parse_events(logs)
        snapshots = load_snapshots()

        print("\nTest results")
        outcomes = [
            test_tc1(logs),
            test_tc2(events),
            test_tc3(),
            test_tc4(),
            test_tc5(),
            test_tc6(logs),
        ]
        print(f"\nSummary: {sum(outcomes)}/{len(outcomes)} tests passed")
        print(f"Artifacts: {os.path.abspath(LOG_DIR)}")
        print(f"Snapshots: {len(snapshots)}/{len(CONFIG)}")
        return 0 if all(outcomes) else 1
    finally:
        stop_processes(processes)


if __name__ == "__main__":
    raise SystemExit(main())
