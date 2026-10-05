"""Visibility controls around an automatically arranged screen wireframe."""
import json

from nicegui import ui

import database as db
from ui.admin_display import ADMIN_ICONS_JS
from ui.lyne import asset_url, lyne_assets

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
    return "".join(f'<sbb-checkbox size="s" data-setting="{key}" checked>{label}</sbb-checkbox>' for key, label in controls.items())


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
                <div class="outline-greeter-zone" data-part="show_greeter"><div class="outline-greeter"></div></div>
                <div class="outline-clock-stack" data-time-zone>
                    <span class="outline-date" data-part="show_date"></span>
                    <span class="outline-clock" data-part="show_clock"></span>
                    <span class="outline-time" data-part="show_digital_time"></span>
                </div>
                {cards}
            </div>
        </div>
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
    targets = "".join(f'<sbb-radio-button value="{screen}" {"checked" if screen == "display" else ""}>{label}</sbb-radio-button>' for screen, label in SCREEN_LABELS.items())
    ui.html(f'''
        <main class="admin-panel admin-panel--settings" data-theme="{theme}">
            <sbb-container color="transparent" expanded class="admin-panel-shell">
                <header class="admin-header">
                    <h1 class="admin-heading">Display settings.</h1>
                    <sbb-secondary-button href="/admin" size="m">Back</sbb-secondary-button>
                </header>
                <div class="settings-body">
                    <sbb-radio-button-group name="screen" size="s" aria-label="Screen" data-target>{targets}</sbb-radio-button-group>
                    <div class="settings-controls" aria-label="Screen components">{_checkboxes(SCREEN_CONTROLS)}</div>
                    {_screen_outline()}
                    <div class="settings-card-controls">
                        <div class="settings-controls" aria-label="Card information">{_checkboxes(CARD_CONTROLS)}</div>
                    </div>
                </div>
                <div class="settings-actions">
                    <span id="settings-status" role="status" aria-live="polite"></span>
                    <sbb-secondary-button id="settings-reset" size="m">Reset</sbb-secondary-button>
                    <sbb-button id="settings-apply" size="m">Apply</sbb-button>
                </div>
            </sbb-container>
        </main>
    ''', sanitize=False).classes('w-full admin-panel-host')
