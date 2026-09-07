const processes = ['hub', 'restaurant1', 'restaurant2', 'delivery1'];
const labels = { hub: 'Hub', restaurant1: 'Restaurant 1', restaurant2: 'Restaurant 2', delivery1: 'Delivery' };
const processIds = { hub: 'P1', restaurant1: 'P2', restaurant2: 'P3', delivery1: 'P4' };
const incomingChannels = { r1_hub: 'restaurant1 -> hub', r2_hub: 'restaurant2 -> hub', hub_r1: 'hub -> restaurant1', hub_r2: 'hub -> restaurant2', hub_d1: 'hub -> delivery1', d1_hub: 'delivery1 -> hub' };
const state = { clocks: {}, events: [], eventIndex: 0, running: false, paused: false, snapshotPoint: false, countdown: null, countdownValue: 5, timers: new Set(), currentMarker: null, generation: 0, establishedChannels: new Set(), connections: [] };

function emptyClock() { return Object.fromEntries(processes.map((process) => [process, 0])); }
function emptyClocks() { return Object.fromEntries(processes.map((process) => [process, emptyClock()])); }
function clockArray(clock) { return `[${processes.map((process) => clock[process] ?? 0).join(',')}]`; }
function escapeHtml(value) { return String(value).replace(/[&<>'"]/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#039;', '"': '&quot;' }[character])); }
function schedule(callback, delay) {
  const timer = { callback, remaining: delay, due: Date.now() + delay, id: null, paused: false };
  const arm = () => { timer.due = Date.now() + timer.remaining; timer.id = window.setTimeout(() => { state.timers.delete(timer); callback(); }, timer.remaining); };
  timer.arm = arm; arm(); state.timers.add(timer); return timer;
}
function clearTimers() { state.timers.forEach((timer) => window.clearTimeout(timer.id)); state.timers.clear(); }
function pauseTimers() { state.timers.forEach((timer) => { if (!timer.paused) { window.clearTimeout(timer.id); timer.remaining = Math.max(0, timer.due - Date.now()); timer.paused = true; } }); }
function resumeTimers() { state.timers.forEach((timer) => { if (timer.paused) { timer.paused = false; timer.arm(); } }); }

function makeEvents() {
  return [
    { process: 'hub', kind: 'internal', label: 'Creates Order #101', note: 'Hub creates Order #101 locally.' },
    { process: 'restaurant1', kind: 'internal', label: 'Restaurant 1 Ready', note: 'Restaurant 1 is ready to receive an order.' },
    { process: 'restaurant2', kind: 'internal', label: 'Restaurant 2 Ready', note: 'Restaurant 2 is ready to receive an order.' },
    { process: 'delivery1', kind: 'internal', label: 'Delivery Service Ready', note: 'Delivery service is ready for an assignment.' },
    { process: 'hub', kind: 'send', to: 'restaurant1', message: 'Order #101', channel: 'hub_r1', label: 'Sends Order #101', note: 'Hub sends Order #101 to Restaurant 1.' },
    { process: 'restaurant1', kind: 'receive', from: 'hub', channel: 'hub_r1', label: 'Receives Order #101', note: 'Restaurant 1 receives the Hub message.' },
    { process: 'restaurant1', kind: 'internal', label: 'Start Preparing Order #101', note: 'Restaurant 1 starts preparing the received order.' },
    { process: 'hub', kind: 'send', to: 'restaurant2', message: 'Order #102', channel: 'hub_r2', label: 'Sends Order #102', note: 'Hub sends Order #102 to Restaurant 2.' },
    { process: 'restaurant2', kind: 'receive', from: 'hub', channel: 'hub_r2', label: 'Receives Order #102', note: 'Restaurant 2 receives the Hub message.' },
    { process: 'restaurant2', kind: 'internal', label: 'Start Preparing Order #102', note: 'Restaurant 2 starts preparing the received order.' },
    { process: 'hub', kind: 'send', to: 'delivery1', message: 'Assignment #101', channel: 'hub_d1', label: 'Sends to Delivery', note: 'Hub assigns Order #101 to Delivery.' },
    { process: 'delivery1', kind: 'receive', from: 'hub', channel: 'hub_d1', label: 'Receives Order #101', note: 'Delivery receives the assignment.' },
    { process: 'hub', kind: 'marker', label: 'SNAPSHOT CUT', note: 'A meaningful cut is selected before the ready confirmations arrive.' },
    { process: 'restaurant1', kind: 'send', to: 'hub', message: 'Order Ready #101', channel: 'r1_hub', label: 'Sends Order Ready', note: 'Restaurant 1 confirms the order is ready.' },
    { process: 'hub', kind: 'receive', from: 'restaurant1', channel: 'r1_hub', label: 'Receives Ready #101', note: 'Hub receives Restaurant 1 confirmation.' },
    { process: 'restaurant2', kind: 'send', to: 'hub', message: 'Order Ready #102', channel: 'r2_hub', label: 'Sends Order Ready', note: 'Restaurant 2 confirms independently.' },
    { process: 'hub', kind: 'receive', from: 'restaurant2', channel: 'r2_hub', label: 'Receives Ready #102', note: 'Hub receives Restaurant 2 confirmation.' },
  ];
}

function resetVisuals() {
  clearTimers();
  state.generation += 1; state.clocks = emptyClocks(); state.events = makeEvents(); state.eventIndex = 0; state.running = false; state.paused = false; state.snapshotPoint = false; state.countdown = null; state.countdownValue = 5; state.currentMarker = null; state.establishedChannels = new Set(); state.connections = [];
  document.querySelectorAll('.lane-track').forEach((track) => { track.innerHTML = ''; });
  const layer = document.querySelector('#message-layer');
  layer.querySelectorAll('.message-path, .event-channel').forEach((path) => path.remove());
  document.querySelector('#snapshot-boundary').classList.remove('visible');
  document.querySelector('#start-demo').disabled = false;
  document.querySelector('#snapshot-button').disabled = true;
  document.querySelector('#pause-demo').disabled = true;
  document.querySelector('#simulation-message').textContent = 'Press START to initialize each process with its first local event.';
  document.querySelector('#snapshot-instruction').textContent = 'The simulation will pause at a meaningful point so the class can inspect the cut before capturing it.';
  document.querySelector('#snapshot-status').textContent = 'Not Taken';
  document.querySelector('#current-step').textContent = 'Waiting for START';
  document.querySelector('#event-progress').textContent = `0/${state.events.length}`;
  document.querySelector('#snapshot-results').hidden = true;
  document.querySelector('#snapshot-modal').hidden = true;
  document.querySelector('#consistency-result').innerHTML = '<strong>Snapshot not captured</strong><span>Process and channel states will be checked after marker propagation.</span>';
  document.querySelectorAll('.process-label small').forEach((node) => { node.textContent = '[0,0,0,0]'; });
}

function updateClockLabel(process) { const node = document.querySelector(`[data-process="${process}"] .process-label small`); if (node) node.textContent = clockArray(state.clocks[process]); }
function tick(process) { state.clocks[process][process] += 1; }
function receive(process, incoming) { processes.forEach((name) => { state.clocks[process][name] = Math.max(state.clocks[process][name], incoming[name] || 0); }); tick(process); }
function eventPosition(index) { return 5 + (index / Math.max(1, state.events.length - 1)) * 90; }

function addEventMarker(event, index, clock) {
  const track = document.querySelector(`#lane-${event.process}`);
  if (state.currentMarker) state.currentMarker.classList.remove('current');
  const laneEventIndex = track.querySelectorAll('.event-marker').length;
  const marker = document.createElement('div'); marker.className = `event-marker ${event.kind} level-${index % 3} clock-level-${laneEventIndex % 3}${event.pending ? ' pending-event' : ' current'}`; marker.style.left = `${eventPosition(index)}%`;
  marker.innerHTML = `<span class="event-clock">${escapeHtml(clockArray(clock))}</span><i class="event-dot"></i><div class="event-card"><b>${escapeHtml(event.label)}</b><span>${escapeHtml(event.kind)}</span></div>`;
  marker.title = event.note; track.appendChild(marker); event.marker = marker; state.currentMarker = marker;
  return marker;
}

function showPendingReturnEvents() {
  const pendingEvents = state.events.slice(state.eventIndex).filter((event) => event.channel === 'r1_hub' || event.channel === 'r2_hub');
  pendingEvents.forEach((event) => {
    event.pending = true;
    addEventMarker(event, state.events.indexOf(event), emptyClock());
  });
  const pendingSends = pendingEvents.filter((event) => event.kind === 'send');
  pendingSends.forEach((send) => {
    const receive = pendingEvents.find((event) => event.kind === 'receive' && event.channel === send.channel);
    if (receive) state.connections.push({ send, receive, channel: send.channel, pending: true });
  });
  drawPermanentChannels();
}

function drawPermanentChannels() {
  const timeline = document.querySelector('#timeline'); const bounds = timeline.getBoundingClientRect(); const layer = document.querySelector('#message-layer');
  layer.querySelectorAll('.event-channel').forEach((path) => path.remove());
  const channelColors = { hub_r1: '#287ff2', r1_hub: '#26ae79', hub_r2: '#ed9d20', r2_hub: '#e48718', hub_d1: '#6749db', d1_hub: '#d14f8a' };
  state.connections.forEach(({ send, receive, channel, pending }) => {
    if (!send?.marker || !receive?.marker) return;
    const source = send.marker.querySelector('.event-dot').getBoundingClientRect();
    const target = receive.marker.querySelector('.event-dot').getBoundingClientRect();
    const x = source.left + source.width / 2 - bounds.left; const targetX = target.left + target.width / 2 - bounds.left;
    const y = source.top + source.height / 2 - bounds.top; const targetY = target.top + target.height / 2 - bounds.top;
    const bend = Math.max(28, Math.abs(targetY - y) * .35); const direction = targetY > y ? 1 : -1; const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', `M ${x} ${y} C ${x + bend} ${y + direction * bend}, ${targetX - bend} ${targetY - direction * bend}, ${targetX} ${targetY}`); path.setAttribute('class', `event-channel${pending ? ' pending-channel' : ''}`); path.setAttribute('data-channel', channel); path.setAttribute('stroke', channelColors[channel]); path.setAttribute('marker-end', 'url(#channel-arrow)'); layer.appendChild(path);
  });
  layer.setAttribute('viewBox', `0 0 ${bounds.width} ${bounds.height}`);
}

function drawMessage(event) {
  if (event.kind === 'send') return;
  if (event.kind === 'receive') {
    const send = state.events.find((candidate) => candidate.kind === 'send' && candidate.channel === event.channel && candidate.marker);
    if (send) state.connections.push({ send, receive: event, channel: event.channel });
    drawPermanentChannels();
  }
}

function advance() {
  if (!state.running || state.paused || state.eventIndex >= state.events.length) return;
  const event = state.events[state.eventIndex];
  if (event.kind === 'internal') tick(event.process);
  if (event.kind === 'send') { tick(event.process); event.sentClock = { ...state.clocks[event.process] }; }
  if (event.kind === 'receive') { const senderEvent = [...state.events].reverse().find((item) => item.kind === 'send' && item.channel === event.channel && item.sentClock); receive(event.process, senderEvent?.sentClock || emptyClock()); }
  if (event.kind === 'marker') { document.querySelector('#snapshot-boundary').classList.add('visible'); state.snapshotPoint = true; state.running = false; document.querySelector('#pause-demo').disabled = false; document.querySelector('#snapshot-button').disabled = false; document.querySelector('#simulation-message').textContent = 'SNAPSHOT POINT REACHED. Explain the cut, then capture the global state.'; document.querySelector('#snapshot-instruction').textContent = 'Snapshot point reached. Ready to capture the global state using Chandy-Lamport.'; document.querySelector('#current-step').textContent = 'Snapshot point reached'; ['restaurant1', 'restaurant2', 'delivery1'].forEach((target, pathIndex) => schedule(() => drawMessage({ ...event, to: target, channel: 'marker', kind: 'marker' }, state.eventIndex + pathIndex), pathIndex * 180)); }
  addEventMarker(event, state.eventIndex, { ...state.clocks[event.process] });
  if (event.kind === 'marker') showPendingReturnEvents();
  drawMessage(event);
  updateClockLabel(event.process); state.eventIndex += 1; document.querySelector('#event-progress').textContent = `${state.eventIndex}/${state.events.length}`; document.querySelector('#current-step').textContent = event.label; document.querySelector('#simulation-message').textContent = event.note;
  if (event.kind === 'marker') document.querySelector('#simulation-message').textContent = 'SNAPSHOT POINT REACHED. Explain the cut, then capture the global state.';
  if (!state.snapshotPoint) schedule(advance, 1050);
}

async function start() { if (state.snapshotPoint) return; const generation = state.generation; state.running = true; state.paused = false; document.querySelector('#start-demo').disabled = true; document.querySelector('#pause-demo').disabled = false; document.querySelector('#simulation-message').textContent = 'Starting four real distributed processes...'; try { const resetResponse = await fetch('/api/reset', { method: 'POST' }); if (!resetResponse.ok) throw new Error('Could not reset all processes.'); const demoResponse = await fetch('/api/demo', { method: 'POST' }); if (!demoResponse.ok) throw new Error('Could not start the distributed workflow.'); } catch (error) { document.querySelector('#simulation-message').textContent = error.message; } if (generation === state.generation) advance(); }
function togglePause() { state.paused = !state.paused; document.querySelector('#timeline').classList.toggle('paused', state.paused); if (state.paused) pauseTimers(); else { resumeTimers(); } document.querySelector('#pause-demo').innerHTML = state.paused ? '▶ <span>Resume</span>' : 'Ⅱ <span>Pause</span>'; document.querySelector('#simulation-message').textContent = state.paused ? 'Simulation paused. Explain the current vector clocks.' : 'Simulation resumed.'; if (!state.paused && state.running && !state.timers.size) advance(); }

function renderSnapshot(data) {
  const snapshots = data.snapshot?.processes || {}; const entries = Object.entries(snapshots).filter(([, value]) => value);
  const complete = entries.filter(([, value]) => value.complete).length; const channels = entries.flatMap(([, value]) => Object.values(value.channel_states || {})); const transit = channels.reduce((total, messages) => total + messages.length, 0);
  document.querySelector('#processes-recorded').textContent = `${complete}/4`; document.querySelector('#channels-recorded').textContent = `${entries.reduce((total, [, value]) => total + Object.keys(value.channel_states || {}).length, 0)}/6`; document.querySelector('#messages-transit').textContent = transit;
  document.querySelector('#result-status').textContent = data.snapshot?.complete ? 'COMPLETE' : 'RECORDING';
  document.querySelector('#process-state-table').innerHTML = entries.length ? entries.map(([process, value]) => `<tr><td><b>${processIds[process]} ${labels[process]}</b></td><td>${clockArray(value.local_state?.vc || {})}</td><td>${escapeHtml(summarizeState(value.local_state))}</td><td class="${value.complete ? 'status-recorded' : 'status-open'}">${value.complete ? '✓ Recorded' : 'Recording...'}</td></tr>`).join('') : '<tr><td colspan="4" class="empty">Waiting for process states.</td></tr>';
  const channelRows = Object.entries(snapshots).flatMap(([process, value]) => Object.entries(value?.channel_states || {}).map(([channel, messages]) => `<tr><td>${escapeHtml(channel)}</td><td>${escapeHtml(incomingChannels[channel] || `to ${processIds[process]}`)}</td><td>${messages.length ? messages.map((message) => escapeHtml(message.type)).join(', ') : '—'}</td><td class="status-recorded">✓ Recorded</td></tr>`));
  document.querySelector('#channel-state-table').innerHTML = channelRows.length ? channelRows.join('') : '<tr><td colspan="4" class="empty">Waiting for channel states.</td></tr>';
  if (data.snapshot?.complete) document.querySelector('#consistency-result').innerHTML = '<strong>✓ CONSISTENT GLOBAL SNAPSHOT</strong><span>No recorded receive depends on a send outside the captured process or channel state.</span>';
}
function summarizeState(localState) { const orders = Object.keys(localState?.orders || {}); return orders.length ? orders.map((order) => `${order}: ${localState.orders[order].status}`).join(', ') : 'No active orders'; }

async function beginSnapshot() {
  if (!state.snapshotPoint || state.countdown) return; state.countdownValue = 5; state.paused = false; document.querySelector('#pause-demo').disabled = false; document.querySelector('#pause-demo').innerHTML = 'Ⅱ <span>Pause</span>'; document.querySelector('#snapshot-button').disabled = true; document.querySelector('#snapshot-modal').hidden = false; document.querySelector('#snapshot-status').textContent = 'Countdown'; document.querySelector('#snapshot-instruction').textContent = 'Taking global snapshot at this instance...'; document.querySelector('#countdown-value').textContent = '5';
  const generation = state.generation;
  const countdownTick = async () => { if (generation !== state.generation) return; state.countdownValue -= 1; document.querySelector('#countdown-value').textContent = String(Math.max(0, state.countdownValue)); if (state.countdownValue > 0) { state.countdown = schedule(countdownTick, 1000); return; } state.countdown = null; document.querySelector('#snapshot-modal').hidden = true; document.querySelector('#snapshot-status').textContent = 'Capturing'; document.querySelector('#snapshot-instruction').textContent = 'Chandy-Lamport markers are travelling through the channels...'; try { await fetch('/api/snapshot', { method: 'POST' }); } catch (error) { if (generation === state.generation) document.querySelector('#snapshot-instruction').textContent = error.message; } if (generation !== state.generation) return; document.querySelector('#snapshot-results').hidden = false; pollSnapshot(generation); };
  state.countdown = schedule(countdownTick, 1000);
}
async function pollSnapshot(generation) { if (generation !== state.generation) return; try { const response = await fetch('/api/dashboard', { cache: 'no-store' }); const data = await response.json(); if (generation !== state.generation) return; renderSnapshot(data); if (!data.snapshot?.complete) schedule(() => pollSnapshot(generation), 1800); else { document.querySelector('#snapshot-status').textContent = 'Complete'; document.querySelector('#snapshot-instruction').textContent = 'SNAPSHOT CAPTURED. Process and channel states are recorded below.'; } } catch (error) { if (generation === state.generation) schedule(() => pollSnapshot(generation), 2000); } }

document.querySelector('#start-demo').addEventListener('click', start);
document.querySelector('#pause-demo').addEventListener('click', togglePause);
document.querySelector('#reset-demo').addEventListener('click', async () => { if (state.countdown) window.clearInterval(state.countdown); resetVisuals(); try { await fetch('/api/reset', { method: 'POST' }); } catch (error) { /* local reset remains available */ } });
document.querySelector('#snapshot-button').addEventListener('click', beginSnapshot);
resetVisuals();
window.addEventListener('resize', drawPermanentChannels);
