# Research: Distributed Food Delivery System

## Decision: Use one shared Flask runtime selected by `PROCESS_NAME`

**Rationale**: Four independent processes must run identical logic while
retaining private memory. Runtime role selection prevents restaurant1 and
restaurant2 from drifting into separate implementations and matches the
constitution.

**Alternatives considered**: Separate applications per role would make process
boundaries explicit but duplicate logic and violate the one-shared-runtime
principle. A single in-process simulation would not demonstrate independent
memory or message passing.

## Decision: Use a four-component Vector Clock for all causal decisions

**Rationale**: The process set is fixed and known. `tick` handles internal and
send events; receive handling takes the component-wise maximum and increments
the receiver. A standalone comparison returns happened-before, equal, or
concurrent. Wall-clock values may be diagnostic metadata but never determine
ordering.

**Alternatives considered**: Lamport clocks cannot identify concurrency, and
wall-clock ordering violates the assignment objective.

## Decision: Keep the six-channel topology in shared configuration

**Rationale**: A static source of truth makes valid senders, receivers, channel
IDs, ports, and incoming channels available to both messaging and snapshot
logic. It prevents arbitrary links and gives Chandy-Lamport a complete channel
set.

**Alternatives considered**: Dynamic peer discovery or arbitrary URLs would
weaken topology validation and make channel recording incomplete.

## Decision: Use validated message envelopes with IDs and receiver deduplication

**Rationale**: HTTP requests can be retried or duplicated at the application
level. Each application message needs a unique ID, declared source/destination
channel, type, payload, and vector timestamp. The receiver validates the source
and channel against shared topology, acknowledges accepted messages, and
ignores an already-seen ID without applying business logic twice.

**Alternatives considered**: Relying only on TCP or a send lock does not provide
application-level deduplication or recovery after a timeout.

## Decision: Serialize markers and application messages through the same
per-channel send lock

**Rationale**: Chandy-Lamport depends on FIFO channels. A marker must not overtake
an application message sent earlier on the same channel. The lock protects the
entire outbound request path for that channel, including marker transmission.

**Alternatives considered**: A process-wide lock is simpler but unnecessarily
blocks unrelated channels. No lock leaves ordering dependent on concurrent
Flask request scheduling.

## Decision: Snapshot state uses an explicit lifecycle and atomic copies

**Rationale**: The generic engine records local state once, marks the incoming
channel that carried the first marker empty, records later messages until each
channel marker arrives, propagates markers once, and reports completion when all
incoming markers arrive. Snapshot ID/state guards and deep copies prevent a
second request or concurrent mutation from overwriting the recorded cut.

**Alternatives considered**: A single boolean without a lifecycle cannot safely
support repeated demonstrations or distinguish active, complete, and unavailable
recordings.

## Decision: Validate with unit, endpoint, integration, and Docker checks

**Rationale**: Vector-clock math and envelope validation are deterministic unit
concerns; concurrency, FIFO, and snapshot consistency require multi-process
checks; Docker validates reproducibility. The host demo remains the grading path.

**Alternatives considered**: A demo-only check would miss malformed messages,
duplicate delivery, and lock ordering failures.

## Resolved risks

- Spoofed sender or channel claims are rejected before clock merge or logging.
- Retries are bounded and use message IDs so accepted messages are not applied
  twice; unrecoverable delivery is reported rather than silently claimed valid.
- Markers share the channel serialization path with application messages.
- Snapshot local state and order data are copied while the state guard is held.
- Snapshot completion is tied to a snapshot identifier and can be reset for a
  new run after the current run is complete.
