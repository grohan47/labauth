# Logs QA — 7 October 2026

Implemented `/logs` using the existing NiceGUI/Lyne stack and the documented
Lyne native-table pattern. No subtitles or explanatory panels are present.
The production database was not used for test fixtures.

## Query behavior

- Current occupants appear first. Completed visits follow in descending checkout order.
- A visit pairs adjacent check-in and checkout events for the same user, ordered
  by timestamp and event ID. Repeated check-ins and orphan checkouts are marked
  incomplete; unknown timestamps and durations are never invented.
- Cache-only current occupants are labelled in visit details and excluded from
  historical time-window queries. They do not become presence events.
- `Present during` matches overlaps, including overnight visits and arrivals
  before the selected interval. A departure exactly at the start is excluded.
- From/Until define one continuous interval in the lab host's local timezone.
  Empty times mean start/end of day. Times without dates use today. An entered
  end minute includes its final second. Display timestamps use the same host
  timezone even when the browser has a different timezone.
- Name/ID, entry or exit method, visitor/member, active/inactive account, current
  access permission, entry or exit device, minimum duration and visit state can
  be combined. User/account/access/photo information reflects current records.
- Future dates are disabled and rejected by the API; future presence events are excluded.
- Filters update automatically: text input is debounced by 300 ms, dropdown changes are immediate. There is no Search button.
- Pagination uses 50 visits. Filters persist in the page URL. Desktop headers
  remain visible while the table scrolls; pagination remains visible below it.
- Results refresh in place every 30 seconds while visible and on visibility
  restoration. SQL and visit dialogs retain their displayed snapshot.
- CSV exports the applied filter results, including UTC timestamps and evidence
  source, up to 10000 visits; larger results require narrower filters.
- The table selector updates a compact schema legend with column types, primary keys and foreign-key destinations. Schemas are discovered from SQLite, including backend-added tables.
- User removal uses deactivation; bans retain user identity, credentials and presence history. There is no hard-delete user helper or user-delete frontend route.
- SQL is restricted to read-only queries across the database. Every database table and view is selectable, including credentials, settings and backup logs. Binary values have a compact preview. Writes, attachment,
  pragmas and extension loading are denied. Runtime, query length, cell length,
  column count, result size and returned row count are bounded.

## Validation

- Incident query/security/retention tests: 15 passed.
- Existing database suite: 17 passed.
- Existing display settings suite: 10 passed.
- Lyne asset validation: 6 passed; table and tooltip modules included in the
  existing offline bundle and CDN fallback list.
- Python compilation, JavaScript syntax and diff whitespace checks passed.
- Real Chromium tests passed against an isolated database: unauthorized APIs,
  login, live-first ordering, pagination, name input, actual Lyne select clicks,
  visit details, overlap query, filtered CSV, invalid ranges, SQL execution, all-table selection/schema updates and
  write rejection (including direct API bypass attempts), keyboard navigation, in-place visibility restoration and Back.
- Light/dark layouts passed at 1440, 1024, 768 and 375 pixels: no page horizontal
  overflow, portrait loading, visible controls, and visible desktop pagination.
  Narrow tables use their own scroll area. No JavaScript or resource-load errors.
- Screenshots visually reviewed; adjusted dialog spacing, circular portraits,
  date field sizing, narrow filter grouping and desktop table scrolling.

Run:

```
.venv/bin/python tests/test_logs.py
.venv/bin/python tests/test_logs_browser.py
```

Browser screenshots/results: `/tmp/labauth-logs-qa/`.
