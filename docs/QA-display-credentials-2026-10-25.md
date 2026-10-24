# Display and credentials QA — 25 October 2026

Tested the dirty working tree based on `633afcc2110c84793ad428ec8d5ecf15a695f490`. Existing unrelated changes were retained. The app uses NiceGUI and the existing Lyne components.

## Browser checks

T3 collaborative preview, real app on port 8091, isolated SQLite database and POSIX PTY reader emulator. No HTTP responses were mocked.

- 16 IN/OUT cases: `/display` and `/admin-display`, each at 375×812, 768×1024, 1280×800 and 1920×1080, with a long name.
- Date and digital time horizontal centers stayed within 0.008 px of the analogue clock center. The clock stack's right edge matched its reserved panel's right edge.
- Every IN/OUT card stayed inside the viewport, with no internal overflow. The portrait began 12 px below the IN/OUT bar. Both real area labels appeared.
- Date size changed to 24 px through the settings input and Apply button, reported Saved, survived navigation, and rendered at 24 px. Public and admin settings remain independent; default is 18 px.
- Credentials: unassigned sensor slots appeared; assigning template 42 selected a real person and persisted; deleting template 43 while unassigned and template 42 after assignment removed their rows after serial deletion confirmation.
- Forced `ERR FP NOT_READY`: deletion dialog stayed open, error appeared, retry stayed enabled, and the database credential remained. Retrying successfully removed it.
- Forced partial inventory followed by `ERR FP 0x01 FAILED`: error appeared, previous complete inventory remained, and partial slot 999 did not leak into the table.
- Fingerprint search for slot 43 returned exactly one unassigned row. Final credentials navigation had no resource responses >=400.

Screenshots:

- [Live display, centered date/time and right-aligned clock group](/home/rgcodes/.t3/userdata/browser-artifacts/browser-screenshot-127-0-0-1-mvmy1maq-24ae282b.png)
- [Public IN card, 1280 px](/home/rgcodes/.t3/userdata/browser-artifacts/browser-screenshot-127-0-0-1-mvmxy1yk-a679791c.png)
- [Admin OUT card, 1280 px](/home/rgcodes/.t3/userdata/browser-artifacts/browser-screenshot-127-0-0-1-mvmxy3n4-605d6ff3.png)
- [Public OUT card, 375 px](/home/rgcodes/.t3/userdata/browser-artifacts/browser-screenshot-127-0-0-1-mvmxxydk-07558fa7.png)
- [Unassigned credentials](/home/rgcodes/.t3/userdata/browser-artifacts/browser-screenshot-127-0-0-1-mvmy25id-e1276620.png)
- [Saved date-size setting](/home/rgcodes/.t3/userdata/browser-artifacts/browser-screenshot-127-0-0-1-mvmxx6la-5fbd89e0.png)

## Physical reader check

The local app on port 8080 was restarted with its existing environment after confirming no pending enrollment. SQLite backup: `/tmp/labauth-before-area-fix.db`. Startup removed the three fictitious areas and their permissions, retaining their prior rows and grants in the audit log.

The first physical inventory request returned `ERR FP NOT_READY`, exposing a maintenance-readiness race. The service now waits for a fresh raw READY state after mode/enable changes. After this fix, the actual connected sensor completed `FP LIST` through `EVT FP LIST_END`: **2 occupied slots, including 1 unassigned template**, checked at `2026-10-24T22:01:05.447Z`. No physical template was assigned or deleted during QA. Physical deletion remains unverified; assignment/deletion above used the PTY emulator.

Initial preview navigation to stale port 8089 produced `chrome-error://chromewebdata/`; the existing app was on port 8080. Navigation then worked normally; no browser fallback was required.

## Focused automated checks

- `python tests/test_pico_service.py`: 19 passed, including fresh READY, complete inventory, partial-list failure, ghost filtering, assignment verification and confirmed deletion.
- `python tests/test_database.py`: 18 passed, including removal/audit of fictitious areas and rejecting their recreation.
- `python tests/test_display_settings.py`: 11 passed, including date-size validation and screen isolation.
- `pytest tests/test_temp_and_credentials.py tests/test_people.py -q`: 13 passed.
- `python tests/test_reader_api.py`: authorization, origin, ownership and credential-forgery checks passed.
- JavaScript syntax checks for credentials/display/settings, Python compilation, and `git diff --check` passed.

Lyne references consulted: [Card](https://digital.sbb.ch/en/design-system/lyne/components/card/) and [Dialog](https://digital.sbb.ch/en/design-system/lyne/components/dialog/).
