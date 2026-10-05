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
  let fpStatus = 'waiting';
  let nfcStatus = 'waiting';
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
  }

  function setPhoto(src) {
    photo = src;
    $('mock-card-avatar').src = src;
    $('btn-remove-photo').hidden = src === defaultPhoto;
  }

  function review(record, access) {
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

  // --- Biometric & NFC Reader States with Large Checkmark Sync ---
  function setFingerprintStatus(status) {
    fpStatus = status;
    const anim = $('fp-animation');
    const checkmark = $('fp-checkmark');
    const title = $('fp-status-title');
    const desc = $('fp-status-desc');
    const skipBtn = $('btn-fp-skip');

    if (status === 'complete' || status === 'verified') {
      if (anim) anim.hidden = true;
      if (checkmark) checkmark.hidden = false;
      if (title) title.textContent = 'Fingerprint Enrolled';
      if (desc) desc.textContent = 'Biometric template registered';
      if (skipBtn) {
        skipBtn.textContent = 'Next';
        skipBtn.setAttribute('icon-name', 'arrow-right-small');
      }
      enrolledFp = true;
    } else if (status === 'unavailable') {
      if (anim) anim.hidden = false;
      if (checkmark) checkmark.hidden = true;
      if (title) title.textContent = 'Reader unavailable';
      if (desc) desc.textContent = 'Hardware not detected';
      if (skipBtn) {
        skipBtn.textContent = 'Skip';
        skipBtn.setAttribute('icon-name', 'arrow-right-small');
      }
      enrolledFp = false;
    } else {
      // 'waiting' / scanning state
      if (anim) anim.hidden = false;
      if (checkmark) checkmark.hidden = true;
      if (title) title.textContent = 'Reader ready';
      if (desc) desc.textContent = 'Touch the biometric sensor to register fingerprint';
      if (skipBtn) {
        skipBtn.textContent = 'Skip';
        skipBtn.setAttribute('icon-name', 'arrow-right-small');
      }
      enrolledFp = false;
    }
  }

  function setNfcStatus(status, uid) {
    nfcStatus = status;
    const anim = $('nfc-tap-animation');
    const checkmark = $('nfc-checkmark');
    const title = $('nfc-status-title');
    const desc = $('nfc-status-desc');
    const skipBtn = $('btn-nfc-skip');

    if (status === 'complete' || status === 'verified' || status === 'tapped') {
      const cardUid = uid || 'C8:CB:70:69:F0';
      if (anim) anim.hidden = true;
      if (checkmark) checkmark.hidden = false;
      if (title) title.textContent = 'Card Registered';
      if (desc) desc.textContent = `Unique UID: ${cardUid}`;
      if (skipBtn) {
        skipBtn.textContent = 'Next';
        skipBtn.setAttribute('icon-name', 'arrow-right-small');
      }
      enrolledNfcUid = cardUid;
    } else if (status === 'unavailable') {
      if (anim) anim.hidden = false;
      if (checkmark) checkmark.hidden = true;
      if (title) title.textContent = 'Reader unavailable';
      if (desc) desc.textContent = 'Tap reader not detected';
      if (skipBtn) {
        skipBtn.textContent = 'Skip';
        skipBtn.setAttribute('icon-name', 'arrow-right-small');
      }
      enrolledNfcUid = null;
    } else {
      // 'waiting' state
      if (anim) anim.hidden = false;
      if (checkmark) checkmark.hidden = true;
      if (title) title.textContent = 'Hold card to reader';
      if (desc) desc.textContent = 'Tap your card on the contactless reader';
      if (skipBtn) {
        skipBtn.textContent = 'Skip';
        skipBtn.setAttribute('icon-name', 'arrow-right-small');
      }
      enrolledNfcUid = null;
    }
  }

  window.setFingerprintStatus = setFingerprintStatus;
  window.setNfcStatus = setNfcStatus;

  // Click on stage toggles simulation so user can easily test the transitions and checkmarks
  if ($('fp-stage')) {
    $('fp-stage').addEventListener('click', () => {
      setFingerprintStatus(fpStatus === 'complete' ? 'waiting' : 'complete');
    });
  }
  if ($('nfc-stage')) {
    $('nfc-stage').addEventListener('click', () => {
      setNfcStatus(nfcStatus === 'complete' ? 'waiting' : 'complete');
    });
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
  $('btn-fp-skip').addEventListener('click', () => setStep(3));

  $('btn-step3-back').addEventListener('click', () => setStep(2));
  $('btn-nfc-skip').addEventListener('click', () => {
    review(values(), [...document.querySelectorAll('sbb-checkbox[name="access"]')].filter(c => c.checked).map(c => c.textContent.trim()));
    setStep(4);
  });

  $('btn-step4-back').addEventListener('click', () => setStep(3));
  $('btn-edit-details').addEventListener('click', () => setStep(1));

  $('enrolment-close-btn').addEventListener('click', event => {
    stopCamera();
    if (dirty()) { event.preventDefault(); $('discard-dialog').open(); }
  });

  window.addEventListener('beforeunload', event => { if (dirty()) { event.preventDefault(); event.returnValue = ''; } });
  $('discard-dialog').querySelector('sbb-button-link').addEventListener('click', () => { saved = true; stopCamera(); });

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
        body: JSON.stringify(values())
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || 'Could not save. Try again.');
      saved = true;
      review(result.user, result.user.access);
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
    $('identity-form').reset();
    document.querySelectorAll('sbb-checkbox[name="access"]').forEach(c => c.checked = false);
    setPhoto(defaultPhoto);
    setFingerprintStatus('waiting');
    setNfcStatus('waiting');
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
