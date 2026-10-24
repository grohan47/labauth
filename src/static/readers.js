async function initializeReaderControls() {
  // NiceGUI mounts ui.html after head modules have been loaded.
  if (!document.querySelector('#admin-reader-controls')) {
    await new Promise((resolve) => {
      const observer = new MutationObserver(() => {
        if (document.querySelector('#admin-reader-controls')) {
          observer.disconnect();
          resolve();
        }
      });
      observer.observe(document.body, { childList: true, subtree: true });
    });
  }
  await Promise.all(['sbb-checkbox', 'sbb-secondary-button'].map((name) => customElements.whenDefined(name)));
  const control = document.querySelector('#admin-reader-controls');

  const fingerprint = document.querySelector('#reader-fingerprint-enabled');
  const nfc = document.querySelector('#reader-nfc-enabled');
  const error = document.querySelector('#reader-control-error');
  let pending = false;
  let pollTimer = null;

  function setBusy(value) {
    pending = value;
    [fingerprint, nfc, ...control.querySelectorAll('[data-reader-mode]')].forEach((element) => {
      if (element) element.disabled = value;
    });
  }

  function describeReader(reader, enabled) {
    if (typeof reader === 'string') return `${enabled ? 'Enabled' : 'Disabled'} · ${reader.replaceAll('_', ' ')}`;
    if (!reader || typeof reader !== 'object') return enabled ? 'Unavailable' : 'Disabled';
    const state = reader.status || reader.state || reader.health || (reader.ready ? 'READY' : 'ABSENT');
    return `${enabled ? 'Enabled' : 'Disabled'} · ${String(state).replaceAll('_', ' ')}`;
  }

  function showStatus(status) {
    const connection = document.querySelector('#reader-connection');
    const fpStatus = document.querySelector('#reader-fingerprint-status');
    const nfcStatus = document.querySelector('#reader-nfc-status');
    if (!status || typeof status !== 'object') return;
    connection.textContent = status.error || (status.connected ? (status.ready ? 'Ready' : 'Connected') : 'Disconnected');
    connection.dataset.state = status.error ? 'error' : status.ready ? 'ready' : 'unavailable';
    fpStatus.textContent = describeReader(status.fp, status.fp_enabled);
    nfcStatus.textContent = describeReader(status.nfc, status.nfc_enabled);
    fingerprint.checked = Boolean(status.fp_enabled);
    nfc.checked = Boolean(status.nfc_enabled);
    control.querySelectorAll('[data-reader-mode]').forEach((button) => {
      const selected = button.dataset.readerMode === status.mode;
      button.setAttribute('aria-pressed', String(selected));
      button.classList.toggle('reader-mode-selected', selected);
    });
    control.dataset.configured = String(Boolean(status.configured));
  }

  async function refreshStatus() {
    if (document.hidden || pending) return;
    try {
      const response = await fetch('/api/readers/status', { cache: 'no-store' });
      if (!response.ok) return;
      showStatus(await response.json());
    } catch (cause) {
      // Keep the last observed state; the next visible poll retries.
    }
  }

  async function update(payload) {
    if (pending) return;
    error.hidden = true;
    setBusy(true);
    try {
      const response = await fetch('/api/readers/control', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || `Reader control failed (${response.status})`);
      showStatus(data);
    } catch (cause) {
      error.textContent = cause.message || 'Reader control failed.';
      error.hidden = false;
      setBusy(false);
      await refreshStatus();
    } finally {
      setBusy(false);
    }
  }

  fingerprint.addEventListener('change', () => update({ reader: 'fingerprint', enabled: fingerprint.checked }));
  nfc.addEventListener('change', () => update({ reader: 'nfc', enabled: nfc.checked }));
  control.querySelectorAll('[data-reader-mode]').forEach((button) => {
    button.addEventListener('click', () => update({ mode: button.dataset.readerMode }));
  });

  function startPolling() {
    if (document.hidden || pollTimer !== null) return;
    void refreshStatus();
    pollTimer = window.setInterval(refreshStatus, 2_000);
  }

  function stopPolling() {
    if (pollTimer !== null) window.clearInterval(pollTimer);
    pollTimer = null;
  }

  document.addEventListener('visibilitychange', () => {
    if (document.hidden) stopPolling();
    else startPolling();
  });
  startPolling();
}

void initializeReaderControls();
