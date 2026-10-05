# LabAuth Testing Suite

This directory contains test scripts to test and verify the **LabAuth** presence display in real time:
1. **`test_time.py`**: Test specifying arbitrary times and dates, verifying analogue clock hands, digital readout, multilingual greetings, and automatic Light/Dark mode transitions.
2. **`test_users.py`**: Add, remove, list, empty, and populate lab occupants, observing live UI reactivity, card scaling (1 to 12 occupants), and 2-row carousel transitions (13+ occupants).

---

## Quick Start

Make sure the LabAuth server is running (default port is `8080`):
```bash
PYTHONPATH=src uv run python src/main.py
```

All test commands communicate directly with the running server and update any active browser windows in real time over WebSockets.

---

## 1. Testing Time & Color Scheme (`test_time.py`)

### Command Line Usage

#### Specify a Time
```bash
# Set time to 14:15 (Afternoon, Light mode, clock hands at 14:15)
uv run python tests/test_time.py --time 14:15

# Set evening time with a custom date
uv run python tests/test_time.py --time 19:30 --date "September 12, 2026"

# Set late night time (Dark mode, "Good night!" greeting)
uv run python tests/test_time.py --time 23:45
```

#### Reset Back to Live System Time
```bash
uv run python tests/test_time.py --reset
```

#### Run Automated Suite Across All 4 Day Periods
Tests Morning, Afternoon, Evening, and Night sequentially:
```bash
uv run python tests/test_time.py --all
```

#### Capture a Screenshot
```bash
uv run python tests/test_time.py --time 08:30 --screenshot tests/morning_preview.png
```

### Python API Usage
```python
from tests.test_time import set_time, reset_time, get_time

# Set mock time
set_time("14:15", date_str="September 12, 2026")

# Inspect current mock time state
state = get_time()
print(state)  # {'mock_time': '14:15', 'mock_date': 'September 12, 2026'}

# Reset to live clock
reset_time()
```

### Expected Behavior Matrix
| Time Range | Period | Greeter Period | Color Scheme |
|---|---|---|---|
| `05:00` – `11:59` | Morning | `"Good morning!"` (en) / `"Bonjour !"` (fr) / ... | Light (Dark before `06:00`) |
| `12:00` – `16:59` | Afternoon | `"Good afternoon!"` / `"Bon après-midi !"` / ... | Light |
| `17:00` – `20:59` | Evening | `"Good evening!"` / `"Bonsoir !"` / ... | Dark (auto switches at `18:00`) |
| `21:00` – `04:59` | Night | `"Good night!"` / `"Bonne nuit !"` / ... | Dark |

---

## 2. Managing Lab Occupants (`test_users.py`)

### Command Line Usage

#### Add a User
```bash
# Basic check-in
uv run python tests/test_users.py add "Elena Rossi"

# Check-in with specific access permissions and portrait
uv run python tests/test_users.py add "Elena Rossi" \
  --photo "/static/portraits/default.svg" \
  --access "3D printers" "Laser cutter"
```

#### Remove a User
```bash
uv run python tests/test_users.py remove "Elena Rossi"
```

#### List Currently Checked-in Occupants
```bash
uv run python tests/test_users.py list
```

#### Empty the Lab

Empties the lab (checks everyone out). Nothing is invented and no demo users are created:

```bash
uv run python tests/test_users.py empty
```

#### Populate Exact Occupant Counts (Layout Testing)
Test the dynamic vertical card scaling and 13+ carousel thresholds:
```bash
# 1 row (up to 4 cards): Spacious ID cards
uv run python tests/test_users.py populate 4

# 2 rows (5 to 8 cards): Medium ID cards
uv run python tests/test_users.py populate 8

# 3 rows (9 to 12 cards): Compact ID cards
uv run python tests/test_users.py populate 12

# Carousel mode (13+ cards): 4x2 synchronized sliding views
uv run python tests/test_users.py populate 16
```

#### Run Automated Presence Simulation
Runs a live visual demo that steps through occupant arrivals and departures:
```bash
uv run python tests/test_users.py simulate --delay 1.5
```

#### Capture a Screenshot with User Commands
```bash
uv run python tests/test_users.py populate 8 --screenshot tests/8_occupants.png
```

### Python API Usage
```python
from tests.test_users import add_user, remove_user, list_users, populate_users, reset_users

# Add occupant
add_user("David Kim", access=["Lab interior", "Laser cutter"])

# List occupants
occupants = list_users()
print(f"Total in lab: {len(occupants)}")

# Remove occupant
remove_user("David Kim")

# Populate specific count to test layout scaling
populate_users(12)

# Reset back to default
reset_users()
```

---

## In-Browser Direct URL Parameters
You can also open the display page in any browser with mock parameters directly in the URL:
- `http://localhost:8081/display?time=14:15`
- `http://localhost:8081/display?time=21:30&date=September%2012,%202026`


## Enrolment

```bash
uv run python tests/test_enrolment.py
uv run python tests/test_database.py
```

The enrolment suite starts its own server and Chromium browser on free ports,
uses a disposable SQLite database, and checks authentication, database-sourced
unchecked areas, photo upload and cropping, camera permission denial, draft
editing and discard, reader skips, name-only saving, duplicate and invalid
permission rejection, demographic persistence and mobile overflow. It also checks
the vertical card layout, server-clock light/dark boundaries, NFC animation loading
and reduced-motion playback. It never
creates simulated reader credentials. It cleans up its browser process group,
server and test database. Screenshots go to `/tmp/labauth-enrolment-qa`; set
`LABAUTH_SCREENSHOT_DIR` to choose another directory. Uploaded test photos are
removed after validation. Physical webcam capture and reader integration are
not hardware-tested by this suite.
