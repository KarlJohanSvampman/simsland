"""
systems/prop_placement.py

Minimum-distance ("margin") enforcement between placed props, plus a
shared "find me a clear tile" search reused by the power-outlet backfill
(systems/electrical.py) and the in-sim redecorate chore (systems/
refurnishing.py). No collision/placement validation of any kind existed
before this round (confirmed via full-codebase grep) -- props could
freely overlap. This is enforced going FORWARD only, at the World
Editor's own placement API (api/props.py's create_prop/move_prop) --
existing, already-persisted placements are left untouched, same
"going forward" precedent this session already used for room_
assignment.py/schema_defaults.py's other prop-field backfills.

No real wall-facing/interior-design geometry exists anywhere in this
codebase (confirmed this round) -- margin is judged purely by footprint
tile overlap/proximity (via systems/transforms.py's rotation-aware
transform_footprint(), reused as-is rather than reinvented), not by
which side of a wall something sits on.
"""

from systems.transforms import transform_footprint, tile_distance

MARGIN = 1           # tiles of required clearance, general furniture/appliance/fixture case
OUTLET_MARGIN = 1    # tiles of required clearance around a power outlet specifically

# Categories whose instances take up real floor space worth protecting.
# Purely decorative/wall-mounted props (posters, paintings) are exempt
# regardless of category -- they don't obstruct anything.
MARGIN_ENFORCED_CATEGORIES = {"furniture", "appliance", "fixture"}

# No "table"/"chair" category exists anywhere in this codebase's
# prop_templates (confirmed via grep) -- matched by keyword against
# name/template id instead, the same soft-taxonomy approach systems/
# chores.py already uses for priority zones/surfaces.
_TABLE_KEYWORDS = ("table", "desk", "counter", "island")
_SEATING_KEYWORDS = ("chair", "stool", "bench", "seat")


def _prop_tiles(prop, template):
    footprint = prop.get("footprint") or template.get("footprint") or [{"dx": 0, "dy": 0}]
    rotation = prop.get("rotation", 0)
    return transform_footprint(prop["x"], prop["y"], footprint, rotation)


def _is_table_like(template_id, template):
    haystack = f"{template.get('name', '')} {template_id}".lower()
    return any(k in haystack for k in _TABLE_KEYWORDS)


def _is_seating_like(template_id, template):
    haystack = f"{template.get('name', '')} {template_id}".lower()
    return any(k in haystack for k in _SEATING_KEYWORDS)


def _is_outlet(template_id, template):
    return template_id == "power_outlet" or "outlet" in (template.get("tags") or [])


def _margin_needed(template_id_a, tmpl_a, template_id_b, tmpl_b):
    """Required tile clearance between these two prop types, or None if
    no margin is enforced between this pair at all."""
    if _is_outlet(template_id_a, tmpl_a) or _is_outlet(template_id_b, tmpl_b):
        return OUTLET_MARGIN

    if tmpl_a.get("wall_mounted") or tmpl_b.get("wall_mounted"):
        return None  # wall art doesn't obstruct floor space

    if tmpl_a.get("category") not in MARGIN_ENFORCED_CATEGORIES:
        return None
    if tmpl_b.get("category") not in MARGIN_ENFORCED_CATEGORIES:
        return None

    # Appliances on tables, chairs at tables -- explicit exceptions
    # (the user's own examples).
    a_table = _is_table_like(template_id_a, tmpl_a)
    b_table = _is_table_like(template_id_b, tmpl_b)
    if a_table and (tmpl_b.get("category") == "appliance" or _is_seating_like(template_id_b, tmpl_b)):
        return None
    if b_table and (tmpl_a.get("category") == "appliance" or _is_seating_like(template_id_a, tmpl_a)):
        return None

    return MARGIN


def _min_tile_distance(tiles_a, tiles_b):
    return min(
        tile_distance(ax, ay, bx, by)
        for ax, ay in tiles_a
        for bx, by in tiles_b
    )


def check_placement(world, defs, building_id, template_id, x, y, rotation=0, exclude_prop_id=None):
    """Returns (True, None) if a prop of this template can be placed at
    (x, y) in this building, else (False, reason). Only checks against
    OTHER props in the same building -- margin is a local, physical
    concern, not a household-wide one. An unknown template is let
    through (nothing to validate against)."""
    prop_templates = defs.get("prop_templates", {})
    template = prop_templates.get(template_id)
    if not template:
        return True, None

    new_tiles = transform_footprint(x, y, template.get("footprint") or [{"dx": 0, "dy": 0}], rotation)

    for other in world.get("props", []):
        if other.get("building_id") != building_id:
            continue
        if exclude_prop_id and other.get("id") == exclude_prop_id:
            continue
        other_template_id = other.get("template")
        other_template = prop_templates.get(other_template_id)
        if not other_template:
            continue

        margin = _margin_needed(template_id, template, other_template_id, other_template)
        if margin is None:
            continue

        other_tiles = _prop_tiles(other, other_template)
        if _min_tile_distance(new_tiles, other_tiles) < margin:
            label = other.get("name") or other_template.get("name") or other_template_id
            if _is_outlet(other_template_id, other_template):
                return False, f"blocks clearance around {label}"
            if _is_outlet(template_id, template):
                return False, f"too close to {label} to leave the outlet clear"
            return False, f"too close to {label}"

    return True, None


def check_all_placements(defs, props):
    """Bulk variant of check_placement() -- validates every prop in
    `props` against every other prop in the SAME building. Returns a
    list of violation dicts (empty if none): {"prop_id",
    "other_prop_id", "building_id", "reason"}.

    Exists because the actual World Editor (frontend/src/editor-main.js)
    doesn't call create_prop/move_prop incrementally at all -- it edits
    a client-side buffer (worldState.props) and posts the WHOLE world
    back in one shot via POST /api/editor/world (api/editor.py::save())
    -- confirmed via grep, no frontend caller of api/props.py's per-prop
    endpoints exists. Those endpoints' own check_placement() call stays
    in place regardless (a real, correct REST contract for whoever/
    whatever else eventually calls them), this is the bulk equivalent
    for the editor's actual save path."""
    prop_templates = defs.get("prop_templates", {})
    violations = []

    by_building = {}
    for p in props:
        by_building.setdefault(p.get("building_id"), []).append(p)

    for building_id, building_props in by_building.items():
        if not building_id:
            continue
        for i, prop in enumerate(building_props):
            template_id = prop.get("template")
            template = prop_templates.get(template_id)
            if not template:
                continue
            tiles = _prop_tiles(prop, template)
            for other in building_props[i + 1:]:
                other_template_id = other.get("template")
                other_template = prop_templates.get(other_template_id)
                if not other_template:
                    continue
                margin = _margin_needed(template_id, template, other_template_id, other_template)
                if margin is None:
                    continue
                other_tiles = _prop_tiles(other, other_template)
                if _min_tile_distance(tiles, other_tiles) < margin:
                    label_a = prop.get("name") or template.get("name") or template_id
                    label_b = other.get("name") or other_template.get("name") or other_template_id
                    violations.append({
                        "prop_id":       prop.get("id"),
                        "other_prop_id": other.get("id"),
                        "building_id":   building_id,
                        "reason":        f"{label_a} is too close to {label_b}",
                    })

    return violations


def find_clear_tile_near(world, defs, building_id, template_id, near_x, near_y, search_radius=6):
    """Small expanding-ring search for a tile where check_placement()
    passes. Used by the power-outlet backfill and the in-sim redecorate
    chore -- neither has real wall/floor-open-space geometry to reason
    about, so this is a best-effort "somewhere nearby and not
    overlapping anything" search, not true interior-design placement."""
    if check_placement(world, defs, building_id, template_id, near_x, near_y)[0]:
        return near_x, near_y
    for radius in range(1, search_radius + 1):
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                if max(abs(dx), abs(dy)) != radius:
                    continue
                x, y = near_x + dx, near_y + dy
                if check_placement(world, defs, building_id, template_id, x, y)[0]:
                    return x, y
    return None
