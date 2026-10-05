# Display settings QA — 5 October 2026

Validated in the Codex inbuilt browser against an isolated SQLite database on
port 8085. The fixture contains 20 occupants, including a long name and four
authorised areas with a long equipment label. The existing app on port 8080 was
also restarted and checked with its existing seven occupants.

## Final behavior

- Screen and card visibility are independent for public and admin displays.
- There are no resize handles or controls for choosing card rows. Old saved
  ratios, row counts and row weights are ignored.
- Cards occupy the cells released by the greeter and time components. Turning
  all header components off releases the whole card area.
- The LabAuth admin bar is permanent, including when stale settings request
  that it be hidden. There is no setting for deleting cards.
- Pictures, names, authorised areas and check-in times can each be hidden.
- Capacity and component sizes adapt to the viewport and enabled information.
  Wrapped text remains complete; excess occupants appear on rotating pages.

## Browser evidence

The final automatic admin layout, with its permanent bar, all card fields
enabled and optional header components disabled, produced:

| Viewport | Cards per page | Occupants retained | Clipped cards | Cards below viewport |
| --- | ---: | ---: | ---: | ---: |
| 800 × 600 | 3 | 20 | 0 | 0 |
| 1280 × 720 | 6 | 20 | 0 | 0 |
| 1920 × 1080 | 12 | 20 | 0 | 0 |

Checks used actual rendered card scroll dimensions and active-page bounds,
alongside visual inspection of wrapped names and access labels. Removing photo
and area content increased capacity on the smaller viewport; disabling names
and check-in times hid both fields while preserving all 20 card nodes.

Normal navigation and ordinary reload loaded the controls and components with
the rebuilt local Lyne bundle. The CDN fallback was also checked during repair.
Settings applied to an already-open display without reloading it. Target
switching preserved separate configurations, Reset and Apply worked, and saved
values survived normal reload. Pagination continued with the greeter disabled.
The settings page scrolled to its footer on laptop-sized viewports. The final
settings screen had zero resize handles and zero row selectors, with no browser
warnings or errors in that run.

Only landscape laptop and TV layouts are acceptance targets for this change.

## Visual comparison with main

A separate server runs the unchanged main checkout on port 8081, using a copy
of the same seven-occupant database. Both versions were compared at 1280 × 720
in the inbuilt browser. The first settings implementation had reduced the clock
from 144px to about 59px and enlarged portraits from 100px to 160px. It also put
the presence heading above the greeter and failed to anchor details within the
Lyne card's internal slot.

The corrected default view restores main's 144px clock, 40px digital time,
100px portraits, 24px card names and 57.6px bold greeting at that viewport. The
presence heading follows the greeting/time area, and the card footer holds
check-in and authorisation information. Rounded area labels use 8px corners,
with two aligned columns when multiple areas are present. Card and grid spacing
follow consistent padding and gaps. Main's branding remains in place.

The corrected default retained all seven occupants across pages and had no
card overflow. The 20-person fixture was also checked with all header components
on, all off, greeter only, and time only; long text remained complete. Auto layout
uses preferred baseline sizes and reduces density or adjusts sizes only when
needed to fit enabled information. New occupant content resets previous layout
limits so a departed long label does not leave the screen unnecessarily shrunk.

## Clock minimum height follow-up

The analogue clock now uses the visible greeting's measured height as its
minimum size, including wrapped lines and the active language's font metrics.
The header reserves that minimum before fitting cards. A greeting resize
observer recalculates the layout on font, language or viewport changes.

Inbuilt-browser measurements with every field enabled and the 20-person
long-content fixture:

| Effective viewport | Greeting height | Clock height | Clipped cards |
| --- | ---: | ---: | ---: |
| 800 × 600, wrapped afternoon greeting | 109.18px | 110.00px | 0 |
| 1280 × 720 | 60.48px | 63.99px | 0 |
| 1920 × 600 | 79.79px | 80.00px | 0 |
| 1920 × 1080 | 79.79px | 143.99px | 0 |

The greeting's automatic language cycle changed from two lines to one line
without a reload; the clock continued to satisfy the height floor. The public
display was also checked at 800 × 600. All 20 card nodes remained present and
there were no browser warnings or errors. The existing seven-person display
at 1422 × 800 showed a 67.99px clock above its 67.20px greeting height.

These are measured effective CSS viewport sizes. The inbuilt browser did not
apply keyboard zoom shortcuts, so native zoom percentages were not independently
verified. Temporary viewport overrides were reset afterwards.

## Automated checks

- Display settings suite: 10/10 passed, using a temporary database.
- Database suite: 15/15 passed, using a temporary database.
- Python source compilation, JavaScript syntax and diff whitespace checks passed.
- Local Lyne asset build passed; checkbox and radio components are included.

No test occupants or test layout settings were written to the existing app's
database. Changes remain in the existing `display-settings` worktree.

## Content density follow-up — 6 October 2026

Card minimum height now accounts for padding and border, each enabled field,
and only the gaps between visible fields. Empty upper/lower sections are hidden
so their spacing is reclaimed too. Automatic rows are limited by the available
height and the number of occupants, rather than an arbitrary three-row ceiling.
Rendered content overflow is checked inside the padding as well as at the card
boundary; long text can reduce density when it needs additional room.

At 1280 × 720, the 20-person fixture with optional header components disabled
produced the following capacities. The final minimum budgets include the 2px
card border:

| Visible card information | Minimum budget | Cards per page |
| --- | ---: | ---: |
| All four fields | 210px | 6 |
| All except photo | 138px | 8 |
| All except name | 178px | 8 |
| All except check-in time | 182px | 8 |
| All except authorised areas | 154px | 12 |
| Name and check-in time | 82px | 20 |
| Name only | 50px | 20 |
| Check-in time only | 46px | 20 |
| Photo only | 90px | 20 |
| Authorised areas only | 74px | 12 |
| No card fields | 26px | 20 |

The settings checkboxes and Apply updated the already-open display. All 20
occupants stayed present. Compact cards were checked on public and admin
screens at 800 × 600 and on the admin screen at 1920 × 1080. Full-information
cards were also checked with all header components enabled at laptop and TV
sizes; the clock's greeting-height floor still held. Final rendered checks
found no card/content overflow, overlapping upper/lower sections, or cards
outside the viewport. A width rule also prevents the permanent admin bar's
NiceGUI wrapper from collapsing on ordinary reload.

The display settings suite remained 10/10, JavaScript syntax and diff whitespace
checks passed, and main stayed clean. Test settings remained in the isolated
database; the real app's saved display settings were preserved.
