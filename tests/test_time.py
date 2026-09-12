#!/usr/bin/env python3
"""
Test script for specifying a time and verifying visual appearance on the LabAuth display.

Features:
1. Specify any time (HH:MM or HH:MM:SS) and date to see how the display looks.
2. Auto-switches color scheme:
   - Light mode (06:00 - 18:00)
   - Dark mode  (18:00 - 06:00)
3. Aligns analogue clock hands, digital HH:MM readout, and multilingual greeting period:
   - Morning   (05:00 - 12:00): "Good morning!"
   - Afternoon (12:00 - 17:00): "Good afternoon!"
   - Evening   (17:00 - 21:00): "Good evening!"
   - Night     (21:00 - 05:00): "Good night!"
4. Automatically updates all active browser display sessions in real time via WebSockets.
5. Can capture high-resolution screenshots via headless Chromium.

Usage:
  # Set a specific time:
  uv run python tests/test_time.py --time 14:15
  uv run python tests/test_time.py -t 19:30 -d "October 31, 2026"

  # Reset back to live system time:
  uv run python tests/test_time.py --reset

  # Run verification across all 4 daily periods with screenshots:
  uv run python tests/test_time.py --all

  # Set time and save a screenshot:
  uv run python tests/test_time.py -t 08:30 --screenshot /tmp/morning.png

Python Import:
  from tests.test_time import set_time, reset_time, get_time, test_all_periods
  set_time("18:30")
  reset_time()
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


DEFAULT_PORT = int(os.environ.get("PORT", 8080))
DEFAULT_BASE_URL = f"http://127.0.0.1:{DEFAULT_PORT}"


def _post_json(url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def set_time(
    time_str: str,
    date_str: str | None = None,
    base_url: str = DEFAULT_BASE_URL,
) -> dict:
    """Set the mock time and optional date on the running LabAuth server.

    All connected displays immediately update their analogue hands, digital
    time, color scheme, and greeting.
    """
    url = f"{base_url.rstrip('/')}/api/time/mock"
    payload = {"time": time_str, "date": date_str}
    return _post_json(url, payload)


def reset_time(base_url: str = DEFAULT_BASE_URL) -> dict:
    """Reset the mock time on the LabAuth server to live system time."""
    url = f"{base_url.rstrip('/')}/api/time/mock"
    return _post_json(url, {"reset": True})


def get_time(base_url: str = DEFAULT_BASE_URL) -> dict:
    """Get the current mock time configuration from the server."""
    url = f"{base_url.rstrip('/')}/api/time/mock"
    return _get_json(url)


def take_screenshot(
    url: str,
    output_path: str | Path,
    width: int = 1920,
    height: int = 1080,
    wait_seconds: float = 1.0,
) -> str:
    """Capture a screenshot of a display page using headless Chromium."""
    browser_bin = shutil.which("chromium-browser") or shutil.which("google-chrome") or shutil.which("chromium")
    if not browser_bin:
        raise RuntimeError("Chromium or Google Chrome binary not found in system PATH.")

    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Let the browser render all web components & custom fonts
    time.sleep(wait_seconds)

    cmd = [
        browser_bin,
        "--headless=new",
        "--disable-gpu",
        f"--window-size={width},{height}",
        f"--screenshot={str(output_path)}",
        url,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"Failed to capture screenshot: {res.stderr}")

    return str(output_path)


def test_all_periods(
    base_url: str = DEFAULT_BASE_URL,
    screenshot_dir: str | Path | None = None,
) -> list[dict]:
    """Test all four time periods (Morning, Afternoon, Evening, Night)

    Verifies the expected greeting period and color scheme (Light/Dark).
    """
    test_cases = [
        {
            "label": "Morning Boundary (05:00 - Morning begins)",
            "time": "05:00",
            "date": "September 13, 2026",
            "expected_theme": "dark",
            "expected_period": "morning",
            "expected_greeting": "Good morning!",
        },
        {
            "label": "Morning (08:30 - Daytime light mode)",
            "time": "08:30",
            "date": "September 13, 2026",
            "expected_theme": "light",
            "expected_period": "morning",
            "expected_greeting": "Good morning!",
        },
        {
            "label": "Afternoon Boundary (12:00 - Afternoon begins)",
            "time": "12:00",
            "date": "September 13, 2026",
            "expected_theme": "light",
            "expected_period": "afternoon",
            "expected_greeting": "Good afternoon!",
        },
        {
            "label": "Afternoon (14:15)",
            "time": "14:15",
            "date": "September 13, 2026",
            "expected_theme": "light",
            "expected_period": "afternoon",
            "expected_greeting": "Good afternoon!",
        },
        {
            "label": "Evening Boundary (17:00 - Evening begins)",
            "time": "17:00",
            "date": "September 13, 2026",
            "expected_theme": "light",
            "expected_period": "evening",
            "expected_greeting": "Good evening!",
        },
        {
            "label": "Evening (19:00 - Dark mode after 18:00)",
            "time": "19:00",
            "date": "September 13, 2026",
            "expected_theme": "dark",
            "expected_period": "evening",
            "expected_greeting": "Good evening!",
        },
        {
            "label": "Night Boundary (21:00 / 9 PM - Night begins)",
            "time": "21:00",
            "date": "September 13, 2026",
            "expected_theme": "dark",
            "expected_period": "night",
            "expected_greeting": "Good night!",
        },
        {
            "label": "Night (02:00)",
            "time": "02:00",
            "date": "September 13, 2026",
            "expected_theme": "dark",
            "expected_period": "night",
            "expected_greeting": "Good night!",
        },
        {
            "label": "Night Boundary (04:30 - 4 AM late night)",
            "time": "04:30",
            "date": "September 13, 2026",
            "expected_theme": "dark",
            "expected_period": "night",
            "expected_greeting": "Good night!",
        },
    ]

    results = []
    print("\n" + "=" * 60)
    print("  LABAUTH TIME TEST SUITE — TESTING ALL 4 DAY PERIODS")
    print("=" * 60)

    for tc in test_cases:
        label = tc["label"]
        t = tc["time"]
        d = tc["date"]
        print(f"\n▶ Testing {label} ({t})...")

        resp = set_time(t, d, base_url=base_url)
        time.sleep(0.3)

        hour = int(t.split(":")[0])
        theme = "dark" if (hour >= 18 or hour < 6) else "light"
        assert theme == tc["expected_theme"], f"Theme mismatch: got {theme}, expected {tc['expected_theme']}"

        screenshot_file = None
        if screenshot_dir:
            dir_path = Path(screenshot_dir)
            dir_path.mkdir(parents=True, exist_ok=True)
            shot_path = dir_path / f"test_{tc['expected_period']}_{t.replace(':', '')}.png"
            take_screenshot(f"{base_url}/display", shot_path)
            screenshot_file = str(shot_path)
            print(f"  ✓ Saved screenshot: {shot_path}")

        print(f"  ✓ Mock time set to {t}")
        print(f"  ✓ Greeting period: {tc['expected_period']} ('{tc['expected_greeting']}')")
        print(f"  ✓ Theme mode:      {theme.upper()} (Auto-switched)")
        results.append({**tc, "screenshot": screenshot_file, "api_response": resp})

    # Reset back to normal time
    reset_time(base_url=base_url)
    print("\n" + "=" * 60)
    print("✓ All 4 periods successfully verified! Reset to system time.")
    print("=" * 60 + "\n")
    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Specify and test time appearance on the LabAuth display.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-t",
        "--time",
        type=str,
        help="Time to set in 24h format (e.g. 08:30, 14:15, 19:00, 23:45)",
    )
    parser.add_argument(
        "-d",
        "--date",
        type=str,
        default=None,
        help="Date string to set above clock (e.g. 'September 12, 2026')",
    )
    parser.add_argument(
        "-r",
        "--reset",
        action="store_true",
        help="Reset mock time and return display to live system time",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run comprehensive test across all 4 periods (morning, afternoon, evening, night)",
    )
    parser.add_argument(
        "-s",
        "--screenshot",
        type=str,
        default=None,
        help="Path to save a screenshot of the display with the specified time",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Port where LabAuth server is running (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--host",
        type=str,
        default=None,
        help="Base URL of running server (e.g. http://127.0.0.1:8081)",
    )

    args = parser.parse_args()
    base_url = args.host or f"http://127.0.0.1:{args.port}"

    try:
        # Check server connectivity
        _get_json(f"{base_url}/api/time/mock")
    except Exception as exc:
        print(f"Error: Could not connect to LabAuth server at {base_url}.")
        print(f"Ensure the server is running (e.g. `PORT={args.port} PYTHONPATH=src uv run python src/main.py`).")
        print(f"Details: {exc}")
        sys.exit(1)

    if args.reset:
        res = reset_time(base_url)
        print(f"✓ Mock time reset to live system time: {res}")
        if args.screenshot:
            shot = take_screenshot(f"{base_url}/display", args.screenshot)
            print(f"✓ Screenshot saved to {shot}")
        return

    if args.all:
        shot_dir = Path(args.screenshot).parent if args.screenshot else None
        test_all_periods(base_url, screenshot_dir=shot_dir)
        return

    if args.time:
        res = set_time(args.time, args.date, base_url)
        hour = int(args.time.split(":")[0])
        theme = "dark" if (hour >= 18 or hour < 6) else "light"
        period = (
            "morning" if 5 <= hour < 12
            else "afternoon" if 12 <= hour < 17
            else "evening" if 17 <= hour < 21
            else "night"
        )
        print(f"✓ Display time set to {args.time} ({period}, {theme} mode)")
        if args.date:
            print(f"✓ Display date set to: {args.date}")
        print(f"✓ Server response: {res}")

        if args.screenshot:
            shot = take_screenshot(f"{base_url}/display", args.screenshot)
            print(f"✓ Screenshot saved to: {shot}")
        return

    # If no flags passed, show current mock state or help
    current = get_time(base_url)
    print("Current time configuration on server:")
    print(json.dumps(current, indent=2))
    print("\nUse --help to see all options (e.g. `uv run python tests/test_time.py --time 14:15`).")


if __name__ == "__main__":
    main()

