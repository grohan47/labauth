import os
import secrets
import time

from nicegui import ui

DEFAULT_ADMIN_PASSWORD = "labauth@2026"
SESSION_MAX_AGE_SECONDS = 3600.0  # 1 hour active session

# In-memory store: session_token -> last_active_timestamp
_admin_sessions: dict[str, float] = {}


def admin_password_is_valid(password: str) -> bool:
    """Validate the hardcoded admin password (labauth@2026)."""
    expected = os.environ.get("LABAUTH_ADMIN_PASSWORD", DEFAULT_ADMIN_PASSWORD)
    return bool(password) and password == expected


def create_admin_session() -> str:
    """Create a new authenticated admin session token."""
    token = secrets.token_urlsafe(32)
    _admin_sessions[token] = time.time()
    return token


def is_admin_session_valid(token: str | None) -> bool:
    """Check if the given admin session token is still active and valid."""
    if not token or token not in _admin_sessions:
        return False
    created_at = _admin_sessions[token]
    if time.time() - created_at > SESSION_MAX_AGE_SECONDS:
        _admin_sessions.pop(token, None)
        return False
    # Refresh activity timestamp
    _admin_sessions[token] = time.time()
    return True


def destroy_admin_session(token: str | None) -> None:
    """Invalidate and remove an active admin session."""
    if token:
        _admin_sessions.pop(token, None)


ADMIN_ICONS_JS = """
const ADMIN_ICONS = {
    'fingerprint-medium': '<svg xmlns="http://www.w3.org/2000/svg" width="36" height="36" fill="none" viewBox="0 0 36 36"><path fill="currentColor" fill-rule="evenodd" d="M11.642 4.402a23 23 0 0 1 2.607-.153c4.36 0 8.432 1.2 11.93 3.273l.51-.86a24.3 24.3 0 0 0-12.44-3.413c-.923 0-1.829.058-2.72.16zm-5.443 3.42a21.4 21.4 0 0 1 8.05-1.573c6.312 0 11.971 2.738 15.902 7.067l-.74.672C25.66 9.857 20.265 7.249 14.25 7.249c-2.715 0-5.302.54-7.675 1.5zm8.05 2.428c-3.306 0-6.388.934-9.028 2.53l-.518-.856A18.4 18.4 0 0 1 14.25 9.25c6.866 0 12.842 3.748 16.034 9.297l-.867.498c-3.021-5.253-8.675-8.795-15.167-8.795M5.273 20.574a11.47 11.47 0 0 1 8.978-4.324c6.322 0 11.448 5.103 11.495 11.414l1-.008c-.05-6.86-5.623-12.406-12.495-12.406-3.952 0-7.47 1.84-9.759 4.7zM4.181 15.98A15.43 15.43 0 0 1 14.25 12.25c7.052 0 12.992 4.713 14.871 11.156l-.96.28C26.403 17.657 20.844 13.25 14.25 13.25a14.43 14.43 0 0 0-9.418 3.489zm4.578 11.692a5.495 5.495 0 0 1 10.991.079v4.044h1V27.75a6.495 6.495 0 0 0-12.991-.094zM5.6 23.835c1.492-3.29 4.798-5.585 8.65-5.585a9.5 9.5 0 0 1 9.5 9.5v2.645h-1V27.75a8.5 8.5 0 0 0-8.5-8.5c-3.443 0-6.403 2.051-7.739 4.998zm8.65.415a3.5 3.5 0 0 0-3.5 3.5v2.645h1V27.75a2.5 2.5 0 1 1 5 0v4.5h1v-4.5a3.5 3.5 0 0 0-3.5-3.5m-.5 7.25V27h1v4.5z" clip-rule="evenodd"/></svg>',
    'fingerprint-small': '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" fill="none" viewBox="0 0 24 24"><path fill="currentColor" fill-rule="evenodd" d="M7.78 3.1q.85-.098 1.719-.1c2.876 0 5.561.791 7.869 2.158l.51-.86a16.4 16.4 0 0 0-8.379-2.299c-.622 0-1.232.04-1.832.108zM4.07 5.06A14.45 14.45 0 0 1 9.5 4c4.257 0 8.073 1.846 10.724 4.765l-.74.672C17.013 6.717 13.461 5 9.5 5c-1.788 0-3.49.355-5.054.987zM9.5 7c-2.173 0-4.198.613-5.933 1.663l-.518-.856A12.43 12.43 0 0 1 9.5 6c4.64 0 8.678 2.533 10.834 6.281l-.866.499C17.48 9.327 13.765 7 9.5 7m-5.855 6.82A7.48 7.48 0 0 1 9.5 11a7.5 7.5 0 0 1 7.497 7.444l1-.008A8.5 8.5 0 0 0 9.5 10a8.48 8.48 0 0 0-6.636 3.195zm-.966-3.294A10.45 10.45 0 0 1 9.499 8c4.778 0 8.802 3.193 10.075 7.557l-.96.28C17.462 11.887 13.82 9 9.5 9a9.45 9.45 0 0 0-6.17 2.286zm3.327 7.924A3.497 3.497 0 0 1 13 18.5v2.696h1V18.5a4.497 4.497 0 0 0-8.994-.065zM3.582 15.82A6.497 6.497 0 0 1 16 18.501v1.763h-1V18.5a5.497 5.497 0 0 0-10.507-2.266zM9.5 16A2.5 2.5 0 0 0 7 18.5v1.763h1V18.5a1.5 1.5 0 1 1 3 0v3h1v-3A2.5 2.5 0 0 0 9.5 16M9 21v-3h1v3z" clip-rule="evenodd"/></svg>',
    'document-text-medium': '<svg xmlns="http://www.w3.org/2000/svg" width="36" height="36" fill="none" viewBox="0 0 36 36"><path fill="currentColor" fill-rule="evenodd" d="M9.252 6.245h9.707l.147.146 7.5 7.5.146.146v15.708h-17.5v-23.5m1 1v21.5h15.5v-14h-7.5v-7.5zm9 .707 5.793 5.793h-5.793zM13.5 19.25h9v-1h-9zm9 3h-9.004v-1H22.5zm-9 3h9v-1h-9z" clip-rule="evenodd"/></svg>',
    'document-text-small': '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" fill="none" viewBox="0 0 24 24"><path fill="currentColor" fill-rule="evenodd" d="M6 4h7l5 5v11H6V4zm1 1v14h10V9.5h-4.5V5H7zm7 .5V9h3.5L14 5.5zM9 12h6v1H9v-1zm6 3H9v-1h6v1zm-6 3h6v-1H9v1z" clip-rule="evenodd"/></svg>',
    'magnifying-glass-medium': '<svg xmlns="http://www.w3.org/2000/svg" width="36" height="36" fill="none" viewBox="0 0 36 36"><path fill="currentColor" fill-rule="evenodd" d="M4.25 15.75c0-5.522 4.476-10 10-10s10 4.478 10 10c0 5.524-4.476 10-10 10s-10-4.476-10-10m10-11c-6.076 0-11 4.926-11 11 0 6.076 4.924 11 11 11 2.913 0 5.56-1.131 7.528-2.979l9.395 8.107.654-.757-9.35-8.068a10.96 10.96 0 0 0 2.773-7.303c0-6.074-4.924-11-11-11" clip-rule="evenodd"/></svg>',
    'magnifying-glass-small': '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" fill="none" viewBox="0 0 24 24"><path fill="currentColor" fill-rule="evenodd" d="M3 10.5a7.5 7.5 0 1 1 15 0 7.5 7.5 0 0 1-15 0m7.5-6.5a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13m5.854 11.646 4.5 4.5-.708.708-4.5-4.5z" clip-rule="evenodd"/></svg>',
    'sign-exclamation-point-medium': '<svg xmlns="http://www.w3.org/2000/svg" width="36" height="36" fill="none" viewBox="0 0 36 36"><path fill="currentColor" fill-rule="evenodd" d="m17.25 3.376.447.901 13.05 26.25.36.723H3.392l.359-.723 13.05-26.25zM29.493 30.25 17.25 5.623 5.006 30.25zM16.75 27v-3h1v3zm1-6v-9h-1v9z" clip-rule="evenodd"/></svg>',
    'sign-exclamation-point-small': '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" fill="none" viewBox="0 0 24 24"><path fill="currentColor" fill-rule="evenodd" d="m11.5 1.877.448.9 8.7 17.5.36.723H1.992l.36-.723 8.7-17.5zM3.607 20h15.786L11.5 4.123zM11 18v-2h1v2zm1-4V8h-1v6z" clip-rule="evenodd"/></svg>',
    'exit-small': '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" fill="none" viewBox="0 0 24 24"><path fill="currentColor" fill-rule="evenodd" d="M3.5 4H3v16h13v-3h-1v2H4V5h11v2h1V4H3.5m14.212 5.005 3.142 3.141.353.354-.353.353-3.142 3.15-.707-.707L19.295 13H7v-1h12.293l-2.288-2.287z" clip-rule="evenodd"/></svg>',
    'cross-small': '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" fill="none" viewBox="0 0 24 24"><path fill="currentColor" fill-rule="evenodd" d="m12.707 12 5.647-5.647-.707-.707L12 11.293 6.354 5.646l-.708.707L11.293 12l-5.647 5.646.708.707L12 12.707l5.647 5.646.707-.707z" clip-rule="evenodd"/></svg>'
};

globalThis.sbbConfig = globalThis.sbbConfig || {};
globalThis.sbbConfig.icon = globalThis.sbbConfig.icon || {};
globalThis.sbbConfig.icon.interceptor = function(context) {
    if (context && context.name && ADMIN_ICONS[context.name]) {
        return ADMIN_ICONS[context.name];
    }
    return typeof context.request === 'function' ? context.request() : Promise.resolve('');
};
"""


def admin_chrome() -> str:
    """Return the Lyne-only controls which distinguish the admin display."""
    return """
        <sbb-header class="admin-titlebar" expanded size="s">
            <sbb-header-link class="admin-brand" href="/admin-display" aria-label="LabAuth admin display">
                <span class="admin-brand__content">
                    <span class="admin-brand__name">LabAuth</span>
                    <svg class="admin-brand__logo" viewBox="0 0 59.233 20.603" xmlns="http://www.w3.org/2000/svg" aria-label="SBB" role="img" focusable="false">
                        <path d="M0 0h59.233v20.603H0V0z" fill="#EC0000"/>
                        <path d="M35.186 17.02h3.75l-5.047-5.163h6.265v5.163h2.96v-5.163h6.267l-5.05 5.163h3.752l6.427-6.708-6.426-6.73h-3.752l5.05 5.185h-6.266V3.583h-2.96v5.184h-6.267l5.047-5.184h-3.75l-6.43 6.73 6.43 6.707" fill="#FFF"/>
                    </svg>
                </span>
            </sbb-header-link>
            <div class="sbb-header-spacer"></div>
            <sbb-header-button id="admin-access-button" type="button">
                <svg slot="icon" class="admin-access-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                    <path d="M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm-7 9.5c0-3.6 3.1-6.5 7-6.5s7 2.9 7 6.5v.5H5v-.5Z"></path>
                </svg>
                Admin
            </sbb-header-button>
        </sbb-header>

        <sbb-dialog id="admin-password-dialog" backdrop="translucent" backdrop-action="close">
            <sbb-dialog-title>Admin access</sbb-dialog-title>
            <sbb-dialog-close-button id="admin-dialog-close" aria-label="Close dialog"></sbb-dialog-close-button>
            <sbb-dialog-content>
                <form id="admin-password-form" novalidate>
                    <p class="admin-dialog__intro">Enter the admin password to continue.</p>
                    <sbb-form-field size="m" width="default" floating-label class="admin-password-field">
                        <label for="admin-password-input">Password</label>
                        <input id="admin-password-input" name="password" type="password" autocomplete="current-password" required>
                        <sbb-error id="admin-password-error" slot="error" hidden></sbb-error>
                    </sbb-form-field>
                </form>
            </sbb-dialog-content>
            <sbb-dialog-actions>
                <sbb-secondary-button id="admin-password-cancel" type="button">Cancel</sbb-secondary-button>
                <sbb-button id="admin-password-submit" type="submit" form="admin-password-form">Continue</sbb-button>
            </sbb-dialog-actions>
        </sbb-dialog>
    """


def build_admin_display() -> None:
    """Render the standard live display with the admin-only Lyne title bar."""
    from ui.display import build_display

    build_display(admin=True)


def build_admin_panel() -> None:
    """Render the full Swiss-design Admin Panel under /admin with SBB clock, Exit, and 4x4 cards."""
    from ui.display import _color_scheme
    current_theme = _color_scheme()

    ui.add_head_html(f"""
        <link rel="icon" type="image/svg+xml" href="/static/favicon.svg">
        <link rel="stylesheet" href="/static/vendor/sbb-variables.css">
        <link rel="stylesheet" href="/static/vendor/standard-theme.css">
        <link rel="stylesheet" href="/static/display.css?v=36">
        <script>
            (function() {{
                const theme = "{current_theme}";
                document.documentElement.setAttribute('data-theme', theme);
                document.documentElement.style.colorScheme = theme;
            }})();
            {ADMIN_ICONS_JS}
        </script>
        <script type="module" src="/static/vendor/sbb-elements.bundle.js"></script>
    """)

    admin_markup = f"""
        <main class="admin-panel" data-theme="{current_theme}">
            <sbb-container color="transparent" expanded class="admin-panel-shell">
                <!-- Top Header: Left 'Admin.', Right Exit button & isolated pure SBB clock -->
                <header class="admin-header">
                    <h1 class="admin-heading">Admin.</h1>
                    <div class="admin-header-controls">
                        <sbb-secondary-button id="admin-exit-btn" size="m" aria-label="Exit admin panel">
                            <sbb-icon slot="icon" name="exit-small"></sbb-icon>
                            Exit
                        </sbb-secondary-button>
                        <div class="admin-clock-wrapper" aria-label="Analogue clock">
                            <sbb-clock></sbb-clock>
                        </div>
                    </div>
                </header>

                <!-- Grid: 4 large rectangular Lyne cards arranged in a 4x4 coordinate space -->
                <div class="admin-cards-grid">
                    <!-- 1. Enrollment: leads to /enrollment -->
                    <sbb-card color="transparent-bordered" class="admin-card">
                        <sbb-card-link href="/enrollment">Enrollment</sbb-card-link>
                        <div class="admin-card-inner">
                            <sbb-icon name="fingerprint-medium" class="admin-card-icon"></sbb-icon>
                            <span class="admin-card-label">Enrollment</span>
                        </div>
                    </sbb-card>

                    <!-- 2. Logs: redirects to /logs -->
                    <sbb-card color="transparent-bordered" class="admin-card">
                        <sbb-card-link href="/logs">Logs</sbb-card-link>
                        <div class="admin-card-inner">
                            <sbb-icon name="document-text-medium" class="admin-card-icon"></sbb-icon>
                            <span class="admin-card-label">Logs</span>
                        </div>
                    </sbb-card>

                    <!-- 3. Search: search by name in /search -->
                    <sbb-card color="transparent-bordered" class="admin-card">
                        <sbb-card-link href="/search">Search</sbb-card-link>
                        <div class="admin-card-inner">
                            <sbb-icon name="magnifying-glass-medium" class="admin-card-icon"></sbb-icon>
                            <span class="admin-card-label">Search</span>
                        </div>
                    </sbb-card>

                    <!-- 4. Alerts: caution symbol, opens alert dialog to type alerts for /display -->
                    <sbb-card color="transparent-bordered" class="admin-card" id="admin-card-alerts">
                        <sbb-card-button id="admin-alerts-open-btn">Alerts</sbb-card-button>
                        <div class="admin-card-inner">
                            <sbb-icon name="sign-exclamation-point-medium" class="admin-card-icon"></sbb-icon>
                            <span class="admin-card-label">Alerts</span>
                        </div>
                    </sbb-card>
                </div>
            </sbb-container>

            <!-- Alerts Dialog: Place for admins to type alerts displayed on /display -->
            <sbb-dialog id="admin-alerts-dialog" trigger="admin-alerts-open-btn" backdrop="translucent" backdrop-action="close">
                <sbb-dialog-title>Lab Alerts</sbb-dialog-title>
                <sbb-dialog-close-button id="admin-alerts-close" aria-label="Close dialog"></sbb-dialog-close-button>
                <sbb-dialog-content>
                    <form id="admin-alerts-form" novalidate>
                        <p class="admin-dialog__intro">Enter an announcement or safety alert to display in the lab.</p>
                        <sbb-form-field size="m" width="default" floating-label class="admin-alert-field">
                            <label for="admin-alert-input">Alert message</label>
                            <input id="admin-alert-input" name="alert" type="text" placeholder="e.g. Laser cutter maintenance in progress" autocomplete="off">
                        </sbb-form-field>
                        <div id="admin-active-alert-status" class="admin-active-alert-status" hidden>
                            <span class="admin-alert-status-label">Active:</span>
                            <span id="admin-active-alert-text"></span>
                        </div>
                    </form>
                </sbb-dialog-content>
                <sbb-dialog-actions>
                    <sbb-secondary-button id="admin-alerts-clear" type="button">Clear alert</sbb-secondary-button>
                    <sbb-button id="admin-alerts-submit" type="submit" form="admin-alerts-form">Broadcast</sbb-button>
                </sbb-dialog-actions>
            </sbb-dialog>
        </main>
    """

    admin_script = """
        function initAdminPanel() {
            const exitBtn = document.querySelector('#admin-exit-btn');
            const alertsCard = document.querySelector('#admin-card-alerts');
            const alertsBtn = document.querySelector('#admin-alerts-open-btn');
            const alertsDialog = document.querySelector('#admin-alerts-dialog');
            const alertsClose = document.querySelector('#admin-alerts-close');
            const alertsForm = document.querySelector('#admin-alerts-form');
            const alertsInput = document.querySelector('#admin-alert-input');
            const alertsClear = document.querySelector('#admin-alerts-clear');
            const alertsSubmit = document.querySelector('#admin-alerts-submit');
            const statusWrap = document.querySelector('#admin-active-alert-status');
            const statusText = document.querySelector('#admin-active-alert-text');

            if (!exitBtn || !alertsCard || !alertsDialog) {
                window.requestAnimationFrame(initAdminPanel);
                return;
            }

            exitBtn.addEventListener('click', async () => {
                try {
                    await fetch('/api/admin/logout', { method: 'POST' });
                } catch (e) {
                    console.error('Logout error', e);
                } finally {
                    window.location.assign('/admin-display');
                }
            });

            const loadAlert = async () => {
                try {
                    const res = await fetch('/api/alerts');
                    if (res.ok) {
                        const data = await res.json();
                        const current = data.alert || '';
                        if (alertsInput) alertsInput.value = current;
                        if (statusText && statusWrap) {
                            if (current) {
                                statusText.textContent = current;
                                statusWrap.hidden = false;
                            } else {
                                statusWrap.hidden = true;
                            }
                        }
                    }
                } catch (e) {}
            };

            const openAlerts = () => {
                loadAlert();
                if (alertsDialog) {
                    if (typeof alertsDialog.open === 'function') {
                        alertsDialog.open();
                    } else if (alertsDialog.showModal) {
                        alertsDialog.showModal();
                    }
                }
                setTimeout(() => alertsInput && alertsInput.focus(), 100);
            };

            const closeAlerts = () => {
                if (alertsDialog) {
                    if (typeof alertsDialog.close === 'function') {
                        alertsDialog.close();
                    }
                }
            };

            alertsCard.addEventListener('click', (e) => {
                openAlerts();
            });

            if (alertsBtn) {
                alertsBtn.addEventListener('click', (e) => {
                    openAlerts();
                });
            }

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
                    const val = (alertsInput ? alertsInput.value : '').trim();
                    try {
                        if (alertsSubmit) alertsSubmit.loading = true;
                        await fetch('/api/alerts', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ alert: val }),
                        });
                        closeAlerts();
                    } catch (err) {
                        console.error('Error broadcasting alert', err);
                    } finally {
                        if (alertsSubmit) alertsSubmit.loading = false;
                    }
                });
            }

            if (alertsClear) {
                alertsClear.addEventListener('click', async () => {
                    try {
                        alertsClear.loading = true;
                        await fetch('/api/alerts', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ alert: '' }),
                        });
                        if (alertsInput) alertsInput.value = '';
                        if (statusWrap) statusWrap.hidden = true;
                        closeAlerts();
                    } catch (err) {
                        console.error('Error clearing alert', err);
                    } finally {
                        alertsClear.loading = false;
                    }
                });
            }
        }

        initAdminPanel();
    """

    ui.html(admin_markup, sanitize=False).classes("w-full h-full admin-panel-host")
    ui.add_body_html(f"<script>{admin_script}</script>")
