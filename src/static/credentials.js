const $ = id => document.getElementById(`cred-${id}`) || document.getElementById(id);
let credentials = [];
let total = 0;
let offset = 0;
let filterType = '';
let searchQuery = '';
let debounceTimer;
let deleteTargetId = null;
let editTargetId = null;
let assigning = false;
let loadVersion = 0;

const esc = text => {
  const d = document.createElement('div');
  d.textContent = text == null ? '' : String(text);
  return d.innerHTML;
};

const payload = async response => {
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || data.detail || 'Request failed');
  return data;
};

function message(text = '', id = 'error') {
  const el = $(id);
  if (!el) return;
  el.textContent = text;
  el.hidden = !text;
}

function formatDate(isoStr) {
  if (!isoStr) return '—';
  try {
    return new Date(isoStr).toLocaleString();
  } catch {
    return isoStr;
  }
}

function render() {
  const tbody = $('results-list');
  if (!tbody) return;

  tbody.innerHTML = credentials.length
    ? credentials.map(c => `
      <tr class="search-user-row" data-cred-id="${c.id}">
        <td>
          <div class="cred-type-cell">
            <sbb-icon name="${c.credential_type === 'fingerprint' ? 'fingerprint-small' : 'document-text-small'}"></sbb-icon>
            <span>${c.credential_type === 'fingerprint' ? 'Fingerprint' : 'NFC UID'}</span>
          </div>
        </td>
        <td><strong>${esc(c.identifier)}</strong></td>
        <td>
          ${c.user_id == null ? '<strong>Unassigned</strong>' : `<div class="search-identity">
            <sbb-image class="search-photo" image-src="${esc(c.user_photo || '/static/portraits/default.svg')}" alt=""></sbb-image>
            <div>
              <sbb-transparent-button size="s" href="/people?q=${encodeURIComponent(c.user_name)}" aria-label="View ${esc(c.user_name)}">
                ${esc(c.user_name)}
              </sbb-transparent-button>
              <div class="cred-user-uid">${esc(c.plaksha_id || 'ID: ' + c.user_id)}</div>
            </div>
          </div>`}
        </td>
        <td>
          <sbb-chip-label size="xs" color="${c.is_active ? 'green' : 'charcoal'}">
            ${c.user_id == null ? 'On sensor' : c.on_sensor === false ? 'Missing on sensor' : c.is_active ? 'Active' : 'Inactive'}
          </sbb-chip-label>
        </td>
        <td>${formatDate(c.enrolled_at)}</td>
        <td>
          <div class="search-entry-actions">
            <sbb-transparent-button size="s" icon-name="pen-small" aria-label="${c.user_id == null ? 'Assign credential' : 'Edit credential'}" data-edit-cred="${c.id}"></sbb-transparent-button>
            <sbb-transparent-button size="s" icon-name="trash-small" aria-label="Delete credential" data-delete-cred="${c.id}"></sbb-transparent-button>
          </div>
        </td>
      </tr>
    `).join('')
    : '<tr><td colspan="6" class="cred-empty-row">No credentials found.</td></tr>';

  const countEl = $('count');
  if (countEl) countEl.textContent = `${total ? offset + 1 : 0}–${offset + credentials.length} / ${total} credentials`;
  $('previous').disabled = offset === 0;
  $('next').disabled = offset + credentials.length >= total;
}

async function load() {
  const version = ++loadVersion;
  message('', 'error');
  try {
    const params = new URLSearchParams({ limit: '100', offset: String(offset) });
    if (filterType) params.set('type', filterType);
    if (searchQuery) params.set('q', searchQuery);
    const data = await payload(await fetch(`/api/credentials?${params}`));
    if (version !== loadVersion) return;
    const sensor = data.sensor || {};
    $('count-status').textContent = sensor.checked_at
      ? `Sensor ${sensor.available ? 'checked' : 'offline; last checked'} ${formatDate(sensor.checked_at)}`
      : 'Sensor inventory has not been read';
    if (offset && offset >= data.total) { offset = Math.max(0, offset - 100); return load(); }
    credentials = data.credentials || [];
    total = data.total || 0;
    render();
  } catch (err) {
    message(err.message, 'error');
  }
}

async function refreshSensor() {
  $('refresh-btn').disabled = true;
  $('count-status').textContent = 'Reading sensor…';
  try {
    await payload(await fetch('/api/credentials/refresh', { method: 'POST' }));
    await load();
  } catch (err) {
    await load();
    message(`Sensor inventory unavailable: ${err.message}`);
  } finally { $('refresh-btn').disabled = false; }
}

async function fetchUsers() {
  try {
    const users = [];
    for (let start = 0; ; start += 100) {
      const data = await payload(await fetch(`/api/users/search?limit=100&offset=${start}`));
      users.push(...(data.users || []));
      if (!(data.users || []).length || users.length >= data.total) return users;
    }
  } catch {
    return [];
  }
}

async function openAddDialog() {
  message('', 'add-error');
  const users = await fetchUsers();
  const userOptions = users.map(u => `<sbb-option value="${u.id}">${esc(u.name)} (${esc(u.plaksha_id || 'ID ' + u.id)})</sbb-option>`).join('');

  $('add-form').innerHTML = `
    <sbb-form-field size="m" floating-label>
      <label for="cred-add-user">Assigned Person</label>
      <sbb-select id="cred-add-user" required>
        ${userOptions}
      </sbb-select>
    </sbb-form-field>
    <sbb-form-field size="m" floating-label>
      <label for="cred-add-type">Credential Type</label>
      <sbb-select id="cred-add-type" value="fingerprint">
        <sbb-option value="fingerprint">Fingerprint template</sbb-option>
        <sbb-option value="nfc">NFC Card UID</sbb-option>
      </sbb-select>
    </sbb-form-field>
    <sbb-form-field size="m" floating-label>
      <label for="cred-add-ident">Identifier (e.g. template:42 or AABBCCDD)</label>
      <input id="cred-add-ident" type="text" required maxlength="100" autocomplete="off" />
    </sbb-form-field>
    <sbb-form-field size="m" floating-label>
      <label for="cred-add-active">Status</label>
      <sbb-select id="cred-add-active" value="true">
        <sbb-option value="true">Active</sbb-option>
        <sbb-option value="false">Inactive</sbb-option>
      </sbb-select>
    </sbb-form-field>
  `;
  $('add-dialog').open();
}

async function saveAdd() {
  message('', 'add-error');
  const userEl = document.getElementById('cred-add-user');
  const typeEl = document.getElementById('cred-add-type');
  const identEl = document.getElementById('cred-add-ident');
  const activeEl = document.getElementById('cred-add-active');

  const userId = userEl ? userEl.value : null;
  const credType = typeEl ? typeEl.value : 'fingerprint';
  const identifier = identEl ? identEl.value.trim() : '';
  const isActive = activeEl ? activeEl.value === 'true' : true;

  if (!userId) {
    message('Select a person to assign', 'add-error');
    return;
  }
  if (!identifier) {
    message('Enter an identifier or template ID', 'add-error');
    return;
  }

  $('add-save').disabled = true;
  try {
    await payload(await fetch('/api/credentials', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_id: Number(userId),
        credential_type: credType,
        identifier,
        is_active: isActive,
      }),
    }));
    $('add-dialog').close();
    await load();
  } catch (err) {
    message(err.message, 'add-error');
  } finally {
    $('add-save').disabled = false;
  }
}

async function openEditDialog(id) {
  const cred = credentials.find(c => String(c.id) === String(id));
  if (!cred) return;
  editTargetId = id;
  assigning = cred.user_id == null;
  $('edit-title').textContent = assigning ? 'Assign fingerprint template' : 'Edit credential';
  message('', 'edit-error');

  const users = await fetchUsers();
  const userOptions = users.map(u => `
    <sbb-option value="${u.id}" ${u.id === cred.user_id ? 'selected' : ''}>
      ${esc(u.name)} (${esc(u.plaksha_id || 'ID ' + u.id)})
    </sbb-option>
  `).join('');

  $('edit-form').innerHTML = `
    <sbb-form-field size="m" floating-label>
      <label for="cred-edit-user">Assigned Person</label>
      <sbb-select id="cred-edit-user" value="${cred.user_id || ''}">
        ${userOptions}
      </sbb-select>
    </sbb-form-field>
    <sbb-form-field size="m" floating-label>
      <label for="cred-edit-ident">${cred.credential_type === 'fingerprint' ? 'Fingerprint Template ID' : 'NFC UID'}</label>
      <input id="cred-edit-ident" type="text" value="${esc(cred.identifier)}" ${cred.credential_type === 'fingerprint' ? 'readonly' : ''} required maxlength="100" />
    </sbb-form-field>
    <sbb-form-field size="m" floating-label>
      <label for="cred-edit-active">Status</label>
      <sbb-select id="cred-edit-active" value="${String(assigning || Boolean(cred.is_active))}">
        <sbb-option value="true">Active</sbb-option>
        <sbb-option value="false">Inactive</sbb-option>
      </sbb-select>
    </sbb-form-field>
  `;
  $('edit-dialog').open();
}

async function saveEdit() {
  if (!editTargetId) return;
  message('', 'edit-error');

  const userEl = document.getElementById('cred-edit-user');
  const identEl = document.getElementById('cred-edit-ident');
  const activeEl = document.getElementById('cred-edit-active');

  const userId = userEl ? userEl.value : null;
  const identifier = identEl ? identEl.value.trim() : '';
  const isActive = activeEl ? activeEl.value === 'true' : true;

  if (!userId) { message('Select a person to assign', 'edit-error'); return; }
  if (!identifier) {
    message('Enter an identifier or template ID', 'edit-error');
    return;
  }

  $('edit-save').disabled = true;
  try {
    await payload(await fetch(assigning ? '/api/credentials' : `/api/credentials/${editTargetId}`, {
      method: assigning ? 'POST' : 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_id: Number(userId),
        ...(assigning ? { credential_type: 'fingerprint' } : {}),
        identifier,
        is_active: isActive,
      }),
    }));
    $('edit-dialog').close();
    await load();
  } catch (err) {
    message(err.message, 'edit-error');
  } finally {
    $('edit-save').disabled = false;
  }
}

function confirmDelete(id) {
  const cred = credentials.find(c => String(c.id) === String(id));
  if (!cred) return;
  deleteTargetId = id;
  message('', 'confirm-error');

  const owner = cred.user_name ? ` assigned to ${cred.user_name}` : ' (unassigned)';
  const warnText = cred.credential_type === 'fingerprint'
    ? `Remove template ${cred.identifier}${owner}? It will be removed from the reader.`
    : `Remove NFC card ${cred.identifier}${owner}?`;

  $('confirm-text').textContent = warnText;
  $('confirm-dialog').open();
}

async function executeDelete() {
  if (!deleteTargetId) return;
  message('', 'confirm-error');
  $('confirm-delete').disabled = true;
  try {
    await payload(await fetch(String(deleteTargetId).startsWith('sensor:') ? `/api/credentials/sensor/${String(deleteTargetId).split(':')[1]}` : `/api/credentials/${deleteTargetId}`, { method: 'DELETE' }));
    $('confirm-dialog').close();
    await load();
  } catch (err) {
    message(err.message, 'confirm-error');
  } finally {
    $('confirm-delete').disabled = false;
  }
}

async function init() {
  while (!$('results-list')) await new Promise(requestAnimationFrame);
  await Promise.all([
    'sbb-table-wrapper', 'sbb-select', 'sbb-option', 'sbb-icon',
    'sbb-chip-label', 'sbb-dialog', 'sbb-form-field', 'sbb-button',
    'sbb-secondary-button', 'sbb-transparent-button',
  ].map(t => customElements.whenDefined(t)));

  document.addEventListener('submit', e => {
    if (e.target.closest('#cred-search-form, [role="search"]')) {
      e.preventDefault();
      offset = 0; searchQuery = $('search-input') ? $('search-input').value.trim() : '';
      load();
    }
  });

  document.addEventListener('input', e => {
    if (e.target.id === 'cred-search-input' || e.target.closest('#cred-search-form')) {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => {
        offset = 0; searchQuery = e.target.value.trim();
        load();
      }, 250);
    }
  });

  document.addEventListener('click', e => {
    if (e.target.closest('#cred-previous')) { offset = Math.max(0, offset - 100); load(); return; }
    if (e.target.closest('#cred-next')) { offset += 100; load(); return; }
    if (e.target.closest('#cred-refresh-btn')) { refreshSensor(); return; }
    // Filter buttons
    const filterAllBtn = e.target.closest('#cred-filter-all, #filter-all');
    if (filterAllBtn) {
      offset = 0; filterType = '';
      load();
      return;
    }
    const filterFpBtn = e.target.closest('#cred-filter-fingerprint, #filter-fingerprint');
    if (filterFpBtn) {
      offset = 0; filterType = 'fingerprint';
      load();
      return;
    }
    const filterNfcBtn = e.target.closest('#cred-filter-nfc, #filter-nfc');
    if (filterNfcBtn) {
      offset = 0; filterType = 'nfc';
      load();
      return;
    }

    // Add dialog
    if (e.target.closest('#cred-add-btn, #add-btn')) {
      openAddDialog();
      return;
    }
    if (e.target.closest('#cred-add-cancel, #add-cancel')) {
      const dlg = $('add-dialog');
      if (dlg) dlg.close();
      return;
    }
    if (e.target.closest('#cred-add-save, #add-save')) {
      saveAdd();
      return;
    }

    // Edit dialog
    if (e.target.closest('#cred-edit-cancel, #edit-cancel')) {
      const dlg = $('edit-dialog');
      if (dlg) dlg.close();
      return;
    }
    if (e.target.closest('#cred-edit-save, #edit-save')) {
      saveEdit();
      return;
    }

    // Confirm dialog
    if (e.target.closest('#cred-confirm-cancel, #confirm-cancel')) {
      const dlg = $('confirm-dialog');
      if (dlg) dlg.close();
      return;
    }
    if (e.target.closest('#cred-confirm-delete, #confirm-delete')) {
      executeDelete();
      return;
    }

    // Row action buttons
    const editBtn = e.target.closest('[data-edit-cred]');
    if (editBtn) {
      openEditDialog(editBtn.dataset.editCred);
      return;
    }
    const delBtn = e.target.closest('[data-delete-cred]');
    if (delBtn) {
      confirmDelete(delBtn.dataset.deleteCred);
      return;
    }
  });

  await load();
  await refreshSensor();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
