# Anchors, targets, and animations

There are **two completely separate things called "anchors"** in this
project. Mixing them up is the single most confusing part of authoring
new content here, so this page leads with telling them apart.

## The two anchor systems

**1. Logical/grid anchors** — pure 2D data, no 3D model involved. A
`prop_templates` JSON entry's `"anchors"` field is a list of `{name,
interaction}` entries with an implicit tile offset, rotated by whatever
rotation the prop instance was placed at. This is what decides *which
tile* a character should walk to and stand on to use a prop — e.g. "stand
one tile south of this stove to cook." You edit this as plain JSON, either
in the [Definitions Editor](tools-definitions-editor.md) or directly in
`definitions.json`.

**2. Literal in-model anchor nodes** — actual named Empties (or any named
object) placed *inside* the `.glb` file itself, at the exact 3D point you
want something to happen. These use a naming convention the game scans
for automatically:

- Nodes named `anchor_<something>` (e.g. `anchor_sit`, `anchor_eat`) —
  where a character's body should precisely sit relative to the model
  (a chair's seat, a sink's front edge).
- Nodes named `target_<something>` — similar, for whatever the game
  targets rather than anchors to.
- Nodes named `ik_hand_r`, `ik_hand_l`, `ik_finger_r`, `ik_finger_l` — IK
  reach points on props like buttons or doorknobs.

At runtime, the game reads the node's **actual transformed position in
the scene graph** — not a manually-entered number — so moving/rotating
the model in Blender moves the anchor with it automatically, as long as
the Empty is parented correctly.

**Which one do you need?** The grid anchor decides "which tile do you
walk to." The in-model anchor decides "once there, exactly where does
your body/hand go." Most props with an interaction that involves sitting,
lying, or precise hand placement need both.

### Adding an in-model anchor

1. In Blender, add an Empty at the exact point you need (e.g. the seat of
   a chair, at pelvis height).
2. Name it `anchor_<interaction_name>` — the interaction name should
   match the `interaction` field of whatever `interaction_templates`
   entry will use it (e.g. an anchor for the `"sit"` interaction should
   be named `anchor_sit`).
3. Parent it to the model correctly (so it moves with the mesh if the
   mesh has separate transforms).
4. Export as part of the same `.glb` (see
   [Blender → .glb pipeline](blender-to-glb.md)).
5. Open [Mesh Bank](tools-meshbank-animbank.md) and confirm it shows up
   as a colored sphere in the Anchors panel, at the position you expect.
   You can also add or reposition an anchor directly in Mesh Bank via
   **📍 Place at click**, without re-exporting from Blender, if you just
   need a quick fix.

Lookup at runtime is by exact name match against the current activity's
interaction (`anchor_<interaction>`); if there's no exact match, the game
falls back to the first available anchor on that model, so an anchor
existing at all is better than none, even if the naming isn't perfect.

## Animation clips

**One `.glb` per character, with every animation clip it needs embedded
in that same file** — not separate files per animation. Clip names are
matched (case-insensitively) directly against a fixed set of expected
names — an action literally named `idle`, `walk`, `run`, `sit_idle`,
`lie_idle`, `eat`, `cook`, `work`, `phone`, `talk`, `read`, `sleep_idle`,
`stand_up`, `shower`, and others. Name your Blender action/clip exactly
that stem and it's picked up automatically — there's no code-side mapping
table to edit for one of these standard names.

An `interaction_templates`/`activity_templates` entry's `animation_state`
field (or an activity's `interaction` field) is the key the game looks up
in this table at runtime — so a new interaction that should play a
specific animation needs its `animation_state` to name a real clip stem
that exists on the character model.

**Every clip is automatically split into upper/lower body variants** by
filtering its bone tracks against the same upper/lower classification
described in [Blender → .glb pipeline](blender-to-glb.md) — you don't
author `eat_lower`/`eat_upper` separately; one full-body `eat` clip
becomes usable as an arms-only overlay automatically, layered on top of a
different lower-body clip (e.g. `sit_idle` legs + `eat` arms, for "sit and
eat").

**Two-character clips** (hugs, altercations, intimate acts) use a pair
group + role (`"a"`/`"b"`) convention, authored in
[Anim Bank](tools-meshbank-animbank.md) — still one clip per actor, both
embedded in the same source `.glb`.

### Adding a new stance or animation without a code change

Beyond the fixed set of standard clip names above, Anim Bank's
**Stances/Transitions** panels are a fully data-driven layer: define a new
stance there (with a Template chaining whichever clips it needs), and it
registers automatically — as long as a clip with the matching name exists
in the source GLB, no code change is required. This is the extension
point for anything beyond the built-in stance vocabulary.

## Checking your work

1. [Mesh Bank](tools-meshbank-animbank.md) — confirm anchors/targets sit
   where you expect, confirm the skeleton looks right.
2. [Anim Bank](tools-meshbank-animbank.md) — Extract Clips, confirm each
   new/renamed clip categorized sensibly, try the Blend mode to check an
   upper/lower combination actually looks right together.
3. Trigger the real interaction in the [Live Viewer](tools-viewer.md) (or
   stage it in the [Social Sandbox](tools-social-sandbox.md)) and watch a
   character actually use it.
