# Feature Specification: Distributed Food Delivery System

**Feature Branch**: `002-distributed-food-delivery-system`

**Created**: 2026-09-03

**Status**: Draft

**Input**: User description: "Build a distributed online food delivery system with four independent processes that demonstrates vector-clock causality and Chandy-Lamport snapshots."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Place and Process an Order (Priority: P1)

As a lab demonstrator, I want an order to travel from a restaurant through the
central hub to a delivery partner so that I can observe a complete distributed
order lifecycle.

**Why this priority**: The order lifecycle is the primary value of the system
and provides the events used by the other demonstrations.

**Independent Test**: Start the four processes, place an order at either
restaurant, and verify that the hub assigns delivery, the delivery partner
reports pickup and delivery, and the originating restaurant receives
confirmation.

**Acceptance Scenarios**:

1. **Given** all four processes are running, **When** restaurant1 or restaurant2
   places an order, **Then** that restaurant records an internal placement event
   followed by an outbound order-ready event to the hub.
2. **Given** the hub receives an order-ready message, **When** it processes the
   order, **Then** it records an inbound event, records an internal assignment
   event, sends an assignment to delivery1, and sends confirmation to the
   originating restaurant.
3. **Given** delivery1 has an assigned order, **When** pickup and delivery are
   triggered, **Then** delivery1 sends pickup and delivered updates to the hub
   and the hub reflects the resulting order status.

---

### User Story 2 - Inspect Causal Events (Priority: P1)

As a student or grader, I want every process to expose its state and event log
with vector timestamps so that I can verify causal ordering without relying on
a global clock.

**Why this priority**: Inspectable evidence is required to demonstrate the
learning objectives of vector clocks and message-passing systems.

**Independent Test**: Trigger an order and query each process state; verify that
internal, send, and receive events are present and each event includes a vector
timestamp sized for all four processes.

**Acceptance Scenarios**:

1. **Given** a process has handled events, **When** its debug state is requested,
   **Then** the response includes its current vector clock, order state, and
   complete event log.
2. **Given** restaurant1 and restaurant2 place orders independently before
   either message reaches the hub, **When** their placement or send vector
   clocks are compared, **Then** the result identifies the events as concurrent
   rather than ordering one before the other.
3. **Given** a process restarts, **When** its state is requested, **Then** its
   orders, vector clock, channel buffers, tokens, and event log contain only
   newly created in-memory state.

---

### User Story 3 - Capture a Consistent Global Snapshot (Priority: P1)

As a lab demonstrator, I want the hub to initiate a Chandy-Lamport snapshot
so that I can inspect a consistent view of all process states and messages in
transit.

**Why this priority**: The global snapshot is the second core learning
objective and depends on the system having explicit, ordered channels.

**Independent Test**: Start a snapshot from hub while messages may be in flight,
then query snapshot state from every process and verify local state, incoming
channel state, and completion status are reported.

**Acceptance Scenarios**:

1. **Given** the hub initiates a snapshot, **When** the marker reaches every
   process, **Then** each process records its local state exactly once and
   forwards markers on its outgoing channels.
2. **Given** an application message arrives after a process records its local
   state but before the marker for that incoming channel, **When** snapshot
   recording completes, **Then** that message appears in the corresponding
   incoming channel state.
3. **Given** all process recordings finish, **When** the global snapshot is
   queried, **Then** it reports each process's local state, every incoming
   channel's recorded messages, and complete status for each process.

---

### User Story 4 - Run the Same Assignment Environment (Priority: P2)

As a group member, I want all four roles to run from one shared application
image and differ only by runtime configuration so that every member can build
and demonstrate the same system consistently.

**Why this priority**: Reproducible execution prevents environment differences
from obscuring the distributed-computing concepts.

**Independent Test**: Build the shared image once, launch the four named
processes with their role configuration, and verify that each process starts,
uses the expected identity, and communicates only over the declared channels.

**Acceptance Scenarios**:

1. **Given** the shared system image is built, **When** four processes are
   launched as restaurant1, restaurant2, delivery1, and hub, **Then** all four
   start independently and expose their inspection interface.
2. **Given** a process attempts to communicate outside the declared topology,
   **When** the message is sent, **Then** it is rejected and does not alter the
   recipient's state.
3. **Given** a message claims to come from another process, **When** its static
   bearer token is invalid, **Then** the receiver rejects it and does not log it
   as a valid receive event.

### Edge Cases

- A message sent to an unavailable process is reported as unsuccessful and does
  not create a false receive event.
- Duplicate delivery updates do not create duplicate order transitions or
  duplicate valid receive events.
- Concurrent order placements from both restaurants remain distinguishable and
  neither is treated as causally preceding the other without a message path.
- A snapshot started while channels contain messages records those messages on
  the appropriate incoming channels and eventually reports completion or the
  process that has not completed.
- A process receives a message from an undeclared sender or on an undeclared
  channel and rejects it without changing order state or vector clock state.
- Repeated snapshot requests do not overwrite the first recorded local state for
  an active snapshot.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST run four independent processes named restaurant1,
  restaurant2, delivery1, and hub, each with private process state.
- **FR-002**: Processes MUST communicate only by message passing and MUST NOT
  share memory or directly access another process's state.
- **FR-003**: Each process MUST maintain a vector clock with one component for
  each of the four processes.
- **FR-004**: The system MUST use vector-clock comparisons as the only mechanism
  for causal ordering and MUST support identifying concurrent events.
- **FR-005**: Each process MUST log every internal, send, and receive event with
  its vector timestamp.
- **FR-006**: The system MUST support restaurant order placement as an internal
  event followed by an order-ready message to hub.
- **FR-007**: The hub MUST process order-ready messages by recording assignment,
  sending assign-delivery to delivery1, and sending order-confirmed to the
  originating restaurant.
- **FR-008**: Delivery1 MUST support pickup and delivery actions that send
  picked-up and delivered updates to hub.
- **FR-009**: Communication MUST use only these directed channels and message
  types: restaurant1->hub and restaurant2->hub for order-ready; hub->restaurant1
  and hub->restaurant2 for order-confirmed; hub->delivery1 for assign-delivery;
  and delivery1->hub for picked-up and delivered.
- **FR-010**: Each declared channel MUST preserve FIFO order, deliver messages
  reliably without duplication, and serialize outbound sends for that channel.
- **FR-011**: The system MUST support a Chandy-Lamport snapshot initiated by hub
  that records each process's local state and messages in transit on each
  incoming channel.
- **FR-012**: Snapshot reporting MUST include completion status for every
  process and MUST distinguish recorded local state from recorded channel state.
- **FR-013**: Every process MUST expose its current vector clock, order state,
  event log, and snapshot state for inspection and grading.
- **FR-014**: Process authentication MUST use one static in-memory bearer token
  per process, and receivers MUST reject invalid sender tokens.
- **FR-015**: All state MUST be in memory only and MUST reset when a process
  restarts; the system MUST NOT depend on a database, message broker, external
  identity provider, or persistent store.
- **FR-016**: All four roles MUST be provided by one shared Python/Flask
  application, with the role selected at runtime through an environment
  variable.
- **FR-017**: The system MUST be buildable and runnable through Docker using one
  shared image for all four processes.

### Key Entities *(include if feature involves data)*

- **Process**: One of restaurant1, restaurant2, delivery1, or hub, with a role,
  private state, vector clock, event log, and authentication identity.
- **Order**: A food-delivery request identified by an order identifier and
  associated restaurant, delivery partner, and lifecycle status.
- **Message**: A typed application or snapshot-marker transmission between two
  processes, carrying sender identity and causal timestamp where applicable.
- **Directed Channel**: One declared sender-to-receiver path whose ordered
  in-transit messages can be recorded by a snapshot.
- **Vector Clock**: The four-component causal timestamp attached to process
  events and used to compare happened-before and concurrent events.
- **Global Snapshot**: A Chandy-Lamport capture containing every process's local
  state, each incoming channel's in-transit messages, and completion status.
- **Event Log Entry**: A record of an internal, send, or receive event and its
  vector timestamp.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A clean demonstration starts all four named processes from one
  shared build and reaches an inspectable healthy state for all four processes.
- **SC-002**: For every demonstrated order, the system records at least one
  internal event, one send event, and one receive event with four-component
  vector timestamps.
- **SC-003**: A demonstration with two independent restaurant placements
  identifies at least one concurrent event pair and does not report either
  event as causally preceding the other.
- **SC-004**: One hub-initiated snapshot reports local state and completion
  status for all four processes and records every declared incoming channel,
  including any messages that were in transit during recording.
- **SC-005**: Across 100 valid messages sent on each declared channel in a
  controlled run, messages arrive in send order and no message is observed more
  than once.
- **SC-006**: Invalid authentication and undeclared-channel attempts are
  rejected without changing the recipient's order state, vector clock, or valid
  event log.
- **SC-007**: A reviewer can determine each order's lifecycle, each process's
  causal history, and the snapshot's consistency from the exposed inspection
  state without accessing process memory directly.

## Assumptions

- The assignment environment provides network connectivity between the four
  processes and uses stable process names for the duration of a demonstration.
- A single shared image and the runtime role variable are sufficient for the
  four roles; role-specific behavior is part of the shared application behavior.
- The directed topology listed in FR-009 is complete for the assignment. No
  additional process-to-process channels are required.
- Static in-memory bearer tokens are acceptable for the lab and are not intended
  to provide production security.
- Restarting any process intentionally clears its state; persistence, fault
  tolerance, crash recovery, real payments, geolocation, and production
  scalability are outside the feature scope.
- Demonstrations may control message timing sufficiently to create concurrent
  restaurant events and to observe messages in transit during a snapshot.
