"""Static topology for the 4-process food delivery system.

Each entry in CHANNELS is a directed channel: messages flow from `src` to `dst`.
This file is the single source of truth used by every process to figure out
its own outgoing/incoming channels and where to reach its peers.
"""

PROCESSES = ["restaurant1", "restaurant2", "delivery1", "hub"]

# Used only for local (non-docker) testing / demo.py
LOCAL_PORTS = {
    "hub": 5000,
    "restaurant1": 5001,
    "restaurant2": 5002,
    "delivery1": 5003,
}

# In docker-compose every service listens on 5000 inside its own container
DOCKER_PORTS = {p: 5000 for p in PROCESSES}

CHANNELS = [
    {"id": "r1_hub", "src": "restaurant1", "dst": "hub"},
    {"id": "r2_hub", "src": "restaurant2", "dst": "hub"},
    {"id": "hub_r1", "src": "hub", "dst": "restaurant1"},
    {"id": "hub_r2", "src": "hub", "dst": "restaurant2"},
    {"id": "hub_d1", "src": "hub", "dst": "delivery1"},
    {"id": "d1_hub", "src": "delivery1", "dst": "hub"},
]

AUTH_TOKENS = {
    "restaurant1": "tok-restaurant1",
    "restaurant2": "tok-restaurant2",
    "delivery1": "tok-delivery1",
    "hub": "tok-hub",
}


def outgoing(process):
    return [c for c in CHANNELS if c["src"] == process]


def incoming(process):
    return [c for c in CHANNELS if c["dst"] == process]


def channel_to(src, dst):
    for c in CHANNELS:
        if c["src"] == src and c["dst"] == dst:
            return c
    raise ValueError(f"No channel from {src} to {dst}")


def base_url(process, use_docker):
    port = DOCKER_PORTS[process] if use_docker else LOCAL_PORTS[process]
    host = process if use_docker else "localhost"
    return f"http://{host}:{port}"
