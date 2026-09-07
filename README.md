# Distributed Food Delivery System
CCZG 526 — Lab Assignment I (Vector Clocks + Chandy-Lamport Global Snapshot)

This project is built using **Spec-Driven Development (SDD)**. The requirements,
architecture, and implementation tasks are documented in
`specs/002-distributed-food-delivery-system/`.

## What this is
`food_delivery_dc` is a distributed food-delivery simulation made up of four
independent Python processes communicating over TCP sockets:
`OrderProcessor`, `Restaurant1`, `Restaurant2`, and `DeliveryPartner`.
Each process maintains its own vector clock and records internal, send, and
receive events. The system demonstrates concurrent events and captures a
Chandy-Lamport global snapshot containing process state and in-transit messages.

## Run the demo and test cases
The implementation uses only the Python standard library. From the repository root:

```bash
cd food_delivery_dc
python run_demo.py
```

`run_demo.py` starts all four processes, runs the order and delivery flow, finds
a concurrent vector-clock event pair, and prints the captured Chandy-Lamport
global snapshot and its consistency analysis.

To run the acceptance test cases:

```bash
cd food_delivery_dc
python run_test_cases.py
```

The test runner starts and stops the same four processes automatically, then
reports the results for the normal order flow, concurrent events, and snapshot
behavior. Logs and snapshot files are written to `food_delivery_dc/logs/`.

## Distributed execution
For a detailed single-machine walkthrough and instructions for running the four
processes on separate cloud-lab nodes, see
[food_delivery_dc/README.md](food_delivery_dc/README.md).

## Why the snapshot is consistent
The Chandy-Lamport algorithm guarantees a consistent cut over the FIFO channels:

- Every process records its own local state **exactly once** — either when
  it initiates the snapshot, or upon receiving the *first* marker on any
  incoming channel.
- For each incoming channel, the process records every application message
  that arrives **after** its own local snapshot but **before** the marker
  on that specific channel. Once the marker arrives, that channel's
  recording is frozen.
- Because channels are FIFO, a marker on a channel guarantees no
  pre-snapshot message from that channel can arrive after it — so nothing
  is missed and nothing is double-counted.
- Consequently, no message appears as received in the recorded state without
  also appearing in the sender's recorded state or in a recorded channel state.

## Project layout
```
food_delivery_dc/        four-process TCP implementation
  run_demo.py             demo runner and snapshot analysis
  run_test_cases.py       acceptance-test runner
  node.py                 socket process base class and snapshots
  vector_clock.py         vector-clock implementation
  logs/                   runtime logs and snapshot JSON files
specs/002-.../            SDD specification, plan, and research artifacts
```
