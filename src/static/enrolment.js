/* Swiss Lyne Enrolment Flow Client Logic */
const ready = async () => {
  if (!document.querySelector('#identity-form')) {
    await new Promise(resolve => {
      const observer = new MutationObserver(() => {
        if (document.querySelector('#identity-form')) { observer.disconnect(); resolve(); }
      });
      observer.observe(document.body, {childList: true, subtree: true});
    });
  }
  await Promise.all(['sbb-button', 'sbb-secondary-button', 'sbb-transparent-button', 'sbb-card',
    'sbb-secondary-button-link', 'sbb-button-link', 'sbb-notification', 'sbb-form-field', 'sbb-checkbox', 'sbb-image', 'sbb-menu', 'sbb-dialog'].map(n => customElements.whenDefined(n)));
  
  const $ = id => document.getElementById(id);
  const defaultPhoto = '/static/portraits/default.svg';
  let photo = defaultPhoto, step = 1, saved = false, saving = false, stream = null, cameraGeneration = 0;
  let themeTimer = null, themeRequest = false;
  let readerDraft = null, readerBusy = false, readerPoll = null, readerCreatePromise = null;
  let readerStatusPolling = false, readerGeneration = 0;
  let enrolledFp = false;
  let enrolledNfcUid = null;

  // Use the same host clock and 06:00/18:00 boundary as the public display
  async function syncTheme() {
    if (themeRequest || document.hidden) return;
    themeRequest = true;
    try {
      const response = await fetch('/api/time', {cache: 'no-store', signal: AbortSignal.timeout(5000)});
      if (!response.ok) return;
      const clock = await response.json();
      const hour = clock.mock_time ? Number(clock.mock_time.split(':')[0]) : clock.hour;
      if (!Number.isInteger(hour) || hour < 0 || hour > 23) return;
      const theme = hour >= 18 || hour < 6 ? 'dark' : 'light';
      const root = document.documentElement;
      root.dataset.theme = theme; root.style.colorScheme = theme;
      root.classList.toggle('sbb-dark', theme === 'dark'); root.classList.toggle('sbb-light', theme === 'light');
    } catch { /* Keep the last server-derived theme */ }
    finally { themeRequest = false; }
  }

  document.addEventListener('visibilitychange', syncTheme);
  window.addEventListener('focus', syncTheme);
  window.addEventListener('pageshow', () => { syncTheme(); if (!themeTimer) themeTimer = setInterval(syncTheme, 15000); });
  window.addEventListener('pagehide', () => { clearInterval(themeTimer); themeTimer = null; });
  syncTheme(); themeTimer = setInterval(syncTheme, 15000);

  // Set loaded indicator for tap animation container
  if ($('nfc-tap-animation')) {
    $('nfc-tap-animation').dataset.loaded = 'true';
  }

  const values = () => ({
    name: $('input-fullname').value.trim(), plaksha_id: $('input-plaksha-id').value.trim(),
    phone: $('input-phone').value.trim(), email: $('input-email').value.trim(), photo,
    access_area_ids: [...document.querySelectorAll('sbb-checkbox[name="access"]')].filter(c => c.checked).map(c => Number(c.value)),
  });

  const dirty = () => !saved && (photo !== defaultPhoto || [...$('identity-form').querySelectorAll('input')].some(i => i.value) || values().access_area_ids.length);

  const error = (id, message = '') => {
    $(id).replaceChildren(); $(id).hidden = !message;
    if (message) {
      const notice = document.createElement('sbb-notification');
      notice.setAttribute('type', 'error'); notice.setAttribute('animation', 'none'); notice.setAttribute('readonly', '');
      notice.textContent = message; $(id).append(notice);
    }
  };

  function setStep(next) {
    step = next;
    document.querySelectorAll('.enrolment-step').forEach(s => s.hidden = s.id !== `step-${next}`);
    const progress = next === 'success' ? 100 : next * 25;
    $('enrolment-progress').setAttribute('aria-valuenow', progress);
    $('enrolment-progress').setAttribute('aria-valuetext', $(`heading-${next}`).textContent);
    $('enrolment-progress-fill').style.width = `${progress}%`;
    $(`heading-${next}`).focus({preventScroll: true});
    window.scrollTo({top: 0, behavior: 'instant'});
    ensureReaderPolling();
    if (next === 2 && !readerDraft) ensureReaderDraft().catch(err => {
      renderReaderDraft({id: null, status: 'failed', stage: 'error', readers: {ready: false}, message: err.message || 'Reader unavailable'});
      error('fp-error', err.message || 'Reader unavailable');
    });
  }

  function setPhoto(src) {
    photo = src;
    $('mock-card-avatar').src = src;
    $('btn-remove-photo').hidden = src === defaultPhoto;
  }

  function review(record, access, savedCredentials = null) {
    $('final-card-name').textContent = record.name;
    $('final-card-photo').src = record.photo;
    $('final-demo-id').textContent = record.plaksha_id || '—';
    $('final-demo-phone').textContent = record.phone || '—';
    $('final-demo-email').textContent = record.email || '—';
    $('final-card-chips').replaceChildren();
    (access && access.length ? access : ['No authorised areas']).forEach(label => {
      const chip = document.createElement('sbb-chip-label'); chip.setAttribute('size', 's');
      chip.textContent = label; $('final-card-chips').append(chip);
    });

    if (savedCredentials) {
      enrolledFp = savedCredentials.some(c => ['fingerprint', 'fp'].includes(String(c.credential_type || c.type || '').toLowerCase()));
      enrolledNfcUid = savedCredentials.find(c => ['nfc', 'card'].includes(String(c.credential_type || c.type || '').toLowerCase()))?.identifier || null;
    }
    if (enrolledFp) {
      $('final-cred-fp').querySelector('.credential-state').textContent = 'Enrolled';
      $('final-cred-fp').style.color = 'var(--sbb-color-red, #eb0000)';
    } else {
      $('final-cred-fp').querySelector('.credential-state').textContent = 'Not enrolled';
      $('final-cred-fp').style.color = 'var(--display-muted)';
    }

    if (enrolledNfcUid) {
      $('final-cred-nfc').querySelector('.credential-state').textContent = `Enrolled (${enrolledNfcUid})`;
      $('final-cred-nfc').style.color = 'var(--sbb-color-red, #eb0000)';
    } else {
      $('final-cred-nfc').querySelector('.credential-state').textContent = 'Not enrolled';
      $('final-cred-nfc').style.color = 'var(--display-muted)';
    }
  }

  function renderReaderDraft(draft) {
    readerDraft = draft.id ? draft : null;
    const fpHealth = String(draft.readers?.fp || '').toUpperCase();
    const fpReady = draft.readers?.connected && draft.readers?.ready && draft.readers?.fp_enabled
      && ['READY', 'BUSY'].includes(fpHealth);
    const fpTitle = $('fp-status-title'), fpDesc = $('fp-status-desc');
    $('fp-guidance').hidden = true;
    $('fp-checkmark').hidden = draft.fp_template == null;
    $('btn-fp-skip').textContent = draft.fp_template != null ? 'Next' : 'Skip';
    $('fp-animation').hidden = !$('fp-checkmark').hidden;
    $('btn-fp-start').hidden = !fpReady || ['fingerprint','learning'].includes(draft.stage) || draft.fp_template != null;
    $('btn-fp-start').disabled = readerBusy;
    $('btn-fp-finish').hidden = draft.stage !== 'learning';
    $('btn-fp-finish').disabled = readerBusy;
    if (draft.fp_template != null) {
      fpTitle.textContent = 'Fingerprint enrolled'; fpDesc.textContent = 'Fingerprint template registered'; enrolledFp = true;
    } else if (!fpReady) {
      fpTitle.textContent = 'Reader unavailable'; fpDesc.textContent = 'Connect a fingerprint reader to continue'; enrolledFp = false;
    } else {
      enrolledFp = false;
      fpTitle.textContent = draft.stage === 'learning' ? 'Finish learning' : draft.stage === 'fingerprint' ? 'Place finger on sensor' : 'Fingerprint reader ready';
      fpDesc.textContent = draft.message || (draft.stage === 'idle' ? 'Start fingerprint enrolment' : '');
      const progress = draft.progress || {};
      const updateText = typeof progress.update === 'string' ? progress.update : '';
      const rawGuide = `${progress.hint || ''} ${progress.phase || ''} ${JSON.stringify(progress.matches || '')} ${updateText}`.toLowerCase();
      const guide = /left/.test(rawGuide) ? 'Move your finger slightly left'
        : /right/.test(rawGuide) ? 'Move your finger slightly right'
          : /center|centre|overlap|middle/.test(rawGuide) ? 'Cover the centre of the sensor'
            : progress.hint || updateText || (progress.phase && String(progress.phase).replaceAll('_', ' ')) || '';
      if (guide) { $('fp-guidance').textContent = guide; $('fp-guidance').hidden = false; }
    }
    const nfcHealth = String(draft.readers?.nfc || '').toUpperCase();
    const nfcReady = draft.readers?.connected && draft.readers?.ready && draft.readers?.nfc_enabled
      && ['READY', 'BUSY'].includes(nfcHealth);
    const nfcTitle = $('nfc-status-title'), nfcDesc = $('nfc-status-desc');
    $('nfc-checkmark').hidden = !draft.nfc_uid;
    $('btn-nfc-skip').textContent = draft.nfc_uid ? 'Next' : 'Skip';
    $('nfc-tap-animation').hidden = !$('nfc-checkmark').hidden;
    $('btn-nfc-start').hidden = !nfcReady || draft.nfc_uid != null;
    $('btn-nfc-start').disabled = readerBusy;
    if (draft.nfc_uid) { nfcTitle.textContent = 'Card registered'; nfcDesc.textContent = 'NFC card enrolled'; enrolledNfcUid = draft.nfc_uid; }
    else if (!nfcReady) { nfcTitle.textContent = 'Reader unavailable'; nfcDesc.textContent = 'Connect an NFC reader to continue'; enrolledNfcUid = null; }
    else { nfcTitle.textContent = 'Hold card to reader'; nfcDesc.textContent = draft.message || 'Tap your card on the contactless reader'; enrolledNfcUid = null; }
    if (draft.status === 'failed' || draft.stage === 'error') {
      const msg = draft.message || 'Reader operation failed. Retry or skip.';
      error('fp-error', msg); error('nfc-error', msg);
    } else { error('fp-error'); error('nfc-error'); }
  }

  async function readerRequest(path, method = 'GET', body) {
    const response = await fetch(path, {method, credentials: 'same-origin', cache: 'no-store',
      headers: body ? {'Content-Type': 'application/json'} : undefined,
      body: body ? JSON.stringify(body) : undefined});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || 'Reader unavailable');
    return data;
  }
  const readerPath = () => readerDraft ? `/api/readers/enrolments/${encodeURIComponent(readerDraft.id)}` : null;
  async function ensureReaderDraft() {
    if (readerDraft) return readerDraft;
    if (readerCreatePromise) return readerCreatePromise;
    readerCreatePromise = (async () => {
      const draft = await readerRequest('/api/readers/enrolments', 'POST', {});
      renderReaderDraft(draft); ensureReaderPolling(); return draft;
    })();
    try { return await readerCreatePromise; }
    finally { readerCreatePromise = null; }
  }
  async function readerAction(action, source = 'fp-error') {
    if (readerBusy) return false;
    readerGeneration += 1;
    readerBusy = true; $('btn-fp-start').disabled = true; $('btn-fp-finish').disabled = true; $('btn-nfc-start').disabled = true;
    $('btn-fp-skip').disabled = true; $('btn-nfc-skip').disabled = true;
    error(source);
    try {
      if (action === 'fingerprint' || action === 'nfc') await ensureReaderDraft();
      if (!readerDraft) return false;
      const draft = await readerRequest(readerPath(), 'POST', {action});
      renderReaderDraft(draft); return true;
    } catch (err) {
      error(source, err.message || 'Reader unavailable');
      if (!readerDraft) {
        renderReaderDraft({id: null, status: 'failed', stage: 'error', readers: {ready: false}, message: err.message});
      }
      return false;
    } finally {
      readerBusy = false;
      $('btn-fp-start').disabled = false; $('btn-fp-finish').disabled = false; $('btn-nfc-start').disabled = false;
      $('btn-fp-skip').disabled = false; $('btn-nfc-skip').disabled = false;
    }
  }
  async function pollReader() {
    if (!readerDraft || readerBusy || readerStatusPolling || document.hidden || saved) return;
    readerStatusPolling = true;
    const generation = readerGeneration;
    try {
      const draft = await readerRequest(readerPath());
      if (!readerBusy && generation === readerGeneration && !saved) renderReaderDraft(draft);
    } catch (err) {
      if (readerDraft && !readerBusy && generation === readerGeneration) {
        error(step === 2 ? 'fp-error' : 'nfc-error', err.message || 'Reader status unavailable');
      }
    } finally { readerStatusPolling = false; }
  }
  function ensureReaderPolling() {
    clearInterval(readerPoll); readerPoll = null;
    if (readerDraft && !saved) { pollReader(); readerPoll = setInterval(pollReader, 400); }
  }
  async function cancelReaderDraft(beacon = false) {
    readerGeneration += 1;
    clearInterval(readerPoll); readerPoll = null;
    if (!readerDraft || saved) return;
    const url = readerPath(); const payload = JSON.stringify({action: 'cancel'});
    if (beacon && navigator.sendBeacon) {
      navigator.sendBeacon(url, new Blob([payload], {type: 'application/json'})); readerDraft = null; return;
    }
    try { await readerRequest(url, 'POST', {action: 'cancel'}); } catch { /* expiry remains server-owned */ }
    readerDraft = null;
  }

  // --- Step 1 Form Actions ---
  $('input-fullname').addEventListener('input', () => {
    $('btn-step1-next').hidden = !$('input-fullname').value.trim();
    error('identity-error');
  });

  $('identity-form').addEventListener('submit', event => {
    event.preventDefault();
    if (!values().name) { error('identity-error', 'Enter your full name'); $('input-fullname').focus(); return; }
    if (!$('identity-form').reportValidity()) return;
    error('identity-error');
    setStep(2);
  });

  $('btn-step2-back').addEventListener('click', () => setStep(1));
  $('btn-fp-start').addEventListener('click', () => readerAction('fingerprint'));
  $('btn-fp-finish').addEventListener('click', () => readerAction('finish'));
  $('btn-fp-skip').addEventListener('click', async () => {
    if (readerBusy) return;
    if (readerCreatePromise) await readerCreatePromise.catch(() => null);
    if (readerDraft && readerDraft.fp_template == null && !await readerAction('skip_fingerprint')) return;
    setStep(3);
  });

  $('btn-step3-back').addEventListener('click', () => setStep(2));
  $('btn-nfc-start').addEventListener('click', () => readerAction('nfc', 'nfc-error'));
  $('btn-nfc-skip').addEventListener('click', async () => {
    if (readerBusy) return;
    if (readerCreatePromise) await readerCreatePromise.catch(() => null);
    if (readerDraft && !readerDraft.nfc_uid && !await readerAction('skip_nfc', 'nfc-error')) return;
    review(values(), [...document.querySelectorAll('sbb-checkbox[name="access"]')].filter(c => c.checked).map(c => c.textContent.trim()));
    setStep(4);
  });

  $('btn-step4-back').addEventListener('click', () => setStep(3));
  $('btn-edit-details').addEventListener('click', () => setStep(1));

  $('enrolment-close-btn').addEventListener('click', event => {
    stopCamera();
    if (dirty()) { event.preventDefault(); $('discard-dialog').open(); }
    else cancelReaderDraft(true);
  });

  window.addEventListener('beforeunload', event => { if (dirty()) { event.preventDefault(); event.returnValue = ''; } });
  $('discard-dialog').querySelector('sbb-button-link').addEventListener('click', () => { stopCamera(); cancelReaderDraft(true); saved = true; });
  window.addEventListener('pagehide', () => { if (!saved) cancelReaderDraft(true); });

  // --- Step 4 Save to Database ---
  $('btn-finish-enrolment').addEventListener('click', async () => {
    if (saving || saved || step !== 4) return;
    saving = true; $('btn-finish-enrolment').disabled = true; $('btn-finish-enrolment').loading = true;
    $('enrolment-close-btn').disabled = true; $('btn-edit-details').disabled = true; $('btn-step4-back').disabled = true;
    error('save-error');
    try {
      const response = await fetch('/api/enrolment/complete', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({...values(), ...(readerDraft ? {reader_session: readerDraft.id} : {})})
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || 'Could not save. Try again.');
      saved = true;
      clearInterval(readerPoll); readerPoll = null;
      review(result.user, result.user.access, result.user.credentials || result.credentials || []);
      const card = document.querySelector('.final-card').cloneNode(true);
      card.querySelectorAll('[id]').forEach(el => el.removeAttribute('id'));
      $('saved-card-host').replaceChildren(card);
      setStep('success');
    } catch (err) {
      error('save-error', err.message || 'Could not save. Try again.');
    } finally {
      saving = false; $('btn-finish-enrolment').disabled = false; $('btn-finish-enrolment').loading = false;
      $('enrolment-close-btn').disabled = false; $('btn-edit-details').disabled = false; $('btn-step4-back').disabled = false;
    }
  });

  // --- Enrol Another User ---
  $('btn-enrol-another').addEventListener('click', () => {
    cancelReaderDraft(); readerDraft = null; enrolledFp = false; enrolledNfcUid = null;
    $('identity-form').reset();
    document.querySelectorAll('sbb-checkbox[name="access"]').forEach(c => c.checked = false);
    setPhoto(defaultPhoto);
    renderReaderDraft({id: null, status: 'active', stage: 'idle', readers: {ready: false}});
    saved = false;
    $('btn-step1-next').hidden = true;
    $('saved-card-host').replaceChildren();
    error('save-error');
    error('identity-error');
    setStep(1);
  });

  // --- Photo Cropping and Camera ---
  async function cropImage(source, fraction = 1, mirror = false) {
    const w = source.videoWidth || source.naturalWidth, h = source.videoHeight || source.naturalHeight;
    if (!w || !h) throw new Error('Photo unavailable. Try again.');
    const side = Math.min(w, h) * fraction;
    const canvas = document.createElement('canvas'); canvas.width = canvas.height = 480;
    const ctx = canvas.getContext('2d');
    if (mirror) { ctx.translate(480, 0); ctx.scale(-1, 1); }
    ctx.drawImage(source, (w - side) / 2, (h - side) / 2, side, side, 0, 0, 480, 480);
    return canvas.toDataURL('image/png');
  }

  $('btn-choose-file').addEventListener('click', () => { $('photo-menu').close(); $('photo-file-input').click(); });
  $('btn-remove-photo').addEventListener('click', () => { setPhoto(defaultPhoto); $('photo-menu').close(); });

  $('photo-file-input').addEventListener('change', async event => {
    const file = event.target.files[0]; if (!file) return;
    if (!['image/jpeg','image/png','image/webp'].includes(file.type) || file.size > 8 * 1024 * 1024) {
      error('identity-error', 'Choose a JPG, PNG or WebP photo under 8 MB'); event.target.value = ''; return;
    }
    const url = URL.createObjectURL(file);
    try {
      const image = new Image(); image.src = url; await image.decode();
      setPhoto(await cropImage(image)); error('identity-error');
    } catch { error('identity-error', 'Could not open this photo. Choose another.'); }
    finally { URL.revokeObjectURL(url); event.target.value = ''; }
  });

  function stopCamera() {
    cameraGeneration++;
    stream?.getTracks().forEach(t => t.stop()); stream = null;
    $('webcam-video').srcObject = null; $('btn-camera-capture').disabled = true;
  }

  $('camera-dialog').addEventListener('willClose', stopCamera);
  window.addEventListener('pagehide', stopCamera);
  $('btn-camera-cancel').addEventListener('click', () => $('camera-dialog').close());

  $('btn-choose-camera').addEventListener('click', async () => {
    $('photo-menu').close(); error('camera-error'); stopCamera();
    const generation = cameraGeneration;
    $('camera-dialog').open();
    try {
      const acquired = await navigator.mediaDevices.getUserMedia({video: {facingMode:'user', width:{ideal:720},height:{ideal:720}}, audio:false});
      if (generation !== cameraGeneration) { acquired.getTracks().forEach(t => t.stop()); return; }
      stream = acquired; $('webcam-video').srcObject = stream;
      await $('webcam-video').play();
      if (generation === cameraGeneration) $('btn-camera-capture').disabled = false;
    } catch { error('camera-error', 'Camera unavailable. Allow camera access or choose a photo.'); }
  });

  $('btn-camera-capture').addEventListener('click', async () => {
    if (!stream) return;
    try { setPhoto(await cropImage($('webcam-video'), 0.76, true)); $('camera-dialog').close(); }
    catch (err) { error('camera-error', err.message); }
  });

  document.querySelector('.enrolment-page').dataset.ready = 'true';
};

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', ready, {once:true}); else ready();
