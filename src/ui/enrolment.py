"""Lyne enrolment: identity, optional readers, review, persisted confirmation."""

from __future__ import annotations

from nicegui import ui
import database as db
from ui.lyne import (
    asset_url,
    button,
    card,
    checkbox,
    element,
    form_field,
    icon,
    lyne_assets,
    menu_button,
    title,
)
from ui.display import _color_scheme


def build_enrolment_page() -> None:
    areas = db.list_access_areas()
    checkboxes = "".join(checkbox(area.label, name="access", value=area.id) for area in areas)
    theme = _color_scheme()
    ui.add_head_html(f"""
        {lyne_assets()}
        <link rel="stylesheet" href="{asset_url("display.css")}">
        <link rel="stylesheet" href="{asset_url("enrolment.css")}">
        <script>document.documentElement.dataset.theme = "{theme}"; document.documentElement.style.colorScheme = "{theme}"; document.documentElement.classList.add("sbb-{theme}");</script>
        <script type="module" src="{asset_url("enrolment.js")}"></script>
    """)

    avatar_button = element(
        "sbb-transparent-button",
        '<img id="mock-card-avatar" class="portrait sbb-image-1-1 sbb-image-border-radius-round" '
        'src="/static/portraits/default.svg" alt="Profile photo">'
        f'<span class="photo-caption">{icon("camera-small")}<span>Photo</span></span>',
        id="avatar-click-zone",
        css_class="photo-button",
        size="l",
        aria_label="Add or change photo",
    )
    name_field = form_field(
        label="Full name *",
        input_id="input-fullname",
        size="l",
        css_class="name-field",
        input_attrs={"name": "name", "type": "text", "autocomplete": "name", "maxlength": 200, "required": True},
    )
    record_fields = "".join((
        form_field(
            label="Plaksha ID",
            input_id="input-plaksha-id",
            size="l",
            input_attrs={"name": "plaksha_id", "maxlength": 100, "autocomplete": "off"},
        ),
        form_field(
            label="Phone",
            input_id="input-phone",
            size="l",
            input_attrs={"name": "phone", "type": "tel", "maxlength": 100, "autocomplete": "tel"},
        ),
        form_field(
            label="Email",
            input_id="input-email",
            size="l",
            input_attrs={"name": "email", "type": "email", "maxlength": 254, "autocomplete": "email"},
        ),
    ))
    access_group = element(
        "sbb-checkbox-group",
        checkboxes or '<span class="muted">No areas configured</span>',
        id="access-checkbox-group",
        orientation="vertical",
    )
    identity_card = card(
        f"""
              <div class="identity-top">
                {avatar_button}
                {name_field}
              </div>
              <div class="card-record-fields">
                {record_fields}
              </div>
              <fieldset class="access-fieldset">
                <legend>Authorised areas</legend>
                {access_group}
              </fieldset>
        """,
        css_class="identity-card build-card student-card",
    )
    final_card = card(
        f"""
              <div class="identity-top">
                <img id="final-card-photo" class="portrait sbb-image-1-1 sbb-image-border-radius-round" src="/static/portraits/default.svg" alt="Profile photo">
                {title("", level=2, visual_level=3, html_id="final-card-name")}
              </div>
              <div id="final-card-chips" class="access-chips"></div>
              <div class="credentials">
                <span class="credential" id="final-cred-fp">{icon("fingerprint-small")}<span>Fingerprint <span class="credential-state">Not enrolled</span></span></span>
                <span class="credential" id="final-cred-nfc">{icon("swisspass-small")}<span>NFC card <span class="credential-state">Not enrolled</span></span></span>
              </div>
        """,
        css_class="identity-card final-card student-card",
    )
    photo_menu = element(
        "sbb-menu",
        menu_button("Choose photo", html_id="btn-choose-file", icon_name="folder-open-small")
        + menu_button("Take photo", html_id="btn-choose-camera", icon_name="camera-small")
        + menu_button("Remove photo", html_id="btn-remove-photo", icon_name="trash-small", hidden=True),
        id="photo-menu",
        trigger="avatar-click-zone",
    )
    camera_dialog = element(
        "sbb-dialog",
        element("sbb-dialog-title", '<span id="camera-title">Take photo</span>')
        + element("sbb-dialog-close-button", "", aria_label="Close camera")
        + element(
            "sbb-dialog-content",
            '<div class="camera-preview"><video id="webcam-video" autoplay playsinline muted></video>'
            '<div class="camera-guide" aria-hidden="true"></div></div>'
            '<p class="camera-instruction">Centre your face in the circle</p>'
            '<div id="camera-error" role="alert" hidden></div>',
        )
        + element(
            "sbb-dialog-actions",
            button("Cancel", variant="transparent", html_id="btn-camera-cancel", sbb_dialog_close=True)
            + button("Capture", html_id="btn-camera-capture", icon_name="camera-small", disabled=True),
        ),
        id="camera-dialog",
        aria_labelledby="camera-title",
    )
    discard_dialog = element(
        "sbb-dialog",
        element("sbb-dialog-title", '<span id="discard-title">Discard enrolment?</span>')
        + element("sbb-dialog-close-button", "", aria_label="Keep editing")
        + element(
            "sbb-dialog-actions",
            button("Keep editing", variant="transparent", sbb_dialog_close=True)
            + button("Discard", link=True, href="/admin"),
        ),
        id="discard-dialog",
        aria_labelledby="discard-title",
    )

    ui.html(f"""
    <main class="enrolment-page">
      <div id="enrolment-progress" class="enrolment-progress" role="progressbar" aria-label="Enrolment progress" aria-valuemin="0" aria-valuemax="100" aria-valuenow="25" aria-valuetext="Details">
        {element("sbb-divider", "", id="enrolment-progress-fill", aria_hidden="true")}
      </div>
      <div class="enrolment-shell">
        <section id="step-1" class="enrolment-step" aria-labelledby="heading-1">
          {title("Hello!", level=1, visual_level=2, html_id="heading-1", tabindex="-1")}
          <form id="identity-form" novalidate>
            {identity_card}
            <div id="identity-error" role="alert" hidden></div>
            <nav class="enrolment-actions" aria-label="Step actions">
              {button("Back", link=True, html_id="enrolment-close-btn", size="l", href="/admin", icon_name="arrow-left-small")}
              {button("Next", html_id="btn-step1-next", size="l", type_="submit", icon_name="arrow-right-small", icon_placement="end", hidden=True)}
            </nav>
          </form>
        </section>
        <section id="step-2" class="enrolment-step reader-step" aria-labelledby="heading-2" hidden>
          {title("Fingerprint", level=1, visual_level=2, html_id="heading-2", tabindex="-1")}
          <div class="reader-stage" id="fp-stage" role="region" aria-live="polite" title="Click to simulate touch">
            <div id="fp-animation" class="reader-anim-wrap">
              {icon("fingerprint-medium", css_class="reader-icon", aria_hidden="true")}
            </div>
            <div class="reader-checkmark-container" id="fp-checkmark" hidden>
              <svg class="reader-checkmark-svg" viewBox="0 0 120 120">
                <circle class="reader-checkmark-circle" cx="60" cy="60" r="50" fill="var(--sbb-color-red, #eb0000)" />
                <path class="reader-checkmark-check" fill="none" stroke="#ffffff" stroke-width="8" stroke-linecap="round" stroke-linejoin="round" d="M36 62 L52 78 L84 44" />
              </svg>
            </div>
            {title("Reader ready", level=2, visual_level=4, html_id="fp-status-title")}
            <p class="reader-subtitle" id="fp-status-desc">Touch the biometric sensor to register fingerprint</p>
          </div>
          <nav class="enrolment-actions" aria-label="Step actions">
            {button("Back", html_id="btn-step2-back", size="l", icon_name="arrow-left-small")}
            {button("Skip", html_id="btn-fp-skip", size="l", icon_name="arrow-right-small", icon_placement="end")}
          </nav>
        </section>
        <section id="step-3" class="enrolment-step reader-step" aria-labelledby="heading-3" hidden>
          {title("NFC card", level=1, visual_level=2, html_id="heading-3", tabindex="-1")}
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
            {title("Hold card to reader", level=2, visual_level=4, html_id="nfc-status-title")}
            <p class="reader-subtitle" id="nfc-status-desc">Tap your card on the contactless reader</p>
          </div>
          <nav class="enrolment-actions" aria-label="Step actions">
            {button("Back", html_id="btn-step3-back", size="l", icon_name="arrow-left-small")}
            {button("Skip", html_id="btn-nfc-skip", size="l", icon_name="arrow-right-small", icon_placement="end")}
          </nav>
        </section>
        <section id="step-4" class="enrolment-step" aria-labelledby="heading-4" hidden>
          <div class="review-heading">
            {title("Your card", level=1, visual_level=2, html_id="heading-4", tabindex="-1")}
            {button("Edit details", variant="transparent", html_id="btn-edit-details", size="m", icon_name="pen-small")}
          </div>
          <div class="identity-layout">
            {final_card}
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
            {button("Back", html_id="btn-step4-back", size="l", icon_name="arrow-left-small")}
            {button("Save", html_id="btn-finish-enrolment", size="l", icon_name="tick-small", icon_placement="end")}
          </nav>
        </section>
        <section id="step-success" class="enrolment-step" aria-labelledby="heading-success" hidden>
          {title("Enrolled", level=1, visual_level=2, html_id="heading-success", tabindex="-1")}
          <div id="saved-card-host"></div>
          <nav class="enrolment-actions" aria-label="Enrolment actions">
            {button("Enrol another", html_id="btn-enrol-another", size="l")}
            {button("Done", link=True, href="/admin", size="l")}
          </nav>
        </section>
      </div>
    </main>
    {photo_menu}
    <input id="photo-file-input" type="file" accept="image/jpeg,image/png,image/webp" hidden>
    {camera_dialog}
    {discard_dialog}
    """, sanitize=False)
