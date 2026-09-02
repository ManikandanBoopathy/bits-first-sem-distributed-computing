<!--
Sync Impact Report
Version change: unversioned -> 1.0.0
Modified principles: Existing assignment guidance consolidated into eight explicit principles.
Added sections: Additional Constraints; Development Workflow; Governance.
Removed sections: Numbered Purpose, Technology Stack, Non-Goals, and Definition of Done
headings, whose applicable content is preserved below in the scaffold sections.
Follow-up TODOs: Confirm the original constitution ratification date.
-->

# Distributed Food Delivery Monitor Constitution

## Core Principles

### Process Independence
Each restaurant, delivery partner, and order-processing hub MUST run as an
independent operating-system process with its own memory space. Processes MUST
coordinate only through message passing over the configured HTTP interface and
MUST NOT read or mutate another process's memory. This makes process boundaries
and distributed events observable for the lab.

### Causal Ordering Only
Vector Clocks MUST be the sole source of causal event ordering. The system MUST
not use a global clock, wall-clock timestamp, or elapsed time to decide whether
one distributed event happened before another. Every internal, send, and receive
event MUST update and record the local vector clock.

### In-Memory State
The implementation MUST use no external database, message broker, or persistent
store. Orders, vector clocks, channel buffers, and authentication tokens MUST
remain in process memory and MUST reset on restart. Persistence, fault tolerance,
and crash recovery are outside this assignment's causality and snapshot focus.

### Explicit Static Topology
The communication topology MUST be explicit and static. Each permitted channel
between processes MUST be declared in the shared topology configuration so the
Chandy-Lamport algorithm has a known set of incoming channels to record. Runtime
calls MUST NOT create arbitrary undeclared process links.

### FIFO Reliable Channels
Application channels MUST behave as FIFO, reliable, and non-duplicating
channels. Each process MUST use a per-process send lock to serialize outbound
messages on each channel, preserving send order over the HTTP transport. Channel
state MUST be recordable during a Chandy-Lamport snapshot.

### One Shared Runtime
All roles MUST be implemented in one shared Python/Flask codebase. The selected
role MUST come from the `PROCESS_NAME` environment variable at runtime, allowing
restaurant, delivery partner, and hub processes to use the same implementation
without role-specific code drift.

### Simple Process Authentication
Process-to-process authentication MUST use one static in-memory bearer token per
process. A receiver MUST validate the token associated with the claimed sender.
External identity providers and production-grade security controls are
non-goals; this mechanism exists to make lab messages attributable and bounded.

### Observable State
Every process MUST expose a debug endpoint that reports its current vector clock,
order state, and event log. Snapshot state MUST also be inspectable so graders
can verify local states, recorded channel messages, event timestamps, and the
consistency of a Chandy-Lamport global snapshot.

## Additional Constraints

- The implementation MUST use Python 3.11, Flask, HTTP/JSON via `requests`, and
  in-memory Python data structures.
- Docker Compose MAY launch the independent processes from one shared image.
- The demonstration MUST include internal, send, and receive events, at least
  one pair of concurrent events, and a Chandy-Lamport snapshot of process and
  channel state.
- The system MUST model the roles restaurant, delivery partner, and hub without
  implementing real payment processing, geolocation, or production scalability.

## Development Workflow

Changes MUST be checked against every applicable principle before they are
accepted. Tests or demonstrations MUST verify vector-clock updates, message
delivery and authentication, FIFO send serialization, explicit topology, and
snapshot consistency. A change is complete only when the configured processes
can run independently, their event logs are inspectable, concurrent events are
demonstrated, and the global snapshot includes process and channel state.

## Governance

This constitution is the governing document for the lab implementation. Any
amendment MUST be proposed in writing, identify affected principles, explain its
rationale, update the Sync Impact Report, and preserve or explicitly revise the
assignment's causal-ordering and snapshot requirements. Source changes that
conflict with this document MUST be revised or justified by a constitution
amendment before acceptance.

Constitution versions MUST follow semantic versioning. A MAJOR increment removes
or redefines a principle incompatibly; a MINOR increment adds a principle or
materially expands governance; a PATCH increment clarifies wording without
changing requirements. Every review MUST check compliance with the principles,
constraints, workflow gates, and non-goals, and MUST record unresolved exceptions.

**Version**: 1.0.0 | **Ratified**: TODO(RATIFICATION_DATE): confirm original adoption date | **Last Amended**: 2026-09-03
