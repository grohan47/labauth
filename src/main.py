import sys
import time
from datetime import datetime
from pathlib import Path

from nicegui import app, ui
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, RedirectResponse

import database as db
from presence import store
from ui.admin_display import (
    admin_password_is_valid,
    build_admin_display,
    build_admin_panel,
    create_admin_session,
    destroy_admin_session,
    is_admin_session_valid,
)
from ui.display import build_display

SESSION_COOKIE_NAME = "labauth_admin_session"


def request_has_valid_admin_session(request: Request) -> bool:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    return is_admin_session_valid(token)


if getattr(sys, "frozen", False):
    BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
else:
    BASE_DIR = Path(__file__).resolve().parent

STATIC_ROOT = BASE_DIR / "static" if (BASE_DIR / "static").exists() else BASE_DIR / "src" / "static"
if not STATIC_ROOT.exists():
    STATIC_ROOT = Path(__file__).resolve().parent / "static"

app.add_static_files("/static", STATIC_ROOT, max_cache_age=0)


@app.get("/api/presence")
def api_get_presence() -> JSONResponse:
    people = store.get_people()
    return JSONResponse({
        "count": len(people),
        "people": [p.to_dict() for p in people],
    })


@app.get("/api/presence/events")
def api_get_presence_events(request: Request) -> JSONResponse:
    try:
        since = int(request.query_params.get("since", 0))
    except (ValueError, TypeError):
        since = 0
    events = store.get_events(since_id=since, max_age_seconds=20.0)
    return JSONResponse({"events": events})


@app.post("/api/presence/check-in")
async def api_check_in(request: Request) -> JSONResponse:
    try:
        data = await request.json()
    except Exception:
        data = {}
    name = str(data.get("name", "")).strip()
    if not name:
        return JSONResponse({"error": "Missing 'name' in request body"}, status_code=400)

    photo = str(data.get("photo", "/static/portraits/default.svg"))
    access = tuple(data.get("access", ["Lab interior", "Tool area"]))
    checked_in = data.get("checked_in")
    if checked_in:
        checked_in = str(checked_in).strip()
    plaksha_id = data.get("plaksha_id")
    if plaksha_id:
        plaksha_id = str(plaksha_id).strip()
    person = store.check_in(
        name=name,
        photo=photo,
        access=access,
        checked_in=checked_in,
        is_temp=bool(data.get("is_temp", False)),
        plaksha_id=plaksha_id,
    )
    return JSONResponse({
        "status": "ok",
        "person": person.to_dict(),
        "total_count": len(store.get_people()),
    })


@app.post("/api/presence/check-out")
async def api_check_out(request: Request) -> JSONResponse:
    try:
        data = await request.json()
    except Exception:
        data = {}
    name = str(data.get("name", "")).strip()
    if not name:
        return JSONResponse({"error": "Missing 'name' in request body"}, status_code=400)

    check_out_time = data.get("check_out") or data.get("time")
    if check_out_time:
        check_out_time = str(check_out_time).strip()

    removed, person, out_time = store.check_out(name, check_out_time=check_out_time)
    return JSONResponse({
        "status": "ok",
        "removed": removed,
        "name": name,
        "person": person.to_dict() if person else None,
        "check_out": out_time,
        "total_count": len(store.get_people()),
    })


@app.post("/api/presence/reset")
def api_presence_reset() -> JSONResponse:
    store.reset()
    return JSONResponse({
        "status": "ok",
        "total_count": len(store.get_people()),
    })


@app.post("/api/presence/populate")
async def api_presence_populate(request: Request) -> JSONResponse:
    try:
        data = await request.json()
    except Exception:
        data = {}
    try:
        count = int(data.get("count", 8))
    except (ValueError, TypeError):
        count = 8
    count = max(0, min(count, 48))
    people = store.populate(count)
    return JSONResponse({
        "status": "ok",
        "count": count,
        "total_count": len(people),
    })


@app.post("/api/admin/login")
async def api_admin_login(request: Request) -> JSONResponse:
    """Check the admin password (labauth@2026) and issue session cookie."""
    try:
        data = await request.json()
    except Exception:
        data = {}
    password = str(data.get("password", ""))
    if not admin_password_is_valid(password):
        return JSONResponse({"error": "Incorrect password."}, status_code=401)
    token = create_admin_session()
    db.log_audit("admin", "admin_login", "session")
    resp = JSONResponse({"status": "ok", "redirect": "/admin"})
    resp.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        path="/",
        max_age=3600,
    )
    return resp


@app.post("/api/admin/logout")
def api_admin_logout_post(request: Request) -> JSONResponse:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    destroy_admin_session(token)
    resp = JSONResponse({"status": "ok", "redirect": "/admin-display"})
    resp.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
    return resp


@app.get("/api/admin/logout")
def api_admin_logout_get(request: Request) -> RedirectResponse:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    destroy_admin_session(token)
    resp = RedirectResponse("/admin-display")
    resp.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
    return resp


@app.get("/api/alerts")
def api_get_alerts() -> JSONResponse:
    return JSONResponse({
        "status": "ok",
        "alert": store.get_alert(),
    })


@app.post("/api/alerts")
async def api_post_alerts(request: Request) -> JSONResponse:
    try:
        data = await request.json()
    except Exception:
        data = {}
    alert_text = data.get("alert")
    previous = store.get_alert()
    store.set_alert(alert_text)
    current = store.get_alert()
    if previous != current:
        db.log_audit(
            "admin",
            "settings_changed",
            "display",
            entity_id="alert",
            before=previous,
            after=current,
        )
    return JSONResponse({
        "status": "ok",
        "alert": store.get_alert(),
    })


@app.get("/api/time")
def api_get_time() -> JSONResponse:
    now = datetime.now()
    mock_t = store.get_mock_time()
    mock_d = store.get_mock_date()
    return JSONResponse({
        "status": "ok",
        "timestamp": time.time(),
        "iso": now.isoformat(),
        "time": now.strftime("%H:%M"),
        "time_seconds": now.strftime("%H:%M:%S"),
        "date": now.strftime("%B %d, %Y"),
        "hour": now.hour,
        "minute": now.minute,
        "second": now.second,
        "mock_time": mock_t,
        "mock_date": mock_d,
    })


@app.get("/api/time/mock")
def api_get_mock_time() -> JSONResponse:
    return JSONResponse({
        "mock_time": store.get_mock_time(),
        "mock_date": store.get_mock_date(),
    })


@app.post("/api/time/mock")
async def api_set_mock_time(request: Request) -> JSONResponse:
    try:
        data = await request.json()
    except Exception:
        data = {}
    if data.get("reset"):
        store.set_mock_time(None, None)
    else:
        time_val = data.get("time")
        date_val = data.get("date")
        store.set_mock_time(time_val, date_val)
    return JSONResponse({
        "status": "ok",
        "mock_time": store.get_mock_time(),
        "mock_date": store.get_mock_date(),
    })


FAVICON_PATH = STATIC_ROOT / "favicon.svg"


@app.get("/favicon.ico")
def favicon_ico() -> FileResponse:
    return FileResponse(FAVICON_PATH, media_type="image/svg+xml")


@app.get("/favicon.svg")
def favicon_svg() -> FileResponse:
    return FileResponse(FAVICON_PATH, media_type="image/svg+xml")


@ui.page("/", dark=None, favicon=FAVICON_PATH)
def index() -> RedirectResponse:
    return RedirectResponse("/display")


@ui.page(
    "/display",
    title="LabAuth",
    dark=None,
    viewport="width=device-width, initial-scale=1, viewport-fit=cover",
    favicon=FAVICON_PATH,
)
def display() -> None:
    build_display()


@ui.page(
    "/admin-display",
    title="LabAuth \u2013 Admin",
    dark=None,
    viewport="width=device-width, initial-scale=1, viewport-fit=cover",
    favicon=FAVICON_PATH,
)
def admin_display() -> None:
    build_admin_display()


@ui.page("/admin", title="LabAuth \u2013 Administration", dark=None, favicon=FAVICON_PATH)
def admin_panel(request: Request) -> RedirectResponse | None:
    if not request_has_valid_admin_session(request):
        return RedirectResponse("/admin-display")
    build_admin_panel()
    return None


@ui.page("/enrollment", title="LabAuth \u2013 Enrollment", dark=None, favicon=FAVICON_PATH)
def enrollment_page(request: Request) -> RedirectResponse | None:
    """Enrollment route that authenticates whether the admin login session is still active or not."""
    if not request_has_valid_admin_session(request):
        return RedirectResponse("/admin-display")
    ui.add_head_html("""
        <link rel="icon" type="image/svg+xml" href="/static/favicon.svg">
        <link rel="stylesheet" href="/static/vendor/sbb-variables.css">
        <link rel="stylesheet" href="/static/vendor/standard-theme.css">
        <link rel="stylesheet" href="/static/display.css?v=35">
        <script type="module" src="/static/vendor/sbb-elements.bundle.js"></script>
    """)
    ui.html("""
        <main class="admin-panel">
            <sbb-container color="transparent" class="admin-panel-shell">
                <header class="admin-header">
                    <h1 class="admin-heading">Enrollment.</h1>
                    <div class="admin-header-controls">
                        <sbb-secondary-button href="/admin" size="m" aria-label="Return to administration">
                            Admin
                        </sbb-secondary-button>
                    </div>
                </header>
                <div style="margin-block-start: var(--sbb-spacing-responsive-l);">
                    <sbb-title level="2" visual-level="3">Step 1: Identity</sbb-title>
                    <p style="color: var(--display-muted); margin-block-start: var(--sbb-spacing-fixed-2x);">
                        Session active. Sequential enrollment workflow begins here.
                    </p>
                </div>
            </sbb-container>
        </main>
    """, sanitize=False)
    return None


@ui.page("/logs", title="LabAuth \u2013 Logs", dark=None, favicon=FAVICON_PATH)
def logs_page(request: Request) -> RedirectResponse | None:
    if not request_has_valid_admin_session(request):
        return RedirectResponse("/admin-display")
    ui.add_head_html("""
        <link rel="icon" type="image/svg+xml" href="/static/favicon.svg">
        <link rel="stylesheet" href="/static/vendor/sbb-variables.css">
        <link rel="stylesheet" href="/static/vendor/standard-theme.css">
        <link rel="stylesheet" href="/static/display.css?v=35">
        <script type="module" src="/static/vendor/sbb-elements.bundle.js"></script>
    """)
    ui.html("""
        <main class="admin-panel">
            <sbb-container color="transparent" class="admin-panel-shell">
                <header class="admin-header">
                    <h1 class="admin-heading">Logs.</h1>
                    <div class="admin-header-controls">
                        <sbb-secondary-button href="/admin" size="m" aria-label="Return to administration">
                            Admin
                        </sbb-secondary-button>
                    </div>
                </header>
                <div style="margin-block-start: var(--sbb-spacing-responsive-l);">
                    <p style="color: var(--display-muted);">Immutable audit & presence logs (not yet constructed).</p>
                </div>
            </sbb-container>
        </main>
    """, sanitize=False)
    return None


@ui.page("/search", title="LabAuth \u2013 Search", dark=None, favicon=FAVICON_PATH)
def search_page(request: Request) -> RedirectResponse | None:
    if not request_has_valid_admin_session(request):
        return RedirectResponse("/admin-display")
    ui.add_head_html("""
        <link rel="icon" type="image/svg+xml" href="/static/favicon.svg">
        <link rel="stylesheet" href="/static/vendor/sbb-variables.css">
        <link rel="stylesheet" href="/static/vendor/standard-theme.css">
        <link rel="stylesheet" href="/static/display.css?v=35">
        <script type="module" src="/static/vendor/sbb-elements.bundle.js"></script>
    """)
    ui.html("""
        <main class="admin-panel">
            <sbb-container color="transparent" class="admin-panel-shell">
                <header class="admin-header">
                    <h1 class="admin-heading">Search.</h1>
                    <div class="admin-header-controls">
                        <sbb-secondary-button href="/admin" size="m" aria-label="Return to administration">
                            Admin
                        </sbb-secondary-button>
                    </div>
                </header>
                <div style="margin-block-start: var(--sbb-spacing-responsive-l); max-width: 32rem;">
                    <sbb-form-field size="m" width="default" floating-label>
                        <label for="search-user-input">Search enrolled users by name</label>
                        <input id="search-user-input" type="search" placeholder="Type a name..." autocomplete="off">
                    </sbb-form-field>
                    <div id="search-results-list" style="margin-block-start: var(--sbb-spacing-fixed-4x);"></div>
                </div>
            </sbb-container>
        </main>
    """, sanitize=False)
    ui.add_body_html("""
        <script>
            (function() {
                const input = document.querySelector('#search-user-input');
                const list = document.querySelector('#search-results-list');
                if (input && list) {
                    input.addEventListener('input', async () => {
                        const query = (input.value || '').trim().toLowerCase();
                        if (!query) {
                            list.innerHTML = '';
                            return;
                        }
                        try {
                            const res = await fetch('/api/presence');
                            if (res.ok) {
                                const data = await res.json();
                                const matches = (data.people || []).filter(p => p.name.toLowerCase().includes(query));
                                if (matches.length === 0) {
                                    list.innerHTML = '<p style="color: var(--display-muted);">No enrolled users found.</p>';
                                } else {
                                    list.innerHTML = matches.map(m => `
                                        <div style="padding: 12px 16px; border-bottom: 1px solid var(--display-border); display: flex; justify-content: space-between; align-items: center;">
                                            <span style="font-weight: 500;">${m.name}</span>
                                            <span style="color: var(--display-muted); font-size: 0.875rem;">${(m.access || []).join(', ')}</span>
                                        </div>
                                    `).join('');
                                }
                            }
                        } catch (e) {}
                    });
                }
            })();
        </script>
    """)
    return None


import os

def run() -> None:
    port = int(os.environ.get("PORT", 8080))
    ui.run(
        host="127.0.0.1",
        port=port,
        title="LabAuth",
        dark=None,
        favicon=FAVICON_PATH,
        show=False,
        reload=False,
        show_welcome_message=False,
    )


if __name__ in {"__main__", "__mp_main__"}:
    run()
