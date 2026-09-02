# Project Constitution: Distributed Food Delivery Monitor

## 1. Purpose
Build a distributed system simulation of an online food delivery platform that
demonstrates event ordering with **Vector Clocks** and consistent global state
capture with the **Chandy-Lamport snapshot algorithm**, as required by
CCZG 526 Lab Assignment I.

## 2. Core Principles

### 2.1 Process Independence
Every logical role (restaurant, delivery partner, order-processing hub) runs
as its own **independent OS process** with its own memory space. No process
reads another process's memory directly. All coordination happens strictly
through message passing over HTTP.

### 2.2 No Shared Clock, No Shared Database
- No wall-clock timestamps are used to order events.
- No external database, message broker, or persistent store is used.
- All state (orders, vector clocks, channel buffers, auth tokens) lives
  **in-memory** inside each process and is lost on restart. This is
  intentional and keeps the system's causality model honest: the only
  ordering information a process has is what it derives from Vector Clocks.

### 2.3 Explicit Channels
Communication paths between processes are declared explicitly (a static
channel topology), not implicit HTTP calls to arbitrary partners. This is
required so the Chandy-Lamport algorithm has a well-defined channel set to
mark and record.

### 2.4 FIFO Channels (assumption)
Chandy-Lamport requires reliable, FIFO, non-duplicating channels. Since HTTP
does not guarantee this by default, every process serializes its outbound
sends on a given channel with a lock, guaranteeing messages on one channel
arrive at the destination in the order they were sent.

### 2.5 One Codebase, Many Roles
A single Flask application image is used for all four processes. Behavior is
selected at runtime via a `PROCESS_NAME` environment variable. This avoids
code drift between processes that are conceptually the same kind of node
(e.g., restaurant1 vs restaurant2) and keeps the Docker build simple.

### 2.6 In-Memory Auth
Each process is issued a static, hardcoded bearer token (`AUTH_TOKENS` in
`common/channels.py`). Incoming `/message` and `/snapshot/marker` calls must
present the token belonging to the claimed sender. This is intentionally
simple (no database, no external IdP) since the assignment's focus is
distributed coordination, not security engineering.

### 2.7 Observability Over Cleverness
Every process exposes `/state` and `/snapshot/state` endpoints purely for
demonstration and grading — so a grader (or `demo.py`) can query any node at
any time and see its vector clock, event log, and (if a snapshot is running)
its recorded local/channel state.

## 3. Technology Stack
- **Language:** Python 3.11
- **Web framework:** Flask (threaded dev server, sufficient for demo load)
- **Inter-process transport:** HTTP/JSON via `requests`
- **Containerization:** Docker + Docker Compose (one image, four services)
- **Storage:** None — in-memory Python dicts only

## 4. Non-Goals
- Production-grade security, persistence, or scalability
- Real payment processing or geolocation
- Fault tolerance / crash recovery (out of scope for this lab)

## 5. Definition of Done
- 4+ independent processes running (restaurant1, restaurant2, delivery1, hub)
- Internal, send, and receive events are logged with vector timestamps
- At least one demonstrated pair of concurrent events
- Chandy-Lamport snapshot capturing process + channel state
- A written argument for why the captured global state is/is not consistent
