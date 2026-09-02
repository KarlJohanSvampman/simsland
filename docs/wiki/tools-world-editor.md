# World Editor & Floorplan Designer

Two related tools: the **World Editor** places buildings/props/terrain and
spawns characters on the live map; the **Floorplan Designer** authors the
actual room layouts (tiles, walls, doors, rooms) those buildings use.

## World Editor (`editor.html`)

A real 3D scene (Three.js, `OrbitControls`) over an 80×80 world grid.
Left-drag orbits, right-drag pans, scroll zooms — same controls as the
[Live Viewer](tools-viewer.md).

**Tools panel** (bottom-left):

- **🏠 Place Floorplan** — opens a picker of `floorplan_templates`. Pick
  one, then double-click a tile to commit (or single-click, then **✅
  Place Here**). **⟳ Rotate 90°** (or key `R`) rotates the pending
  placement first. Placed buildings render as a flat blue placeholder
  rectangle sized to the template — not a real model.
- **📦 Place Prop** — same workflow, from `prop_templates`. Rendered as a
  plain orange cylinder marker; there's no free-form drag, only grid cell
  + 90° rotation steps. Props placed this way sit directly on the world
  grid — there's no "put this inside room X of building Y" concept in this
  tool; a prop's room gets resolved automatically from its position once
  saved.
- **🖌 Paint Tile** — paints world-grid terrain (grass/road/sidewalk/etc.
  from `tile_templates`), with rotation and corner-orientation support.
- **👤 Spawn Character** — lists your saved `character_templates`; click
  one, click a tile, and a real live character is created immediately
  (this is the one action here that takes effect right away, rather than
  waiting for Save — it calls `POST /api/editor/spawn_character` directly).

**Moving or deleting** a placed building or prop isn't supported yet —
clicking one only shows its info (template, coordinates, rotation) in a
read-only inspector panel. If you place something wrong, your only option
today is to edit `world.json`/the running world state directly, or ask
someone with backend access to remove it.

**Saving**: click **Save World**. This writes buildings, props, and
painted tiles all together in one request — there's no per-object save.

## Floorplan Designer (`floorplan.html`)

A 2D top-down canvas editor for one `floorplan_template` at a time —
individual tiles, their four wall edges, doors, windows, and room
boundaries. Scroll to zoom, middle- or right-drag to pan, right-click
erases.

**Paint tools** (left panel): **🔲 Tile** (floor material, from a
dropdown), **🧱 Wall**, **🚪 Door**, **🪟 Window** (each paints on
whichever edge of the hovered tile your cursor is nearest — a dashed
preview shows where it'll land), **🪜 Staircase**, **🗑 Erase** (erases
floor first, then the nearest wall). A **Wall Material** dropdown sets
what gets applied to any wall you paint next. Walls automatically mirror
onto the adjacent tile's matching edge.

### Creating a floorplan from scratch

1. Set **Template ID** (defaults to `starter_house`) and **Width**/
   **Height** in tiles.
2. Click **New Floorplan** to reset the working model.
3. Paint tiles, walls, doors, windows.
4. Place rooms and props (below).
5. Click **💾 Save**.

**📂 Load** prompts for an existing template ID and opens it for editing.

### Adding a room

Two ways:

- **Manual**: click **☑ Room Select Mode**, click tiles to toggle them
  into a selection, then in the panel that appears pick a **Room Type**
  (Living Room, Bedroom, Kitchen, Dining Room, Restroom/Bathroom, Home
  Office, Corridor, Main Entrance, Secondary Exit, Storage, Garage,
  Laundry, Generic Room), optionally add comma-separated **Tags**, and
  click **✔ Confirm Room**. Each existing room has its own **Remove**
  button in the Rooms panel.
- **Automatic**: **⚡ Auto-Detect Rooms** flood-fills over floored tiles,
  treating any `wall`-type edge (not doors/windows, which are passable)
  as a barrier — each enclosed region of 2+ tiles becomes a generic,
  untagged room. This only runs automatically on Save if no rooms exist
  yet; otherwise your manual rooms are kept, and you can still hit the
  button any time to force a re-detect.

**This is the tool to use if you want to split an existing single-room
house into a proper separate bathroom/bedroom** — auto-detect can't infer
subdivisions from open floor alone, it strictly needs a `wall` edge
already painted. The workflow is: Load the floorplan, paint interior
walls (and a door) where you want the division, then either manually
select+confirm each side as its own room, or hit Auto-Detect once the
dividing wall exists.

### Prop spawns

A separate **📦 Place Prop** tool here (with a template dropdown and 0°/
90°/180°/270° rotation) places props tied to the *floorplan template*
itself, distinct from the World Editor's per-instance props — these get
instantiated wherever that floorplan is placed as a building.

### Saving

**💾 Save** regenerates the room graph/navigation caches if needed, then
writes the whole floorplan into `definitions.floorplan_templates[id]` and
saves the full definitions document — the same save path as the
[Definitions Editor](tools-definitions-editor.md), so this also takes
effect on the next tick with no restart needed.
