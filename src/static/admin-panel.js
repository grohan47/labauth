// Admin panel (/admin) interactions: logout and the alerts pane.
// The Python layer renders markup + data; this file owns the alert CRUD.
const ALERT_SEVERITIES = ['critical', 'caution', 'info'];
const ALERT_TTL_OPTIONS = [
  [0, 'No expiry'],
  [3600, '1 hour'],
  [28800, '8 hours'],
  [86400, '24 hours'],
  [604800, '7 days'],
];

function escapeHtml(value) {
  if (value === null || value === undefined) return '';
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function severityOf(alert) {
  return ALERT_SEVERITIES.includes(alert.severity) ? alert.severity : 'info';
}

function severityLabel(severity) {
  return `${severity[0].toUpperCase()}${severity.slice(1)}`;
}

function formatRemaining(seconds) {
  if (seconds === null || seconds === undefined) return 'No expiry';
  if (seconds <= 0) return 'Expiring';
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (days) return `${days}d ${hours}h left`;
  if (hours) return `${hours}h ${minutes}m left`;
  return `${Math.max(1, minutes)}m left`;
}

function severityOptions(selected) {
  return ALERT_SEVERITIES.map(
    (value) => `<sbb-option value="${value}"${value === selected ? ' selected' : ''}>${severityLabel(value)}</sbb-option>`,
  ).join('');
}

function ttlChoices(alert) {
  const id = alert.id;
  return `
    <div class="admin-alert-row__ttl-choices">
      ${ALERT_TTL_OPTIONS.map(([seconds, label]) => `<sbb-secondary-button size="s" data-alert-id="${id}" data-ttl="${seconds}">${label}</sbb-secondary-button>`).join('')}
    </div>`;
}

function alertRow(alert, ttlOpen) {
  const severity = severityOf(alert);
  return `
    <div class="admin-alert-row admin-alert-row--${severity}" role="listitem" data-alert-id="${alert.id}">
      <span class="admin-alert-row__severity">${severityLabel(severity)}</span>
      <p class="admin-alert-row__message">${escapeHtml(alert.message)}</p>
      <div class="admin-alert-row__top">
        <span class="admin-alert-row__ttl">${formatRemaining(alert.remaining_seconds)}</span>
        <div class="admin-alert-row__actions">
          <sbb-secondary-button class="admin-alert-action" size="s" id="alert-edit-${alert.id}" aria-label="Edit alert"><sbb-icon slot="icon" name="pen-small"></sbb-icon></sbb-secondary-button>
          <sbb-secondary-button class="admin-alert-action" size="s" id="alert-ttl-${alert.id}" aria-label="Set expiry"><sbb-icon slot="icon" name="clock-small"></sbb-icon></sbb-secondary-button>
          <sbb-secondary-button class="admin-alert-action" size="s" id="alert-delete-${alert.id}" aria-label="Delete alert"><sbb-icon slot="icon" name="trash-small"></sbb-icon></sbb-secondary-button>
        </div>
      </div>
      ${ttlOpen ? ttlChoices(alert) : ''}
    </div>`;
}

function alertEditRow(alert) {
  const severity = severityOf(alert);
  return `
    <div class="admin-alert-row admin-alert-row--${severity} is-editing" role="listitem" data-alert-id="${alert.id}">
      <input class="admin-alert-row__input" type="text" maxlength="500" value="${escapeHtml(alert.message)}" aria-label="Alert message" />
      <div class="admin-alert-row__edit-controls">
        <sbb-form-field size="s" class="admin-alert-row__severity-field">
          <sbb-select class="admin-alert-row__severity" aria-label="Severity" value="${severity}">${severityOptions(severity)}</sbb-select>
        </sbb-form-field>
        <div class="admin-alert-row__actions">
          <sbb-secondary-button class="admin-alert-action" size="s" id="alert-save-${alert.id}" aria-label="Save alert"><sbb-icon slot="icon" name="tick-small"></sbb-icon></sbb-secondary-button>
          <sbb-secondary-button class="admin-alert-action" size="s" id="alert-cancel-${alert.id}" aria-label="Cancel edit"><sbb-icon slot="icon" name="cross-small"></sbb-icon></sbb-secondary-button>
        </div>
      </div>
    </div>`;
}

function initAdminPanel() {
  const exitBtn = document.querySelector('#admin-exit-btn');
  const alertsCard = document.querySelector('#admin-card-alerts');
  const alertsDialog = document.querySelector('#admin-alerts-dialog');
  const alertsClose = document.querySelector('#admin-alerts-close');
  const alertsForm = document.querySelector('#admin-alerts-form');
  const alertsInput = document.querySelector('#admin-alert-input');
  const alertsSeverity = document.querySelector('#admin-alert-severity');
  const alertsSubmit = document.querySelector('#admin-alerts-submit');
  const alertsList = document.querySelector('#admin-alerts-list');
  const alertsError = document.querySelector('#admin-alerts-error');

  if (!exitBtn || !alertsCard || !alertsDialog || !alertsList) {
    window.requestAnimationFrame(initAdminPanel);
    return;
  }

  let alerts = [];
  let editingId = null;
  let openTtlId = null;
  let loadVersion = 0;

  exitBtn.addEventListener('click', async () => {
    try {
      await fetch('/api/admin/logout', { method: 'POST' });
    } catch (e) {
      console.error('Logout error', e);
    } finally {
      window.location.assign('/admin-display');
    }
  });

  const showError = (message) => {
    if (!alertsError) return;
    alertsError.textContent = message || '';
    alertsError.hidden = !message;
  };

  const render = () => {
    if (!alerts.length) {
      alertsList.innerHTML = '<p class="admin-alerts-empty">No active alerts.</p>';
      return;
    }
    alertsList.innerHTML = alerts
      .map((alert) => {
        const id = String(alert.id);
        if (id === editingId) return alertEditRow(alert);
        return alertRow(alert, id === openTtlId);
      })
      .join('');
    wire();
  };

  const wire = () => {
    alertsList.querySelectorAll('[id^="alert-edit-"]').forEach((btn) =>
      btn.addEventListener('click', () => {
        editingId = btn.id.replace('alert-edit-', '');
        openTtlId = null;
        render();
      }),
    );
    alertsList.querySelectorAll('[id^="alert-ttl-"]').forEach((btn) =>
      btn.addEventListener('click', () => {
        const id = btn.id.replace('alert-ttl-', '');
        openTtlId = openTtlId === id ? null : id;
        editingId = null;
        render();
        if (openTtlId) {
          window.requestAnimationFrame(() => {
            const choices = alertsList.querySelector(
              `.admin-alert-row[data-alert-id="${id}"] .admin-alert-row__ttl-choices`,
            );
            if (choices) choices.scrollIntoView({ block: 'nearest' });
          });
        }
      }),
    );
    alertsList.querySelectorAll('[id^="alert-delete-"]').forEach((btn) =>
      btn.addEventListener('click', () => {
        const id = btn.id.replace('alert-delete-', '');
        removeAlert(id);
      }),
    );
    alertsList.querySelectorAll('sbb-secondary-button[data-ttl]').forEach((btn) =>
      btn.addEventListener('click', () => {
        setTtl(btn.dataset.alertId, Number(btn.dataset.ttl));
      }),
    );
    alertsList.querySelectorAll('[id^="alert-save-"]').forEach((btn) =>
      btn.addEventListener('click', () => {
        saveEdit(btn.id.replace('alert-save-', ''));
      }),
    );
    alertsList.querySelectorAll('[id^="alert-cancel-"]').forEach((btn) =>
      btn.addEventListener('click', () => {
        editingId = null;
        render();
      }),
    );
  };

  const load = async () => {
    const version = ++loadVersion;
    try {
      const res = await fetch('/api/alerts', { cache: 'no-store' });
      if (!res.ok) return;
      const data = await res.json();
      if (version !== loadVersion) return;
      alerts = Array.isArray(data.alerts) ? data.alerts : [];
      render();
    } catch (e) {
      // Keep the last rendered list on a transient failure.
    }
  };

  const mutate = async (url, options, beforeRender) => {
    showError('');
    try {
      const res = await fetch(url, { ...options, cache: 'no-store' });
      if (res.status === 401) {
        window.location.assign('/admin-display?login=1');
        return false;
      }
      const data = await res.json();
      if (!res.ok) {
        showError(data.error || data.detail || 'Could not save the alert.');
        return false;
      }
      // Paint the confirmed write response. A cached or older list request must
      // never undo a deletion or hide a successfully saved expiry.
      if (Array.isArray(data.alerts)) {
        alerts = data.alerts;
      } else if (data.alert) {
        alerts = alerts.filter(alert => String(alert.id) !== String(data.alert.id));
        alerts.push(data.alert);
        alerts.sort((a, b) => ALERT_SEVERITIES.indexOf(severityOf(a)) - ALERT_SEVERITIES.indexOf(severityOf(b))
          || String(a.created_at).localeCompare(String(b.created_at)) || Number(a.id) - Number(b.id));
      } else {
        showError('Could not read the saved alert. Close and reopen the pane to refresh.');
        return false;
      }
      loadVersion += 1;
      if (beforeRender) beforeRender();
      render();
      return true;
    } catch (e) {
      showError('Could not reach the server. Please try again.');
      return false;
    }
  };

  const removeAlert = async (id) => {
    await mutate(`/api/alerts/${id}`, { method: 'DELETE' });
  };

  const setTtl = async (id, ttl) => {
    await mutate(`/api/alerts/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ttl_seconds: ttl }),
    }, () => { openTtlId = null; });
  };

  const saveEdit = async (id) => {
    const row = alertsList.querySelector(`.admin-alert-row[data-alert-id="${id}"]`);
    const input = row && row.querySelector('.admin-alert-row__input');
    const select = row && row.querySelector('.admin-alert-row__severity');
    const message = input ? input.value.trim() : '';
    if (!message) {
      showError('Enter an alert message.');
      input && input.focus();
      return;
    }
    await mutate(
      `/api/alerts/${id}`,
      {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message, severity: select ? select.value : 'info' }),
      },
      () => {
        editingId = null;
      },
    );
  };

  const openAlerts = () => {
    showError('');
    editingId = null;
    openTtlId = null;
    if (alertsDialog) {
      if (typeof alertsDialog.open === 'function') {
        alertsDialog.open();
      } else if (alertsDialog.showModal) {
        alertsDialog.showModal();
      }
    }
    load();
    setTimeout(() => alertsInput && alertsInput.focus(), 100);
  };

  const closeAlerts = () => {
    if (alertsDialog && typeof alertsDialog.close === 'function') {
      alertsDialog.close();
    }
  };

  alertsCard.addEventListener('click', openAlerts);
  // The trigger is inside the card, so its click already bubbles to this handler.

  if (alertsClose) {
    alertsClose.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      closeAlerts();
    });
  }

  alertsDialog.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      closeAlerts();
    }
  });

  if (alertsForm) {
    alertsForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const message = (alertsInput ? alertsInput.value : '').trim();
      if (!message) {
        showError('Enter an alert message.');
        alertsInput && alertsInput.focus();
        return;
      }
      const severity = (alertsSeverity && alertsSeverity.value) || 'info';
      if (alertsSubmit) alertsSubmit.loading = true;
      const saved = await mutate('/api/alerts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message, severity }),
      });
      if (alertsSubmit) alertsSubmit.loading = false;
      if (saved) {
        if (alertsInput) alertsInput.value = '';
        if (alertsSeverity) alertsSeverity.value = 'info';
        if (alertsInput) alertsInput.focus();
      }
    });
  }
}

initAdminPanel();
