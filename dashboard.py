"""Streamlit dashboard for the distributed food-delivery monitor."""
import os
from datetime import datetime

import requests
import streamlit as st


st.set_page_config(
    page_title="Team 14 | Food Delivery Monitor",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="expanded",
)

PROCESSES = ["hub", "restaurant1", "restaurant2", "delivery1"]
LABELS = {
    "hub": "Hub",
    "restaurant1": "Restaurant 1",
    "restaurant2": "Restaurant 2",
    "delivery1": "Delivery 1",
}
COLORS = {
    "hub": "#b66cff",
    "restaurant1": "#27c9ff",
    "restaurant2": "#f25cc7",
    "delivery1": "#53dd83",
}
DEFAULT_HOSTS = {
    "hub": "http://localhost:5000",
    "restaurant1": "http://localhost:5001",
    "restaurant2": "http://localhost:5002",
    "delivery1": "http://localhost:5003",
}

st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Space+Grotesk:wght@400;500;600;700&display=swap');
:root { --ink:#f4f3ff; --muted:#9897bd; --panel:#111331; --line:#292753; --cyan:#27c9ff; --violet:#b66cff; }
html, body, [class*="css"] { font-family:'Space Grotesk', sans-serif; }
.stApp { background: radial-gradient(circle at 82% 0%, #211b51 0, #090a20 42%, #060717 100%); color:var(--ink); }
.block-container { max-width:1500px; padding:1.4rem 2rem 2rem; }
section[data-testid="stSidebar"] { background:linear-gradient(180deg,#10102b,#0a0a1e); border-right:1px solid #222248; }
section[data-testid="stSidebar"] .block-container { padding:1.5rem 1.1rem; }
.team-logo { display:flex; align-items:center; gap:11px; margin-bottom:2rem; }
.logo-mark { width:42px; height:42px; display:grid; place-items:center; border:1px solid #6d4cf2; border-radius:12px; color:#36d8ff; font-size:25px; background:#16143b; box-shadow:0 0 22px #4b2caf88; }
.logo-name { font-weight:700; letter-spacing:.08em; font-size:17px; color:#fff; } .logo-sub { color:#8d8bb0; font-size:11px; margin-top:2px; }
.topline { display:flex; justify-content:space-between; align-items:end; margin-bottom:1rem; }
.eyebrow { color:#27c9ff; font-size:11px; letter-spacing:.11em; text-transform:uppercase; } h1 { font-size:28px !important; margin:.15rem 0 0 !important; letter-spacing:-.02em; } .subtitle { color:var(--muted); font-size:13px; }
.panel { background:linear-gradient(145deg,#111432e8,#0c0d24e8); border:1px solid #22234c; border-radius:10px; padding:18px; height:100%; box-shadow:inset 0 1px 0 #ffffff08; }
.panel-title { color:#aaa8d6; font-size:12px; font-weight:600; letter-spacing:.08em; text-transform:uppercase; margin-bottom:13px; }
.metric { font-family:'DM Mono', monospace; font-size:25px; font-weight:500; color:#fff; } .metric-label { color:var(--muted); font-size:11px; margin-top:3px; }
.status { display:inline-flex; align-items:center; gap:7px; color:#8cf09b; border:1px solid #255536; border-radius:20px; padding:7px 12px; font-size:12px; } .dot { width:7px; height:7px; border-radius:50%; background:#62e77b; box-shadow:0 0 9px #62e77b; }
.node { position:absolute; width:122px; height:84px; border:1px solid var(--node); border-radius:13px; background:#121433; text-align:center; padding-top:13px; box-shadow:0 0 25px color-mix(in srgb, var(--node) 28%, transparent); }
.node strong { display:block; font-size:12px; color:#fff; } .node small { display:block; color:#9694b8; font-size:10px; margin-top:5px; }
.topology { position:relative; height:330px; border:1px solid #1e2045; border-radius:8px; background:radial-gradient(circle at 50% 48%,#1a1740 0,#0b0c25 65%); overflow:hidden; }
.topology svg { position:absolute; inset:0; width:100%; height:100%; }
.n-hub { top:25px; left:calc(50% - 61px); } .n-r1 { top:125px; left:7%; } .n-r2 { top:125px; right:7%; } .n-d1 { bottom:17px; left:calc(50% - 61px); }
.event { display:flex; gap:10px; padding:9px 0; border-bottom:1px solid #202142; font-size:11px; align-items:center; } .event:last-child { border:0; } .event-time { width:65px; color:#8583a9; font-family:'DM Mono',monospace; } .event-kind { color:#fff; flex:1; } .event-vc { color:#8e8cff; font-family:'DM Mono',monospace; font-size:10px; }
.clock-table { width:100%; border-collapse:collapse; font-size:11px; } .clock-table th,.clock-table td { padding:9px 7px; border-bottom:1px solid #242449; text-align:center; } .clock-table th { color:#aaa8d6; background:#171735; } .clock-table td:first-child,.clock-table th:first-child { text-align:left; } .clock-table td { color:#e5e3ff; font-family:'DM Mono',monospace; }
.channel { display:grid; grid-template-columns:112px 1fr 25px; gap:8px; align-items:center; margin:14px 0; font-size:11px; } .channel-name { color:#c4c2e5; } .channel-line { height:3px; border-radius:4px; background:linear-gradient(90deg,var(--c),#ffffff22,var(--c)); box-shadow:0 0 10px var(--c); } .channel-count { color:#c2c0e8; text-align:right; font-family:'DM Mono',monospace; }
.stButton>button { border:1px solid #42389b; background:#30209a; color:#fff; border-radius:7px; font-size:12px; } .stButton>button:hover { border-color:#61d8ff; color:#fff; }
[data-testid="stMetric"] { background:#111432; border:1px solid #22234c; border-radius:9px; padding:12px 15px; }
[data-testid="stExpander"] { background:#111432; border:1px solid #22234c; }
</style>
""",
    unsafe_allow_html=True,
)


def fetch_processes(hosts):
    states = {}
    for process, base_url in hosts.items():
        try:
            health = requests.get(f"{base_url}/health", timeout=1.5)
            state = requests.get(f"{base_url}/state", timeout=1.5)
            snapshot = requests.get(f"{base_url}/snapshot/state", timeout=1.5)
            states[process] = {
                "online": health.ok and state.ok,
                "state": state.json() if state.ok else {},
                "snapshot": snapshot.json() if snapshot.ok else {},
            }
        except requests.RequestException:
            states[process] = {"online": False, "state": {}, "snapshot": {}}
    return states


def trigger_process(process, action, order_id=None):
    payload = {"order_id": order_id} if order_id else {}
    response = requests.post(
        f"{DEFAULT_HOSTS[process]}/trigger/{action}",
        json=payload,
        timeout=3,
    )
    response.raise_for_status()
    return response.json()


def demo_states():
    clocks = {"hub": 8, "restaurant1": 5, "restaurant2": 6, "delivery1": 4}
    sample_events = {
        "restaurant1": [("11:41:45", "Placed order #101", "(4, 8, 4, 3)")],
        "restaurant2": [("11:41:46", "Placed order #102", "(4, 4, 7, 3)")],
        "hub": [("11:41:52", "Dispatched order #101", "(8, 5, 6, 4)")],
        "delivery1": [("11:41:55", "Delivered order #101", "(4, 3, 4, 7)")],
    }
    return {
        process: {"online": False, "state": {"vector_clock": {p: clocks.get(p, 0) for p in PROCESSES}, "orders": {}, "log": []}, "snapshot": {"complete": True}, "sample": sample_events.get(process, [])}
        for process in PROCESSES
    }


def event_rows(states):
    rows = []
    for process, info in states.items():
        for event in info.get("state", {}).get("log", []):
            detail = event.get("detail", {})
            if isinstance(detail, dict):
                text = detail.get("action") or detail.get("type") or detail.get("order_id") or "Message"
            else:
                text = str(detail)
            rows.append((event.get("wall_time", 0), process, event.get("event", "event"), text, event.get("vc", {})))
        if not info.get("state", {}).get("log"):
            for time_text, text, vector_clock in info.get("sample", []):
                rows.append((0, process, "demo", text, vector_clock))
    return sorted(rows, reverse=True)[:7]


with st.sidebar:
    st.markdown('<div class="team-logo"><div class="logo-mark">◈</div><div><div class="logo-name">TEAM 14</div><div class="logo-sub">DISTRIBUTED SYSTEMS LAB</div></div></div>', unsafe_allow_html=True)
    st.markdown("**Monitor controls**")
    mode = st.radio("Data source", ["Live processes", "Demo preview"], label_visibility="collapsed")
    states = demo_states() if mode == "Demo preview" else fetch_processes(DEFAULT_HOSTS)
    refresh = st.toggle("Auto refresh", value=False)
    refresh_seconds = st.slider("Refresh interval", 2, 15, 5, disabled=not refresh)
    st.divider()
    st.caption("Four independent Flask processes connected by HTTP channels.")
    st.markdown("**Live workflow**")
    order_id = st.text_input("New order ID", placeholder="order-101", disabled=mode != "Live processes")
    restaurant = st.selectbox(
        "Restaurant",
        options=["restaurant1", "restaurant2"],
        format_func=lambda process: LABELS[process],
        disabled=mode != "Live processes",
    )
    if st.button("Place order", use_container_width=True, disabled=mode != "Live processes"):
        try:
            result = trigger_process(restaurant, "place_order", order_id or None)
            st.toast(f"Order {result['order_id']} placed")
        except requests.RequestException as error:
            st.error(f"Could not place order: {error}")

    known_orders = sorted(states.get("hub", {}).get("state", {}).get("orders", {}))
    delivery_order = st.selectbox(
        "Delivery order",
        options=known_orders or [""],
        disabled=mode != "Live processes" or not known_orders,
        format_func=lambda value: value or "No orders at hub",
    )
    pickup_col, deliver_col = st.columns(2)
    with pickup_col:
        if st.button("Pickup", use_container_width=True, disabled=mode != "Live processes" or not known_orders):
            try:
                trigger_process("delivery1", "pickup", delivery_order)
                st.toast(f"Order {delivery_order} picked up")
            except requests.RequestException as error:
                st.error(f"Pickup failed: {error}")
    with deliver_col:
        if st.button("Deliver", use_container_width=True, disabled=mode != "Live processes" or not known_orders):
            try:
                trigger_process("delivery1", "deliver", delivery_order)
                st.toast(f"Order {delivery_order} delivered")
            except requests.RequestException as error:
                st.error(f"Delivery failed: {error}")

    if st.button("Start global snapshot", use_container_width=True):
        try:
            response = requests.post(f"{DEFAULT_HOSTS['hub']}/snapshot/start", timeout=2)
            st.toast("Snapshot initiated" if response.ok else "Snapshot could not start")
        except requests.RequestException:
            st.toast("Hub is offline")

online_count = sum(info["online"] for info in states.values())
all_events = event_rows(states)
all_orders = sum(len(info.get("state", {}).get("orders", {})) for info in states.values())
complete_snapshot = all(info.get("snapshot", {}).get("complete", False) for info in states.values())

st.markdown('<div class="topline"><div><div class="eyebrow">◈ TEAM 14 / OBSERVABILITY</div><h1>Food Delivery Command Center</h1><div class="subtitle">Vector clocks, causal events, and global state in one view.</div></div><div class="status"><span class="dot"></span> ' + (f"{online_count}/4 PROCESSES HEALTHY" if mode == "Live processes" else "DEMO DATA ACTIVE") + '</div></div>', unsafe_allow_html=True)

metric_cols = st.columns(4)
for col, value, label in zip(metric_cols, [f"{online_count}/4", all_orders, len(all_events), "READY" if complete_snapshot else "RECORDING"], ["Processes online", "Orders observed", "Recent events", "Snapshot state"]):
    with col:
        st.markdown(f'<div class="metric">{value}</div><div class="metric-label">{label}</div>', unsafe_allow_html=True)

st.write("")
left, right = st.columns([1.45, 1])
with left:
    st.markdown('<div class="panel"><div class="panel-title">⌁ System topology</div><div class="topology"><svg viewBox="0 0 700 330" preserveAspectRatio="none"><defs><filter id="glow"><feGaussianBlur stdDeviation="3" result="blur"/><feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs><g fill="none" stroke-width="2" filter="url(#glow)"><path d="M350 74 L150 151" stroke="#27c9ff"/><path d="M350 74 L550 151" stroke="#f25cc7"/><path d="M150 190 L350 280" stroke="#27c9ff"/><path d="M550 190 L350 280" stroke="#f25cc7"/><path d="M350 100 L350 270" stroke="#b66cff"/><path d="M170 165 L530 165" stroke="#b66cff"/></g><g fill="#fff"><circle cx="245" cy="114" r="4"/><circle cx="455" cy="114" r="4"/><circle cx="350" cy="190" r="4"/><circle cx="350" cy="230" r="4"/></g></svg><div class="node n-hub" style="--node:#b66cff"><strong>▦ HUB</strong><small>PORT 5000 · ONLINE</small></div><div class="node n-r1" style="--node:#27c9ff"><strong>▤ RESTAURANT 1</strong><small>PORT 5001 · ONLINE</small></div><div class="node n-r2" style="--node:#f25cc7"><strong>▤ RESTAURANT 2</strong><small>PORT 5002 · ONLINE</small></div><div class="node n-d1" style="--node:#53dd83"><strong>♧ DELIVERY 1</strong><small>PORT 5003 · ONLINE</small></div></div></div>', unsafe_allow_html=True)
with right:
    clock_headers = ["Process"] + [p[:2].upper() for p in PROCESSES]
    table = "<table class='clock-table'><tr>" + "".join(f"<th>{header}</th>" for header in clock_headers) + "</tr>"
    for process in PROCESSES:
        clock = states[process].get("state", {}).get("vector_clock", {})
        table += "<tr><td>" + LABELS[process] + "</td>" + "".join(f"<td>{clock.get(item, 0)}</td>" for item in PROCESSES) + "</tr>"
    table += "</table>"
    st.markdown(f'<div class="panel"><div class="panel-title">◷ Vector clocks</div>{table}<div style="color:#77759d;font-size:10px;margin-top:14px">Each row is the latest local clock snapshot.</div></div>', unsafe_allow_html=True)

st.write("")
left, right = st.columns([1.05, 1])
with left:
    rows = ""
    for timestamp, process, kind, text, clock in all_events:
        time_text = datetime.fromtimestamp(timestamp).strftime("%H:%M:%S") if timestamp else "--:--:--"
        rows += f"<div class='event'><span class='event-time'>{time_text}</span><span class='event-kind'><b style='color:{COLORS[process]}'>{LABELS[process]}</b> &nbsp; {text.replace('_', ' ')}</span><span class='event-vc'>{tuple(clock.values()) if clock else '—'}</span></div>"
    if not rows:
        rows = "<div style='color:#8d8bb0;font-size:12px;padding:16px 0'>No events yet. Start the processes or switch to Demo preview.</div>"
    st.markdown(f'<div class="panel"><div class="panel-title">∿ Event timeline / latest</div>{rows}</div>', unsafe_allow_html=True)
with right:
    channel_data = [("Restaurant 1 → Hub", "#27c9ff", "r1_hub"), ("Restaurant 2 → Hub", "#f25cc7", "r2_hub"), ("Hub → Delivery 1", "#b66cff", "hub_d1"), ("Delivery 1 → Hub", "#53dd83", "d1_hub")]
    channels_html = ""
    for label, color, channel_id in channel_data:
        count = sum(1 for _, _, _, text, _ in all_events if channel_id in text)
        channels_html += f"<div class='channel'><span class='channel-name'>{label}</span><span class='channel-line' style='--c:{color}'></span><span class='channel-count'>{count}</span></div>"
    st.markdown(f'<div class="panel"><div class="panel-title">↗ Channels & in-transit messages</div>{channels_html}<div style="color:#77759d;font-size:10px;margin-top:22px">Live counts are derived from process event logs.</div></div>', unsafe_allow_html=True)

if mode == "Live processes" and refresh:
    import time
    time.sleep(refresh_seconds)
    st.rerun()
