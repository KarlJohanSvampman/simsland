# Simsland/HoloSims Wiki

Step-by-step guides for working with this project's content and tools. For
a technical map of the simulation's systems (needs, cognition, health,
economy, etc.), see [`docs/architecture_,,map.md`](../architecture_,,map.md)
instead — this wiki is about *making things* (content, assets, art),
that one is about *how the sim works*.

## Start here

All of these tools are simple HTML pages served alongside the FastAPI
backend. Start the backend (`uvicorn main:app`, port 8000 by default —
or via the project's Docker setup) and, for the Vite-built pages
(`index.html`, `character_creator.html`, `definitions.html`, `editor.html`,
`floorplan.html`, `meshbank.html`, `animbank.html`, `social_debug.html`),
also run the frontend dev server (`npm run dev --prefix frontend`, default
port 5174 per `.claude/launch.json`'s `viewer-dev` config — Vite proxies
`/api`, `/resources`, `/debug`, `/view` through to the backend). Two pages
(`admin.html`, `debug` at `/debug`) are served directly by FastAPI instead
and don't need the Vite server at all.

## Using the graphical tools

- [The Live Viewer](tools-viewer.md) — watching the simulation run, the
  Inspector, event timeline, debug overlays, admin controls, dev tools
- [Character Creator](tools-character-creator.md) — building and spawning
  characters
- [Definitions Editor](tools-definitions-editor.md) — the content/template
  registry editor (**start here if you just want to add one new template**)
- [World Editor & Floorplan Designer](tools-world-editor.md) — placing
  buildings/props/terrain on the map, and designing floorplans/rooms
- [Mesh Bank & Anim Bank](tools-meshbank-animbank.md) — inspecting/
  authoring 3D model and animation metadata
- [Social Sandbox](tools-social-sandbox.md) — isolated testing of
  character conversations and social state, safe from the live sim

## Adding content

- [Adding templates, step by step](adding-templates.md) — the general
  workflow for adding a new item, prop, job, trait, or any other template
  type, including the ~48 registries the Definitions Editor doesn't expose
  a tab for
- [Blender → .glb pipeline](blender-to-glb.md) — modeling and exporting an
  asset so the game can actually load and use it
- [Anchors, targets, and animations](anchors-and-animations.md) — how the
  game finds "where exactly does a sitting character's body go on this
  chair" and "which animation clip plays for which activity"

## A note on scope

This wiki is written from a close reading of the actual current code and
UI (as of when each page was last updated), not from a spec — where the
tools have a rough edge (a dead search box, a silent overwrite-on-New, a
registry the editor can't reach), the guide says so, because that's what
you'll actually run into.
