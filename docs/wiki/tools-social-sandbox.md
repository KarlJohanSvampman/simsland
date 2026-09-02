# Social Sandbox

An isolated test bed for character conversations and social state —
**fully separate from the live simulation**, so you can experiment freely.
Open **`social_debug.html`** on the backend
(`http://localhost:8000/social_debug.html` if the backend's the only
thing running it — it fetches from `/api/editor/definitions` and `/debug/
sandbox/...` directly).

Per the tool's own backend docstring, it stages real `character_templates`
into a synthetic in-memory world for testing — sandboxes live only in an
in-memory list, capped at 20, and every edit you make (health, emotion,
equip, off-grid, running a turn) touches only that sandbox's copies. It
never reads or writes real game state.

## Layout

- **Left column** — a 3D sandbox view (characters as simple colored
  capsules with name/speech labels), and a **＋ Stage Character** drawer
  for spawning characters into the sandbox.
- **Right column** — the selected character's name, a small camera
  perspective bar (Front/Back/Left/Right/Top), a solo preview render, and
  a tab bar: **Outfit, Appearance, State, Runtime, Template, Log,
  Prompts, Offgrid, Family**.

## Staging characters

Pick a template from the dropdown in the drawer, click **＋ Stage**. Note
this re-stages *everyone* currently in the sandbox along with the new
character — there's no incremental "just add one more" call under the
hood, though the effect on screen is the same. You can also add **absent
relationships** (a name + relation label tied to a staged character, for
simulating an off-screen person like "mother" without spawning them).
Click a capsule in the 3D view to select/inspect it.

## Running conversations

This tool does not watch the live simulation — it drives its own sandbox
one turn at a time, with real LLM calls:

- **Turn dropdown** (top bar) — pick whose turn is next.
- **▶ Next Turn** — runs one real decision for that character; they may
  think, speak, or act. If the result is part of an ongoing conversation,
  the turn dropdown automatically advances to the correct next speaker.
  Needs at least 2 staged characters.
- **🔁 Auto: Off/On** — auto-advances turns on a timer (set the interval
  with the Auto interval slider, 2–60s).
- **■ Stop Auto** — hard-stops the auto loop.
- **⚡ Escalate** — instantly sets the *selected* character to furious /
  emotional_temperature 90, a shortcut for forcing a conflict scenario.

## The State tab

Directly editable, applies immediately to the sandbox character:

- **Emotion** dropdown and **Emotional Temperature** slider (0–100).
- **Mood** — read-only display (it's data-driven, not settable directly).
- **Health** meters — hunger, energy, hydration, hygiene, bladder,
  fatigue, stress, each a live editable number, plus a sick checkbox and
  any active conditions.

This is the tool for forcing a character into a specific state (starving,
furious, exhausted) and then running turns to see how it actually plays
out in conversation.

## Other tabs

- **Appearance** — Name/Sex/Age (editable), plus read-only Traits,
  Physical Traits, Hobbies, and physical-appearance fields (height,
  build, hair, eyes, clothing style — often unpopulated, since character
  generation doesn't fill these in yet).
- **Outfit** — worn-item chips per slot; double-click a catalog item to
  equip it, or click a worn item for an Equip/Remove overlay.
- **Runtime** — the full raw character JSON, read-only — this is where to
  look for anything not surfaced elsewhere, including the real
  relationship fields (`familiarity`, `trust`, `friendship`, `respect`,
  `attraction`, `romantic_interest`, `resentment`, etc.) under
  `relationships`. There's no dedicated relationship-inspector UI; this
  raw dump is it.
- **Template** — the raw `character_templates` entry this character was
  staged from.
- **Log** — a filterable feed of everything that's happened (💬 Speech /
  💭 Thought / ⚡ Event / 🔧 System toggles), with a Clear button.
- **Prompts** — every real LLM call made for this character, each
  expandable to system/user prompt + response, plus a **Compose & Send**
  panel to hand-edit and resend a prompt directly — useful for
  prompt-engineering without running a full turn.
- **Offgrid** — send the character off-grid for a category (shopping,
  gym, work, hospital, jail, a named event, etc.) and a tick duration,
  then see the generated trip narration and their post-return state.
- **Family** — generate/inspect a family tree (depth 1 or 2) for the
  selected character, with role tags, ages, and pairwise relation labels.

## Thought bubble toggle

The **💭 Thoughts** checkbox in the top bar (default on) controls whether
each turn's internal thought shows as a floating bubble above the
character in the 3D view. It's always logged in the Log tab regardless —
this only controls the extra visual. Same white-speech/blue-thought
distinction as the main [Live Viewer](tools-viewer.md).
