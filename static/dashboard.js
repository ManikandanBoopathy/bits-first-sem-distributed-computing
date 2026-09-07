// Classroom dashboard: replays the REAL events of the four Flask processes as a
// space-time diagram, then drives a real Chandy-Lamport snapshot through the hub.
// Nothing here is simulated client-side: every dot, clock and arrow comes from
// the processes' own event logs via /api/dashboard.

const processes = ['hub', 'restaurant1', 'restaurant2', 'delivery1'];
const labels = { hub: 'Hub', restaurant1: 'Restaurant 1', restaurant2: 'Restaurant 2', delivery1: 'Delivery' };
const processIds = { hub: 'P1', restaurant1: 'P2', restaurant2: 'P3', delivery1: 'P4' };
const channelDirection = { r1_hub: 'restaurant1 → hub', r2_hub: 'restaurant2 → hub', hub_r1: 'hub → restaurant1', hub_r2: 'hub → restaurant2', hub_d1: 'hub → delivery1', d1_hub: 'delivery1 → hub' };
const messageNames = { order_ready: 'ORDER_READY', assign_delivery: 'ASSIGN_DELIVERY', order_confirmed: 'ORDER_CONFIRMED', picked_up: 'PICKED_UP', delivered: 'DELIVERED' };

const X0 = 26;        // px offset of the first event inside a lane track
const STEP = 104;     // px between consecutive events (global time axis)
const POLL_MS = 700;
const REVEAL_MS = 950;

const $ = (selector) => document.querySelector(selector);

const state = {
  phase: 'idle',            // idle | orders | cut | capturing | done
  running: false,
  paused: false,
  generation: 0,
  timers: new Set(),
  pollTimer: null,
  revealTimer: null,
  seen: {},                 // process -> number of log entries already queued
  pending: [],              // events fetched but not yet drawn
  revealed: 0,
  quietPolls: 0,
  clocks: {},
  pendingSends: {},         // channel -> [dot elements] (FIFO pairing of send/receive)
  cutPoints: {},            // process -> dot element of its recorded local state
  latest: null,
  countdown: null,
};

// --------------------------------------------------------------------------- //
// Small utilities
// --------------------------------------------------------------------------- //
function emptyClock() { return Object.fromEntries(processes.map((process) => [process, 0])); }
function clockArray(clock) { return `[${processes.map((process) => clock?.[process] ?? 0).join(',')}]`; }
function escapeHtml(value) { return String(value ?? '').replace(/[&<>'"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#039;', '"': '&quot;' }[c])); }
function shortOrder(orderId) { return orderId ? `#${String(orderId).replace(/^order-/, '')}` : ''; }

// Pausable timers: every animation delay goes through schedule() so Pause can freeze the replay.
function schedule(callback, delay) {
  const timer = { callback, remaining: delay, due: 0, id: null, paused: false };
  timer.arm = () => { timer.due = Date.now() + timer.remaining; timer.id = window.setTimeout(() => { state.timers.delete(timer); callback(); }, timer.remaining); };
  timer.arm(); state.timers.add(timer); return timer;
}
function clearTimers() { state.timers.forEach((timer) => window.clearTimeout(timer.id)); state.timers.clear(); }
function pauseTimers() { state.timers.forEach((timer) => { if (!timer.paused) { window.clearTimeout(timer.id); timer.remaining = Math.max(0, timer.due - Date.now()); timer.paused = true; } }); }
function resumeTimers() { state.timers.forEach((timer) => { if (timer.paused) { timer.paused = false; timer.arm(); } }); }

function setMessage(text) { $('#simulation-message').textContent = text; }
function setStep(text) { $('#current-step').textContent = text; }
function setSnapshotStatus(text) { $('#snapshot-status').textContent = text; }
function setInstruction(text) { $('#snapshot-instruction').textContent = text; }

// --------------------------------------------------------------------------- //
// Turning raw log entries into classroom narration
// --------------------------------------------------------------------------- //
function describe(event) {
  const who = labels[event.process];
  const d = event.detail || {};
  const order = shortOrder(d.order_id || d.payload?.order_id);
  const msg = messageNames[d.type] || d.type;
  switch (event.event) {
    case 'internal':
      if (d.action === 'order_created') return { label: `Create ${order}`, note: `${who} creates order ${order} locally — an internal event, so only its own clock component increments.` };
      if (d.action === 'assign_delivery_decision') return { label: `Assign ${order}`, note: `${who} decides (internally) to assign a delivery partner for ${order}.` };
      if (d.action === 'picked_up_locally') return { label: `Pick up ${order}`, note: `${who} picks up ${order} (internal event).` };
      if (d.action === 'delivered_locally') return { label: `Deliver ${order}`, note: `${who} hands over ${order} to the customer (internal event).` };
      return { label: d.action || 'Internal', note: `${who}: internal event.` };
    case 'send':
      return { label: `Send ${msg}`, note: `${who} → ${labels[d.to]}: ${msg} ${order}. Send event: own component +1, timestamp travels with the message.` };
    case 'receive':
      return { label: `Recv ${msg}`, note: `${who} receives ${msg} ${order} from ${labels[d.from]}. Receive event: clock = max(local, ${clockArray(d.vc_sent)}) then own component +1.` };
    case 'snapshot':
      return { label: 'Record state', note: d.trigger === 'initiator' ? `${who} initiates the snapshot: records its local state and sends a MARKER on every outgoing channel.` : `${who} received its first marker: records its local state now and forwards a MARKER on every outgoing channel.` };
    case 'marker-send':
      return { label: 'Send MARKER', note: `${who} → ${labels[d.to]}: MARKER on ${d.channel}. Markers use the same FIFO channel as data, so nothing sent earlier can arrive after them.` };
    case 'marker-receive':
      return d.first
        ? { label: 'First MARKER', note: `${who} gets its first MARKER on ${d.channel}: channel ${d.channel} is recorded as EMPTY.` }
        : { label: 'MARKER closes ch.', note: `${who} gets a MARKER on ${d.channel}: recording of that channel stops. Everything received on it since the local snapshot is “in transit”.` };
    default:
      return { label: event.event, note: `${who}: ${event.event}` };
  }
}
function cssKind(event) {
  if (event.event === 'snapshot' || event.event.startsWith('marker')) return `marker ${event.event}`;
  return event.event;
}

// --------------------------------------------------------------------------- //
// Drawing
// --------------------------------------------------------------------------- //
function laneTrack(process) { return $(`#lane-${process}`); }
function canvasWidthFor(x) { return x + STEP + 170; }
function ensureCanvas(x) {
  const timeline = $('#timeline');
  const needed = canvasWidthFor(x);
  const current = parseFloat(timeline.style.getPropertyValue('--canvas-width')) || 0;
  if (needed > current) timeline.style.setProperty('--canvas-width', `${needed}px`);
  const layer = $('#message-layer');
  const svgWidth = Math.max(timeline.scrollWidth, needed);
  layer.setAttribute('width', svgWidth); layer.setAttribute('height', timeline.clientHeight);
}
function dotCenter(dot) {
  const rect = dot.getBoundingClientRect(); const layer = $('#message-layer').getBoundingClientRect();
  return { x: rect.left + rect.width / 2 - layer.left, y: rect.top + rect.height / 2 - layer.top };
}
function drawArrow(fromDot, toDot, isMarker) {
  const a = dotCenter(fromDot); const b = dotCenter(toDot);
  const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  const dx = Math.max(24, (b.x - a.x) * 0.35);
  path.setAttribute('d', `M ${a.x} ${a.y} C ${a.x + dx} ${a.y}, ${b.x - dx} ${b.y}, ${b.x} ${b.y}`);
  path.setAttribute('class', `message-path active${isMarker ? ' marker-path' : ''}`);
  $('#message-layer').appendChild(path);
  schedule(() => path.classList.remove('active'), 1200);
  return path;
}
function drawCut() {
  const layer = $('#message-layer');
  layer.querySelectorAll('.cut-line').forEach((node) => node.remove());
  const points = processes.filter((process) => state.cutPoints[process]).map((process) => dotCenter(state.cutPoints[process]));
  if (points.length < 2) return;
  const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  path.setAttribute('d', points.map((p, i) => `${i ? 'L' : 'M'} ${p.x} ${p.y}`).join(' '));
  path.setAttribute('class', 'cut-line');
  layer.appendChild(path);
}
function redrawOverlay() {
  // Positions are DOM-derived, so on resize/scroll-width change we rebuild the cut line only;
  // arrows are static paths and stay valid because the canvas never reflows horizontally.
  ensureCanvas(X0 + state.revealed * STEP);
  drawCut();
}
function updateClockLabel(process) { const node = $(`[data-process="${process}"] .process-label small`); if (node) node.textContent = clockArray(state.clocks[process]); }

function reveal(event) {
  const index = state.revealed; state.revealed += 1;
  const x = X0 + index * STEP;
  ensureCanvas(x);
  document.querySelectorAll('.event-marker.current').forEach((node) => node.classList.remove('current'));
  const { label, note } = describe(event);
  const marker = document.createElement('div');
  marker.className = `event-marker ${cssKind(event)} active current`;
  marker.style.left = `${x}px`;
  marker.title = note;
  marker.innerHTML = `<i class="event-dot"></i><div class="event-card"><b>${escapeHtml(label)}</b><span>${escapeHtml(clockArray(event.vc))}</span></div>`;
  laneTrack(event.process).appendChild(marker);
  schedule(() => marker.classList.remove('active'), 800);
  const dot = marker.querySelector('.event-dot');

  state.clocks[event.process] = { ...emptyClock(), ...(event.vc || {}) };
  updateClockLabel(event.process);

  const channel = event.detail?.channel;
  if (event.event === 'send' || event.event === 'marker-send') {
    (state.pendingSends[channel] ||= []).push({ dot, marker: event.event === 'marker-send' });
  } else if (event.event === 'receive' || event.event === 'marker-receive') {
    const source = (state.pendingSends[channel] || []).shift();   // FIFO channel ⇒ oldest unmatched send
    if (source) drawArrow(source.dot, dot, event.event === 'marker-receive');
  }
  if (event.event === 'snapshot') { state.cutPoints[event.process] = dot; drawCut(); }

  $('#event-progress').textContent = `${state.revealed}/${state.revealed + state.pending.length}`;
  setStep(`${processIds[event.process]} ${labels[event.process]}: ${label}`);
  setMessage(note);
  const timeline = $('#timeline');
  timeline.scrollTo({ left: Math.max(0, x + 160 + 190 - timeline.clientWidth), behavior: 'smooth' });
}

// --------------------------------------------------------------------------- //
// Replay engine: poll the real processes, queue new events, reveal them one by one
// --------------------------------------------------------------------------- //
async function poll(generation) {
  if (generation !== state.generation) return;
  try {
    const response = await fetch('/api/dashboard', { cache: 'no-store' });
    const data = await response.json();
    if (generation !== state.generation) return;
    ingest(data);
  } catch (error) { /* keep polling; the next tick may succeed */ }
  if (generation === state.generation && state.running) state.pollTimer = window.setTimeout(() => poll(generation), POLL_MS);
}
function ingest(data) {
  state.latest = data;
  const online = data.processes.filter((process) => process.status === 'online').length;
  $('#process-count').textContent = `${online}/4`;
  let added = 0;
  data.processes.forEach((process) => {
    const log = process.log || []; const seen = state.seen[process.process] || 0;
    for (let i = seen; i < log.length; i += 1) { state.pending.push({ ...log[i], process: process.process }); added += 1; }
    state.seen[process.process] = log.length;
  });
  if (added) { state.pending.sort((a, b) => (a.wall_time || 0) - (b.wall_time || 0)); state.quietPolls = 0; kickReveal(); }
  else if (!state.pending.length) state.quietPolls += 1;
  $('#event-progress').textContent = `${state.revealed}/${state.revealed + state.pending.length}`;
  if (!state.paused) {
    renderConcurrency(data.concurrency);
    if (state.phase === 'capturing' || state.phase === 'done') renderSnapshot(data);
  }
  if (online < 4 && state.phase === 'orders') setMessage(`Only ${online}/4 processes are reachable — start all four (hub, restaurant1, restaurant2, delivery1).`);
  checkPhase();
}
function kickReveal() {
  if (state.revealTimer || !state.running || state.paused || !state.pending.length) return;
  const backlog = state.pending.length;
  const delay = Math.max(320, REVEAL_MS - backlog * 60);   // catch up faster when many events are queued
  state.revealTimer = schedule(() => { state.revealTimer = null; if (!state.running || state.paused) return; const event = state.pending.shift(); if (event) reveal(event); kickReveal(); if (!state.pending.length) checkPhase(); }, delay);
}
function quiescent() { return state.pending.length === 0 && state.quietPolls >= 3 && state.revealed > 0; }
function checkPhase() {
  if (state.phase === 'orders' && quiescent()) reachSnapshotPoint();
  if (state.phase === 'capturing' && state.latest?.snapshot?.complete && quiescent()) finishSnapshot();
}

function reachSnapshotPoint() {
  state.phase = 'cut';
  $('#snapshot-button').disabled = false;
  setSnapshotStatus('Ready');
  setStep('Snapshot point reached');
  setMessage('Both orders are confirmed and assigned. The two order creations are CONCURRENT — neither vector clock dominates the other.');
  setInstruction('Snapshot point reached. Capturing will slow the delivery1 → hub channel, fire PICKED_UP/DELIVERED, and let the hub initiate the snapshot while those messages are still travelling.');
}
function finishSnapshot() {
  state.phase = 'done';
  setSnapshotStatus('Complete');
  setStep('Demo complete');
  setMessage('Snapshot complete. Messages that cross the purple cut line were in transit — they are recorded in the receiver’s channel state, not in any process state.');
  setInstruction('SNAPSHOT CAPTURED. Process states, channel states and the consistency check are recorded below.');
  $('#pause-demo').disabled = true;
}

// --------------------------------------------------------------------------- //
// Snapshot + concurrency panels (rendered from the real /api/dashboard payload)
// --------------------------------------------------------------------------- //
function summarizeState(localState) {
  const orders = Object.entries(localState?.orders || {});
  return orders.length ? orders.map(([order, value]) => `${shortOrder(order)}: ${value.status}`).join(', ') : 'No orders';
}
function renderSnapshot(data) {
  const snapshots = data.snapshot?.processes || {};
  const entries = processes.map((process) => [process, snapshots[process]]).filter(([, value]) => value && value.recording);
  const recorded = entries.filter(([, value]) => value.complete).length;
  const closedChannels = entries.reduce((total, [, value]) => total + (value.markers_received || []).length, 0);
  const transit = entries.reduce((total, [, value]) => total + Object.values(value.channel_states || {}).reduce((sum, messages) => sum + messages.length, 0), 0);
  $('#processes-recorded').textContent = `${recorded}/4`;
  $('#channels-recorded').textContent = `${closedChannels}/6`;
  $('#messages-transit').textContent = String(transit);
  $('#result-status').textContent = data.snapshot?.complete ? 'COMPLETE' : 'RECORDING';

  $('#process-state-table').innerHTML = entries.length
    ? entries.map(([process, value]) => `<tr><td><b>${processIds[process]} ${labels[process]}</b></td><td>${clockArray(value.local_state?.vc)}</td><td>${escapeHtml(summarizeState(value.local_state))}</td><td class="${value.complete ? 'status-recorded' : 'status-open'}">${value.complete ? '✓ Recorded' : 'Recording…'}</td></tr>`).join('')
    : '<tr><td colspan="4" class="empty">Waiting for the first marker to arrive.</td></tr>';

  const channelRows = entries.flatMap(([process, value]) => Object.entries(value.channel_states || {}).map(([channel, messages]) => {
    const closed = (value.markers_received || []).includes(channel);
    const content = messages.length ? messages.map((message) => `${messageNames[message.type] || message.type} ${shortOrder(message.payload?.order_id)}`).join(', ') : '∅ empty';
    return `<tr><td>${escapeHtml(channel)}</td><td>${escapeHtml(channelDirection[channel] || `→ ${processIds[process]}`)}</td><td class="${messages.length ? 'in-transit' : ''}">${escapeHtml(content)}</td><td class="${closed ? 'status-recorded' : 'status-open'}">${closed ? '✓ Recorded' : 'Recording…'}</td></tr>`;
  }));
  $('#channel-state-table').innerHTML = channelRows.length ? channelRows.join('') : '<tr><td colspan="4" class="empty">Channel recording will appear here.</td></tr>';

  const consistency = data.snapshot?.consistency;
  const box = $('#consistency-result');
  if (consistency?.verified) {
    const checks = consistency.checks.map((check) => `<li class="${check.ok ? 'ok' : 'bad'}">${escapeHtml(check.channel)}: sent ${check.sent} = received ${check.received} + in transit ${check.in_transit} ${check.ok ? '✓' : '✗'}</li>`).join('');
    box.classList.toggle('inconsistent', !consistency.consistent);
    box.innerHTML = consistency.consistent
      ? `<strong>✓ CONSISTENT GLOBAL SNAPSHOT</strong><span>For every channel, messages sent before the sender’s cut equal messages received before the receiver’s cut plus messages recorded in the channel — nothing lost, nothing duplicated.</span><ul>${checks}</ul>`
      : `<strong>✗ INCONSISTENT CUT</strong><span>At least one channel’s send/receive counts do not balance.</span><ul>${checks}</ul>`;
  } else {
    box.classList.remove('inconsistent');
    box.innerHTML = '<strong>Verifying…</strong><span>The consistency check runs once all four processes have received markers on every incoming channel.</span>';
  }
}
function renderConcurrency(pair) {
  const node = $('#concurrency-note');
  if (!pair) { node.hidden = true; return; }
  const name = (event) => `${labels[event.process]} “${describe(event).label}” ${clockArray(event.vc)}`;
  node.hidden = false;
  node.innerHTML = `<b>Concurrent events (vector clocks incomparable):</b> ${escapeHtml(name(pair.first))} <b>∥</b> ${escapeHtml(name(pair.second))}`;
}

// --------------------------------------------------------------------------- //
// Controls
// --------------------------------------------------------------------------- //
function resetVisuals() {
  clearTimers();
  window.clearTimeout(state.pollTimer);
  Object.assign(state, { phase: 'idle', running: false, paused: false, pollTimer: null, revealTimer: null, seen: {}, pending: [], revealed: 0, quietPolls: 0, clocks: Object.fromEntries(processes.map((process) => [process, emptyClock()])), pendingSends: {}, cutPoints: {}, latest: null, countdown: null });
  state.generation += 1;
  document.querySelectorAll('.lane-track').forEach((track) => { track.innerHTML = ''; });
  $('#message-layer').querySelectorAll('path').forEach((path) => path.remove());
  const timeline = $('#timeline'); timeline.style.removeProperty('--canvas-width'); timeline.scrollTo({ left: 0 }); timeline.classList.remove('paused');
  $('#start-demo').disabled = false; $('#snapshot-button').disabled = true; $('#pause-demo').disabled = true; $('#pause-demo').innerHTML = 'Ⅱ <span>Pause</span>';
  setMessage('Press START: both restaurants place an order at the same time and the hub assigns delivery — every dot is a real event from a real process.');
  setInstruction('The replay pauses once the orders settle so the class can inspect the clocks before capturing the global state.');
  setSnapshotStatus('Not Taken'); setStep('Waiting for START');
  $('#event-progress').textContent = '0/0';
  $('#snapshot-results').hidden = true; $('#snapshot-modal').hidden = true; $('#concurrency-note').hidden = true;
  $('#consistency-result').classList.remove('inconsistent');
  $('#consistency-result').innerHTML = '<strong>Snapshot not captured</strong><span>Process and channel states will be checked after marker propagation.</span>';
  document.querySelectorAll('.process-label small').forEach((node) => { node.textContent = '[0,0,0,0]'; });
}

async function start() {
  if (state.phase !== 'idle') return;
  const generation = state.generation;
  state.phase = 'orders'; state.running = true;
  $('#start-demo').disabled = true; $('#pause-demo').disabled = false;
  setMessage('Resetting the four processes and placing two orders concurrently…'); setStep('Starting');
  try {
    const response = await fetch('/api/scenario/start', { method: 'POST' });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.error || `HTTP ${response.status}`);
  } catch (error) {
    if (generation !== state.generation) return;
    state.running = false; state.phase = 'idle'; $('#start-demo').disabled = false; $('#pause-demo').disabled = true;
    setMessage(`Could not start the scenario: ${error.message}`); setStep('Error');
    return;
  }
  if (generation === state.generation) poll(generation);
}

function togglePause() {
  state.paused = !state.paused;
  $('#timeline').classList.toggle('paused', state.paused);
  if (state.paused) pauseTimers(); else resumeTimers();
  $('#pause-demo').innerHTML = state.paused ? '▶ <span>Resume</span>' : 'Ⅱ <span>Pause</span>';
  if (state.paused) setMessage('Replay paused. Compare the vector clocks on the lanes — a receive always ends up strictly greater than its send.');
  else { setMessage('Replay resumed.'); kickReveal(); }
}

function beginSnapshot() {
  if (state.phase !== 'cut' || state.countdown) return;
  const generation = state.generation;
  let remaining = 5;
  $('#snapshot-button').disabled = true; $('#snapshot-modal').hidden = false; $('#countdown-value').textContent = String(remaining);
  setSnapshotStatus('Countdown'); setInstruction('Taking the global snapshot in a moment…');
  const tick = async () => {
    if (generation !== state.generation) return;
    remaining -= 1; $('#countdown-value').textContent = String(Math.max(0, remaining));
    if (remaining > 0) { state.countdown = schedule(tick, 1000); return; }
    state.countdown = null; $('#snapshot-modal').hidden = true;
    state.phase = 'capturing'; state.quietPolls = 0;
    setSnapshotStatus('Capturing'); setStep('Snapshot in progress');
    setInstruction('Hub recorded its state and sent markers. PICKED_UP/DELIVERED are still travelling on delivery1 → hub — watch them cross the cut.');
    $('#snapshot-results').hidden = false;
    try {
      const response = await fetch('/api/scenario/snapshot', { method: 'POST' });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
    } catch (error) { if (generation === state.generation) setInstruction(`Snapshot request failed: ${error.message}`); }
  };
  state.countdown = schedule(tick, 1000);
}

$('#start-demo').addEventListener('click', start);
$('#pause-demo').addEventListener('click', togglePause);
$('#snapshot-button').addEventListener('click', beginSnapshot);
$('#reset-demo').addEventListener('click', async () => { resetVisuals(); try { await fetch('/api/reset', { method: 'POST' }); } catch (error) { /* local reset still applies */ } });
window.addEventListener('resize', redrawOverlay);
resetVisuals();
// One-shot probe so the status strip shows which processes are reachable before START.
(async () => {
  try {
    const data = await (await fetch('/api/dashboard', { cache: 'no-store' })).json();
    const online = data.processes.filter((process) => process.status === 'online').length;
    $('#process-count').textContent = `${online}/4`;
    if (online < 4) setMessage(`Only ${online}/4 processes are reachable — start hub, restaurant1, restaurant2 and delivery1, then press START.`);
  } catch (error) { $('#process-count').textContent = '?/4'; }
})();
