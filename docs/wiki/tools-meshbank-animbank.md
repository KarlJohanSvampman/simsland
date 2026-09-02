# Mesh Bank & Anim Bank

Two related authoring tools for 3D assets. Mesh Bank is about a model's
*geometry* (anchors, bone slots, placement); Anim Bank is about a
character's *animation clips* (extraction, blending, stance mapping).
Open **`meshbank.html`** / **`animbank.html`** alongside the frontend dev
server. See also [Anchors, targets, and animations](anchors-and-animations.md)
for how the game actually consumes what you author here.

## Mesh Bank (`meshbank.html`)

Browse every `.glb` under `resources/`, preview it, and author the
metadata the live game reads at runtime.

- **Loading a model**: pick a category (Characters / Props / Items /
  Vehicles / Buildings / Animations) to filter the sidebar list, then
  click a row. The model loads, the camera frames it automatically, and a
  battery of fixups run (see
  [Blender → .glb pipeline](blender-to-glb.md) for what these correct and
  why you shouldn't rely on them).
- **Animation buttons** — one per embedded clip; click to play it solo.
- **Bones panel** — every bone name found on the model, if it has a
  skeleton (shown as a skeleton overlay in the 3D view automatically).
  **Bone Slots** lets you assign specific bones as named attachment points
  (clothing, held items).
- **Anchors / Targets panels** — nodes in the model named with an
  `anchor_`/`target_` prefix show up here automatically, each drawn as a
  colored sphere in the 3D view (green = anchor, blue = target) with a
  facing arrow for anchors. You can add/edit/rename them, or click **📍
  Place at click** to raycast onto the model's surface and drop a new one
  exactly there.
- **Statistics / Hierarchy** — bounding-box dimensions (computed from
  actual bone world positions, so it stays correct even on a corrected/
  reposed skeleton) and a full node-name dump.
- **Placement / Transform / Pivot panels** — position/rotation/scale and
  a snap-to-ground/snap-to-grid pivot choice, applied on top of the raw
  model — this is what the live game actually uses when it instances the
  asset, independent of wherever the origin sits in the source file.

If a `.glb` fails to load, you'll see an orange semi-transparent "ghost"
placeholder with a `⚠ Model file not found` message — the tool keeps
working, it just can't show you the real geometry.

## Anim Bank (`animbank.html`)

A library and editor for **animation clips extracted from character
models**, plus tools for blending and mapping them to game stances — not
a geometry/anchor tool.

- **Sources tab** — add a character `.glb`, then **⚡ Extract Clips**
  pulls every embedded animation into the bank, auto-categorizing each by
  name (idle / locomotion / gesture / action / reaction / converse /
  touch / phone / clean / intoxicated / sex / altercation).
- **Clip editor** — rename, re-categorize, tag, mark loop/paired (for
  two-actor clips, with a pair group + role), and attach frame-indexed
  **notifies** (footstep, impact, ik add/remove, etc.) that fire during
  playback.
- **Transport controls** — play/pause, scrub, set in/out frame range,
  loop mode (repeat/ping-pong/once), speed — a real scrubber, which
  Mesh Bank doesn't have.
- **Blend mode** — pick separate upper-body and lower-body clips and
  preview them playing together (the tool classifies bones into upper/
  lower automatically by name). This is exactly what the live game does
  at runtime for things like "sit and eat."
- **IK panel** — drag 3D gizmos (right hand / left hand / both / look-at)
  and see live 2-bone IK solve on the skeleton, for previewing hand-reach
  without authoring a new clip.
- **Templates tab** — chain multiple clips into a reusable sequence (each
  step with its own start/end frame, speed, loop count, and alternatives).
- **Stances / Transitions panels** — map each character stance's idle/
  movement animation, and each stance-to-stance transition, to a
  Template. This is the live source of truth the game reads at runtime —
  **adding a new stance here, with a matching clip name in the source
  GLB, does not require any code change.**

## Which tool do I need?

- Fixing where an anchor/target sits on a model, or checking a model's
  skeleton/bones → **Mesh Bank**.
- Extracting/organizing/blending animation clips, or mapping a stance to
  a clip → **Anim Bank**.
- Both read/write their own JSON file (`meshbank.json` / `animbank.json`)
  — they don't conflict with each other or with `definitions.json`.
