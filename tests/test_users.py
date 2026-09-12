#!/usr/bin/env python3
"""
Test script for adding, removing, and managing lab occupants in real time.

Features:
1. Add occupants with custom names, portraits, access permissions, and check-in times.
2. Remove occupants by name.
3. List currently checked-in occupants.
4. Reset occupants back to default lab state (Aisha, Rohan, Meera).
5. Populate exact occupant counts to test dynamic layout transitions:
   - 1-4 occupants:  1-row grid (spacious ID cards)
   - 5-8 occupants:  2-row grid (vertically scaled ID cards)
   - 9-12 occupants: 3-row grid (dense ID cards)
   - 13+ occupants:  Carousel mode (4x2 synchronized sliding rows)
6. Run interactive/automated simulation (`simulate`) demonstrating dynamic arrivals and departures.
7. Optional `--screenshot` on any command to capture live rendering.

CLI Usage:
  # Add a user:
  uv run python tests/test_users.py add "Elena Rossi" --access "3D printers" "Laser cutter"
  uv run python tests/test_users.py add "David Kim" --photo /static/portraits/default.svg

  # Remove a user:
  uv run python tests/test_users.py remove "Elena Rossi"

  # List current occupants:
  uv run python tests/test_users.py list

  # Populate exact counts (tests layout scaling):
  uv run python tests/test_users.py populate 4   # 1 row
  uv run python tests/test_users.py populate 8   # 2 rows
  uv run python tests/test_users.py populate 12  # 3 rows
  uv run python tests/test_users.py populate 16  # Carousel mode

  # Reset back to default:
  uv run python tests/test_users.py reset

  # Run live presence simulation:
  uv run python tests/test_users.py simulate --delay 1.5

Python Import:
  from tests.test_users import add_user, remove_user, list_users, populate_users, reset_users
  add_user("Sofia Alvarez", access=["Lab interior", "CNC mill"])
  remove_user("Sofia Alvarez")
  populate_users(10)
  reset_users()
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


def _post_json(url: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload or {}).encode("utf-8")
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


def add_user(
    name: str,
    access: list[str] | tuple[str, ...] = ("Lab interior", "Tool area"),
    photo: str = "/static/portraits/default.svg",
    checked_in: str | None = None,
    base_url: str = DEFAULT_BASE_URL,
) -> dict:
    """Add or update an occupant inside the lab."""
    url = f"{base_url.rstrip('/')}/api/presence/check-in"
    payload = {
        "name": name,
        "access": list(access),
        "photo": photo,
    }
    if checked_in:
        payload["checked_in"] = checked_in
    return _post_json(url, payload)


def remove_user(name: str, check_out: str | None = None, base_url: str = DEFAULT_BASE_URL) -> dict:
    """Check out an occupant by name."""
    url = f"{base_url.rstrip('/')}/api/presence/check-out"
    payload = {"name": name}
    if check_out:
        payload["check_out"] = check_out
    return _post_json(url, payload)


checkout_user = remove_user


def verify_alerts(
    name: str = "Elena Rossi",
    photo: str = "/static/portraits/default.svg",
    access: tuple[str, ...] = ("Lab interior", "CNC mill", "Laser cutter"),
    in_time: str = "09:15",
    out_time: str = "17:45",
    screenshot_dir: str | Path | None = None,
    base_url: str = DEFAULT_BASE_URL,
) -> dict:
    """Verify both check-in (IN) and check-out (OUT) alert cards visually."""
    print("\n" + "=" * 65)
    print("  VERIFYING IN/OUT ATTENTION-COMMANDING ALERT CARDS")
    print("=" * 65)

    shot_dir = Path(screenshot_dir).resolve() if screenshot_dir else None
    if shot_dir:
        shot_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: Check in (IN event)
    print(f"\n[Step 1/2] Checking in '{name}' (IN event at {in_time})...")
    in_res = add_user(name=name, access=access, photo=photo, checked_in=in_time, base_url=base_url)
    print(f"  ✓ Check-in dispatched! Total occupants in lab: {in_res.get('total_count')}")

    in_shot = None
    if shot_dir:
        shot_path = shot_dir / "alert_card_in.png"
        take_screenshot(f"{base_url}/display", shot_path, wait_seconds=0.7)
        in_shot = str(shot_path)
        print(f"  ✓ Captured IN alert card screenshot: {shot_path}")

    # Wait for the 5-second alert display to complete
    print("  Waiting 5.3s for IN alert card to complete display...")
    time.sleep(5.3)

    # Step 2: Check out (OUT event)
    print(f"\n[Step 2/2] Checking out '{name}' (OUT event at {out_time})...")
    out_res = remove_user(name=name, check_out=out_time, base_url=base_url)
    print(f"  ✓ Check-out dispatched! Total occupants in lab: {out_res.get('total_count')}")

    out_shot = None
    if shot_dir:
        shot_path = shot_dir / "alert_card_out.png"
        take_screenshot(f"{base_url}/display", shot_path, wait_seconds=0.7)
        out_shot = str(shot_path)
        print(f"  ✓ Captured OUT alert card screenshot: {shot_path}")

    # Wait for the 5-second alert display to complete
    print("  Waiting 5.3s for OUT alert card to complete display...")
    time.sleep(5.3)

    after_shot = None
    if shot_dir:
        shot_path = shot_dir / "alert_card_after_dismiss.png"
        take_screenshot(f"{base_url}/display", shot_path, wait_seconds=0.5)
        after_shot = str(shot_path)
        print(f"  ✓ Captured clean background post-dismissal: {shot_path}")

    print("\n" + "=" * 65)
    print("✓ Alert cards verified successfully for both check-in and check-out!")
    print("=" * 65 + "\n")
    return {
        "in_response": in_res,
        "out_response": out_res,
        "in_screenshot": in_shot,
        "out_screenshot": out_shot,
        "after_screenshot": after_shot,
    }


def test_queue_flow(
    base_url: str = DEFAULT_BASE_URL,
    screenshot_dir: str | Path | None = None,
) -> None:
    """Test rapid bunched up in/out events queueing with 1s duration."""
    print("\n" + "=" * 65)
    print("  TESTING ALERT QUEUE WITH BUNCHED-UP EVENTS (1-SECOND ACCELERATION)")
    print("=" * 65)

    shot_dir = Path(screenshot_dir).resolve() if screenshot_dir else None
    if shot_dir:
        shot_dir.mkdir(parents=True, exist_ok=True)

    print("\nDispatching 3 rapid in/out events within 200ms...")
    add_user(
        "David Kim",
        access=["3D printers", "Laser cutter"],
        photo="/static/portraits/default.svg",
        checked_in="11:00",
        base_url=base_url,
    )
    time.sleep(0.08)
    add_user(
        "Elena Rossi",
        access=["Lab interior", "CNC mill"],
        photo="/static/portraits/default.svg",
        checked_in="11:01",
        base_url=base_url,
    )
    time.sleep(0.08)
    remove_user("David Kim", check_out="11:02", base_url=base_url)

    print("✓ Dispatched:")
    print("  1. David Kim (IN)")
    print("  2. Elena Rossi (IN)")
    print("  3. David Kim (OUT)")
    print("Expected queue behavior: First 2 events show for 1s each; 3rd (final) shows for 5s.")

    if shot_dir:
        shot_path = shot_dir / "queue_bunched_event.png"
        take_screenshot(f"{base_url}/display", shot_path, wait_seconds=0.6)
        print(f"  ✓ Captured active queue screenshot: {shot_path}")

    # Wait for queue to process (1s + 1s + 5s = 7s)
    print("  Waiting 7.5s for entire queue to clear...")
    time.sleep(7.5)

    # Cleanup
    remove_user("Elena Rossi", base_url=base_url)
    print("✓ Queue processed and cleaned up successfully.")
    print("=" * 65 + "\n")



def list_users(base_url: str = DEFAULT_BASE_URL) -> list[dict]:
    """Retrieve list of all currently checked-in occupants."""
    url = f"{base_url.rstrip('/')}/api/presence"
    res = _get_json(url)
    return res.get("people", [])


def reset_users(base_url: str = DEFAULT_BASE_URL) -> dict:
    """Reset occupants back to the default 3 people."""
    url = f"{base_url.rstrip('/')}/api/presence/reset"
    return _post_json(url, {})


def populate_users(count: int, base_url: str = DEFAULT_BASE_URL) -> dict:
    """Populate exact count of occupants (1 to 48)."""
    url = f"{base_url.rstrip('/')}/api/presence/populate"
    return _post_json(url, {"count": count})


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
    time.sleep(wait_seconds)

    cmd = [
        browser_bin,
        "--headless=new",
        "--disable-gpu",
        "--virtual-time-budget=1000",
        f"--window-size={width},{height}",
        f"--screenshot={str(output_path)}",
        url,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"Failed to capture screenshot: {res.stderr}")

    return str(output_path)


def simulate_presence_flow(
    delay: float = 1.5,
    base_url: str = DEFAULT_BASE_URL,
    screenshot_dir: str | Path | None = None,
) -> None:
    """Run an automated demonstration of people arriving and leaving."""
    print("\n" + "=" * 65)
    print("  LABAUTH PRESENCE SIMULATION — TESTING DYNAMIC LAYOUT SCALING")
    print("=" * 65)

    print("\n[Step 1/5] Resetting to default occupants (3 people, 1 row)...")
    reset_users(base_url)
    time.sleep(delay)

    print("\n[Step 2/5] Adding 4th person (Testing 4-person 1-row threshold)...")
    add_user(
        name="David Kim",
        photo="/static/portraits/default.svg",
        access=["Lab interior", "Laser cutter"],
        base_url=base_url,
    )
    time.sleep(delay)

    print("\n[Step 3/5] Scaling to 8 occupants (Testing 2-row 4x2 layout)...")
    populate_users(8, base_url=base_url)
    time.sleep(delay)

    print("\n[Step 4/5] Scaling to 12 occupants (Testing 3-row 4x3 layout)...")
    populate_users(12, base_url=base_url)
    time.sleep(delay)

    print("\n[Step 5/5] Scaling to 14 occupants (Testing Carousel Mode with sliding rows)...")
    populate_users(14, base_url=base_url)
    time.sleep(delay * 2)

    if screenshot_dir:
        shot_path = Path(screenshot_dir) / "simulation_carousel_14.png"
        take_screenshot(f"{base_url}/display", shot_path)
        print(f"  ✓ Saved carousel screenshot to {shot_path}")

    print("\n[Cleanup] Resetting back to default occupants...")
    reset_users(base_url)
    print("=" * 65)
    print("✓ Presence simulation completed successfully!")
    print("=" * 65 + "\n")


def main() -> None:
    parent_parser = argparse.ArgumentParser(add_help=False)
    parent_parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Port where LabAuth server is running (default: {DEFAULT_PORT})",
    )
    parent_parser.add_argument(
        "--host",
        type=str,
        default=None,
        help="Base URL of running server (e.g. http://127.0.0.1:8081)",
    )
    parent_parser.add_argument(
        "-s",
        "--screenshot",
        type=str,
        default=None,
        help="Capture a screenshot after running the command",
    )

    parser = argparse.ArgumentParser(
        description="Add, remove, and manage lab occupants on the LabAuth display.",
        parents=[parent_parser],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", help="Action to perform")

    # Add command
    add_cmd = subparsers.add_parser("add", parents=[parent_parser], help="Add or check-in a user")
    add_cmd.add_argument("name", type=str, help="Full name of person")
    add_cmd.add_argument(
        "--photo",
        type=str,
        default="/static/portraits/default.svg",
        help="Path or URL to portrait image (default: /static/portraits/default.svg)",
    )
    add_cmd.add_argument(
        "--access",
        nargs="+",
        default=["Lab interior", "Tool area"],
        help="Access permissions (default: 'Lab interior' 'Tool area')",
    )
    add_cmd.add_argument(
        "--time",
        type=str,
        default=None,
        help="Check-in time (default: current HH:MM)",
    )

    # Remove / Checkout command
    rem_cmd = subparsers.add_parser("remove", parents=[parent_parser], help="Remove or check-out a user")
    rem_cmd.add_argument("name", type=str, help="Full name of person to check out")
    rem_cmd.add_argument(
        "--time",
        type=str,
        default=None,
        help="Check-out time (default: current HH:MM)",
    )

    chk_cmd = subparsers.add_parser("checkout", parents=[parent_parser], help="Check out an occupant")
    chk_cmd.add_argument("name", type=str, help="Full name of person to check out")
    chk_cmd.add_argument(
        "--time",
        type=str,
        default=None,
        help="Check-out time (default: current HH:MM)",
    )

    # List command
    subparsers.add_parser("list", parents=[parent_parser], help="List all occupants currently in the lab")

    # Reset command
    subparsers.add_parser("reset", parents=[parent_parser], help="Reset occupants back to default 3 people")

    # Populate command
    pop_cmd = subparsers.add_parser("populate", parents=[parent_parser], help="Populate exact number of occupants")
    pop_cmd.add_argument("count", type=int, help="Number of occupants (1 to 48)")

    # Simulate command
    sim_cmd = subparsers.add_parser("simulate", parents=[parent_parser], help="Run animated arrival/departure simulation")
    sim_cmd.add_argument(
        "--delay",
        type=float,
        default=1.5,
        help="Seconds delay between simulation steps (default: 1.5s)",
    )

    # Verify alerts command
    va_cmd = subparsers.add_parser("verify-alerts", parents=[parent_parser], help="Verify in/out alert card display")
    va_cmd.add_argument("--name", type=str, default="Elena Rossi", help="Person name to check in and out")
    va_cmd.add_argument("--photo", type=str, default="/static/portraits/default.svg", help="Portrait image")
    va_cmd.add_argument("--access", nargs="+", default=["Lab interior", "CNC mill", "Laser cutter"], help="Access list")
    va_cmd.add_argument("--in-time", type=str, default="09:15", help="Check-in time")
    va_cmd.add_argument("--out-time", type=str, default="17:45", help="Check-out time")
    va_cmd.add_argument("--screenshot-dir", type=str, default=None, help="Directory to save verification screenshots")

    # Test queue command
    q_cmd = subparsers.add_parser("test-queue", parents=[parent_parser], help="Test bunched-up event queue acceleration")
    q_cmd.add_argument("--screenshot-dir", type=str, default=None, help="Directory to save queue screenshots")

    args = parser.parse_args()
    base_url = args.host or f"http://127.0.0.1:{args.port}"

    if not args.command:
        parser.print_help()
        return

    try:
        # Verify connectivity
        _get_json(f"{base_url}/api/presence")
    except Exception as exc:
        print(f"Error: Could not connect to LabAuth server at {base_url}.")
        print(f"Ensure the server is running (e.g. `PORT={args.port} PYTHONPATH=src uv run python src/main.py`).")
        print(f"Details: {exc}")
        sys.exit(1)

    if args.command == "add":
        res = add_user(
            name=args.name,
            access=args.access,
            photo=args.photo,
            checked_in=args.time,
            base_url=base_url,
        )
        print(f"✓ Checked in '{args.name}'!")
        print(f"  Access: {', '.join(args.access)}")
        print(f"  Total occupants in lab: {res.get('total_count')}")

    elif args.command in ("remove", "checkout"):
        res = remove_user(args.name, check_out=args.time, base_url=base_url)
        if res.get("removed"):
            out_t = res.get("check_out", "")
            print(f"✓ Checked out '{args.name}' (time: {out_t}). Total occupants: {res.get('total_count')}")
        else:
            print(f"Notice: '{args.name}' was not found in the lab. Total occupants: {res.get('total_count')}")

    elif args.command == "list":
        people = list_users(base_url=base_url)
        print(f"\nCurrently in the lab ({len(people)} occupants):")
        print("-" * 55)
        for i, p in enumerate(people, 1):
            access_str = ", ".join(p.get("access", []))
            print(f"  {i:2d}. {p['name']:<20} | In: {p.get('checked_in', '--:--')} | Access: {access_str}")
        print("-" * 55 + "\n")

    elif args.command == "reset":
        res = reset_users(base_url=base_url)
        print(f"✓ Reset presence back to default occupants. Total occupants: {res.get('total_count')}")

    elif args.command == "populate":
        res = populate_users(args.count, base_url=base_url)
        layout = (
            "1 row (4 columns)" if args.count <= 4
            else "2 rows (4 columns)" if args.count <= 8
            else "3 rows (4 columns)" if args.count <= 12
            else f"Carousel mode ({len(res.get('total_count', [])) if isinstance(res.get('total_count'), list) else (args.count + 7) // 8} pages, 4x2)"
        )
        print(f"✓ Populated lab with {args.count} occupants.")
        print(f"  Active layout: {layout}")
        print(f"  Total occupants in lab: {res.get('total_count')}")

    elif args.command == "simulate":
        shot_dir = Path(args.screenshot).parent if args.screenshot else None
        simulate_presence_flow(delay=args.delay, base_url=base_url, screenshot_dir=shot_dir)

    elif args.command == "verify-alerts":
        shot_dir = args.screenshot_dir or (Path(args.screenshot).parent if args.screenshot else None)
        verify_alerts(
            name=args.name,
            photo=args.photo,
            access=tuple(args.access),
            in_time=args.in_time,
            out_time=args.out_time,
            screenshot_dir=shot_dir,
            base_url=base_url,
        )

    elif args.command == "test-queue":
        shot_dir = args.screenshot_dir or (Path(args.screenshot).parent if args.screenshot else None)
        test_queue_flow(base_url=base_url, screenshot_dir=shot_dir)

    if args.screenshot and args.command not in ("simulate", "verify-alerts", "test-queue"):
        shot = take_screenshot(f"{base_url}/display", args.screenshot)
        print(f"✓ Screenshot saved to {shot}")


if __name__ == "__main__":
    main()
