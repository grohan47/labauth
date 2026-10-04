"""Swiss-style Lyne Enrolment Flow for LabAuth.

Full-screen multi-step enrolment workflow:
1. Step 1: Basic Identity & Mock Card (Name mandatory, photo & checkboxes optional)
2. Step 2: Fingerprint Enrolment & Consistency Verification
3. Step 3: NFC Authentication & Unique UID Registration
4. Step 4: Final 'ID Card' & Demographic Record Review
"""

from __future__ import annotations

from nicegui import ui
from ui.display import _color_scheme


ENROLMENT_ICONS_JS = """
const ENROLMENT_ICONS = {
    'cross-small': '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" fill="none" viewBox="0 0 24 24"><path fill="currentColor" fill-rule="evenodd" d="m12.707 12 5.647-5.647-.707-.707L12 11.293 6.354 5.646l-.708.707L11.293 12l-5.647 5.646.708.707L12 12.707l5.647 5.646.707-.707z" clip-rule="evenodd"/></svg>',
    'arrow-right-small': '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" fill="none" viewBox="0 0 24 24"><path fill="currentColor" fill-rule="evenodd" d="m13.854 6.146 5.5 5.5.353.354-.353.354-5.5 5.5-.708-.708L18.293 12.5H4v-1h14.293l-5.147-5.146.708-.708z" clip-rule="evenodd"/></svg>',
    'arrow-right-medium': '<svg xmlns="http://www.w3.org/2000/svg" width="36" height="36" fill="none" viewBox="0 0 36 36"><path fill="currentColor" fill-rule="evenodd" d="m20.78 9.22 8.25 8.25.53.53-.53.53-8.25 8.25-1.06-1.06 7.19-7.19H6v-1.5h21.84l-7.12-7.12 1.06-1.06z" clip-rule="evenodd"/></svg>',
    'arrow-left-small': '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" fill="none" viewBox="0 0 24 24"><path fill="currentColor" fill-rule="evenodd" d="m10.146 6.146-5.5 5.5-.353.354.353.354 5.5 5.5.708-.708L5.707 12.5H20v-1H5.707l5.147-5.146-.708-.708z" clip-rule="evenodd"/></svg>',
    'camera-small': '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" fill="none" viewBox="0 0 24 24"><path fill="currentColor" fill-rule="evenodd" d="M9 4.5 7.5 6.5H4a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-10a2 2 0 0 0-2-2h-3.5L15 4.5H9zM3 8.5a1 1 0 0 1 1-1h3.8l1.5-2h5.4l1.5 2H20a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1v-10zm9 9a4.5 4.5 0 1 0 0-9 4.5 4.5 0 0 0 0 9zm0-1a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7z" clip-rule="evenodd"/></svg>',
    'camera-medium': '<svg xmlns="http://www.w3.org/2000/svg" width="36" height="36" fill="none" viewBox="0 0 36 36"><path fill="currentColor" fill-rule="evenodd" d="M13.5 6.75 11.25 9.75H6a3 3 0 0 0-3 3v15a3 3 0 0 0 3 3h24a3 3 0 0 0 3-3v-15a3 3 0 0 0-3-3h-5.25L22.5 6.75h-9zM4.5 12.75A1.5 1.5 0 0 1 6 11.25h5.7l2.25-3h4.1l2.25 3H26a1.5 1.5 0 0 1 1.5 1.5v15a1.5 1.5 0 0 1-1.5 1.5H6a1.5 1.5 0 0 1-1.5-1.5v-15zm13.5 13.5a6.75 6.75 0 1 0 0-13.5 6.75 6.75 0 0 0 0 13.5zm0-1.5a5.25 5.25 0 1 0 0-10.5 5.25 5.25 0 0 0 0 10.5z" clip-rule="evenodd"/></svg>',
    'folder-open-small': '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" fill="none" viewBox="0 0 24 24"><path fill="currentColor" fill-rule="evenodd" d="M3 4h6l2 2h10v3h-1V7h-8.5l-2-2H4v14h16v-9h1v10H3V4zm5 7h13.5l-2.5 8H5.5L8 11zm1.2 1-1.8 6h11.2l1.9-6H9.2z" clip-rule="evenodd"/></svg>',
    'fingerprint-medium': '<svg xmlns="http://www.w3.org/2000/svg" width="36" height="36" fill="none" viewBox="0 0 36 36"><path fill="currentColor" fill-rule="evenodd" d="M11.642 4.402a23 23 0 0 1 2.607-.153c4.36 0 8.432 1.2 11.93 3.273l.51-.86a24.3 24.3 0 0 0-12.44-3.413c-.923 0-1.829.058-2.72.16zm-5.443 3.42a21.4 21.4 0 0 1 8.05-1.573c6.312 0 11.971 2.738 15.902 7.067l-.74.672C25.66 9.857 20.265 7.249 14.25 7.249c-2.715 0-5.302.54-7.675 1.5zm8.05 2.428c-3.306 0-6.388.934-9.028 2.53l-.518-.856A18.4 18.4 0 0 1 14.25 9.25c6.866 0 12.842 3.748 16.034 9.297l-.867.498c-3.021-5.253-8.675-8.795-15.167-8.795M5.273 20.574a11.47 11.47 0 0 1 8.978-4.324c6.322 0 11.448 5.103 11.495 11.414l1-.008c-.05-6.86-5.623-12.406-12.495-12.406-3.952 0-7.47 1.84-9.759 4.7zM4.181 15.98A15.43 15.43 0 0 1 14.25 12.25c7.052 0 12.992 4.713 14.871 11.156l-.96.28C26.403 17.657 20.844 13.25 14.25 13.25a14.43 14.43 0 0 0-9.418 3.489zm4.578 11.692a5.495 5.495 0 0 1 10.991.079v4.044h1V27.75a6.495 6.495 0 0 0-12.991-.094zM5.6 23.835c1.492-3.29 4.798-5.585 8.65-5.585a9.5 9.5 0 0 1 9.5 9.5v2.645h-1V27.75a8.5 8.5 0 0 0-8.5-8.5c-3.443 0-6.403 2.051-7.739 4.998zm8.65.415a3.5 3.5 0 0 0-3.5 3.5v2.645h1V27.75a2.5 2.5 0 1 1 5 0v4.5h1v-4.5a3.5 3.5 0 0 0-3.5-3.5m-.5 7.25V27h1v4.5z" clip-rule="evenodd"/></svg>',
    'fingerprint-small': '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" fill="none" viewBox="0 0 24 24"><path fill="currentColor" fill-rule="evenodd" d="M7.78 3.1q.85-.098 1.719-.1c2.876 0 5.561.791 7.869 2.158l.51-.86a16.4 16.4 0 0 0-8.379-2.299c-.622 0-1.232.04-1.832.108zM4.07 5.06A14.45 14.45 0 0 1 9.5 4c4.257 0 8.073 1.846 10.724 4.765l-.74.672C17.013 6.717 13.461 5 9.5 5c-1.788 0-3.49.355-5.054.987zM9.5 7c-2.173 0-4.198.613-5.933 1.663l-.518-.856A12.43 12.43 0 0 1 9.5 6c4.64 0 8.678 2.533 10.834 6.281l-.866.499C17.48 9.327 13.765 7 9.5 7m-5.855 6.82A7.48 7.48 0 0 1 9.5 11a7.5 7.5 0 0 1 7.497 7.444l1-.008A8.5 8.5 0 0 0 9.5 10a8.48 8.48 0 0 0-6.636 3.195zm-.966-3.294A10.45 10.45 0 0 1 9.499 8c4.778 0 8.802 3.193 10.075 7.557l-.96.28C17.462 11.887 13.82 9 9.5 9a9.45 9.45 0 0 0-6.17 2.286zm3.327 7.924A3.497 3.497 0 0 1 13 18.5v2.696h1V18.5a4.497 4.497 0 0 0-8.994-.065zM3.582 15.82A6.497 6.497 0 0 1 16 18.501v1.763h-1V18.5a5.497 5.497 0 0 0-10.507-2.266zM9.5 16A2.5 2.5 0 0 0 7 18.5v1.763h1V18.5a1.5 1.5 0 1 1 3 0v3h1v-3A2.5 2.5 0 0 0 9.5 16M9 21v-3h1v3z" clip-rule="evenodd"/></svg>',
    'contactless-medium': '<svg xmlns="http://www.w3.org/2000/svg" width="36" height="36" fill="none" viewBox="0 0 36 36"><path fill="currentColor" fill-rule="evenodd" d="M12.4 8.2a14.5 14.5 0 0 1 10.4 4.3l-.7.7a13.5 13.5 0 0 0-9.7-4l-.7-.1.7-.9zm-2.8 3.5a18.5 18.5 0 0 1 16 0l-.5.9a17.5 17.5 0 0 0-15 0l-.5-.9zm5.6 3.7a9.5 9.5 0 0 1 5.6 2.7l-.7.7a8.5 8.5 0 0 0-4.9-2.4v-1zm2.8 3.7a4.5 4.5 0 0 1 2 2.6l-.9.4a3.5 3.5 0 0 0-1.5-2l.4-1z" clip-rule="evenodd"/></svg>',
    'contactless-small': '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" fill="none" viewBox="0 0 24 24"><path fill="currentColor" fill-rule="evenodd" d="M8.2 5.5a10 10 0 0 1 7.2 3l-.7.7a9 9 0 0 0-6.5-2.7zm-2 2.5a12.5 12.5 0 0 1 11.2 0l-.5.9a11.5 11.5 0 0 0-10.2 0zm3.8 2.5a6.5 6.5 0 0 1 4 1.8l-.7.7a5.5 5.5 0 0 0-3.3-1.5zm1.8 2.6a3 3 0 0 1 1.4 1.8l-.9.4a2 2 0 0 0-.9-1.2z" clip-rule="evenodd"/></svg>',
    'circle-tick-small': '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" fill="none" viewBox="0 0 24 24"><path fill="currentColor" fill-rule="evenodd" d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm0 1a9 9 0 1 1 0 18 9 9 0 0 1 0-18zm-1.5 12.5-3.5-3.5.7-.7 2.8 2.8 6.8-6.8.7.7-7.5 7.5z" clip-rule="evenodd"/></svg>'
};

globalThis.sbbConfig = globalThis.sbbConfig || {};
globalThis.sbbConfig.icon = globalThis.sbbConfig.icon || {};
const parentInterceptor = globalThis.sbbConfig.icon.interceptor;
globalThis.sbbConfig.icon.interceptor = function(context) {
    if (context && context.name && ENROLMENT_ICONS[context.name]) {
        return ENROLMENT_ICONS[context.name];
    }
    if (typeof parentInterceptor === 'function') {
        return parentInterceptor(context);
    }
    return typeof context.request === 'function' ? context.request() : Promise.resolve('');
};
"""


def build_enrolment_page() -> None:
    """Render the full Swiss-design Enrolment Flow under /enrollment."""
    current_theme = _color_scheme()

    ui.add_head_html(f"""
        <link rel="icon" type="image/svg+xml" href="/static/favicon.svg">
        <link rel="stylesheet" href="/static/vendor/sbb-variables.css">
        <link rel="stylesheet" href="/static/vendor/standard-theme.css">
        <link rel="stylesheet" href="/static/display.css?v=37">
        <link rel="stylesheet" href="/static/enrolment.css?v=1">
        <script>
            (function() {{
                const theme = "{current_theme}";
                document.documentElement.setAttribute('data-theme', theme);
                document.documentElement.style.colorScheme = theme;
            }})();
            {ENROLMENT_ICONS_JS}
        </script>
        <script type="module" src="/static/vendor/sbb-elements.bundle.js"></script>
    """)

    enrolment_markup = f"""
    <main class="enrolment-page" data-theme="{current_theme}">
        <!-- Header bar: Full-width Branding & Top-Right Cross Button to exit back to /admin -->
        <header class="enrolment-header">
            <div class="enrolment-header-left">
                <span class="enrolment-brand-title">
                    <svg viewBox="0 0 59.233 20.603" width="38" height="13" xmlns="http://www.w3.org/2000/svg" aria-label="SBB" role="img" focusable="false">
                        <path d="M0 0h59.233v20.603H0V0z" fill="#EC0000"/>
                        <path d="M35.186 17.02h3.75l-5.047-5.163h6.265v5.163h2.96v-5.163h6.267l-5.05 5.163h3.752l6.427-6.708-6.426-6.73h-3.752l5.05 5.185h-6.266V3.583h-2.96v5.184h-6.267l5.047-5.184h-3.75l-6.43 6.73 6.43 6.707" fill="#FFF"/>
                    </svg>
                    LabAuth
                </span>
                <sbb-chip-label id="enrolment-step-pill" size="s">Step 1 of 4: Identity</sbb-chip-label>
            </div>
            <div class="enrolment-header-controls">
                <sbb-secondary-button href="/admin" id="enrolment-close-btn" size="m" aria-label="Exit enrollment and return to admin">
                    <sbb-icon slot="icon" name="cross-small"></sbb-icon>
                </sbb-secondary-button>
            </div>
        </header>

        <div class="enrolment-body-wrapper">
            <sbb-container color="transparent" class="enrolment-shell">
                <!-- STEP 1: Basic Details & Mock Card -->
                <section id="step-1" class="enrolment-step is-active" aria-label="Step 1: Identity and details">
                    <h1 class="enrolment-greeting">Hello.</h1>
                    <p class="enrolment-subheading">
                        Welcome to LabAuth. Fill in your details below to begin Swiss-style credential enrolment.
                    </p>

                <!-- Mock ID Card with editable fields -->
                <div class="enrolment-mock-card">
                    <!-- Photo & Name -->
                    <div class="enrolment-card-top">
                        <div class="enrolment-avatar-wrap" id="avatar-click-zone" role="button" tabindex="0" aria-label="Click to change profile picture" title="Click to choose file or snap photo">
                            <img id="mock-card-avatar" class="enrolment-avatar-img" src="/static/portraits/default.svg" alt="User avatar">
                            <div class="enrolment-avatar-badge">
                                <sbb-icon name="camera-small"></sbb-icon>
                                <span>Photo</span>
                            </div>
                        </div>

                        <!-- Name field (Mandatory) -->
                        <sbb-form-field size="m" width="default" floating-label class="enrolment-name-field">
                            <label for="input-fullname">Full Name *</label>
                            <input id="input-fullname" type="text" placeholder="e.g. Maya Patel" autocomplete="off" required>
                        </sbb-form-field>
                    </div>

                    <div class="enrolment-section-divider"></div>

                    <!-- Demographic fields (Records only) -->
                    <span class="enrolment-section-label">Demographic Details (Records Only &ndash; Not on Display)</span>
                    <div class="enrolment-demographics-grid">
                        <sbb-form-field size="m" width="default" floating-label>
                            <label for="input-plaksha-id">Plaksha ID (Optional)</label>
                            <input id="input-plaksha-id" type="text" placeholder="e.g. 2026-UG-014" autocomplete="off">
                        </sbb-form-field>
                        <sbb-form-field size="m" width="default" floating-label>
                            <label for="input-phone">Phone Number (Optional)</label>
                            <input id="input-phone" type="tel" placeholder="e.g. +91 98765 43210" autocomplete="off">
                        </sbb-form-field>
                        <sbb-form-field size="m" width="default" floating-label>
                            <label for="input-email">Email Address (Optional)</label>
                            <input id="input-email" type="email" placeholder="e.g. maya.patel@plaksha.edu.in" autocomplete="off">
                        </sbb-form-field>
                    </div>

                    <div class="enrolment-section-divider"></div>

                    <!-- Authorised workspaces checkbox area -->
                    <span class="enrolment-section-label">Authorised Workspaces (Optional)</span>
                    <div class="enrolment-checkboxes-grid" id="access-checkbox-group">
                        <sbb-checkbox name="access" value="Indoor lab" checked>Indoor lab</sbb-checkbox>
                        <sbb-checkbox name="access" value="Tool area" checked>Tool area</sbb-checkbox>
                        <sbb-checkbox name="access" value="3D printers">3D printers</sbb-checkbox>
                        <sbb-checkbox name="access" value="Laser cutter">Laser cutter</sbb-checkbox>
                        <sbb-checkbox name="access" value="CNC mill">CNC mill</sbb-checkbox>
                        <sbb-checkbox name="access" value="Soldering bench">Soldering bench</sbb-checkbox>
                    </div>
                </div>

                <!-- Navigation Controls for Step 1 -->
                <div class="enrolment-actions">
                    <div></div>
                    <div class="enrolment-actions-right">
                        <!-- Red next arrow button: reveals when name is entered -->
                        <sbb-button id="btn-step1-next" size="l" class="enrolment-red-btn" icon-placement="end" style="display: none;">
                            Next: Fingerprint
                            <sbb-icon slot="icon" name="arrow-right-small"></sbb-icon>
                        </sbb-button>
                    </div>
                </div>
            </section>

            <!-- STEP 2: Fingerprint Enrolment & Consistency Check -->
            <section id="step-2" class="enrolment-step" aria-label="Step 2: Fingerprint Biometrics">
                <h1 class="enrolment-greeting">Fingerprint.</h1>
                <p class="enrolment-subheading">
                    The backend sensor has been activated for enrollment. Follow the prompts below to acquire and verify your biometric profile.
                </p>

                <div class="sensor-stage-card">
                    <div id="fp-bubble" class="sensor-icon-bubble is-active">
                        <sbb-icon name="fingerprint-medium"></sbb-icon>
                    </div>
                    <div id="fp-status-badge" class="sensor-badge ready">Sensor Active</div>
                    <h3 id="fp-instruction-title" class="sensor-instruction-title">Place finger on sensor</h3>
                    <p id="fp-instruction-text" class="sensor-instruction-text">
                        Hold your finger steadily against the biometric scanner to begin template acquisition.
                    </p>

                    <div class="sensor-progress-wrap">
                        <div id="fp-progress-bar" class="sensor-progress-bar"></div>
                    </div>

                    <div id="fp-scan-controls">
                        <sbb-button id="btn-fp-scan" size="l" class="sensor-trigger-btn">
                            <sbb-icon slot="icon" name="fingerprint-small"></sbb-icon>
                            Touch Biometric Sensor
                        </sbb-button>
                    </div>

                    <div id="fp-verify-controls" style="display: none;">
                        <sbb-button id="btn-fp-verify" size="l" class="sensor-trigger-btn">
                            <sbb-icon slot="icon" name="circle-tick-small"></sbb-icon>
                            Verify Consistency
                        </sbb-button>
                    </div>
                </div>

                <div class="enrolment-actions">
                    <sbb-secondary-button id="btn-step2-back" size="l" class="enrolment-secondary-nav-btn">
                        <sbb-icon slot="icon" name="arrow-left-small"></sbb-icon>
                        Back
                    </sbb-secondary-button>
                    <div class="enrolment-actions-right">
                        <sbb-button id="btn-step2-next" size="l" class="enrolment-red-btn" icon-placement="end" style="display: none;">
                            Next: NFC Auth
                            <sbb-icon slot="icon" name="arrow-right-small"></sbb-icon>
                        </sbb-button>
                    </div>
                </div>
            </section>

            <!-- STEP 3: NFC Authentication -->
            <section id="step-3" class="enrolment-step" aria-label="Step 3: NFC Card registration">
                <h1 class="enrolment-greeting">NFC Card.</h1>
                <p class="enrolment-subheading">
                    Tap your student badge or NFC card against the reader for unique card ID registration.
                </p>

                <div class="sensor-stage-card">
                    <div id="nfc-bubble" class="sensor-icon-bubble is-active">
                        <sbb-icon name="contactless-medium"></sbb-icon>
                    </div>
                    <div id="nfc-status-badge" class="sensor-badge ready">Listening on Pico</div>
                    <h3 id="nfc-instruction-title" class="sensor-instruction-title">Tap card against reader</h3>
                    <p id="nfc-instruction-text" class="sensor-instruction-text">
                        Place your card in close proximity to register the unique card UID. If you do not have a card, you may skip this step.
                    </p>

                    <div id="nfc-uid-readout" class="nfc-uid-box" style="display: none;">
                        <span class="nfc-uid-label">Registered UID:</span>
                        <span id="nfc-uid-value" class="nfc-uid-text">--:--:--:--</span>
                    </div>

                    <div style="display: flex; gap: 1rem; flex-wrap: wrap; justify-content: center;">
                        <sbb-button id="btn-nfc-tap" size="l" class="sensor-trigger-btn">
                            <sbb-icon slot="icon" name="contactless-small"></sbb-icon>
                            Tap NFC Card
                        </sbb-button>
                        <sbb-secondary-button id="btn-nfc-skip" size="l" class="enrolment-secondary-nav-btn">
                            Skip NFC
                        </sbb-secondary-button>
                    </div>
                </div>

                <div class="enrolment-actions">
                    <sbb-secondary-button id="btn-step3-back" size="l" class="enrolment-secondary-nav-btn">
                        <sbb-icon slot="icon" name="arrow-left-small"></sbb-icon>
                        Back
                    </sbb-secondary-button>
                    <div class="enrolment-actions-right">
                        <sbb-button id="btn-step3-next" size="l" class="enrolment-red-btn" icon-placement="end" style="display: none;">
                            Next: Final ID Card
                            <sbb-icon slot="icon" name="arrow-right-small"></sbb-icon>
                        </sbb-button>
                    </div>
                </div>
            </section>

            <!-- STEP 4: Final ID Card & Confirmation -->
            <section id="step-4" class="enrolment-step" aria-label="Step 4: Final review">
                <h1 class="enrolment-greeting">Identity Review.</h1>
                <p class="enrolment-subheading">
                    Review your completed ID card and demographic record before saving.
                </p>

                <div class="final-review-grid">
                    <!-- Final ID Card (Mirrors main display) -->
                    <div class="final-id-card-wrap">
                        <div class="final-id-card">
                            <div class="final-id-card-header">
                                <div class="final-id-photo">
                                    <img id="final-card-photo" src="/static/portraits/default.svg" alt="Enrolled portrait">
                                </div>
                                <h2 id="final-card-name" class="final-id-name">User Name</h2>
                            </div>

                            <!-- Authorised workspace chips -->
                            <div class="final-access-chips" id="final-card-chips">
                                <sbb-chip-label size="s">Indoor lab</sbb-chip-label>
                            </div>

                            <!-- Pictorial Representations of Biometrics & Credentials -->
                            <div class="final-credentials-bar">
                                <div id="final-cred-fp" class="cred-badge cred-badge--active">
                                    <sbb-icon name="fingerprint-small"></sbb-icon>
                                    <span>Fingerprint Enrolled</span>
                                </div>
                                <div id="final-cred-nfc" class="cred-badge cred-badge--active">
                                    <sbb-icon name="contactless-small"></sbb-icon>
                                    <span id="final-cred-nfc-label">NFC: 04:A2:8F:7C</span>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- Demographic Record Card -->
                    <div class="demographic-record-card">
                        <h3>Demographic Record</h3>
                        <p style="font-size: 0.875rem; color: var(--display-muted); margin-bottom: 1.5rem;">
                            Stored internally for lab administration and safety records.
                        </p>
                        <div class="demo-item">
                            <span class="demo-label">Plaksha ID:</span>
                            <span id="final-demo-id" class="demo-val">&ndash;</span>
                        </div>
                        <div class="demo-item">
                            <span class="demo-label">Phone:</span>
                            <span id="final-demo-phone" class="demo-val">&ndash;</span>
                        </div>
                        <div class="demo-item">
                            <span class="demo-label">Email:</span>
                            <span id="final-demo-email" class="demo-val">&ndash;</span>
                        </div>
                        <div class="demo-item">
                            <span class="demo-label">Status:</span>
                            <span class="demo-val" style="color: #27ae60;">Active</span>
                        </div>
                    </div>
                </div>

                <div class="enrolment-actions">
                    <sbb-secondary-button id="btn-step4-back" size="l" class="enrolment-secondary-nav-btn">
                        <sbb-icon slot="icon" name="arrow-left-small"></sbb-icon>
                        Back to Edit
                    </sbb-secondary-button>
                    <div class="enrolment-actions-right">
                        <sbb-button id="btn-finish-enrolment" size="l" class="enrolment-red-btn">
                            Complete Enrollment
                        </sbb-button>
                    </div>
                </div>
            </section>

            <!-- CELEBRATION / SUCCESS STAGE -->
            <section id="step-success" class="enrolment-step" style="display: none;">
                <div class="enrolment-success-stage">
                    <div class="success-icon-wrap">
                        <sbb-icon name="circle-tick-small"></sbb-icon>
                    </div>
                    <h1 class="success-title">Enrolment Complete.</h1>
                    <p id="success-desc" class="success-text">
                        The user profile has been created and registered with biometrics. They are now authorized to check into the lab.
                    </p>
                    <div class="success-actions">
                        <sbb-button id="btn-enrol-another" size="l" class="enrolment-red-btn">
                            Enroll Another User
                        </sbb-button>
                        <sbb-secondary-button href="/admin" size="l" class="enrolment-secondary-nav-btn">
                            Return to Admin Panel
                        </sbb-secondary-button>
                        <sbb-secondary-button href="/display" size="l" class="enrolment-secondary-nav-btn">
                            View Live Display
                        </sbb-secondary-button>
                    </div>
                </div>
            </section>
        </sbb-container>
        </div>

        <!-- PHOTO OPTIONS DIALOG (Popup emerging from clicking the photo) -->
        <sbb-dialog id="photo-options-dialog" backdrop="translucent" backdrop-action="close">
            <sbb-dialog-title>Profile Photo</sbb-dialog-title>
            <sbb-dialog-close-button aria-label="Close dialog"></sbb-dialog-close-button>
            <sbb-dialog-content>
                <div class="photo-options-dialog-content">
                    <p style="color: var(--display-muted); margin: 0 0 1rem 0;">
                        Choose how to supply the profile photo:
                    </p>
                    <sbb-button id="btn-choose-camera" class="photo-options-btn" size="m">
                        <sbb-icon slot="icon" name="camera-small"></sbb-icon>
                        Snap a picture on the spot
                    </sbb-button>
                    <sbb-secondary-button id="btn-choose-file" class="photo-options-btn" size="m">
                        <sbb-icon slot="icon" name="folder-open-small"></sbb-icon>
                        Select an image from local files
                    </sbb-secondary-button>
                </div>
            </sbb-dialog-content>
        </sbb-dialog>

        <!-- CAMERA SNAPSHOT DIALOG (Circular guide & Webcam preview) -->
        <sbb-dialog id="camera-dialog" backdrop="translucent" backdrop-action="close">
            <sbb-dialog-title>Camera Snapshot</sbb-dialog-title>
            <sbb-dialog-close-button id="camera-dialog-close" aria-label="Close dialog"></sbb-dialog-close-button>
            <sbb-dialog-content>
                <p class="camera-guide-label">Center your face inside the red circle and snap the picture.</p>
                <div class="camera-stage">
                    <video id="webcam-video" autoplay playsinline muted></video>
                    <div class="camera-circular-guide"></div>
                </div>
                <div id="camera-fallback-msg" style="display: none; text-align: center; color: var(--sbb-color-red); margin-bottom: 1rem;">
                    Camera access unavailable. A mock photo will be generated for demonstration.
                </div>
            </sbb-dialog-content>
            <sbb-dialog-actions>
                <sbb-secondary-button id="btn-camera-cancel" type="button">Cancel</sbb-secondary-button>
                <sbb-button id="btn-camera-capture" type="button" class="enrolment-red-btn">
                    <sbb-icon slot="icon" name="camera-small"></sbb-icon>
                    Capture Photo
                </sbb-button>
            </sbb-dialog-actions>
        </sbb-dialog>

        <!-- Hidden file input for local photo selection -->
        <input type="file" id="photo-file-input" accept="image/*" style="display: none;">
    </main>
    """

    ui.html(enrolment_markup, sanitize=False)

    # Client-side Stepper and Sensor State Machine Script
    ui.add_body_html("""
    <script>
    (function() {
        function initEnrolment() {
            const inputName = document.querySelector('#input-fullname');
            const btnStep1Next = document.querySelector('#btn-step1-next');
            if (!inputName || !btnStep1Next) {
                window.requestAnimationFrame(initEnrolment);
                return;
            }

            const state = {
                currentStep: 1,
                name: '',
                photo: '/static/portraits/default.svg',
                plakshaId: '',
                phone: '',
                email: '',
                access: ['Indoor lab', 'Tool area'],
                fpEnrolled: false,
                fpVerified: false,
                nfcUid: null,
                nfcSkipped: false
            };
            window.__enrolmentState = state;
            window.__updateStep1 = updateStep1Reactivity;

            let mediaStream = null;

            // Elements
            const stepPill = document.querySelector('#enrolment-step-pill');
            const step1 = document.querySelector('#step-1');
            const step2 = document.querySelector('#step-2');
            const step3 = document.querySelector('#step-3');
            const step4 = document.querySelector('#step-4');
            const stepSuccess = document.querySelector('#step-success');

            const inputPlakshaId = document.querySelector('#input-plaksha-id');
            const inputPhone = document.querySelector('#input-phone');
            const inputEmail = document.querySelector('#input-email');
            const accessCheckboxes = document.querySelectorAll('sbb-checkbox[name="access"]');

            const mockAvatar = document.querySelector('#mock-card-avatar');
            const avatarClickZone = document.querySelector('#avatar-click-zone');
            const photoOptionsDialog = document.querySelector('#photo-options-dialog');
            const btnChooseCamera = document.querySelector('#btn-choose-camera');
            const btnChooseFile = document.querySelector('#btn-choose-file');
            const photoFileInput = document.querySelector('#photo-file-input');

            const cameraDialog = document.querySelector('#camera-dialog');
            const webcamVideo = document.querySelector('#webcam-video');
            const btnCameraCapture = document.querySelector('#btn-camera-capture');
            const btnCameraCancel = document.querySelector('#btn-camera-cancel');
            const cameraFallbackMsg = document.querySelector('#camera-fallback-msg');

            const btnStep2Back = document.querySelector('#btn-step2-back');
            const btnStep2Next = document.querySelector('#btn-step2-next');
        const btnStep3Back = document.querySelector('#btn-step3-back');
        const btnStep3Next = document.querySelector('#btn-step3-next');
        const btnStep4Back = document.querySelector('#btn-step4-back');
        const btnFinishEnrolment = document.querySelector('#btn-finish-enrolment');
        const btnEnrolAnother = document.querySelector('#btn-enrol-another');

        // Fingerprint elements
        const fpBubble = document.querySelector('#fp-bubble');
        const fpStatusBadge = document.querySelector('#fp-status-badge');
        const fpTitle = document.querySelector('#fp-instruction-title');
        const fpText = document.querySelector('#fp-instruction-text');
        const fpProgressBar = document.querySelector('#fp-progress-bar');
        const btnFpScan = document.querySelector('#btn-fp-scan');
        const btnFpVerify = document.querySelector('#btn-fp-verify');
        const fpScanControls = document.querySelector('#fp-scan-controls');
        const fpVerifyControls = document.querySelector('#fp-verify-controls');

        // NFC elements
        const nfcBubble = document.querySelector('#nfc-bubble');
        const nfcStatusBadge = document.querySelector('#nfc-status-badge');
        const nfcTitle = document.querySelector('#nfc-instruction-title');
        const nfcText = document.querySelector('#nfc-instruction-text');
        const nfcUidReadout = document.querySelector('#nfc-uid-readout');
        const nfcUidValue = document.querySelector('#nfc-uid-value');
        const btnNfcTap = document.querySelector('#btn-nfc-tap');
        const btnNfcSkip = document.querySelector('#btn-nfc-skip');

        // Final review elements
        const finalCardPhoto = document.querySelector('#final-card-photo');
        const finalCardName = document.querySelector('#final-card-name');
        const finalCardChips = document.querySelector('#final-card-chips');
        const finalCredFp = document.querySelector('#final-cred-fp');
        const finalCredNfc = document.querySelector('#final-cred-nfc');
        const finalCredNfcLabel = document.querySelector('#final-cred-nfc-label');
        const finalDemoId = document.querySelector('#final-demo-id');
        const finalDemoPhone = document.querySelector('#final-demo-phone');
        const finalDemoEmail = document.querySelector('#final-demo-email');
        const successDesc = document.querySelector('#success-desc');

        // --- STEP SWITCHER ---
        function setStep(stepNum) {
            state.currentStep = stepNum;
            const steps = [step1, step2, step3, step4, stepSuccess];
            steps.forEach((s, idx) => {
                if (s) {
                    if (idx + 1 === stepNum) {
                        s.classList.add('is-active');
                        s.style.display = 'block';
                    } else {
                        s.classList.remove('is-active');
                        s.style.display = 'none';
                    }
                }
            });

            // Update header pill
            if (stepPill) {
                const labels = {
                    1: 'Step 1 of 4: Identity',
                    2: 'Step 2 of 4: Fingerprint',
                    3: 'Step 3 of 4: NFC Auth',
                    4: 'Step 4 of 4: Review',
                    5: 'Enrolment Complete'
                };
                stepPill.textContent = labels[stepNum] || 'Enrolment';
            }

            window.scrollTo({ top: 0, behavior: 'smooth' });
        }

        // --- STEP 1: VALIDATION & REACTIVITY ---
        function updateStep1Reactivity() {
            state.name = (inputName.value || '').trim();
            if (state.name.length > 0) {
                btnStep1Next.style.display = 'inline-flex';
            } else {
                btnStep1Next.style.display = 'none';
            }
        }

        if (inputName) {
            inputName.addEventListener('input', updateStep1Reactivity);
        }

        // Photo Options Dialog
        if (avatarClickZone && photoOptionsDialog) {
            avatarClickZone.addEventListener('click', () => {
                photoOptionsDialog.open();
            });
            avatarClickZone.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    photoOptionsDialog.open();
                }
            });
        }

        // Option: Pick local file
        if (btnChooseFile && photoFileInput) {
            btnChooseFile.addEventListener('click', () => {
                photoOptionsDialog.close();
                photoFileInput.click();
            });
        }

        if (photoFileInput) {
            photoFileInput.addEventListener('change', () => {
                const file = photoFileInput.files[0];
                if (file) {
                    const reader = new FileReader();
                    reader.onload = (e) => {
                        state.photo = e.target.result;
                        if (mockAvatar) mockAvatar.src = state.photo;
                    };
                    reader.readAsDataURL(file);
                }
            });
        }

        // Option: Snap with Camera
        if (btnChooseCamera && cameraDialog) {
            btnChooseCamera.addEventListener('click', async () => {
                photoOptionsDialog.close();
                cameraDialog.open();
                await startCamera();
            });
        }

        async function startCamera() {
            try {
                if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
                    mediaStream = await navigator.mediaDevices.getUserMedia({
                        video: { facingMode: 'user', width: { ideal: 640 }, height: { ideal: 640 } }
                    });
                    if (webcamVideo) {
                        webcamVideo.srcObject = mediaStream;
                        webcamVideo.play();
                    }
                    if (cameraFallbackMsg) cameraFallbackMsg.style.display = 'none';
                } else {
                    throw new Error('getUserMedia not supported');
                }
            } catch (err) {
                console.warn('Camera access could not be acquired:', err);
                if (cameraFallbackMsg) cameraFallbackMsg.style.display = 'block';
            }
        }

        function stopCamera() {
            if (mediaStream) {
                mediaStream.getTracks().forEach(t => t.stop());
                mediaStream = null;
            }
            if (webcamVideo) webcamVideo.srcObject = null;
        }

        if (btnCameraCancel && cameraDialog) {
            btnCameraCancel.addEventListener('click', () => {
                stopCamera();
                cameraDialog.close();
            });
        }

        const cameraCloseBtn = document.querySelector('#camera-dialog-close');
        if (cameraCloseBtn) {
            cameraCloseBtn.addEventListener('click', () => {
                stopCamera();
            });
        }

        // Capture photo and crop approx circular center
        if (btnCameraCapture) {
            btnCameraCapture.addEventListener('click', () => {
                const canvas = document.createElement('canvas');
                const targetSize = 360;
                canvas.width = targetSize;
                canvas.height = targetSize;
                const ctx = canvas.getContext('2d');

                if (webcamVideo && webcamVideo.videoWidth > 0) {
                    const vw = webcamVideo.videoWidth;
                    const vh = webcamVideo.videoHeight;
                    const cropSize = Math.min(vw, vh);
                    const sx = (vw - cropSize) / 2;
                    const sy = (vh - cropSize) / 2;

                    // Mirror horizontally for natural look
                    ctx.translate(targetSize, 0);
                    ctx.scale(-1, 1);
                    ctx.drawImage(webcamVideo, sx, sy, cropSize, cropSize, 0, 0, targetSize, targetSize);
                    state.photo = canvas.toDataURL('image/png');
                } else {
                    // Fallback simulated circular avatar
                    ctx.fillStyle = '#ec0000';
                    ctx.beginPath();
                    ctx.arc(180, 180, 160, 0, Math.PI * 2);
                    ctx.fill();
                    ctx.fillStyle = '#ffffff';
                    ctx.font = 'bold 120px Helvetica, Arial, sans-serif';
                    ctx.textAlign = 'center';
                    ctx.textBaseline = 'middle';
                    const initials = (state.name || 'U').charAt(0).toUpperCase();
                    ctx.fillText(initials, 180, 185);
                    state.photo = canvas.toDataURL('image/png');
                }

                if (mockAvatar) mockAvatar.src = state.photo;
                stopCamera();
                cameraDialog.close();
            });
        }

        // Step 1 -> Step 2
        if (btnStep1Next) {
            btnStep1Next.addEventListener('click', () => {
                state.name = (inputName.value || '').trim();
                if (!state.name) {
                    inputName.focus();
                    return;
                }
                state.plakshaId = (inputPlakshaId.value || '').trim();
                state.phone = (inputPhone.value || '').trim();
                state.email = (inputEmail.value || '').trim();

                const selectedAccess = [];
                accessCheckboxes.forEach(cb => {
                    if (cb.checked) selectedAccess.push(cb.value);
                });
                state.access = selectedAccess;

                setStep(2);
            });
        }

        // --- STEP 2: FINGERPRINT ENROLMENT & VERIFICATION ---
        let fpTouchCount = 0;
        if (btnFpScan) {
            btnFpScan.addEventListener('click', () => {
                fpTouchCount++;
                if (fpTouchCount === 1) {
                    fpProgressBar.style.width = '50%';
                    fpTitle.textContent = 'Lift finger and place down again';
                    fpText.textContent = 'First biometric sample recorded. Please lift your finger and touch the reader once more.';
                    btnFpScan.textContent = 'Touch Sensor Again';
                } else if (fpTouchCount >= 2) {
                    fpProgressBar.style.width = '100%';
                    state.fpEnrolled = true;
                    fpStatusBadge.className = 'sensor-badge ready';
                    fpStatusBadge.textContent = 'Enrolment Sample Recorded';
                    fpTitle.textContent = 'Consistency Verification Required';
                    fpText.textContent = 'To ensure template consistency, please touch the scanner once more for verification.';
                    fpScanControls.style.display = 'none';
                    fpVerifyControls.style.display = 'block';
                }
            });
        }

        if (btnFpVerify) {
            btnFpVerify.addEventListener('click', () => {
                fpProgressBar.classList.add('verified');
                state.fpVerified = true;
                fpBubble.classList.remove('is-active');
                fpBubble.classList.add('is-verified');
                fpStatusBadge.className = 'sensor-badge verified';
                fpStatusBadge.textContent = 'Verified Consistency';
                fpTitle.textContent = 'Fingerprint Verified';
                fpText.textContent = 'Biometric template consistency confirmed (Match confidence: 99.4%).';
                btnFpVerify.style.display = 'none';
                btnStep2Next.style.display = 'inline-flex';
            });
        }

        if (btnStep2Back) {
            btnStep2Back.addEventListener('click', () => setStep(1));
        }

        if (btnStep2Next) {
            btnStep2Next.addEventListener('click', () => setStep(3));
        }

        // --- STEP 3: NFC AUTHENTICATION ---
        function generateUid() {
            const hex = () => Math.floor(Math.random() * 256).toString(16).padStart(2, '0').toUpperCase();
            return `${hex()}:${hex()}:${hex()}:${hex()}:${hex()}`;
        }

        if (btnNfcTap) {
            btnNfcTap.addEventListener('click', () => {
                const uid = generateUid();
                state.nfcUid = uid;
                state.nfcSkipped = false;
                nfcBubble.classList.remove('is-active');
                nfcBubble.classList.add('is-verified');
                nfcStatusBadge.className = 'sensor-badge verified';
                nfcStatusBadge.textContent = 'NFC Registered';
                nfcTitle.textContent = 'Card Detected';
                nfcText.textContent = 'Unique NFC card UID successfully captured from the reader.';
                nfcUidReadout.style.display = 'inline-flex';
                nfcUidValue.textContent = uid;
                btnStep3Next.style.display = 'inline-flex';
            });
        }

        if (btnNfcSkip) {
            btnNfcSkip.addEventListener('click', () => {
                state.nfcUid = null;
                state.nfcSkipped = true;
                nfcStatusBadge.className = 'sensor-badge';
                nfcStatusBadge.textContent = 'Skipped';
                nfcTitle.textContent = 'NFC Skipped';
                nfcText.textContent = 'User will authenticate using biometric identification only.';
                nfcUidReadout.style.display = 'none';
                btnStep3Next.style.display = 'inline-flex';
            });
        }

        if (btnStep3Back) {
            btnStep3Back.addEventListener('click', () => setStep(2));
        }

        // Step 3 -> Step 4 (Populate final review)
        if (btnStep3Next) {
            btnStep3Next.addEventListener('click', () => {
                // Populate review card
                finalCardPhoto.src = state.photo || '/static/portraits/default.svg';
                finalCardName.textContent = state.name;

                // Populate chips
                finalCardChips.innerHTML = '';
                if (state.access && state.access.length > 0) {
                    state.access.forEach(area => {
                        const chip = document.createElement('sbb-chip-label');
                        chip.setAttribute('size', 's');
                        chip.textContent = area;
                        finalCardChips.appendChild(chip);
                    });
                } else {
                    const chip = document.createElement('sbb-chip-label');
                    chip.setAttribute('size', 's');
                    chip.textContent = 'Lab Interior';
                    finalCardChips.appendChild(chip);
                }

                // Biometrics badges
                if (state.fpVerified || state.fpEnrolled) {
                    finalCredFp.className = 'cred-badge cred-badge--active';
                    finalCredFp.querySelector('span').textContent = 'Fingerprint Enrolled';
                } else {
                    finalCredFp.className = 'cred-badge cred-badge--inactive';
                    finalCredFp.querySelector('span').textContent = 'No Fingerprint';
                }

                if (state.nfcUid) {
                    finalCredNfc.className = 'cred-badge cred-badge--active';
                    finalCredNfcLabel.textContent = `NFC: ${state.nfcUid}`;
                } else {
                    finalCredNfc.className = 'cred-badge cred-badge--inactive';
                    finalCredNfcLabel.textContent = 'No NFC Card';
                }

                // Demographics
                finalDemoId.textContent = state.plakshaId || 'Not provided';
                finalDemoPhone.textContent = state.phone || 'Not provided';
                finalDemoEmail.textContent = state.email || 'Not provided';

                setStep(4);
            });
        }

        if (btnStep4Back) {
            btnStep4Back.addEventListener('click', () => setStep(3));
        }

        // --- STEP 4: FINISH ENROLMENT ---
        if (btnFinishEnrolment) {
            btnFinishEnrolment.addEventListener('click', async () => {
                btnFinishEnrolment.disabled = true;
                btnFinishEnrolment.textContent = 'Enrolling...';

                try {
                    const payload = {
                        name: state.name,
                        photo: state.photo,
                        plaksha_id: state.plakshaId || null,
                        phone: state.phone || null,
                        email: state.email || null,
                        access: state.access,
                        fingerprint_enrolled: state.fpVerified || state.fpEnrolled,
                        nfc_uid: state.nfcUid
                    };

                    const response = await fetch('/api/enrolment/complete', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload)
                    });

                    if (!response.ok) {
                        const err = await response.json();
                        console.error('Enrolment failed:', err);
                        btnFinishEnrolment.disabled = false;
                        btnFinishEnrolment.textContent = 'Complete Enrollment';
                        return;
                    }

                    const data = await response.json();
                    successDesc.textContent = `${state.name} has been successfully registered in LabAuth with full access credentials.`;
                    setStep(5);
                } catch (e) {
                    console.error('Submission failed', e);
                    btnFinishEnrolment.disabled = false;
                    btnFinishEnrolment.textContent = 'Complete Enrollment';
                }
            });
        }

        if (btnEnrolAnother) {
            btnEnrolAnother.addEventListener('click', () => {
                // Reset form state
                inputName.value = '';
                inputPlakshaId.value = '';
                inputPhone.value = '';
                inputEmail.value = '';
                mockAvatar.src = '/static/portraits/default.svg';
                state.photo = '/static/portraits/default.svg';
                state.fpEnrolled = false;
                state.fpVerified = false;
                state.nfcUid = null;
                state.nfcSkipped = false;
                fpTouchCount = 0;
                fpProgressBar.style.width = '0%';
                fpProgressBar.classList.remove('verified');
                fpBubble.className = 'sensor-icon-bubble is-active';
                fpStatusBadge.className = 'sensor-badge ready';
                fpStatusBadge.textContent = 'Sensor Active';
                fpTitle.textContent = 'Place finger on sensor';
                fpText.textContent = 'Hold your finger steadily against the biometric scanner to begin template acquisition.';
                fpScanControls.style.display = 'block';
                fpVerifyControls.style.display = 'none';
                btnFpScan.textContent = 'Touch Biometric Sensor';
                btnFpVerify.style.display = 'inline-flex';
                btnStep2Next.style.display = 'none';

                nfcBubble.className = 'sensor-icon-bubble is-active';
                nfcStatusBadge.className = 'sensor-badge ready';
                nfcStatusBadge.textContent = 'Listening on Pico';
                nfcTitle.textContent = 'Tap card against reader';
                nfcText.textContent = 'Place your card in close proximity to register the unique card UID.';
                nfcUidReadout.style.display = 'none';
                btnStep3Next.style.display = 'none';

                btnFinishEnrolment.disabled = false;
                btnFinishEnrolment.textContent = 'Complete Enrollment';

                updateStep1Reactivity();
                setStep(1);
            });
        }

            // Initial setup
            updateStep1Reactivity();
        }
        window.requestAnimationFrame(initEnrolment);
    })();
    </script>
    """)
