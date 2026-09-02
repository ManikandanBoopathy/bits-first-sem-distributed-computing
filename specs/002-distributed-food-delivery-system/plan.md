# Implementation Plan: Distributed Food Delivery System

**Branch**: `002-distributed-food-delivery-system` | **Date**: 2026-09-03 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/002-distributed-food-delivery-system/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

Build one reproducible four-process food-delivery demonstration. Each role uses
the same Flask application and selects behavior with `PROCESS_NAME`; processes
communicate over six declared HTTP channels, maintain four-component Vector
Clocks, and run a generic Chandy-Lamport snapshot engine. In-memory state,
message IDs, validated envelopes, serialized channel sends, and deduplication
make the causal and snapshot behavior observable without external services.

## Technical Context

<!--
  ACTION REQUIRED: Replace the content in this section with the technical details
  for the project. The structure here is presented in advisory capacity to guide
  the iteration process.
-->

**Language/Version**: Python 3.11

**Primary Dependencies**: Flask 3.0.3; requests 2.32.3

**Storage**: In-memory Python state only; no database, broker, or persistence

**Testing**: Python unit tests/sanity checks, Flask endpoint tests, four-process
smoke test, and Docker Compose demonstration

**Target Platform**: Python 3.11 on Linux containers or local development hosts

**Project Type**: Multi-process HTTP web service demonstration

**Performance Goals**: Complete the scripted lifecycle and snapshot for four
processes within the demonstration timeout; preserve ordering under 100
messages per declared channel in a controlled run

**Constraints**: Six static directed channels; four independent processes; no
global-clock ordering; per-channel serialized sends including markers; bounded
HTTP timeouts/retries; static in-memory bearer tokens; no external services

**Scale/Scope**: Four named processes, one delivery partner, two restaurants,
one shared image, in-memory lab-scale order flows and snapshots

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

* **Process Independence**: PASS. Roles run as separate processes and share no
  memory; all coordination uses message envelopes.
* **Causal Ordering Only**: PASS. Internal, send, and receive operations use
  Vector Clocks; wall time is diagnostic metadata only and never orders events.
* **In-Memory State**: PASS. Orders, clocks, buffers, tokens, and snapshot state
  are process-local and reset on restart.
* **Explicit Static Topology**: PASS. The shared config is the single source of
  truth for four processes and six directed channels.
* **FIFO Reliable Channels**: PASS with design controls. Per-channel send locks
  cover application messages and markers; message IDs, acknowledgements,
  retries, and receiver deduplication address HTTP delivery behavior.
* **One Shared Runtime**: PASS. One app is selected by `PROCESS_NAME`.
* **Simple Process Authentication**: PASS. Static in-memory bearer tokens are
  validated together with sender and channel claims.
* **Observable State**: PASS. State, event logs, and snapshot records have
  inspectable HTTP contracts.
* **Assignment boundary**: PASS. Production security, persistence, crash
  recovery, payments, geolocation, and production scalability remain out of
  scope.

## Project Structure

### Documentation (this feature)

```text
specs/[###-feature]/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md        # Phase 1 output (/speckit-plan command)
├── quickstart.md        # Phase 1 output (/speckit-plan command)
├── contracts/           # Phase 1 output (/speckit-plan command)
└── tasks.md             # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)
<!--
  ACTION REQUIRED: Replace the placeholder tree below with the concrete layout
  for this feature. Delete unused options and expand the chosen structure with
  real paths (e.g., apps/admin, packages/something). The delivered plan must
  not include Option labels.
-->

```text
common/
├── channels.py          # process list, static topology, ports, auth tokens
├── messages.py          # validated message envelopes, IDs, deduplication data
├── vector_clock.py      # VectorClock tick/merge and compare
└── snapshot.py          # generic Chandy-Lamport state machine
app.py                   # shared Flask runtime and role behavior
demo.py                  # host-side lifecycle, concurrency, and snapshot demo
Dockerfile               # one image for all roles
docker-compose.yml       # four services on one bridge network
requirements.txt         # pinned runtime dependencies
tests/
├── test_vector_clock.py
├── test_messages.py
├── test_snapshot.py
└── test_endpoints.py
```

**Structure Decision**: Keep the existing repository-root single application
layout. Shared protocol and algorithm code belongs in `common/`; the one Flask
entry point and host orchestration script remain at the root. Focused tests live
under `tests/`, while all feature design artifacts remain under this directory.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| None | N/A | The four roles are required independent processes, not separate projects. |

## Post-Design Constitution Check

* **PASS**: The design keeps each role in a separate process with private
  in-memory state and a single shared runtime.
* **PASS**: Vector Clock updates are defined for internal, send, and receive
  events; no wall-clock value participates in causal decisions.
* **PASS**: The six-channel topology, sender/channel validation, and static
  in-memory tokens are centralized and documented by contract.
* **PASS**: Application messages and snapshot markers share per-channel FIFO
  serialization, with IDs, acknowledgements, bounded retries, and deduplication.
* **PASS**: Snapshot recording is generic, marker-driven, completion-aware, and
  based on atomic copies of local state.
* **PASS**: Debug contracts, unit checks, multi-process smoke tests, and Docker
  validation satisfy the observability and workflow requirements.
* **PASS**: No constitution violation or complexity exception remains.
