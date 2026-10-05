#!/usr/bin/env python3
"""Tests for the display settings: persistence, automatic layout settings, and rendering.

Run directly:  PYTHONPATH=src uv run python tests/test_display_settings.py
Pytest:        uv run pytest tests/test_display_settings.py

The suite always points LABAUTH_DB_PATH at a throwaway temporary database.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

_TMP_DIR = Path(tempfile.mkdtemp(prefix="labauth-display-settings-"))
os.environ["LABAUTH_DB_PATH"] = str(_TMP_DIR / "labauth.db")

import database as db  # noqa: E402
from presence import PersonInside  # noqa: E402
from ui.display import _person_card, _presence_content  # noqa: E402


def _reset() -> None:
    for screen in db.SCREEN_TARGETS:
        db.set_screen_settings(screen, dict(db.DEFAULT_SCREEN_SETTINGS))


def _person(name: str = "Aisha Khan", access: tuple[str, ...] = ("Laser cutter",)) -> PersonInside:
    return PersonInside(
        name=name,
        photo="/static/portraits/default.svg",
        checked_in="08:00",
        access=access,
    )


def test_defaults_apply_to_unset_targets():
    _reset()
    for screen in db.SCREEN_TARGETS:
        assert db.get_screen_settings(screen) == db.DEFAULT_SCREEN_SETTINGS


def test_settings_persist_and_stay_isolated_per_target():
    _reset()
    updated = db.set_screen_settings("display", {"show_clock": False, "show_names": False})
    assert updated["show_clock"] is False
    assert updated["show_names"] is False
    assert db.get_screen_settings("display") == updated

    assert db.get_screen_settings("admin-display") == db.DEFAULT_SCREEN_SETTINGS


def test_partial_updates_preserve_earlier_values():
    _reset()
    db.set_screen_settings("display", {"show_photos": False, "show_names": False})
    merged = db.set_screen_settings("display", {"show_tools": False})

    assert merged["show_photos"] is False
    assert merged["show_tools"] is False
    assert merged["show_names"] is False
    assert merged["show_greeter"] is True


def test_old_manual_layout_values_are_ignored():
    _reset()
    obsolete = {"grid_ratio": 90, "max_rows": 1, "row_sizes": [10, 80, 10]}
    db.set_setting("display_settings_display", json.dumps({**obsolete, "show_clock": False}))
    stored = db.get_screen_settings("display")
    assert stored["show_clock"] is False
    assert not any(key in stored for key in obsolete)
    saved = db.set_screen_settings("display", obsolete)
    assert saved == stored


def test_corrupt_stored_value_falls_back_to_defaults():
    _reset()
    db.set_setting("display_settings_display", "{not json")
    assert db.get_screen_settings("display") == db.DEFAULT_SCREEN_SETTINGS


def test_unknown_keys_are_not_persisted():
    _reset()
    result = db.set_screen_settings("display", {"nonsense": "value"})
    assert "nonsense" not in result
    assert "nonsense" not in db.get_screen_settings("display")


def test_person_card_respects_photo_and_access_switches():
    person = _person()

    full = _person_card(person, density="1row", show_photos=True, show_tools=True)
    assert "person-photo" in full
    assert "Laser cutter" in full

    no_photo = _person_card(person, density="1row", show_photos=False, show_tools=True)
    assert "person-photo" not in no_photo
    assert "Laser cutter" in no_photo
    assert "person-card--no-photo" in no_photo

    no_tools = _person_card(person, density="1row", show_photos=True, show_tools=False)
    assert "person-photo" in no_tools
    assert "Laser cutter" not in no_tools
    assert "person-card--no-tools" in no_tools


def test_configured_render_never_drops_people():
    people = tuple(_person(name=f"User {index}") for index in range(20))
    for components in ({}, {"show_greeter": False}, {"show_greeter": False, "show_clock": False}, {"show_photos": False, "show_tools": False}):
        html = _presence_content(people, settings=components)
        assert html.count('<sbb-card ') == len(people)
        for person in people:
            assert person.name in html


def test_optional_fields_persist():
    _reset()
    result = db.set_screen_settings("display", {"show_digital_time": False, "show_check_in": False, "show_summary": False})
    assert result["show_digital_time"] is False
    assert result["show_check_in"] is False
    assert result["show_summary"] is False
    assert db.get_screen_settings("admin-display") == db.DEFAULT_SCREEN_SETTINGS


def test_admin_bar_cannot_be_removed_by_stale_settings():
    _reset()
    db.set_setting("display_settings_admin-display", '{"show_admin_bar": false}')
    assert "show_admin_bar" not in db.get_screen_settings("admin-display")
    result = db.set_screen_settings("admin-display", {"show_admin_bar": False, "show_cards": False})
    assert "show_admin_bar" not in result
    assert "show_cards" not in result


def main() -> int:
    db.init_db()
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    failures = 0
    print("=" * 65)
    print("  LABAUTH DISPLAY SETTINGS SUITE")
    print("=" * 65)
    for test in tests:
        try:
            test()
            print(f"  PASS  {test.__name__}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"  FAIL  {test.__name__}: {type(exc).__name__}: {exc}")
    print("-" * 65)
    print(f"  {len(tests) - failures}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    finally:
        shutil.rmtree(_TMP_DIR, ignore_errors=True)
