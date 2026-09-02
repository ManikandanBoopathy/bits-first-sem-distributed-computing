# Quickstart Validation Guide

## Prerequisites

- Python 3.11 and the packages in `requirements.txt`
- Docker and Docker Compose for the container validation
- The repository root as the working directory

## Local four-process run

Install dependencies:

```bash
pip install -r requirements.txt
```

Start four independent processes in separate terminals:

```bash
PROCESS_NAME=hub PORT=5000 python app.py
PROCESS_NAME=restaurant1 PORT=5001 python app.py
PROCESS_NAME=restaurant2 PORT=5002 python app.py
PROCESS_NAME=delivery1 PORT=5003 python app.py
```

On Windows PowerShell, use `$env:PROCESS_NAME='hub'; $env:PORT='5000'; python
app.py` in each terminal, changing the values per process.

Run the host demonstration:

```bash
python demo.py
```

Expected results:

- `/health` succeeds for all four processes.
- Two restaurant placement events are logged independently and their vector
  clocks compare as `concurrent`.
- The hub assigns both orders; delivery1 reports pickup and delivery.
- Each process exposes vector clock, order state, and event log data.
- A hub-initiated snapshot reports local state, channel state, and completion
  for all four processes.

## Unit and endpoint validation

Run the focused tests once they are implemented:

```bash
python -m pytest tests/test_vector_clock.py tests/test_messages.py tests/test_snapshot.py tests/test_endpoints.py
```

The tests must cover tick/merge/compare semantics, four-component clock shape,
message validation and deduplication, role restrictions, snapshot marker
ordering, and thread-safe state access.

## Docker validation

Build and launch the four services from one image:

```bash
docker compose up --build
```

In another terminal, run:

```bash
pip install -r requirements.txt
python demo.py --docker
```

Expected Docker results match the local run. The four services use distinct host
ports 5000-5003 and communicate internally by service name on the shared bridge
network. Stop the run with `docker compose down`; restarting a service must clear
its in-memory orders, clocks, buffers, tokens, and event log.

## Snapshot consistency check

Start a snapshot while messages are deliberately in flight. Compare the
assembled `/snapshot/state` responses against the rules in
[http-api.md](contracts/http-api.md) and [data-model.md](data-model.md): each
process records local state once, each incoming channel closes on its marker,
and every message recorded in a channel was received after local capture and
before that channel marker.
