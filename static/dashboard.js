const refreshToggle = document.querySelector('#refresh-toggle');
const refreshRange = document.querySelector('#refresh-range');
const refreshValue = document.querySelector('#refresh-value');
const actionStatus = document.querySelector('#action-status');
let refreshTimer;

const labels = {
  restaurant1: 'Restaurant 1', restaurant2: 'Restaurant 2', delivery1: 'Delivery 1', hub: 'Hub'
};

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#039;', '"': '&quot;' }[character]));
}

function clockValues(clock) {
  return ['hub', 'restaurant1', 'restaurant2', 'delivery1'].map((key) => clock?.[key] ?? 0);
}

function renderTopology(processes) {
  const byName = Object.fromEntries(processes.map((item) => [item.process, item]));
  document.querySelectorAll('.node').forEach((node) => {
    const name = node.classList.contains('hub') ? 'hub' : node.classList.contains('restaurant-one') ? 'restaurant1' : node.classList.contains('restaurant-two') ? 'restaurant2' : 'delivery1';
    const item = byName[name];
    const state = item?.status === 'online' ? 'ONLINE' : 'OFFLINE';
    const statusDot = node.querySelector('.status-dot');
    if (statusDot) statusDot.classList.toggle('online', state === 'ONLINE');
    node.classList.toggle('online-node', state === 'ONLINE');
  });
}

function renderClocks(processes) {
  const table = document.querySelector('#clock-table');
  table.innerHTML = processes.map((item) => `<tr><td>${escapeHtml(labels[item.process] || item.process)}</td>${clockValues(item.vector_clock).map((value) => `<td>${value}</td>`).join('')}</tr>`).join('') || '<tr><td colspan="5" class="empty">No process data yet</td></tr>';
}

function renderEvents(events) {
  const table = document.querySelector('#event-log-table');
  table.innerHTML = events.length ? events.map((event) => {
    const detail = typeof event.detail === 'object' ? event.detail : { value: event.detail };
    const description = detail.type ? `${detail.type} · ${detail.from || detail.channel || ''}` : detail.action || detail.value || JSON.stringify(detail);
    const time = event.wall_time ? new Date(event.wall_time * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '--:--:--';
    return `<tr class="event-row" data-process="${escapeHtml(event.process)}"><td>${escapeHtml(labels[event.process] || event.process)}</td><td><b class="event-kind">${escapeHtml(event.event)}</b></td><td>${escapeHtml(description)}</td><td class="vector-value">${escapeHtml(JSON.stringify(event.vc || {}))}</td><td>${time}</td></tr>`;
  }).join('') : '<tr><td colspan="5" class="empty">Waiting for events...</td></tr>';
}

function renderSnapshotTable(data) {
  const table = document.querySelector('#snapshot-table');
  const rows = Object.entries(data.snapshot?.processes || {}).filter(([, snapshot]) => snapshot).map(([process, snapshot]) => {
    const vectorClock = snapshot.local_state?.vc || {};
    return `<tr><td>${escapeHtml(labels[process] || process)}</td><td>${escapeHtml(summarizeLocalState(snapshot.local_state))}</td><td>${escapeHtml(JSON.stringify(vectorClock))}</td><td class="${snapshot.complete ? 'online' : 'offline-text'}">${snapshot.complete ? 'COMPLETE' : 'OPEN'}</td></tr>`;
  });
  table.innerHTML = rows.length ? rows.join('') : '<tr><td colspan="4" class="empty">Run a snapshot to record global state.</td></tr>';
}

function summarizeLocalState(localState) {
  const orders = localState?.orders || {};
  const orderIds = Object.keys(orders);
  if (!orderIds.length) return 'No active orders';
  const statuses = orderIds.reduce((counts, orderId) => {
    const status = orders[orderId]?.status || 'unknown';
    counts[status] = (counts[status] || 0) + 1;
    return counts;
  }, {});
  return `${orderIds.length} order${orderIds.length === 1 ? '' : 's'} · ${Object.entries(statuses).map(([status, count]) => `${count} ${status}`).join(', ')}`;
}

function renderChannels(data) {
  const list = document.querySelector('#channel-list');
  const snapshots = data.snapshot?.processes || {};
  const processStates = Object.entries(snapshots).filter(([, snapshot]) => snapshot).map(([process, snapshot]) => ({
    channel: `${labels[process] || process} local state`,
    type: summarizeLocalState(snapshot.local_state),
  }));
  const messages = Object.entries(snapshots).flatMap(([process, snapshot]) => Object.entries(snapshot?.channel_states || {}).flatMap(([channel, items]) => items.map((item) => ({ channel: `${channel} -> ${process}`, type: item.type }))));
  document.querySelector('#channel-count').textContent = `${data.channels.length} channels`;
  const rows = [...processStates, ...messages];
  list.innerHTML = rows.length ? rows.map((item) => `<div class="channel-row"><span><b>${escapeHtml(item.channel)}</b><br><small>${escapeHtml(item.type)}</small></span><span class="online">RECORDED</span></div>`).join('') : '<p class="empty">No snapshot recorded yet.</p>';
}

async function loadDashboard() {
  try {
    const response = await fetch('/api/dashboard', { cache: 'no-store' });
    if (!response.ok) throw new Error(`Dashboard returned ${response.status}`);
    const data = await response.json();
    const online = data.processes.filter((item) => item.status === 'online').length;
    document.querySelector('#process-count').textContent = `${online}/4`;
    document.querySelector('#order-count').textContent = Object.keys(data.orders).length;
    document.querySelector('#event-count').textContent = data.events.length;
    document.querySelector('#snapshot-status').textContent = data.snapshot?.complete ? 'READY' : data.snapshot?.recording ? 'CAPTURING' : 'IDLE';
    const snapshotProcesses = Object.values(data.snapshot?.processes || {});
    const completeCount = snapshotProcesses.filter((snapshot) => snapshot?.complete).length;
    const channelMessageCount = snapshotProcesses.flatMap((snapshot) => Object.values(snapshot?.channel_states || {}).flat()).length;
    document.querySelector('#snapshot-detail').textContent = data.snapshot?.complete ? `Consistent cut · ${completeCount}/4 processes · ${channelMessageCount} in-transit messages` : `Chandy-Lamport recording · ${completeCount}/4 processes complete`;
    document.querySelector('#concurrency-detail').textContent = data.concurrency ? `Concurrent events detected: ${data.concurrency.first.process} || ${data.concurrency.second.process}` : 'No concurrent pair detected yet.';
    const eventCounts = data.events.reduce((counts, event) => { counts[event.event] = (counts[event.event] || 0) + 1; return counts; }, {});
    document.querySelector('#event-summary').textContent = `Event evidence: internal ${eventCounts.internal || 0} · send ${eventCounts.send || 0} · receive ${eventCounts.receive || 0}`;
    const health = document.querySelector('#health-pill');
    health.classList.toggle('offline', online !== 4);
    health.innerHTML = `<span></span>${online}/4 PROCESSES ${online === 4 ? 'HEALTHY' : 'AVAILABLE'}`;
    document.querySelector('#last-updated').textContent = `updated ${new Date().toLocaleTimeString()}`;
    renderTopology(data.processes); renderClocks(data.processes); renderEvents(data.events); renderSnapshotTable(data); renderChannels(data);
  } catch (error) {
    document.querySelector('#health-pill').classList.add('offline');
    document.querySelector('#health-pill').innerHTML = '<span></span>BACKEND UNAVAILABLE';
    actionStatus.textContent = error.message;
  }
}

async function postAction(url, payload) {
  actionStatus.textContent = 'Sending operation...';
  try {
    const response = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Operation failed');
    actionStatus.textContent = 'Operation accepted.';
    await loadDashboard();
  } catch (error) { actionStatus.textContent = error.message; }
}

function pulseOrderChannel(restaurant) {
  const topology = document.querySelector('#topology');
  topology.classList.remove('pulse-r1', 'pulse-r2');
  void topology.offsetWidth;
  topology.classList.add(restaurant === 'restaurant2' ? 'pulse-r2' : 'pulse-r1');
  window.setTimeout(() => topology.classList.remove('pulse-r1', 'pulse-r2'), 2600);
}

function pulseProcessPath(process) {
  const topology = document.querySelector('#topology');
  topology.classList.remove('pulse-r1', 'pulse-r2', 'pulse-delivery');
  void topology.offsetWidth;
  if (process === 'restaurant1') topology.classList.add('pulse-r1');
  if (process === 'restaurant2') topology.classList.add('pulse-r2');
  if (process === 'delivery1') topology.classList.add('pulse-delivery');
  if (process === 'hub') topology.classList.add('pulse-r1', 'pulse-r2');
  window.setTimeout(() => topology.classList.remove('pulse-r1', 'pulse-r2', 'pulse-delivery'), 1800);
}

document.querySelector('#place-order').addEventListener('click', () => {
  const restaurant = document.querySelector('#restaurant').value;
  pulseOrderChannel(restaurant);
  postAction('/api/orders', { order_id: document.querySelector('#order-id').value.trim(), restaurant });
});
document.querySelector('#snapshot-button').addEventListener('click', () => postAction('/api/snapshot', {}));
document.querySelector('#demo-button').addEventListener('click', () => postAction('/api/demo', {}));
document.querySelector('#event-log-table').addEventListener('click', (event) => {
  const row = event.target.closest('tr[data-process]');
  if (row) pulseProcessPath(row.dataset.process);
});
refreshRange.addEventListener('input', () => { refreshValue.textContent = `${refreshRange.value}s`; scheduleRefresh(); });
refreshToggle.addEventListener('change', scheduleRefresh);
function scheduleRefresh() { clearInterval(refreshTimer); if (refreshToggle.checked) refreshTimer = setInterval(loadDashboard, Number(refreshRange.value) * 1000); }
loadDashboard(); scheduleRefresh();
