import json
import sys
from datetime import datetime

from nicegui import ui

from presence import PersonInside, store
from ui.lyne import card, chip, icon, image, title


def _formatted_date() -> str:
    mock_d = store.get_mock_date()
    if mock_d:
        return mock_d
    return datetime.now().strftime("%B %-d, %Y")


def _color_scheme() -> str:
    mock_t = store.get_mock_time()
    if mock_t and ":" in mock_t:
        try:
            hour = int(mock_t.split(":")[0])
        except ValueError:
            hour = datetime.now().hour
    else:
        hour = datetime.now().hour
    return "dark" if (hour >= 18 or hour < 6) else "light"


def _initial_greeting() -> str:
    mock_t = store.get_mock_time()
    if mock_t and ":" in mock_t:
        try:
            hour = int(mock_t.split(":")[0])
        except ValueError:
            hour = datetime.now().hour
    else:
        hour = datetime.now().hour
    if 5 <= hour < 12:
        return "Good morning!"
    if 12 <= hour < 17:
        return "Good afternoon!"
    if 17 <= hour < 21:
        return "Good evening!"
    return "Good night!"


LYNE_ELEMENTS_VERSION = "5.8.0"
LYNE_DESIGN_TOKENS_VERSION = "2.1.3"
JSDELIVR_NPM = "https://cdn.jsdelivr.net/npm"
LYNE_COMPONENT_MODULES = (
    "button",
    "clock",
    "title",
    "container",
    "card",
    "dialog",
    "form-field",
    "header",
    "image",
    "chip-label",
    "carousel",
    "icon",
    "signet",
    "logo",
)


def _grid_density(count: int) -> str:
    if count <= 4:
        return "1row"
    if count <= 8:
        return "2rows"
    return "3rows"


def _person_card(person: PersonInside, *, density: str) -> str:
    tool_count = len(person.access)
    chip_size = "xs" if (density == "3rows" or tool_count > 2) else "s"
    access = "".join(chip(item, size=chip_size) for item in person.access)
    visual_level = 5 if density == "3rows" else 4 if density == "2rows" else 3
    spacing = {
        "1row": "sbb-card-spacing-xxs",
        "2rows": "sbb-card-spacing-xxs",
        "3rows": "sbb-card-spacing-4x-xxs",
    }.get(density, "sbb-card-spacing-xxs")
    content = f"""
        <div class="card-id-header">
            <figure class="person-photo sbb-figure">
                {image(person.photo, alt=f"Portrait of {person.name}", css_class="sbb-image-1-1")}
            </figure>
            {title(person.name, level=2, visual_level=visual_level, css_class="person-name")}
        </div>
        <div class="card-id-body">
            <div class="check-in">
                <span class="check-in-label">Check-in time</span>
                <time class="check-in-time" datetime="{person.checked_in}">{person.checked_in}</time>
            </div>
            <div class="access-list access-list--grid access-list--tools-{min(tool_count, 4)}">
                {access}
            </div>
        </div>
    """
    return card(content, css_class=f"person-card person-card--{density} person-card--tools-{min(tool_count, 4)} {spacing}")


def _people_grid(people: tuple[PersonInside, ...], *, density: str = "1row") -> str:
    cards = "".join(_person_card(person, density=density) for person in people)
    return f"""
        <div class="people-grid people-grid--{density}">{cards}</div>
    """


def _carousel_view(page_people: tuple[PersonInside, ...], page_idx: int, is_active: bool) -> str:
    row1_cards = "".join(_person_card(p, density="2rows") for p in page_people[:4])
    row2_cards = "".join(_person_card(p, density="2rows") for p in page_people[4:8])
    active_class = " is-active" if is_active else ""
    return f"""
        <div class="carousel-view{active_class}" data-page="{page_idx}">
            <div class="carousel-row carousel-row--top">{row1_cards}</div>
            <div class="carousel-row carousel-row--bottom">{row2_cards}</div>
        </div>
    """


def _presence_content(people: tuple[PersonInside, ...] | None = None) -> str:
    if people is None:
        people = store.get_people()

    if len(people) <= 12:
        density = _grid_density(len(people))
        return _people_grid(people, density=density)

    pages = tuple(
        people[start : start + 8]
        for start in range(0, len(people), 8)
    )
    views = "".join(
        _carousel_view(page, idx, idx == 0)
        for idx, page in enumerate(pages)
    )
    return f'<div class="carousel-stage">{views}</div>'


def presence_signature(people: tuple[PersonInside, ...] | None = None) -> str:
    """Cheap fingerprint of the current presence used for client reconciliation."""
    if people is None:
        people = store.get_people()
    return "|".join(
        f"{p.user_id}:{p.name}:{p.checked_in}:{','.join(p.access)}:{int(p.is_temp)}"
        for p in people
    )


def render_presence_html(people: tuple[PersonInside, ...] | None = None) -> str:
    """Server-rendered card markup, reused for in-place client refreshes."""
    return _presence_content(people)


from pathlib import Path


def build_display(*, admin: bool = False) -> None:
    if getattr(sys, "frozen", False):
        base_dir = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
        static_root = base_dir / "static" if (base_dir / "static").exists() else base_dir / "src" / "static"
    else:
        static_root = Path(__file__).resolve().parent.parent / "static"
    has_local_vendor = (
        (static_root / "vendor" / "sbb-elements.bundle.js").exists()
        and (static_root / "vendor" / "sbb-variables.css").exists()
        and (static_root / "vendor" / "standard-theme.css").exists()
    )

    if has_local_vendor:
        sbb_styles = """
        <link rel="stylesheet" href="/static/vendor/sbb-variables.css">
        <link rel="stylesheet" href="/static/vendor/standard-theme.css">
        """
        sbb_scripts = """
        <script type="module" src="/static/vendor/sbb-elements.bundle.js"></script>
        """
    else:
        sbb_styles = f"""
        <link rel="stylesheet" href="{JSDELIVR_NPM}/@sbb-esta/lyne-design-tokens@{LYNE_DESIGN_TOKENS_VERSION}/dist/css/sbb-variables.css">
        <link rel="stylesheet" href="{JSDELIVR_NPM}/@sbb-esta/lyne-elements@{LYNE_ELEMENTS_VERSION}/standard-theme.css">
        """
        component_scripts = "\n".join(
            f'<script type="module" src="{JSDELIVR_NPM}/@sbb-esta/'
            f'lyne-elements@{LYNE_ELEMENTS_VERSION}/{component}.js/+esm"></script>'
            for component in LYNE_COMPONENT_MODULES
        )
        sbb_scripts = component_scripts

    init_mock_t = store.get_mock_time()
    init_mock_d = store.get_mock_date()
    init_event = store.get_recent_event(max_age_seconds=5.0)
    init_mock_js = ""
    if init_mock_t:
        init_mock_js += f'window.INITIAL_MOCK_TIME = "{init_mock_t}";\n'
    if init_mock_d:
        init_mock_js += f'window.INITIAL_MOCK_DATE = "{init_mock_d}";\n'
    if init_event:
        init_mock_js += f"window.INITIAL_AUTH_EVENT = {json.dumps(init_event)};\n"
    init_mock_js += f"window.INITIAL_PRESENCE_SIGNATURE = {json.dumps(presence_signature())};\n"

    initial_theme = _color_scheme()
    ui.add_head_html(
        f"""
        <script>
            (function() {{
                {init_mock_js}
                const theme = "{initial_theme}";
                document.documentElement.setAttribute('data-theme', theme);
                document.documentElement.style.colorScheme = theme;

                const BUILTIN_ICONS = {{
                    'entrance-medium': '<svg xmlns="http://www.w3.org/2000/svg" width="36" height="36" fill="none" viewBox="0 0 36 36"><path fill="#000" fill-rule="evenodd" d="M5.25 6.25h-.5v23.5h19V25.5h-1v3.25h-17V7.25h17v3.25h1V6.25H5.25m5.66 12.147 4.712-4.724.708.706-3.86 3.871h19.045v1H12.473l3.857 3.858-.707.707-4.712-4.712-.353-.353z" clip-rule="evenodd"/></svg>',
                    'entrance-small': '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" fill="none" viewBox="0 0 24 24"><path fill="#000" fill-rule="evenodd" d="M3.5 4H3v16h13v-3h-1v2H4V5h11v2h1V4H3.5m3.656 8.147 3.14-3.15.709.707L8.715 12H21.01v1H8.717l2.287 2.287-.707.707-3.14-3.14-.354-.354z" clip-rule="evenodd"/></svg>',
                    'exit-medium': '<svg xmlns="http://www.w3.org/2000/svg" width="36" height="36" fill="none" viewBox="0 0 36 36"><path fill="#000" fill-rule="evenodd" d="M5.25 6.25h-.5v23.5h19V25.5h-1v3.25h-17V7.25h17v3.25h1V6.25H5.25m21.141 7.435 4.713 4.711.353.354-.352.353-4.713 4.724-.708-.707 3.861-3.87H10.5v-1h19.043l-3.859-3.858z" clip-rule="evenodd"/></svg>',
                    'exit-small': '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" fill="none" viewBox="0 0 24 24"><path fill="#000" fill-rule="evenodd" d="M3.5 4H3v16h13v-3h-1v2H4V5h11v2h1V4H3.5m14.212 5.005 3.142 3.141.353.354-.353.353-3.142 3.15-.707-.707L19.295 13H7v-1h12.293l-2.288-2.287z" clip-rule="evenodd"/></svg>',
                    'cross-small': '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" fill="none" viewBox="0 0 24 24"><path fill="#000" fill-rule="evenodd" d="m12.707 12 5.647-5.647-.707-.707L12 11.293 6.354 5.646l-.708.707L11.293 12l-5.647 5.646.708.707L12 12.707l5.647 5.646.707-.707z" clip-rule="evenodd"/></svg>'
                }};
                globalThis.sbbConfig = globalThis.sbbConfig || {{}};
                globalThis.sbbConfig.icon = globalThis.sbbConfig.icon || {{}};
                globalThis.sbbConfig.icon.interceptor = function(context) {{
                    if (context && context.name && BUILTIN_ICONS[context.name]) {{
                        return BUILTIN_ICONS[context.name];
                    }}
                    return typeof context.request === 'function' ? context.request() : Promise.resolve('');
                }};
            }})();
        </script>
        <link rel="icon" type="image/svg+xml" href="/static/favicon.svg">
        {sbb_styles}
        <link rel="stylesheet" href="/static/display.css?v=32">
        {sbb_scripts}
        <script type="module" src="/static/display.js?v=31"></script>
        {('<script type="module" src="/static/admin-display.js?v=3"></script>' if admin else '')}
        """
    )

    if admin:
        from ui.admin_display import admin_chrome

        ui.html(admin_chrome(), sanitize=False)

    display_classes = "display display-host admin-display" if admin else "display display-host"
    with ui.element("main").classes(display_classes).props(f'data-theme="{_color_scheme()}" aria-labelledby="display-greeting"'):
        with ui.element("sbb-container").classes("display-shell").props('color="transparent"'):
            with ui.element("div").classes("display-frame"):
                header_markup = f"""
                    <header class="display-header sbb-grid-only">
                        <div class="display-intro">
                            {title(_initial_greeting(), level=1, visual_level=2, css_class="display-greeting", html_id="display-greeting")}
                        </div>

                        <aside class="time-panel" aria-label="Current time">
                            <div class="clock-stack">
                                <time class="clock-date" id="clock-date">{_formatted_date()}</time>
                                <sbb-clock aria-label="Analogue clock"></sbb-clock>
                                <time class="digital-time" id="digital-time">--:--</time>
                            </div>
                        </aside>
                    </header>
                """
                ui.html(header_markup, sanitize=False)

                presence_section = ui.element("section").classes("current-presence").props('aria-label="People currently in the lab"')
                with presence_section:
                    ui.html('<p class="display-summary">Here’s who is in the lab.</p>', sanitize=False)
                    presence_body = ui.html(_presence_content(), sanitize=False).classes("presence-content-wrapper")

            ui.html('<div id="auth-alert-overlay" class="auth-alert-overlay" role="dialog" aria-modal="true" aria-live="assertive" hidden></div>', sanitize=False)
            ui.html('<div id="auth-feedback" class="auth-feedback" role="status" aria-live="polite" hidden></div>', sanitize=False)

    client = ui.context.client

    def on_presence_update(event: dict | None = None) -> None:
        try:
            with client:
                presence_body.content = _presence_content()
                if client.has_socket_connection:
                    mock_t = store.get_mock_time()
                    mock_d = store.get_mock_date()
                    if mock_t:
                        d_arg = f'"{mock_d}"' if mock_d else "null"
                        client.run_javascript(f'if (window.setMockTime) window.setMockTime("{mock_t}", {d_arg});')
                    else:
                        client.run_javascript("if (window.setMockTime) window.setMockTime(null);")
                    client.run_javascript("if (window.updateGreetingAlignment) window.updateGreetingAlignment();")
                    client.run_javascript(
                        "if (window.setPresenceSignature) "
                        f"window.setPresenceSignature({json.dumps(presence_signature())});"
                    )
                    if event:
                        event_json = json.dumps(event)
                        client.run_javascript(f"if (window.handleAuthEvent) window.handleAuthEvent({event_json});")
        except Exception:
            pass

    store.add_listener(on_presence_update)
    client.on_disconnect(lambda: store.remove_listener(on_presence_update))
