const $ = (id) => document.getElementById(id);
let currentStatus = null;
let toastTimer = null;

function showToast(message) {
  const toast = $('toast');
  toast.textContent = message;
  toast.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove('show'), 2600);
}
function setDot(id, online) {
  const el = $(id);
  if (!el) return;
  el.classList.toggle('online', !!online);
  el.classList.toggle('offline', !online);
}
function setText(id, value, fallback = '—') {
  const el = $(id);
  if (el) el.textContent = value === null || value === undefined || value === '' ? fallback : value;
}
function formatBytesGB(value) {
  const n = Number(value);
  return Number.isFinite(n) ? `${n.toFixed(1)} GB` : '—';
}

async function api(path, options = {}) {
  const response = await fetch(path, {headers: {'Content-Type': 'application/json', ...(options.headers || {})}, ...options});
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || data.error || `Request failed (${response.status})`);
  return data;
}

async function refreshStatus() {
  try {
    const data = await api('/api/status');
    currentStatus = data;
    const registered = !!data.registered;
    setText('node-status', registered ? 'Registered' : 'Pending');
    setText('node-caption', registered ? 'Worker registration complete' : 'Waiting for registration');
    setDot('node-dot', registered);
    setDot('side-dot', registered);
    setText('side-status', registered ? 'Node registered' : 'Not registered');
    setText('side-subtitle', data.ollama_online ? 'Local inference available' : 'Ollama unavailable');
    setText('ollama-status', data.ollama_online ? 'Online' : 'Offline');
    setText('model-count', `${(data.models || []).length} model${(data.models || []).length === 1 ? '' : 's'} detected`);
    setText('cpu-cores', data.hardware?.cpu?.logical_processors);
    setText('ram-total', formatBytesGB(data.hardware?.ram?.total_ram_gb));
    setText('node-id', data.node_id, 'Not available');
    setText('worker-url', data.worker_url);
    setText('last-heartbeat', data.last_heartbeat, 'Never');
    setText('gpu-name', data.hardware?.gpu?.name, 'Not detected');
    setText('disk-free', formatBytesGB(data.hardware?.ssd?.free_gb));
    const pill = $('registration-pill');
    pill.textContent = registered ? 'REGISTERED' : 'UNREGISTERED';
    pill.classList.toggle('registered', registered);
    $('updated-label').textContent = `Updated ${new Date().toLocaleTimeString([], {hour: '2-digit', minute: '2-digit', second: '2-digit'})}`;
    updateModelSelect(data.models || []);
    populateSettings(data.config || {});
    await refreshLogs();
  } catch (error) {
    setText('node-status', 'Unavailable');
    setText('node-caption', 'Could not reach local API');
    setText('side-status', 'Local API unavailable');
    setText('side-subtitle', 'Check application status');
    setDot('node-dot', false);
    setDot('side-dot', false);
    setText('updated-label', 'Status refresh failed');
  }
}

function updateModelSelect(models) {
  const select = $('model-select');
  const previous = select.value;
  const values = models.length ? models : ['gemma3:latest'];
  select.replaceChildren();
  values.forEach((name) => {
    const option = document.createElement('option');
    option.value = name;
    option.textContent = name;
    select.appendChild(option);
  });
  if (values.includes(previous)) select.value = previous;
}

async function refreshLogs() {
  try {
    const data = await api('/api/logs');
    const container = $('activity-list');
    const logs = data.logs || [];
    if (!logs.length) {
      container.innerHTML = '<div class="empty-state">No events recorded in this session yet.</div>';
      return;
    }
    container.replaceChildren();
    logs.slice(0, 8).forEach((item) => {
      const row = document.createElement('div');
      row.className = `activity-item ${item.level === 'error' ? 'error' : ''}`;
      const marker = document.createElement('span'); marker.className = 'activity-marker';
      const copy = document.createElement('div'); copy.className = 'activity-copy';
      const message = document.createElement('p'); message.textContent = item.message;
      const time = document.createElement('time'); time.textContent = item.time || '';
      copy.append(message, time); row.append(marker, copy); container.appendChild(row);
    });
  } catch (_) { /* dashboard can still show status if logs are unavailable */ }
}

function populateSettings(config) {
  const network = config.network || {};
  const inference = config.inference || {};
  const resources = config.resource_limits || {};
  $('auto-connect').checked = !!network.auto_connect;
  $('auto-start').checked = !!network.auto_start;
  $('remote-inference').checked = inference.allow_remote_inference !== false;
  $('cpu-limit').value = resources.cpu_percent ?? 50;
  $('gpu-limit').value = resources.gpu_percent ?? 50;
  $('cpu-limit-value').textContent = `${$('cpu-limit').value}%`;
  $('gpu-limit-value').textContent = `${$('gpu-limit').value}%`;
}

function showPage(name) {
  document.querySelectorAll('.nav-item').forEach((button) => button.classList.toggle('active', button.dataset.page === name));
  document.querySelectorAll('.page').forEach((page) => page.classList.toggle('active', page.id === `page-${name}`));
  setText('page-title', ({dashboard: 'Dashboard', inference: 'Inference test', settings: 'Settings'})[name] || 'Dashboard');
}

document.querySelectorAll('.nav-item').forEach((button) => button.addEventListener('click', () => showPage(button.dataset.page)));
$('refresh-btn').addEventListener('click', refreshStatus);
$('reconnect-btn').addEventListener('click', async () => {
  const button = $('reconnect-btn'); button.disabled = true;
  try { const result = await api('/api/reconnect', {method: 'POST', body: '{}'}); showToast(result.message || 'Connection attempt started.'); }
  catch (error) { showToast(error.message); }
  finally { button.disabled = false; setTimeout(refreshStatus, 500); }
});
$('copy-node').addEventListener('click', async () => {
  const value = currentStatus?.node_id;
  if (!value) return showToast('Node ID is not available yet.');
  try { await navigator.clipboard.writeText(value); showToast('Node ID copied.'); }
  catch (_) { showToast('Could not access clipboard.'); }
});
$('cpu-limit').addEventListener('input', () => $('cpu-limit-value').textContent = `${$('cpu-limit').value}%`);
$('gpu-limit').addEventListener('input', () => $('gpu-limit-value').textContent = `${$('gpu-limit').value}%`);
$('save-settings').addEventListener('click', async () => {
  const button = $('save-settings'); button.disabled = true; setText('settings-message', 'Saving…');
  const payload = {
    network: {auto_connect: $('auto-connect').checked, auto_start: $('auto-start').checked},
    inference: {allow_remote_inference: $('remote-inference').checked},
    resource_limits: {cpu_percent: Number($('cpu-limit').value), gpu_percent: Number($('gpu-limit').value)}
  };
  try { await api('/api/config', {method: 'POST', body: JSON.stringify(payload)}); setText('settings-message', 'Settings saved successfully.'); showToast('Settings saved.'); }
  catch (error) { setText('settings-message', `Could not save: ${error.message}`); }
  finally { button.disabled = false; }
});
$('run-inference').addEventListener('click', async () => {
  const button = $('run-inference');
  const prompt = $('prompt-input').value.trim();
  if (!prompt) return showToast('Enter a prompt first.');
  button.disabled = true; setText('inference-output', 'Generating…'); setText('response-time', 'Running');
  const started = performance.now();
  try {
    const result = await api('/generate', {method: 'POST', body: JSON.stringify({prompt, model: $('model-select').value, temperature: 0.2, stream: false})});
    const responseText = result.response ?? result.error ?? JSON.stringify(result, null, 2);
    setText('inference-output', responseText);
    setText('response-time', `${((performance.now() - started) / 1000).toFixed(2)}s`);
  } catch (error) {
    setText('inference-output', `Inference failed: ${error.message}`);
    setText('response-time', 'Failed');
  } finally { button.disabled = false; }
});

refreshStatus();
setInterval(refreshStatus, 5000);
