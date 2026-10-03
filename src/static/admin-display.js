function initialiseAdminAccess() {
  const trigger = document.querySelector('#admin-access-button');
  const dialog = document.querySelector('#admin-password-dialog');
  const form = document.querySelector('#admin-password-form');
  const input = document.querySelector('#admin-password-input');
  const error = document.querySelector('#admin-password-error');
  const cancel = document.querySelector('#admin-password-cancel');
  const submit = document.querySelector('#admin-password-submit');
  const closeBtn = document.querySelector('#admin-dialog-close, sbb-dialog-close-button');

  if (!trigger || !dialog || !form || !input || !error || !cancel || !submit) {
    window.requestAnimationFrame(initialiseAdminAccess);
    return;
  }

  const clearError = () => {
    error.textContent = '';
    error.hidden = true;
  };

  const showError = (message) => {
    error.textContent = message;
    error.hidden = false;
    input.focus();
  };

  const close = () => {
    input.value = '';
    clearError();
    if (typeof dialog.close === 'function') {
      dialog.close();
    }
  };

  trigger.addEventListener('click', () => {
    input.value = '';
    clearError();
    if (typeof dialog.open === 'function') {
      dialog.open();
    }
    window.setTimeout(() => input.focus(), 50);
  });

  cancel.addEventListener('click', close);

  if (closeBtn) {
    closeBtn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      close();
    });
  }

  dialog.addEventListener('close', () => {
    input.value = '';
    clearError();
  });

  // Handle Escape key to dismiss modal
  dialog.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      close();
    }
  });

  // Light dismiss fallback
  dialog.addEventListener('click', (event) => {
    // If clicked directly on the dialog wrapper or backdrop outside content
    if (event.target === dialog) {
      close();
    }
  });

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!input.value) {
      showError('Enter the admin password.');
      return;
    }

    submit.loading = true;
    try {
      const response = await fetch('/api/admin/login', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({password: input.value}),
      });
      if (!response.ok) {
        input.value = '';
        showError('Incorrect password.');
        return;
      }
      const result = await response.json();
      window.location.assign(result.redirect || '/admin');
    } catch {
      showError('Unable to verify the password. Please try again.');
    } finally {
      submit.loading = false;
    }
  });
}

initialiseAdminAccess();
