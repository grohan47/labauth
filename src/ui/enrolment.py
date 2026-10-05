"""Lyne enrolment: identity, optional readers, review, persisted confirmation."""

from __future__ import annotations

import html

from nicegui import ui
import database as db
from ui.display import (
    JSDELIVR_NPM,
    LYNE_DESIGN_TOKENS_VERSION,
    LYNE_ELEMENTS_VERSION,
    _color_scheme,
)


def build_enrolment_page() -> None:
    areas = db.list_access_areas()
    checkboxes = "".join(
        f'<sbb-checkbox name="access" value="{area.id}">{html.escape(area.label)}</sbb-checkbox>'
        for area in areas
    )
    theme = _color_scheme()
    modules = (
        "button",
        "card",
        "title",
        "form-field",
        "checkbox",
        "checkbox-group",
        "icon",
        "image",
        "divider",
        "menu",
        "dialog",
        "chip-label",
        "notification",
        "link",
    )
    module_tags = "\n".join(
        f'<script type="module" src="{JSDELIVR_NPM}/@sbb-esta/lyne-elements@{LYNE_ELEMENTS_VERSION}/{module}.js/+esm"></script>'
        for module in modules
    )
    ui.add_head_html(f"""
        <link rel="stylesheet" href="{JSDELIVR_NPM}/@sbb-esta/lyne-design-tokens@{LYNE_DESIGN_TOKENS_VERSION}/dist/css/sbb-variables.css">
        <link rel="stylesheet" href="{JSDELIVR_NPM}/@sbb-esta/lyne-elements@{LYNE_ELEMENTS_VERSION}/standard-theme.css">
        <link rel="stylesheet" href="/static/display.css?v=37">
        <link rel="stylesheet" href="/static/enrolment.css?v=7">
        <script>document.documentElement.dataset.theme = "{theme}"; document.documentElement.style.colorScheme = "{theme}"; document.documentElement.classList.add("sbb-{theme}");</script>
        {module_tags}
        <script type="module" src="/static/enrolment.js?v=7"></script>
    """)
    ui.html(f"""
    <main class="enrolment-page">
      <div id="enrolment-progress" class="enrolment-progress" role="progressbar" aria-label="Enrolment progress" aria-valuemin="0" aria-valuemax="100" aria-valuenow="25" aria-valuetext="Details">
        <sbb-divider id="enrolment-progress-fill" aria-hidden="true"></sbb-divider>
      </div>
      <div class="enrolment-shell">
        <section id="step-1" class="enrolment-step" aria-labelledby="heading-1">
          <sbb-title level="1" visual-level="2" id="heading-1" tabindex="-1">Hello!</sbb-title>
          <form id="identity-form" novalidate>
            <sbb-card class="identity-card build-card student-card" color="transparent-bordered">
              <div class="identity-top">
                <sbb-transparent-button id="avatar-click-zone" class="photo-button" size="l" aria-label="Add or change photo">
                  <img id="mock-card-avatar" class="portrait sbb-image-1-1 sbb-image-border-radius-round" src="/static/portraits/default.svg" alt="Profile photo">
                  <span class="photo-caption"><sbb-icon name="camera-small"></sbb-icon><span>Photo</span></span>
                </sbb-transparent-button>
                <sbb-form-field size="l" class="name-field">
                  <label for="input-fullname">Full name *</label>
                  <input id="input-fullname" name="name" type="text" autocomplete="name" maxlength="200" required>
                </sbb-form-field>
              </div>
              <div class="card-record-fields">
                <sbb-form-field size="l"><label for="input-plaksha-id">Plaksha ID</label><input id="input-plaksha-id" name="plaksha_id" maxlength="100" autocomplete="off"></sbb-form-field>
                <sbb-form-field size="l"><label for="input-phone">Phone</label><input id="input-phone" name="phone" type="tel" maxlength="100" autocomplete="tel"></sbb-form-field>
                <sbb-form-field size="l"><label for="input-email">Email</label><input id="input-email" name="email" type="email" maxlength="254" autocomplete="email"></sbb-form-field>
              </div>
              <fieldset class="access-fieldset">
                <legend>Authorised areas</legend>
                <sbb-checkbox-group id="access-checkbox-group" orientation="vertical">{checkboxes or '<span class="muted">No areas configured</span>'}</sbb-checkbox-group>
              </fieldset>
            </sbb-card>
            <div id="identity-error" role="alert" hidden></div>
            <nav class="enrolment-actions" aria-label="Step actions">
              <sbb-button-link id="enrolment-close-btn" size="l" href="/admin" icon-name="arrow-left-small">Back</sbb-button-link>
              <sbb-button id="btn-step1-next" size="l" type="submit" icon-name="arrow-right-small" icon-placement="end" hidden>Next</sbb-button>
            </nav>
          </form>
        </section>
        <section id="step-2" class="enrolment-step reader-step" aria-labelledby="heading-2" hidden>
          <sbb-title level="1" visual-level="2" id="heading-2" tabindex="-1">Fingerprint</sbb-title>
          <div class="reader-stage" id="fp-stage" role="region" aria-live="polite" title="Click to simulate touch">
            <div id="fp-animation" class="reader-anim-wrap">
              <sbb-icon class="reader-icon" name="fingerprint-medium" aria-hidden="true"></sbb-icon>
            </div>
            <div class="reader-checkmark-container" id="fp-checkmark" hidden>
              <svg class="reader-checkmark-svg" viewBox="0 0 120 120">
                <circle class="reader-checkmark-circle" cx="60" cy="60" r="50" fill="var(--sbb-color-red, #eb0000)" />
                <path class="reader-checkmark-check" fill="none" stroke="#ffffff" stroke-width="8" stroke-linecap="round" stroke-linejoin="round" d="M36 62 L52 78 L84 44" />
              </svg>
            </div>
            <sbb-title level="2" visual-level="4" id="fp-status-title">Reader ready</sbb-title>
            <p class="reader-subtitle" id="fp-status-desc">Touch the biometric sensor to register fingerprint</p>
          </div>
          <nav class="enrolment-actions" aria-label="Step actions">
            <sbb-button id="btn-step2-back" size="l" icon-name="arrow-left-small">Back</sbb-button>
            <sbb-button id="btn-fp-skip" size="l" icon-name="arrow-right-small" icon-placement="end">Skip</sbb-button>
          </nav>
        </section>
        <section id="step-3" class="enrolment-step reader-step" aria-labelledby="heading-3" hidden>
          <sbb-title level="1" visual-level="2" id="heading-3" tabindex="-1">NFC card</sbb-title>
          <div class="reader-stage" id="nfc-stage" role="region" aria-live="polite" title="Click to simulate card tap">
            <div id="nfc-tap-animation" class="nfc-tap-animation" aria-hidden="true" data-loaded="true">
              <img class="nfc-tap-gif nfc-tap-gif--dark" src="/static/animations/nfc-tap-dark.gif" alt="Tap card against contactless transit reader">
              <img class="nfc-tap-gif nfc-tap-gif--light" src="/static/animations/nfc-tap-light.gif" alt="Tap card against contactless transit reader">
            </div>
            <div class="reader-checkmark-container" id="nfc-checkmark" hidden>
              <svg class="reader-checkmark-svg" viewBox="0 0 120 120">
                <circle class="reader-checkmark-circle" cx="60" cy="60" r="50" fill="var(--sbb-color-red, #eb0000)" />
                <path class="reader-checkmark-check" fill="none" stroke="#ffffff" stroke-width="8" stroke-linecap="round" stroke-linejoin="round" d="M36 62 L52 78 L84 44" />
              </svg>
            </div>
            <sbb-title level="2" visual-level="4" id="nfc-status-title">Hold card to reader</sbb-title>
            <p class="reader-subtitle" id="nfc-status-desc">Tap your card on the contactless reader</p>
          </div>
          <nav class="enrolment-actions" aria-label="Step actions">
            <sbb-button id="btn-step3-back" size="l" icon-name="arrow-left-small">Back</sbb-button>
            <sbb-button id="btn-nfc-skip" size="l" icon-name="arrow-right-small" icon-placement="end">Skip</sbb-button>
          </nav>
        </section>
        <section id="step-4" class="enrolment-step" aria-labelledby="heading-4" hidden>
          <div class="review-heading">
            <sbb-title level="1" visual-level="2" id="heading-4" tabindex="-1">Your card</sbb-title>
            <sbb-transparent-button id="btn-edit-details" size="m" icon-name="pen-small">Edit details</sbb-transparent-button>
          </div>
          <div class="identity-layout">
            <sbb-card class="identity-card final-card student-card" color="transparent-bordered">
              <div class="identity-top">
                <img id="final-card-photo" class="portrait sbb-image-1-1 sbb-image-border-radius-round" src="/static/portraits/default.svg" alt="Profile photo">
                <sbb-title level="2" visual-level="3" id="final-card-name"></sbb-title>
              </div>
              <div id="final-card-chips" class="access-chips"></div>
              <div class="credentials">
                <span class="credential" id="final-cred-fp"><sbb-icon name="fingerprint-small"></sbb-icon><span>Fingerprint <span class="credential-state">Not enrolled</span></span></span>
                <span class="credential" id="final-cred-nfc"><sbb-icon name="swisspass-small"></sbb-icon><span>NFC card <span class="credential-state">Not enrolled</span></span></span>
              </div>
            </sbb-card>
            <div class="record-fields review-record">
              <div class="record-heading">For the record</div>
              <dl>
                <div><dt>Plaksha ID</dt><dd id="final-demo-id">—</dd></div>
                <div><dt>Phone</dt><dd id="final-demo-phone">—</dd></div>
                <div><dt>Email</dt><dd id="final-demo-email">—</dd></div>
              </dl>
            </div>
          </div>
          <div id="save-error" role="alert" hidden></div>
          <nav class="enrolment-actions" aria-label="Step actions">
            <sbb-button id="btn-step4-back" size="l" icon-name="arrow-left-small">Back</sbb-button>
            <sbb-button id="btn-finish-enrolment" size="l" icon-name="tick-small" icon-placement="end">Save</sbb-button>
          </nav>
        </section>
        <section id="step-success" class="enrolment-step" aria-labelledby="heading-success" hidden>
          <sbb-title level="1" visual-level="2" id="heading-success" tabindex="-1">Enrolled</sbb-title>
          <div id="saved-card-host"></div>
          <nav class="enrolment-actions" aria-label="Enrolment actions">
            <sbb-button id="btn-enrol-another" size="l">Enrol another</sbb-button>
            <sbb-button-link href="/admin" size="l">Done</sbb-button-link>
          </nav>
        </section>
      </div>
    </main>
    <sbb-menu id="photo-menu" trigger="avatar-click-zone">
      <sbb-menu-button id="btn-choose-file" icon-name="folder-open-small">Choose photo</sbb-menu-button>
      <sbb-menu-button id="btn-choose-camera" icon-name="camera-small">Take photo</sbb-menu-button>
      <sbb-menu-button id="btn-remove-photo" icon-name="trash-small" hidden>Remove photo</sbb-menu-button>
    </sbb-menu>
    <input id="photo-file-input" type="file" accept="image/jpeg,image/png,image/webp" hidden>
    <sbb-dialog id="camera-dialog" aria-labelledby="camera-title">
      <sbb-dialog-title><span id="camera-title">Take photo</span></sbb-dialog-title><sbb-dialog-close-button aria-label="Close camera"></sbb-dialog-close-button>
      <sbb-dialog-content>
        <div class="camera-preview"><video id="webcam-video" autoplay playsinline muted></video><div class="camera-guide" aria-hidden="true"></div></div>
        <p class="camera-instruction">Centre your face in the circle</p>
        <div id="camera-error" role="alert" hidden></div>
      </sbb-dialog-content>
      <sbb-dialog-actions>
        <sbb-transparent-button id="btn-camera-cancel" sbb-dialog-close>Cancel</sbb-transparent-button>
        <sbb-button id="btn-camera-capture" icon-name="camera-small" disabled>Capture</sbb-button>
      </sbb-dialog-actions>
    </sbb-dialog>
    <sbb-dialog id="discard-dialog" aria-labelledby="discard-title">
      <sbb-dialog-title><span id="discard-title">Discard enrolment?</span></sbb-dialog-title><sbb-dialog-close-button aria-label="Keep editing"></sbb-dialog-close-button>
      <sbb-dialog-actions><sbb-transparent-button sbb-dialog-close>Keep editing</sbb-transparent-button><sbb-button-link href="/admin">Discard</sbb-button-link></sbb-dialog-actions>
    </sbb-dialog>
    """, sanitize=False)
