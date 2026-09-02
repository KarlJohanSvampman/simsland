# Blender → .glb pipeline

How to get a model you've made in Blender actually working in the game.

## Where assets live

Everything under `resources/` on disk is served directly by the backend
at `/resources/...`. Subfolders: `resources/characters/`,
`resources/props/`, `resources/items/`, plus `vehicles`/`buildings`/
`animations` categories in the asset picker. Character files are named by
archetype — `adult_male.glb`, `adult_female.glb`, `child_male.glb`,
`child_female.glb`, `teen_male.glb`, `teen_female.glb`, `elder_male.glb`,
`elder_female.glb`. Props use free-form `snake_case` names
(`kitchen_table_001.glb`, `sofa_a.glb`).

## The export checklist

1. **Model and rig in Blender** as normal.
2. **Character skeletons must use Mixamo-style bone names** —
   `mixamorigHips`, `mixamorigSpine1`, `mixamorigSpine2`, `mixamorigNeck`,
   `mixamorigHead`, `mixamorigLeftHand`/`mixamorigRightHand`,
   `mixamorigLeftForeArm`/`mixamorigRightForeArm`,
   `mixamorigLeftFoot`/`mixamorigRightFoot`, and so on. Both
   `mixamorig:Hips` (with colon) and `mixamorigHips` (without) are
   accepted — the loader strips non-alphanumeric characters before
   comparing — but the base names themselves have to match. The easiest
   way to get this right is starting from a Mixamo-rigged character or
   retargeting onto a Mixamo skeleton before export.
3. **Bone names need to carry certain substrings** for the game's
   automatic upper/lower-body split to classify them correctly — a bone
   name containing `leg`, `upleg`, `foot`, `toe`, `ankle`, `knee`, `hip`,
   or `pelvis` is treated as lower-body; everything else is upper-body.
   This drives blending (e.g. "sit" from the legs + "eat" from the arms
   playing together) automatically, with no manual authoring — but only
   if your bone names actually contain these substrings.
4. **Clothing/item attachment needs specific bones present** — the game
   hardcodes attachment targets per clothing slot: head/hair →
   `mixamorigHead`, neck → `mixamorigNeck`, outerwear → `mixamorigSpine2`,
   torso/undershirt → `mixamorigSpine1`, legs/underwear →
   `mixamorigHips`, socks/feet → `mixamorigLeftFoot`/`mixamorigRightFoot`,
   hands → `mixamorigLeftHand`/`mixamorigRightHand`, wrists →
   `mixamorigLeftForeArm`/`mixamorigRightForeArm`. A new character rig
   needs all of these bone names present for clothing/items to attach
   correctly.
5. **Add anchor/target Empties where you need precise attachment
   points** — see
   [Anchors, targets, and animations](anchors-and-animations.md) for the
   naming convention and how the game reads them.
6. **Name your actions/animation clips to match what the game expects**
   — also covered in
   [Anchors, targets, and animations](anchors-and-animations.md).
7. **Export as glTF Binary (.glb)**, with all animations you want
   included in the same file — the game expects **one .glb per character
   model, with every one of its animation clips embedded** (via NLA
   strips/actions exported together), not separate animation-only files
   per clip.
8. **Export with a clean, identity transform on the armature root** if at
   all possible. The game runs an automatic correction at load time for
   two known Mixamo export defects — a doubled cm→m scale (which can
   shrink a character to ~1% size if not caught) and a stray rotation
   baked onto the root (often 90° about X, which tips the character onto
   its back). This correction exists as a safety net, not something to
   rely on — an export with correct transforms from the start avoids
   depending on it.

## Getting it into the game

1. Drop the exported `.glb` into the right `resources/` subfolder (or
   upload it directly through [Mesh Bank](tools-meshbank-animbank.md)'s
   asset uploader).
2. Open **Mesh Bank**, find it in the sidebar list, and confirm it loads
   correctly — check the skeleton overlay appears (for characters), check
   anchors/targets show up as colored spheres if you added any, check the
   bounding-box stats look sane.
3. If it's a character, open **Anim Bank** and **⚡ Extract Clips** to
   pull its animations into the animation library, then verify each
   clip's category/name looks right.
4. Reference the model from its template's `model` field (via the
   [Definitions Editor](tools-definitions-editor.md) or a direct JSON
   edit — see [Adding templates, step by step](adding-templates.md)). The
   Definitions Editor's Mesh Bank Assets browser lets you click an asset
   to auto-fill this field.

## If something looks wrong

- **Renders as a plain colored placeholder shape** (a flat blue-grey
  cylinder for props in the live game, or an orange semi-transparent
  "ghost" in Mesh Bank) — the `model` field doesn't resolve to a real
  `.glb`, or the file 404s. This is a deliberate, non-blocking fallback,
  not a crash — check the path/filename.
- **Character is tiny or lying on its back** — the scale/rotation
  correction described in step 8 is compensating for something in your
  export; check the armature root's transform in Blender before export
  rather than relying on the game's correction indefinitely.
- **Clothing doesn't attach, or attaches to the wrong spot** — check the
  bone names against the list in step 4.
- **An animation doesn't play, or plays on the wrong body part** — check
  the clip's name against
  [Anchors, targets, and animations](anchors-and-animations.md), and
  check the bone-name substrings from step 3 for the upper/lower split.
