# The Live Viewer

The main window onto the running simulation — a real-time 3D view of the
whole town, backed by a WebSocket feed from the backend.

**Launch:** with the backend running (port 8000) and the frontend dev
server running (`npm run dev --prefix frontend -- --port 5174`, or the
`.claude/launch.json` `viewer-dev` config), open **http://localhost:5174/**.

## Camera

Standard orbit controls on an isometric-angled orthographic camera:

- **Left-drag** — orbit
- **Right-drag** (or two-finger drag) — pan
- **Scroll wheel** — zoom

## Selecting things

Click any character, prop, or tile in the 3D scene. Clicking a character
opens the **Inspector** panel in the top-right; clicking empty ground or a
non-interactive prop clears the selection.

## The Inspector panel

Two tabs:

**Status** — name/ID, alive/dead, posture, current activity or animation
state, mood, off-grid/travel status, body needs as percentages (energy,
hunger, thirst, hygiene, bladder, fatigue, stress), sickness/emergency
flags, the character's **cognition type** (Logical / Balanced / Self-Aware)
plus their traits and beliefs (each shown with a description flavored to
match their cognition type), finances (wallet cash, credit score, bank/
credit cards, tax debt), household ID, and a collapsible dump of their
**last LLM request/response** (system prompt, request, response).

**Body** — an SVG body silhouette (head/neck/arms/chest/abdomen/pelvis/
legs) colored by injury severity per part, an untreated-hazard count, a
per-part list of hazards and functional status (normal/impaired/
unusable), and active diseases with their current symptom.

A row of small effect icons above the tabs always shows active
diseases/hazards at a glance.

## Event timeline

Click the **🕒** button to toggle a horizontal timeline bar. It polls
`GET /api/events` and plots real events (choices made, off-grid trip
summaries, chance social encounters) as dots positioned by actual elapsed
ticks — nearby events cluster into one bigger dot. Hover a dot for a
tooltip; click it to open a modal with full details for every event in
that cluster.

## Outliner sidebar

Click the **☰** button (top-left) for a collapsible, Blender-style tree of
every household and its members, with a search box. Click a character row
to select them — this works even if they're currently off-grid, snapping
the camera to their last-known position.

## Debug Overlay Settings

Click the **⚙** button (top-right) to open the settings modal:

- **Show thought bubbles** — blue floating bubbles above characters'
  heads showing internal (non-spoken) state. Real spoken dialogue always
  shows separately in a **white** bubble — white is what a character
  actually says out loud, blue is everything else (thought, reflection).
  On by default; per-source toggles (Thought / Reflection / Current
  intention) let you narrow what shows.
- **Show badges** — small icon badges above characters: 👁 (Suspicion,
  when actively suspicious of someone) and 🎯 (Intention, current goal).
- **Perception overlays** (selected character only) — Vision range,
  Hearing range, Line of sight: colored rings/lines showing what the
  currently-selected character can perceive.

All settings persist across reloads (saved to `localStorage`).

## Mailbox / household admin

Double-click a mailbox prop to open a household admin modal — create a
household if the mailbox isn't linked yet, or (if it is) rename it, add/
remove members, add a building, manage subscriptions.

---

# Admin page

A small standalone page at **http://localhost:8000/admin.html**, served
directly by the backend (no Vite server needed). Two cards:

**Simulated Date & Time** — a live clock/date, and a **Time Scale** row of
ten buttons (`1x` through `10x`). Clicking one calls `POST /admin/
time_scale` and speeds up/slows down the simulation immediately.

**Danger Zone** — a single **"Reset Characters & Households"** button.
Confirms first, then calls `POST /admin/reset_characters`, which wipes
every character and household but leaves the hand-placed map, buildings,
roads, and props untouched. You'll need to create/spawn at least one new
character afterward (via [Character Creator](tools-character-creator.md))
to have anyone to watch.

---

# Dev Tools page (`/debug`)

At **http://localhost:8000/debug** (no `.html`) — a console for testing
the AI decision pipeline against a synthetic character/world, without
touching the live simulation at all.

A shared left sidebar builds a fake character + world: presets (Default,
Stressed Parent, Workaholic, Night Owl, In Conflict), trait chips, emotion/
energy/stress/wealth sliders, body-need sliders, world/location fields,
fake nearby props and characters and relationships, household toggle, and
a free-form "Extra JSON" field merged into the payload.

Three tabs:

- **Context / LLM** — builds and shows the full context the LLM would see
  for this fake character, with an "Auto-send to LLM" option that also
  runs the real LLM call and shows the parsed action.
- **Schedule** — generates and renders a weekly Mon–Sun schedule grid.
- **Activity Phases** — inspect a given intention type's interaction
  phases (walking/using/finishing) and their animations, plus a full
  reference table of every known interaction's phase animations.

Useful for iterating on prompts or debugging why a character's decision
looks wrong, without spinning up real characters or waiting for the sim
to reach the situation naturally.
