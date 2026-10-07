# Search QA — 7 October 2026

`/search` uses the existing NiceGUI/Lyne stack and requires an admin session.
Search matches names, Plaksha IDs, email addresses and phone numbers, with a
250 ms typing debounce. Blank search lists every registered user, including
visitors, inactive accounts and banned users. Results load in pages of 30.

Native Lyne cards show a circular portrait, name, Plaksha ID and LabAuth ID
(`users.id`). Desktop grids show six columns from 1200 px and seven from
1600 px, with five rows for the initial 30 results. Narrow screens adapt
to fewer columns. Clicking or
keyboard activation opens a scrollable Lyne dialog with identity/contact
fields, account state, current presence, registration timestamps, access
grants, credential registrations and ban history. Raw biometric templates
are not returned. All queries use a read-only connection; there are no edit
or delete controls or user-delete API routes.

## Validation

- User search/query tests: 6 passed, including literal wildcard handling,
  SQL-like input, retained accounts, pagination and credential metadata.
- Logs regression tests: 15 passed. Database regression tests: 17 passed.
- Python compilation, JavaScript syntax and diff whitespace checks passed.
- Real Chromium QA with an isolated 55-user database passed: authentication,
  initial results, pagination, live ID/contact search, retained banned account,
  complete profile details, empty results, escaped HTML, card clicks,
  keyboard activation, missing-user response, rejected deletion and Back.
- Light/dark layouts and dialogs passed at 1920, 1440, 768 and 375 pixels, with
  loaded portraits, no horizontal overflow, and a visible Close action.
  Screenshots were visually reviewed. Six-/seven-column desktop grids,
  five initial rows and visible LabAuth IDs were also checked.
  No JavaScript/resource errors occurred.
- Production data was not used for test fixtures.

Run:

```
.venv/bin/python tests/test_user_search.py
.venv/bin/python tests/test_user_search_browser.py
```

Browser screenshots/results: `/tmp/labauth-search-qa/`.
