# Feature Spec: Distributed Food Delivery Monitor

## Summary
Simulate an online food delivery platform as a set of independent processes
that exchange order/delivery events, timestamp every event with a Vector
Clock, and support taking a consistent global snapshot of the whole system
(all process states + all in-transit channel messages) using the
Chandy-Lamport algorithm.

## Actors / Processes (minimum 4)
| Process       | Role                                                             |
|---------------|-------------------------------------------------------------------|
| `restaurant1` | Places orders ("order ready for pickup")                         |
| `restaurant2` | Places orders, independent of restaurant1                        |
| `delivery1`   | Accepts assigned orders, reports pickup and delivery              |
| `hub`         | Central order-processing hub: assigns deliveries, tracks status   |

## Channels (directed, static topology)
| Channel ID | From          | To            | Carries                          |
|------------|---------------|---------------|-----------------------------------|
| r1_hub     | restaurant1   | hub           | `order_ready`                     |
| r2_hub     | restaurant2   | hub           | `order_ready`                     |
| hub_r1     | hub           | restaurant1   | `order_confirmed`                 |
| hub_r2     | hub           | restaurant2   | `order_confirmed`                 |
| hub_d1     | hub           | delivery1     | `assign_delivery`                 |
| d1_hub     | delivery1     | hub           | `picked_up`, `delivered`          |

## Event Types (per process)
- **Internal event**: a state change with no message (e.g. "order created
  locally", "marked ready before notifying hub"). Increments own vector
  clock component only.
- **Send event**: sending a message on an outgoing channel. Increments own
  component, attaches the resulting vector to the message.
- **Receive event**: receiving a message. Merges the sender's vector into the
  local clock (component-wise max), then increments own component.

## Functional Requirements
1. Each process maintains its own `VectorClock` sized to all 4 processes.
2. `POST /trigger/place_order` (restaurants only) creates an order (internal
   event) and sends `order_ready` to `hub`.
3. On receiving `order_ready`, `hub` performs an internal "assign" event,
   then sends `assign_delivery` to `delivery1` and `order_confirmed` back to
   the originating restaurant.
4. `POST /trigger/pickup` and `POST /trigger/deliver` (delivery1 only) send
   `picked_up` / `delivered` to `hub`.
5. Every process exposes `GET /state` returning its vector clock, order
   table, and full event log (type, vector timestamp, detail).
6. `POST /snapshot/start` (called on `hub`, the initiator) begins a
   Chandy-Lamport snapshot: records local state, then sends `MARKER`
   messages on all outgoing channels.
7. `POST /snapshot/marker` implements marker-receipt logic: first marker
   triggers local state recording + marker propagation; subsequent markers
   close channel recording for that channel.
8. `GET /snapshot/state` returns a process's recorded local state, per
   incoming-channel recorded messages, and whether recording is complete.
9. The system must be able to demonstrate **at least one concurrent pair**
   of events — e.g., `restaurant1` and `restaurant2` each independently
   placing an order before either message reaches `hub`. Vector clock
   comparison of these two send events must report `concurrent`.

## Non-Functional Requirements
- No external database or message broker.
- No wall-clock-based ordering logic (wall-clock time may be logged for
  human readability only, never used for causal decisions).
- Single Docker image reused across all 4 service containers, parameterized
  by `PROCESS_NAME`.

## Out of Scope
- Persistence across restarts
- Multiple concurrent snapshots
- Byzantine/faulty processes, message loss, message duplication
