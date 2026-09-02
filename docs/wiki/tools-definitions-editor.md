# Definitions Editor

The content/template registry editor for `simulations/default/
definitions.json` — the single giant JSON file holding every data-driven
template in the game (items, props, jobs, traits, hobbies, and dozens
more). Open **`definitions.html`** alongside the frontend dev server.

If you just want the shortest path to adding one new template, skip to
[Adding a new template, step by step](#adding-a-new-template-step-by-step)
below, or read [Adding templates, step by step](adding-templates.md) for
the general-purpose version of this workflow covering registries this
editor doesn't reach at all.

## Layout

Three columns:

- **Left sidebar** — nav links to the other tools, a row of **tab chips**
  (one per registry this editor exposes), a row of 4 actions (**New**,
  **Duplicate**, **Delete**, **Save**), and the scrollable list of
  existing template IDs for whichever tab is active.
- **Center** — the template's ID, a "Model: …" label, and one big raw-JSON
  textarea that fills the rest of the panel.
- **Right** — a live 3D model/animation preview, a Bone Slots panel and a
  Randomize Traits panel (character templates only), and a Mesh Bank
  Assets browser at the bottom.

## Important: not every registry has a tab here

`definitions.json` has around 73 top-level registries. This editor's tab
row only reaches about 25 of them — the everyday ones (items, props, jobs,
traits, hobbies, interactions, activities, recipes, services, companies,
moods, needs). Registries added by later content rounds — `mental_health_
templates`, `physical_trait_templates`, `sports_teams`, `addiction_
templates`, `health_hazard_templates`, `symptom_templates`, `faction_
templates`, `celebrity_registry`, `icon_templates`, `injury_templates`,
`kinks_registry`, `sexual_acts`, and most of the smaller enum/registry
lists — **are not reachable through this UI at all**. For those, edit
`simulations/default/definitions.json` directly in a text editor (see
[Adding templates, step by step](adding-templates.md)).

## Choosing a registry and a template

Click a tab chip to select a registry; the sidebar list below it fills
with that registry's template IDs. Click a row to open it in the JSON
textarea and refresh the preview.

## Editing

Almost everything is edited as raw JSON in the textarea — there's no
structured form for most fields. Two exceptions add widgets alongside the
textarea, for `character_templates` only: a **Bone Slots** panel (assign
skeleton bones for head/neck/hands/feet/spine/pelvis attachment points)
and a **Randomize Traits** panel (pick trait/physical-trait counts and
polarity, click Generate).

A handful of registries get their own fully custom preview instead of a
plain model viewer:

- **`activity_templates`** — a step-by-step timeline, one mini 3D
  renderer per step showing the linked prop and its animation phases.
- **`interaction_templates`** — a full interactive preview: character/
  prop/target selectors, Play All / Start / Loop / Stop / Abort controls,
  item-equip checkboxes, a draggable prop with an interaction-radius ring,
  and target-region bone markers.
- **`material_templates`** / **`tile_templates`** — a textured sphere /
  small ground plane instead of a model.
- A synthetic **Socioeconomics** tab (not a real registry) replaces the
  JSON textarea with dedicated Statistics / Government / Public Figures
  panels.

The **Mesh Bank Assets search box** in the right panel is currently dead
— it renders but isn't wired to filter anything. Scroll the list manually.

## Adding a new template, step by step

1. Click the tab chip for the registry you want (e.g. `item` or `job`).
2. Click **New**. A browser prompt asks for a **Template ID** — type one
   (e.g. `laptop_gaming`) and confirm.
3. The editor creates a pre-filled skeleton for that registry type and
   opens it automatically.
   - **Caveat**: not every registry has a skeleton defined. `belief_
     templates`, `contact_designations`, `school_templates`, and
     `hobby_templates` fall through to an **empty `{}`** — you'll need to
     type every field yourself. Check an existing entry in the same
     registry first (open one, note its shape, then go back to your new
     blank one) if you're unsure what fields are expected.
   - **Caveat**: typing an ID that already exists **silently overwrites
     it** with a blank/default template — no warning. Double-check the ID
     is actually new.
4. Fill in the JSON fields directly. For a model-bearing template, click
   an entry in the Mesh Bank Assets browser to auto-fill `model`.
5. Click **Save**.

**Duplicate** works the same way but starts from a deep copy of whatever
template is currently open — useful for a near-variant of an existing
entry. Note it does **not** auto-open the new copy; click its row in the
list afterward to actually edit it. It has the same silent-overwrite
behavior as New if you reuse an existing ID.

## Deleting

Select a template, click **Delete**. It's removed from memory
immediately, with **no confirmation dialog** — nothing is written to disk
until you click **Save** afterward, so you can still back out by not
saving.

## Saving, and whether you need to restart

**Save** re-parses the textarea (if a template is open) and, on a real
JSON syntax error, shows exactly what's wrong (`Invalid JSON in <id>:
<message>`) and aborts before sending anything — it won't silently save
broken JSON. On success it POSTs the **entire** `definitions` object (not
just the current tab) to the backend, which writes it atomically and
invalidates the backend's definitions cache — **changes made through this
editor apply on the very next simulation tick, no container restart
needed.**

This does *not* apply if you edit `definitions.json` by hand outside this
tool (a text editor, a script) — nothing tells the running backend to
reload in that case, so a direct file edit needs `docker restart
sim-backend` (or your equivalent) to take effect.

## Validation

Only JSON syntax is checked. There's no required-field validation and no
cross-reference checking — e.g. a `job_templates` entry can name a skill
that doesn't exist, or an `interaction_templates` entry can reference a
prop tag nothing has, and Save will accept it silently. The model preview
is the only soft signal something's off: an unresolved `model` reference
shows an orange placeholder and a status-bar warning.
