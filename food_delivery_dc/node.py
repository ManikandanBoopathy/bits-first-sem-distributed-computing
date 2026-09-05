"""
Generic distributed process for the Food Delivery System lab.

Handles:
  - TCP socket networking (one listener + lazy outgoing connections)
  - Vector-clock timestamping of internal / send / receive events
  - Chandy-Lamport global snapshot algorithm
  - Per-process event + snapshot logging to logs/<name>.log
"""

import socket
import threading
import json
import time
import os

from vector_clock import VectorClock


class Process:
    def __init__(self, name, config, log_dir="logs"):
        self.name = name
        self.config = config
        self.names_sorted = sorted(config.keys())
        self.index_map = {n: i for i, n in enumerate(self.names_sorted)}
        self.n = len(config)
        self.clock = VectorClock(self.n, self.index_map[self.name])

        self.host, self.port = config[self.name]
        self.peers = [p for p in config if p != self.name]

        self.lock = threading.RLock()
        self.conns = {}          # peer -> outgoing socket
        self.local_state = {}    # arbitrary application state (order statuses etc.)
        self.on_message_callback = None
        # Simulated network/processing latency applied to non-marker messages
        # only (markers are handled with priority, as in the real algorithm's
        # requirement that a process forwards markers immediately). This is
        # what lets the demo actually catch a message "in flight" during a
        # snapshot instead of always seeing empty channels.
        self.message_delay = 0.0

        # Snapshot bookkeeping
        self.snapshot_in_progress = False
        self.recording_channels = {}   # peer -> list of recorded in-transit messages
        self.markers_received = set()
        self.recorded_state = None

        os.makedirs(log_dir, exist_ok=True)
        self.log_path = os.path.join(log_dir, f"{self.name}.log")
        self.snapshot_path = os.path.join(log_dir, f"snapshot_{self.name}.json")
        open(self.log_path, "w").close()

        self.server_socket = None

    # ---------------- logging ----------------
    def log(self, msg):
        ts = time.strftime("%H:%M:%S")
        line = f"[{ts}] [{self.name:16s}] {msg}  | VC={self.clock.vector}"
        print(line, flush=True)
        with open(self.log_path, "a") as f:
            f.write(line + "\n")

    # ---------------- networking ----------------
    def start_server(self):
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(10)
        threading.Thread(target=self._accept_loop, daemon=True).start()
        self.log(f"Listening on {self.host}:{self.port}")

    def _accept_loop(self):
        while True:
            conn, _addr = self.server_socket.accept()
            threading.Thread(target=self._handle_conn, args=(conn,), daemon=True).start()

    def _handle_conn(self, conn):
        buf = ""
        while True:
            try:
                data = conn.recv(4096)
            except OSError:
                break
            if not data:
                break
            buf += data.decode()
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                if line.strip():
                    msg = json.loads(line)
                    # Simulate network/processing latency for ordinary
                    # application messages only; markers are always handled
                    # immediately (required for snapshot correctness).
                    if msg.get("type") != "MARKER" and self.message_delay > 0:
                        time.sleep(self.message_delay)
                    self._process_incoming(msg)

    def _get_conn(self, peer):
        with self.lock:
            if peer not in self.conns:
                host, port = self.config[peer]
                s = None
                for _ in range(40):  # retry until peer's listener is up
                    try:
                        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        s.connect((host, port))
                        break
                    except (ConnectionRefusedError, OSError):
                        s.close()
                        time.sleep(0.5)
                self.conns[peer] = s
            return self.conns[peer]

    # ---------------- application events ----------------
    def internal_event(self, description):
        with self.lock:
            self.clock.tick()
        self.log(f"INTERNAL : {description}")

    def send(self, peer, msg_type, payload=None):
        with self.lock:
            self.clock.tick()
            msg = {
                "type": msg_type,
                "from": self.name,
                "to": peer,
                "payload": payload,
                "vc": self.clock.vector.copy(),
            }
        conn = self._get_conn(peer)
        conn.sendall((json.dumps(msg) + "\n").encode())
        self.log(f"SEND     : '{msg_type}' -> {peer}  payload={payload}")

    def _process_incoming(self, msg):
        mtype = msg["type"]
        sender = msg["from"]

        if mtype == "MARKER":
            self._handle_marker(sender)
            return

        with self.lock:
            # If this channel is currently being recorded for an in-progress
            # snapshot, and its marker hasn't arrived yet, record the message
            # as part of the channel state BEFORE applying it.
            if (self.snapshot_in_progress
                    and sender in self.recording_channels
                    and sender not in self.markers_received):
                self.recording_channels[sender].append(msg)
            self.clock.update(msg["vc"])

        self.log(f"RECEIVE  : '{mtype}' <- {sender}  payload={msg.get('payload')}")

        if self.on_message_callback:
            self.on_message_callback(mtype, sender, msg.get("payload"))

    # ---------------- Chandy-Lamport snapshot ----------------
    def initiate_snapshot(self):
        with self.lock:
            self._record_own_state(initiator=True)
            for peer in self.peers:
                self._send_marker(peer)

    def _record_own_state(self, initiator):
        self.snapshot_in_progress = True
        self.recorded_state = {
            "process": self.name,
            "vector_clock": self.clock.vector.copy(),
            "local_state": dict(self.local_state),
        }
        self.markers_received = set()
        self.recording_channels = {p: [] for p in self.peers}
        tag = " (initiator)" if initiator else ""
        self.log(f"SNAPSHOT : recorded own state{tag} -> {self.recorded_state}")

    def _send_marker(self, peer):
        conn = self._get_conn(peer)
        marker = {"type": "MARKER", "from": self.name, "to": peer,
                  "payload": None, "vc": self.clock.vector.copy()}
        conn.sendall((json.dumps(marker) + "\n").encode())
        self.log(f"SNAPSHOT : sent MARKER -> {peer}")

    def _handle_marker(self, sender):
        with self.lock:
            if not self.snapshot_in_progress:
                # First marker seen anywhere -> record own state now.
                self._record_own_state(initiator=False)
                # Channel the marker arrived on is empty (nothing was in
                # transit ahead of the marker on this channel).
                self.recording_channels[sender] = []
                self.markers_received.add(sender)
                self.log(f"SNAPSHOT : first MARKER from {sender}; channel[{sender}] state = []")
                for peer in self.peers:
                    if peer != sender:
                        self._send_marker(peer)
            else:
                if sender not in self.markers_received:
                    self.markers_received.add(sender)
                    ch_state = self.recording_channels.get(sender, [])
                    self.log(f"SNAPSHOT : MARKER from {sender}; channel[{sender}] state = {ch_state}")

            if set(self.markers_received) == set(self.peers):
                self._finalize_snapshot()

    def _finalize_snapshot(self):
        self.snapshot_in_progress = False
        result = {
            "process_state": self.recorded_state,
            "channel_states": {p: self.recording_channels[p] for p in self.peers},
        }
        self.log(f"SNAPSHOT COMPLETE -> {json.dumps(result)}")
        with open(self.snapshot_path, "w") as f:
            json.dump(result, f, indent=2)
