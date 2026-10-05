"""Unit tests for the Display Settings feature."""

from __future__ import annotations

import os
from pathlib import Path
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import database as db
from presence import PersonInside
from ui.display import _person_card, _presence_content, render_presence_html


@pytest.fixture(autouse=True)
def temp_db(tmp_path: Path):
    """Use a clean temporary database for each test."""
    test_db_path = tmp_path / "test_display_settings.db"
    old_env = os.environ.get("LABAUTH_DB_PATH")
    os.environ["LABAUTH_DB_PATH"] = str(test_db_path)
    db.init_db()
    yield
    if old_env is not None:
        os.environ["LABAUTH_DB_PATH"] = old_env
    else:
        os.environ.pop("LABAUTH_DB_PATH", None)


def test_default_display_settings():
    """Verify default screen settings for display and admin-display."""
    cfg = db.get_screen_settings("display")
    assert cfg["show_greeter"] is True
    assert cfg["show_clock"] is True
    assert cfg["show_date"] is True
    assert cfg["show_photos"] is True
    assert cfg["show_tools"] is True
    assert cfg["grid_ratio"] == 70
    assert cfg["max_rows"] == 3


def test_update_and_persist_display_settings():
    """Verify updating and persisting display settings."""
    updated = db.set_screen_settings("display", {
        "show_greeter": False,
        "show_clock": False,
        "show_photos": False,
        "grid_ratio": 80,
        "max_rows": 2,
    })
    assert updated["show_greeter"] is False
    assert updated["show_clock"] is False
    assert updated["show_date"] is True  # preserved default
    assert updated["show_photos"] is False
    assert updated["grid_ratio"] == 80
    assert updated["max_rows"] == 2

    # Fetch fresh
    fetched = db.get_screen_settings("display")
    assert fetched == updated

    # admin-display settings remain unaffected
    admin_cfg = db.get_screen_settings("admin-display")
    assert admin_cfg["show_greeter"] is True
    assert admin_cfg["grid_ratio"] == 70


def test_settings_sanitization_and_clamping():
    """Verify grid_ratio and max_rows clamping."""
    updated = db.set_screen_settings("display", {
        "grid_ratio": 150,  # exceeds max 90
        "max_rows": 10,     # exceeds max 3
    })
    assert updated["grid_ratio"] == 90
    assert updated["max_rows"] == 3

    updated_low = db.set_screen_settings("display", {
        "grid_ratio": 10,   # below min 30
        "max_rows": 0,      # below min 1
    })
    assert updated_low["grid_ratio"] == 30
    assert updated_low["max_rows"] == 1


def test_person_card_photo_and_tool_toggles():
    """Verify _person_card respects show_photos and show_tools."""
    person = PersonInside(
        name="Test Person",
        photo="/static/portraits/default.svg",
        checked_in="12:00",
        access=("Laser cutter", "3D printers"),
    )

    # All enabled
    html_all = _person_card(person, density="1row", show_photos=True, show_tools=True)
    assert "person-photo" in html_all
    assert "Laser cutter" in html_all
    assert "person-card--no-photo" not in html_all
    assert "person-card--no-tools" not in html_all

    # Photo disabled
    html_no_photo = _person_card(person, density="1row", show_photos=False, show_tools=True)
    assert "person-photo" not in html_no_photo
    assert "Laser cutter" in html_no_photo
    assert "person-card--no-photo" in html_no_photo

    # Tools disabled
    html_no_tools = _person_card(person, density="1row", show_photos=True, show_tools=False)
    assert "person-photo" in html_no_tools
    assert "Laser cutter" not in html_no_tools
    assert "person-card--no-tools" in html_no_tools


def test_presence_content_row_limits():
    """Verify _presence_content respects max_rows and density."""
    people = tuple(
        PersonInside(
            name=f"User {i}",
            photo="/static/portraits/default.svg",
            checked_in="10:00",
            access=("Indoor lab",),
        )
        for i in range(6)
    )

    # With max_rows = 1, 6 people should activate carousel with page size 4
    html_1row = _presence_content(people, settings={"max_rows": 1})
    assert "carousel-stage" in html_1row

    # With max_rows = 2, 6 people fits in 2 rows without carousel
    html_2rows = _presence_content(people, settings={"max_rows": 2})
    assert "people-grid--2rows" in html_2rows
    assert "carousel-stage" not in html_2rows
