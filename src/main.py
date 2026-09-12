import sys
import time
from datetime import datetime
from pathlib import Path

from nicegui import app, ui
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse

from presence import store
from ui.display import build_display


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
    person = store.check_in(name=name, photo=photo, access=access, checked_in=checked_in)
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


@ui.page("/", dark=None)
def index() -> RedirectResponse:
    return RedirectResponse("/display")


@ui.page(
    "/display",
    title="LabAuth",
    dark=None,
    viewport="width=device-width, initial-scale=1, viewport-fit=cover",
)
def display() -> None:
    build_display()


import os

def run() -> None:
    port = int(os.environ.get("PORT", 8080))
    ui.run(
        host="127.0.0.1",
        port=port,
        title="LabAuth",
        dark=None,
        show=False,
        reload=False,
        show_welcome_message=False,
    )


if __name__ in {"__main__", "__mp_main__"}:
    run()
