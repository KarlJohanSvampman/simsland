# Adding templates, step by step

Everything in this game that isn't runtime character/world state — items,
props, jobs, traits, hobbies, interactions, mental health conditions,
sports teams, and dozens more — is a **template**: one entry in one of the
~73 top-level registries inside `simulations/default/definitions.json`.
Adding new content almost always means adding a new template entry.

There are two paths, depending on which registry you're adding to.

## Path A — the registry has a tab in the Definitions Editor

About 25 of the most commonly-edited registries (items, props, jobs,
traits, hobbies, interactions, activities, recipes, services, companies,
moods, needs, and a few more) are reachable through
[the Definitions Editor](tools-definitions-editor.md)'s tab row. Use it —
it gives you JSON-syntax error checking, a live model preview, and (for
character templates) structured bone-slot and trait-randomizer widgets.

1. Open `definitions.html`.
2. Click the tab for your registry.
3. Click **New**, type a new, not-already-used template ID.
4. Fill in the fields. If unsure what's expected, open an existing entry
   in the same registry first to see its shape — not every registry has a
   pre-filled skeleton (`belief_templates`, `contact_designations`,
   `school_templates`, `hobby_templates` start you with an empty `{}`).
5. **Save**. This takes effect on the very next simulation tick — no
   restart needed.

Full detail, including the tool's rough edges (silent overwrite-on-New,
the dead search box), is in
[the Definitions Editor guide](tools-definitions-editor.md).

## Path B — the registry has no tab (most of them)

Registries added by later content rounds aren't wired into the editor's
tab list yet — `mental_health_templates`, `physical_trait_templates`,
`sports_teams`, `addiction_templates`, `health_hazard_templates`,
`symptom_templates`, `faction_templates`, `celebrity_registry`,
`icon_templates`, `injury_templates`, `kinks_registry`, `sexual_acts`, and
most smaller enum/registry lists all fall here. For these:

1. Open `simulations/default/definitions.json` in a text editor. It's
   large (1.5MB+) — use your editor's search to jump straight to the
   registry key (e.g. search for `"mental_health_templates"`).
2. Find an existing entry in the same registry and use it as your shape
   reference — copy its structure, don't guess at field names. Registries
   are internally consistent (every entry in a given registry has the
   same field set), so one example tells you everything you need.
3. Add your new entry, keeping the JSON valid (matching braces/commas —
   a linter or your editor's JSON validation catches most mistakes before
   you save).
4. Save the file.
5. **Restart the backend** (`docker restart sim-backend`, or your
   equivalent) — a direct file edit doesn't go through the editor's save
   endpoint, so nothing tells the running process to reload. Definitions
   are cached in memory at startup; the change is invisible until restart.

## Which file is actually live?

If your project has more than one `definitions.json` on disk (a stub
under `backend/data/simulations/default/` and the real one under
`simulations/default/` at the repo root, mounted into the backend
container), **the one at the repo root is the one that's actually
loaded** — confirm by checking what `core/definitions.py::defs_path()`
resolves to, or just check the file size (the real one is ~1.5MB+; a stub
is a few KB). Editing the wrong copy silently does nothing.

## After adding: does anything else need to reference it?

A new template being valid JSON isn't the same as it being *wired up* —
nothing validates cross-references, so check whether your new entry needs
to be:

- Reachable by a random-assignment roll somewhere (many registries — jobs,
  traits, hobbies, conditions — are picked via a weighted roll in
  `character_gen.py` or a system-specific generator; a template that's
  valid but never rolled will just never appear in play unless something
  explicitly requests it)
- Referenced by another registry (e.g. a new `job_templates` entry a
  `faction_templates`' `recruitment_criteria` should include, or a new
  `prop_templates` entry that a `hobby_templates`' `required_props` tag
  list should cover)
- Given a real 3D model — see
  [Blender → .glb pipeline](blender-to-glb.md) if your template needs a
  `model` field pointing at an actual asset (props/items/characters
  render as a placeholder without one — not broken, just unmodeled, per
  [Anchors, targets, and animations](anchors-and-animations.md))

If you're not sure whether something needs code changes to actually take
effect (not just content), that's usually true for genuinely new
*mechanics* (a new interaction type nothing resolves yet, a new need field
nothing reads) — adding a new *instance* of an existing template shape
(one more item, one more job, one more trait) almost never needs code
changes, since the systems that consume that registry already loop over
"whatever's in the registry" generically.
