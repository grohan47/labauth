# LabAuth — SBB Lyne Design Direction

## Principles

* Use actual `@sbb-esta/lyne-elements` components and `@sbb-esta/lyne-design-tokens`.
* Use Lyne as the sole visual and UX authority.
* Consult all available Lyne documentation, including Storybook examples, component documentation, design principles, UX guidance and implementation guidance before making design decisions.
* Keep any Python integration layer thin; it should expose Lyne components, not replace them.
* Use Lyne tokens for layout, spacing, typography and color.
* Prefer whitespace, hierarchy, lists and tables over decorative containers.
* Avoid gradients, unnecessary shadows, decorative icons, excessive badges and generic dashboard patterns.
* Keep labels concise and actions clear.
* Use one primary action per task.
* Use swiss design principles: Grid, hierarchy, whitespace, restraint, clarity, implied function.
* Remove redundant explanatory, marketing, mission-statement and welcome copy.
* Progressively disclose secondary information.
* Preserve accessibility: labels, contrast, target sizes and non-color state indicators.

## Implied function

Prefer **implied function over explanatory text**.

The structure, hierarchy, component choice and label should normally make an interface self-explanatory.

Do not add text that merely explains:

* what a clearly labelled button does
* what a page heading means
* what an obvious form field is for
* what a table contains
* what a status value represents
* the broad purpose of LabAuth
* why a routine administrative feature is useful

Examples:

Use:

`Enroll user`

Not:

`Enroll user`
`Add a new member by capturing their photograph, fingerprint and access permissions.`

Use:

`Backups`

`Last backup 01:30`

Not:

`Configure database backups to keep your laboratory records safe and recoverable.`

If removing a piece of text does not make the next action meaningfully ambiguous, remove it.

Whitespace is preferable to filler copy.

---

## Reference screens

One or two supplied reference screens are the **visual anchors for LabAuth**.

They establish the intended:

* information density
* hierarchy
* whitespace
* visual rhythm
* alignment
* component scale
* treatment of typography
* amount of visible information
* restraint


## Design autonomy

The coding agent is expected to make design decisions.

Do not require a supplied design for every page.

For screens without a reference:

1. Identify the user's primary task.
2. Determine the minimum information required to complete it.
3. Find the appropriate Lyne components and documented patterns.
4. Establish one clear hierarchy and primary action.
5. Implement the simplest valid composition.
6. Review it against the supplied reference screens.
7. Remove unnecessary elements.
8. Iterate.

When multiple solutions are valid, prefer the one with:

* fewer visible elements
* less explanatory text
* stronger hierarchy
* more whitespace
* fewer containers
* fewer simultaneous actions
* greater reliance on established Lyne patterns

Do not add UI merely because a screen appears sparse.

---

## Public display

Show only:

* time and date
* current occupancy
* people inside
* authorised equipment/access
* brief authentication feedback

Keep the idle state calm.

Do not show:

* navigation
* administration
* history
* unrelated statistics
* instructional prose
* explanatory subtitles

Information already implied by placement should not be repeated in text.

For example, people shown under the current occupancy area do not require a `Currently checked in` label on every card.

---

## Admin interface

Expose current operational state and access to:

* Enroll user
* Users
* History
* Settings

Relevant system health may include:

* current occupancy
* NFC status
* fingerprint status
* backup status

Use compact structured layouts rather than collections of dashboard tiles.

Do not place each status value in an individual card unless Lyne guidance and the information structure genuinely require it.

---

## Enrollment

Use sequential steps:

1. Identity
2. Photograph
3. Access permissions
4. Fingerprint
5. Optional NFC
6. Review

Show only controls required for the current step.

Prefer:

`Photograph`

[camera]

`Capture`

over explanatory instructions describing what photograph capture does.

Provide instructions only when the physical interaction itself requires them, such as:

`Place finger on sensor`

---

## Forms and settings

Use actual Lyne form components.

Keep labels short.

Add helper text only for:

* non-obvious input constraints
* information required before making a consequential choice
* unusual hardware interaction
* errors requiring corrective action

Do not use helper text to restate field labels.

---

## Users and history

Use tables or lists where appropriate.

Keep scan-level information visible.

Place detailed information behind dedicated views.

Place advanced functionality such as raw SQL behind an advanced interface rather than exposing it at the main level.

---

## Copy discipline

Treat every additional sentence as a cost.

Prefer:

* values over sentences
* state labels over descriptions
* concise verbs over instructional copy
* layout over narration

Avoid copy such as:

* Welcome to LabAuth
* Manage your robotics lab efficiently
* Everything you need in one place
* Keep your lab secure
* Easily manage users
* Configure your settings below
* Use this page to...
* This section allows you to...

Never introduce text merely to make a page feel complete.

---

## Iteration

After implementing a screen, inspect it as a complete composition rather than considering the task complete once all requested functionality exists.

Perform at least one reduction pass.

Ask:

* What is the primary task?
* Is it immediately obvious?
* What can be removed?
* Is anything being explained that is already implied?
* Are secondary functions competing with the primary task?
* Is whitespace doing enough of the grouping?
* Have unnecessary cards or containers appeared?
* Does this feel consistent with the supplied reference screens?
* Does every visual primitive follow Lyne?

If something can disappear without impairing task completion or comprehension, remove it.

---

## Review

Before completion:

* Consult all relevant Lyne documentation and Storybook examples.
* Confirm every available primitive uses actual Lyne components.
* Confirm Lyne tokens replace arbitrary CSS values.
* Compare the composition against the supplied reference screens.
* Remove anything that does not support the current task.
* Remove redundant text and decorative elements.
* Check hierarchy, accessibility and primary-action clarity.
* Leave unused space empty rather than filling it.


The intended workflow is:

**User provides a small number of strong reference screens → agent understands the design language → agent independently designs and iterates the rest using Lyne.**
