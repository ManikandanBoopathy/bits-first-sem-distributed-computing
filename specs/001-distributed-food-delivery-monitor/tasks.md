# Tasks: Distributed Food Delivery Monitor

- [x] T001 Define channel topology & auth tokens — `common/channels.py`
- [x] T002 Implement `VectorClock` (tick/merge/snapshot) + `compare()` —
      `common/vector_clock.py`
- [x] T003 Implement generic Flask app skeleton with `PROCESS_NAME`-based
      role dispatch — `app.py`
- [x] T004 Implement in-memory bearer-token auth decorator — `app.py`
- [x] T005 Implement `/trigger/place_order` (restaurant role) — internal +
      send event
- [x] T006 Implement `/message` receive handler + `handle_message` business
      logic for `order_ready`, `assign_delivery`, `order_confirmed`,
      `picked_up`, `delivered`
- [x] T007 Implement `/trigger/pickup`, `/trigger/deliver` (delivery role)
- [x] T008 Implement `/state` debug endpoint (vector clock, orders, log)
- [x] T009 Implement Chandy-Lamport engine: `initiate_snapshot`,
      `receive_marker`, `on_receive_message` hook, `check_complete`
- [x] T010 Implement `/snapshot/start`, `/snapshot/marker`,
      `/snapshot/state` endpoints
- [x] T011 Write `Dockerfile` (single shared image)
- [x] T012 Write `docker-compose.yml` (4 services, distinct host ports)
- [x] T013 Write `demo.py`: health checks, concurrent order placement,
      vector-clock concurrency proof, delivery lifecycle, snapshot trigger,
      global snapshot assembly + printout
- [x] T014 Local smoke test (no Docker) — run 4 processes on
      localhost:5000-5003, execute `demo.py`
- [ ] T015 Docker smoke test — `docker compose up --build`, rerun
      `demo.py --docker` (do this on your Cloud Lab node)
- [ ] T016 Fill in `GROUP-<N>.pdf` documentation using the assignment
      template: contribution table, test cases, consistency write-up
- [ ] T017 Record group video demo (each member explains their
      contribution) per assignment submission rules
