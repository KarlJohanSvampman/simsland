"""
systems/lighting.py

Real on/off state for lighting props -- "toggle_light"/"toggle_room_lights"
were declared as anchor interactions on every lamp/switch template
(ceiling_light, pendant_light, wall_sconce, floor_lamp, light_switch) but
had zero backend handling anywhere (confirmed via full-codebase grep) --
interacting with a light did nothing but play an animation. This wires up
the actual effect, dispatched from systems/action_router.py::_route_interact
the moment the interaction is chosen (these are instant flips, not a
multi-phase activity like carry/order_taxi).

A prop instance's own state.on is authoritative once set; template
default_state.on is only the fallback for a prop that's never been
touched (systems/prop_placement.py's default_state is declared on
templates but, like toggle_light itself, was never actually applied to
placed instances anywhere).

Room-scoping for the wall switch recomputes each prop's room live via
systems/navigation.get_room_at_position rather than trusting a stored
prop["room_id"] -- systems/room_assignment.py only backfills that field
through specific live-sim creation paths (systems/electrical.py's outlet
backfill, systems/refurnishing.py's chore); a prop placed through the
World Editor's own bulk save (api/editor.py::save()) never goes through
it, so a stored room_id can't be relied on for editor-placed lamps.
"""


def _iter_props(world):
    props = world.get("props", [])
    return props.values() if isinstance(props, dict) else props


def _is_switch_template(template):
    return any(a.get("interaction") == "toggle_room_lights" for a in (template.get("anchors") or []))


def _is_lighting_template(template):
    return template.get("category") == "lighting" or "lighting" in (template.get("tags") or [])


def light_is_on(prop, template):
    state = prop.get("state") or {}
    if "on" in state:
        return bool(state["on"])
    return bool((template.get("default_state") or {}).get("on", True))


def _set_light_on(prop, value):
    prop.setdefault("state", {})["on"] = value


def _ensure_building_nav_cached(building, world):
    """systems/navigation.py's NAV_CACHE is process-local and only gets
    (re-)primed for an existing building on a genuine Redis cache-miss
    (db.py::load_world's build_world_geometry() call, itself only reached
    when nothing was found in Redis -- see db.py's own comment on that
    branch). Every OTHER load_world() call -- i.e. nearly all of them,
    including right after any code-reload process restart while Redis
    still has the world cached -- skips it entirely, leaving a freshly
    restarted process with an empty NAV_CACHE for buildings that already
    existed before the restart. Self-heals here rather than relying on
    that timing, using the exact same building_manager.py::
    cache_floorplan(building["id"], floorplan) call."""
    from systems.navigation import NAV_CACHE, cache_floorplan
    if building["id"] in NAV_CACHE:
        return
    from systems.templates import get_floorplan_template
    floorplan = get_floorplan_template(world, building)
    if floorplan:
        cache_floorplan(building["id"], floorplan)


def _room_key(prop, world):
    """(building_id, room_id) recomputed live -- see module docstring."""
    building_id = prop.get("building_id")
    if not building_id:
        return None, None
    building = next((b for b in world.get("buildings", []) if b.get("id") == building_id), None)
    if not building:
        return building_id, prop.get("room_id")
    _ensure_building_nav_cached(building, world)
    from systems.navigation import get_room_at_position
    return building_id, get_room_at_position(building, prop.get("x"), prop.get("y"))


def toggle_light(prop, definitions, world=None):
    """A single lamp's own toggle -- flips just this prop."""
    template = definitions.get("prop_templates", {}).get(prop.get("template"), {})
    _set_light_on(prop, not light_is_on(prop, template))
    if world is not None:
        from sim_loop import _mark_dirty
        _mark_dirty(world, prop_ids={prop["id"]})


def toggle_room_lights(switch_prop, world, definitions):
    """A wall switch's toggle -- flips itself, then every OTHER lighting
    prop (not another switch) sharing its building+room. Returns the list
    of affected prop ids (the switch itself excluded)."""
    prop_templates = definitions.get("prop_templates", {})
    switch_template = prop_templates.get(switch_prop.get("template"), {})
    new_on = not light_is_on(switch_prop, switch_template)
    _set_light_on(switch_prop, new_on)

    building_id, room_id = _room_key(switch_prop, world)
    affected = []
    for other in _iter_props(world):
        if other.get("id") == switch_prop.get("id"):
            continue
        if other.get("building_id") != building_id:
            continue
        other_template = prop_templates.get(other.get("template"), {})
        if not _is_lighting_template(other_template) or _is_switch_template(other_template):
            continue
        if _room_key(other, world)[1] != room_id:
            continue
        _set_light_on(other, new_on)
        affected.append(other.get("id"))

    from sim_loop import _mark_dirty
    _mark_dirty(world, prop_ids={switch_prop["id"], *affected})
    return affected
