"""Visibility controls around an automatically arranged screen wireframe."""
import json

from nicegui import ui

import database as db
from ui.admin_display import ADMIN_ICONS_JS
from ui.lyne import asset_url, button, checkbox, container, element, form_field, lyne_assets, radio_button

SCREEN_LABELS = {"display": "Public display", "admin-display": "Admin display"}
SCREEN_CONTROLS = {
    "show_greeter": "Greeter", "show_date": "Date", "show_clock": "Analogue clock",
    "show_digital_time": "Digital time", "show_summary": "Presence heading",
    "show_feedback": "Check-in feedback",
}
CARD_CONTROLS = {
    "show_photos": "Profile pictures", "show_names": "Names",
    "show_check_in": "Check-in time", "show_tools": "Authorised tool areas",
}


def _checkboxes(controls: dict) -> str:
    return "".join(checkbox(label, size="s", data_setting=key, checked=True) for key, label in controls.items())


def _screen_outline() -> str:
    cards = "".join('''<div class="card-outline">
        <span class="card-outline__photo" data-part="show_photos"></span>
        <span class="card-outline__name" data-part="show_names"></span>
        <span class="card-outline__time" data-part="show_check_in"></span>
        <span class="card-outline__access" data-part="show_tools"><i></i><i></i></span>
    </div>''' for _ in range(12))
    return f'''<div class="screen-outline" data-outline role="group" aria-label="Display layout preview">
        <div class="outline-admin-bar" data-part="show_admin_bar"></div>
        <div class="outline-presence">
            <div class="outline-summary" data-part="show_summary"></div>
            <div class="outline-grid" data-grid>
                <div class="outline-greeter-zone" data-part="show_greeter">
                    <div class="outline-greeter">LabAuth</div>
                    <div class="zone-resize-handle" title="Drag to adjust header split"></div>
                </div>
                <div class="outline-clock-stack" data-time-zone>
                    <span class="outline-date" data-part="show_date"></span>
                    <span class="outline-clock" data-part="show_clock"></span>
                    <span class="outline-time" data-part="show_digital_time"></span>
                </div>
                {cards}
            </div>
        </div>
        <div class="outline-resize-handle" title="Drag to resize screen outline"></div>
    </div>'''



def build_display_settings_page() -> None:
    from ui.display import _color_scheme
    theme = _color_scheme()
    configs = {screen: db.get_screen_settings(screen) for screen in SCREEN_LABELS}
    ui.add_head_html(f'''
        <link rel="icon" type="image/svg+xml" href="/static/favicon.svg">
        {lyne_assets()}
        <link rel="stylesheet" href="{asset_url('display.css')}">
        <script>
            document.documentElement.setAttribute('data-theme', '{theme}');
            document.documentElement.style.colorScheme = '{theme}';
            window.SCREEN_SETTINGS = {json.dumps(configs)};
            window.SCREEN_DEFAULTS = {json.dumps(db.DEFAULT_SCREEN_SETTINGS)};
            {ADMIN_ICONS_JS}
        </script>
        <script type="module" src="{asset_url('display-settings.js')}"></script>
    ''')
    targets = "".join(radio_button(label, value=screen, checked=screen == "display") for screen, label in SCREEN_LABELS.items())
    body = (
        element(
            "header",
            element("h1", "Display settings.", css_class="admin-heading")
            + button("Back", variant="secondary", link=True, href="/admin", size="m"),
            css_class="admin-header",
        )
        + element(
            "div",
            element(
                "sbb-radio-button-group",
                targets,
                name="screen",
                size="s",
                aria_label="Screen",
                data_target=True,
            )
            + form_field(label="Date size (px)", input_id="adjust-date-size", size="m",
                         input_attrs={"type": "number", "min": 14, "max": 32, "step": 1, "value": 18})
            + element("div", _checkboxes(SCREEN_CONTROLS), css_class="settings-controls", aria_label="Screen components")
            + element(
                "div",
                element(
                    "div",
                    element("label", "Card scale", **{"for": "adjust-card-scale", "class": "adjust-label"})
                    + element("input", type="range", id="adjust-card-scale", min="70", max="130", value="100", step="5", css_class="adjust-slider")
                    + element("span", "100%", id="adjust-card-scale-val", css_class="adjust-val"),
                    css_class="adjust-group",
                )
                + element(
                    "div",
                    element("label", "Clock scale", **{"for": "adjust-clock-size", "class": "adjust-label"})
                    + element("input", type="range", id="adjust-clock-size", min="70", max="140", value="100", step="5", css_class="adjust-slider")
                    + element("span", "100%", id="adjust-clock-size-val", css_class="adjust-val"),
                    css_class="adjust-group",
                )
                + element(
                    "div",
                    element("label", "Header height", **{"for": "adjust-header-height", "class": "adjust-label"})
                    + element("input", type="range", id="adjust-header-height", min="15", max="40", value="25", step="1", css_class="adjust-slider")
                    + element("span", "25%", id="adjust-header-height-val", css_class="adjust-val"),
                    css_class="adjust-group",
                ),
                css_class="settings-adjustments",
                aria_label="Adjust layout elements",
            )
            + _screen_outline()
            + element(
                "div",
                element("div", _checkboxes(CARD_CONTROLS), css_class="settings-controls", aria_label="Card information"),
                css_class="settings-card-controls",
            ),
            css_class="settings-body",
        )
        + element(
            "div",
            element("span", "", id="settings-status", role="status", aria_live="polite")
            + button("Reset", variant="secondary", html_id="settings-reset", size="m")
            + button("Apply", html_id="settings-apply", size="m"),
            css_class="settings-actions",
        )
    )
    page = element(
        "main",
        container(body, expanded=True, css_class="admin-panel-shell"),
        css_class="admin-panel admin-panel--settings",
        data_theme=theme,
    )
    ui.html(page, sanitize=False).classes('w-full admin-panel-host')
