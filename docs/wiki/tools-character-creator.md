# Character Creator

Builds reusable character **templates** (not live characters — see
[Spawning into the live world](#spawning-into-the-live-world) at the
bottom). Open **`character_creator.html`** alongside the frontend dev
server.

## Layout

Three panes: a **left sidebar** (template list + New/Delete/Save), a
**center panel** with 11 tabs, and a **right "Model Preview"** pane (a
live 3D render of the character with their equipped clothing).

## Sidebar

- **New** — creates a blank template with sensible defaults (age 25,
  sex male).
- **Delete** — removes the open template (takes effect once Saved).
- **Save** — writes everything back to the server. **Save always pushes
  the whole templates blob** — there's no per-template save.
- A relation-type dropdown (Parent/Sibling/Child/Spouse/Grandparent/
  etc.) plus **Generate Relative** — procedurally generates a new,
  linked relative template from the one currently open.
- The template list below — click a row to load it.

## The 11 tabs, in order

**1. Basic Properties** — First Name, Last Name, SSN, Age (0–110, shows a
derived age-group note), Sex, Height, a Weight/body-fat slider, a Bio
textarea, and per-locomotion-type Movement Speed fields (walk/jog/sprint/
crawl/sneak). **🎲 Randomize** randomizes age/sex/height/weight.

**2. Personality Traits** / **3. Physical Traits** — a searchable
**Available** list on the left, drag (or double-click) a chip into the
**Assigned** list on the right; drag back or click ✕ to remove. Chips show
color-coded modifier badges: grey = incompatible (0%), white = automatic
(100%), green = boost, red = penalty — reflecting how this trait
interacts with ones already assigned. A Randomize row lets you set a count
and Positive/Negative filters, then **🎲 Randomize**.

**4. Outfit / Equipment** — one dropdown per clothing slot (14 total,
grouped Head / Torso / Lower body / Hands & Accessories), filtered to
items compatible with the character's body model, plus **🎲 Randomize
Outfit**. A **Starting Inventory** picker (same drag/double-click widget)
covers non-clothing categories. Every spawned character automatically also
gets a Wallet ($100 cash), ID Card, and Bank Card — that's not editable
here. Note: clothing set here only affects this page's own preview, not
how the character actually renders in the live game.

**5. Animation Mapping** — per-character overrides of which animation
clip plays for which of ~47 animation states, independently for lower/
upper body. Saved separately into the animation bank data, not into the
character template itself — see [Mesh Bank & Anim Bank](tools-meshbank-animbank.md).

**6. Jobs / Education** — a searchable Current Job dropdown (or None/
Unemployed/Retired), Education level, Current School, **🎲 Randomize Job /
Education**, and a Work History list you can add/remove rows to (Title,
Industry, Years, Reason left).

**7. Criminal Record** — Status (Free/Awaiting Trial/Jailed), Jail Until
tick, and a Record list (Crime + Tick, add/remove). Mostly flavor —
affects partner-preference scoring; only Jailed status actually gates
movement.

**8. Hobbies** — same picker widget, sourced from `hobby_templates`.
Affects household budget, social events, and attraction/rivalry, not just
flavor.

**9. Household** — pick a **live** household from the running simulation
(not template data), or **+ Create Household** (name field). Assign an
available live building with **Assign Building**; once assigned, set a
street **Address** with **Save Address**. A read-only **Finances**
section explains the automatic Wallet/ID/Bank Card grant and shows
per-member wallet cash, credit score, government debt, credit cards, and
loans — but only once the household has real spawned members.

**10. LLM Config** — a stub; not implemented yet.

**11. Debug Terminal** — three JSON/text fields (Character Patch, World
Patch, System Prompt Override) and a **▶ Send** button that runs a real
context-build + LLM call against your patch, with no live world or save
required — shows the system prompt, user prompt, raw response, and parsed
action. Good for checking how a specific trait/job/mood combination
actually reads to the LLM before you commit to it.

## Spawning into the live world

**Character Creator itself has no Spawn button** — it only authors
templates. To actually bring a character into the running simulation:

1. Finish and **Save** your template here.
2. Go to the **World Editor** (`editor.html`, linked from the sidebar).
3. Click **👤 Spawn Character**, click a tile on the map to set the spawn
   location, then pick your saved template from the list that appears.

This calls `POST /api/editor/spawn_character`, which is also where the
Wallet/ID Card/Bank Card and credit score actually get generated for the
new live character (not at template-save time).

## Quick workflow

1. **New** (or pick an existing template) → fill in **Basic Properties**.
2. Assign **Personality Traits**, **Physical Traits**, **Hobbies**.
3. Set **Outfit / Equipment**, **Jobs / Education**, **Criminal Record**
   if desired.
4. On **Household**: pick/create a household, assign a building, set an
   address.
5. **Save**.
6. In the **World Editor**: **👤 Spawn Character** → click a tile → pick
   your template.
