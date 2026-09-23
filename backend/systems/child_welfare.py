"""
systems/child_welfare.py

Real, deliberately scoped-down detection + response for "this child's
only caregiver just became unavailable" -- previously nothing anywhere
did anything about this: child_care.py::tick_child_needs() silently
no-ops with zero resolved parents, and a resolved-but-jailed/incapacitated
parent was never checked for actual availability at all.

tick_child_welfare() (moderate cadence, mirrors child_care.py's own
sweep shape): for every age_group=="child" character, resolves
caregivers via child_care.py::_find_parents_for_child() (reused as-is)
and checks whether EVERY resolved caregiver is currently unavailable
(jailed/held pending trial/incapacitated/dead) or none ever resolved at
all -- AND no other real adult/elderly, available household member
covers for them.

_find_placement_relative() searches family.py's real kinship graph for
an available, off-household relative -- parent, grandparent, adult
sibling, step/adoptive parent, or guardian (family.py's relations graph
has no separate "aunt"/"uncle" label of its own; deriving one would need
a second hop through a parent's own sibling, deliberately out of scope
this round). If found: a real, immediate household/building
reassignment. If not: a real CPS worker NPC is dispatched (matching
services.py::_spawn_worker()'s exact bare-dict shape), then the child
itself goes off-grid ("cps_care") for the duration of the caregiver's
own known unavailability.

Evaluated against a ChatGPT-authored "Crime & Legal System" spec whose
own child-safeguarding invariants this module already matched closely
(arrest != guilt -- _caregiver_unavailable() keys off actual custody/
incapacitation state, never mere suspicion; a safe present adult always
takes priority over any placement at all; relative placement is tried
before CPS). Two real gaps confirmed and fixed this pass, both about
what happens AFTER placement, which nothing here previously revisited:
a relative placement was permanent with no way back, and a CPS
placement's own docstring already flagged that an early caregiver
release didn't dynamically re-sync the child's return. Both closed by
_review_existing_placements() below, driven by a real origin marker
(_child_welfare_placement) stamped at placement time. Real
wake_character() calls added too -- previously zero in this whole
module, so neither the child nor a receiving relative ever got an
actual reactive decision about any of this, only a passive memory.
"""

import random, uuid

from systems.child_care import _find_parents_for_child


def _caregiver_unavailable(c):
    if not c or c.get("alive") is False:
        return True
    legal_status = c.get("legal", {}).get("status")
    if legal_status in ("held_pending_trial", "jailed"):
        return True
    if c.get("posture") == "incapacitated":
        return True
    return False


def _has_present_covering_adult(child, world):
    """A real adult/elderly, available household member other than the
    unavailable caregiver(s) -- covers for them without needing any
    placement/dispatch at all."""
    hid = child.get("household_id")
    if not hid:
        return False
    for oc in world.get("characters", {}).values():
        if oc["id"] == child["id"] or oc.get("household_id") != hid:
            continue
        if oc.get("age_group") in ("adult", "elderly") and not _caregiver_unavailable(oc):
            return True
    return False


_PLACEMENT_RELATIONS = (
    "parent", "grandparent", "sibling",
    "step_parent", "adoptive_parent", "guardian",
)


def _find_placement_relative(child, world):
    """Searches family.py's kinship graph for a real, available, adult+,
    off-household relative."""
    fam_id = child.get("family_id")
    family = world.get("families", {}).get(fam_id) if fam_id else None
    if not family:
        return None

    chars = world.get("characters", {})
    for other_id in family.get("members", []):
        if other_id == child["id"]:
            continue
        other = chars.get(other_id)
        if not other or other.get("household_id") == child.get("household_id"):
            continue
        if other.get("age_group") not in ("adult", "elderly"):
            continue
        if _caregiver_unavailable(other):
            continue
        relation = family.get("relations", {}).get(f"{other_id}:{child['id']}")
        if relation in _PLACEMENT_RELATIONS:
            return other
    return None


def _place_with_relative(child, relative, world, triggering_parent_ids):
    from systems.household_manager import add_member_to_household
    household = world.get("households", {}).get(relative.get("household_id"))
    if not household:
        return False

    # Confirmed real gap (Crime & Legal System spec pass): this
    # reassignment was permanent with no way back -- a child sent to a
    # relative because a caregiver was unavailable never automatically
    # returned once that caregiver became available again, even years
    # later. Stamping the origin here is what _review_existing_
    # placements() below needs to know when (and where) to reunite them.
    child["_child_welfare_placement"] = {
        "type":                  "relative",
        "triggering_parent_ids": list(triggering_parent_ids),
        "original_household_id": child.get("household_id"),
        "original_building_id":  child.get("building_id"),
        "placed_tick":           world.get("tick", 0),
    }

    add_member_to_household(world, child, household)
    child["building_id"] = relative.get("building_id")
    return True


def _resolve_caregiver_return_tick(child, world, parents):
    """The known return point of whichever caregiver's unavailability
    triggered this -- used to size the child's own CPS-care duration.
    Falls back to a documented default (30 days) when no real return
    tick can be resolved (e.g. a dead caregiver -- no return at all;
    the child stays in care until manually resolved)."""
    best = None
    for p in parents:
        candidate = p.get("legal", {}).get("jail_until") or p.get("return_tick")
        if candidate and (best is None or candidate > best):
            best = candidate
    if best is None:
        from systems.law import TICKS_PER_DAY
        return world.get("tick", 0) + 30 * TICKS_PER_DAY
    return best


def _dispatch_cps_worker(child, world):
    """A real, visible, non-agentic NPC "arriving" at the child's home --
    matches services.py::_spawn_worker()'s exact bare-dict shape."""
    hid = child.get("household_id")
    household = world.get("households", {}).get(hid, {})
    x = household.get("mailbox", {}).get("x", child.get("x", 0))
    y = household.get("mailbox", {}).get("y", child.get("y", 0))

    from systems.service_npc import pick_worker_template
    template, sex = pick_worker_template("cps_worker")

    wid = f"worker_cps_{uuid.uuid4().hex[:6]}"
    world.setdefault("characters", {})[wid] = {
        "id":               wid,
        "name":             random.choice(["Ms. Ortiz", "Mr. Daniels", "Ms. Reyes", "Mr. Coleman"]),
        "x":                x,
        "y":                y,
        "rotation":         0,
        "facing":           "north",
        "template":         template,
        "sex":              sex,
        "is_service_worker": True,
        "service_role":     "cps_worker",
        "animation_state":  "walk",
        "alive":            True,
    }
    return wid


def _send_child_to_cps_care(child, world, parents):
    from systems.offgrid import send_offgrid
    return_tick = _resolve_caregiver_return_tick(child, world, parents)
    duration_minutes = max(60, (return_tick - world.get("tick", 0)) // 60)

    child["_child_welfare_placement"] = {
        "type":                  "cps",
        "triggering_parent_ids": [p["id"] for p in parents],
        "original_household_id": child.get("household_id"),
        "original_building_id":  child.get("building_id"),
        "placed_tick":           world.get("tick", 0),
    }

    send_offgrid(child, world, "cps_care", duration_minutes)


def tick_child_welfare(world):
    _review_existing_placements(world)

    for c in list(world.get("characters", {}).values()):
        if c.get("age_group") != "child" or c.get("alive") is False:
            continue
        if c.get("off_grid") and c.get("off_grid_reason") == "cps_care":
            continue  # already in care, nothing new to detect

        parents = _find_parents_for_child(c, world)
        all_unavailable = (not parents) or all(_caregiver_unavailable(p) for p in parents)
        if not all_unavailable:
            continue
        if _has_present_covering_adult(c, world):
            continue

        caregiver = parents[0] if parents else None
        relative = _find_placement_relative(c, world)
        if relative:
            if not _place_with_relative(c, relative, world, [p["id"] for p in parents]):
                continue
            summary = f"{c.get('name', 'The child')} went to stay with {relative.get('name', 'a relative')} after their caregiver became unavailable."
            tags = ["family", "child_welfare"]
            placement_type, placed_with = "relative", relative
        else:
            _dispatch_cps_worker(c, world)
            _send_child_to_cps_care(c, world, parents)
            summary = f"{c.get('name', 'The child')} was taken into care by social services after their caregiver became unavailable."
            tags = ["cps", "child_welfare", "shock"]
            placement_type, placed_with = "cps", None

        try:
            from systems.stories import add_story
            add_story(c, summary, "shock", tags, 0.85, [p["id"] for p in parents], tick=world.get("tick", 0))
        except Exception:
            pass

        from brain.memory import store_memory
        store_memory(c, summary, 0.9, tags, "child_welfare", world.get("tick", 0))

        # Real reactive wakes -- confirmed gap: this whole module had zero
        # wake_character() calls before this (Crime & Legal System spec
        # pass), so neither the child nor a relative who just took them in
        # ever got a real decision cycle about it, only a passive memory.
        from brain.cognition_scheduler import wake_character
        wake_character(c, world, "child_placement", {
            "placement_type":  placement_type,
            "caregiver_id":    caregiver["id"] if caregiver else None,
            "caregiver_name":  caregiver.get("name", "your parent") if caregiver else "your parent",
            "placed_with_id":  placed_with["id"] if placed_with else None,
            "placed_with_name": placed_with.get("name", "someone") if placed_with else "Child Protective Services",
        })
        if placed_with:
            wake_character(placed_with, world, "took_in_relative_child", {
                "child_id":       c["id"],
                "child_name":     c.get("name", "the child"),
                "caregiver_id":   caregiver["id"] if caregiver else None,
                "caregiver_name": caregiver.get("name", "their parent") if caregiver else "their parent",
            })


def _review_existing_placements(world):
    """The other half of the reunification gap: once placed (relative or
    CPS), nothing ever re-checked whether the triggering caregiver(s)
    became available again -- a relative placement had literally no way
    back (add_member_to_household is permanent), and a CPS placement's
    own docstring already flagged that an early release doesn't
    dynamically re-sync the child's off-grid duration. Both fixed here,
    driven entirely by the same _caregiver_unavailable() check the
    original detection pass uses -- release/acquittal (legal.status back
    to "free") or recovering from incapacitation both count."""
    chars = world.get("characters", {})
    for c in list(chars.values()):
        if c.get("alive") is False:
            continue
        marker = c.get("_child_welfare_placement")
        if not marker:
            continue

        triggers = [chars[pid] for pid in marker.get("triggering_parent_ids", []) if pid in chars]
        if triggers and any(_caregiver_unavailable(p) for p in triggers):
            continue  # at least one triggering caregiver is still unavailable
        if not triggers:
            continue  # triggering caregiver no longer exists -- leave the placement as-is

        if marker["type"] == "relative":
            from systems.household_manager import add_member_to_household
            household = world.get("households", {}).get(marker.get("original_household_id"))
            if not household:
                continue
            add_member_to_household(world, c, household)
            c["building_id"] = marker.get("original_building_id") or c.get("building_id")
            summary = f"{c.get('name', 'The child')} moved back home now that their caregiver is available again."
            del c["_child_welfare_placement"]

            from brain.memory import store_memory
            store_memory(c, summary, 0.75, ["family", "child_welfare", "reunification"],
                         "child_welfare", world.get("tick", 0))

            # Physically present and active right now (unlike the cps
            # branch below, still off-grid) -- a real reactive moment.
            from brain.cognition_scheduler import wake_character
            wake_character(c, world, "reunified_with_caregiver", {
                "caregiver_id":   triggers[0]["id"],
                "caregiver_name": triggers[0].get("name", "your parent"),
            })
        else:
            # cps: still off-grid -- pull the return tick forward instead
            # of waiting out the original (possibly much longer) estimate.
            # No wake_character here: an off-grid child isn't actively
            # thinking, and process_cps_care_return() already gives them
            # a real "came home" moment the instant they naturally return.
            if not c.get("off_grid") or c.get("off_grid_reason") != "cps_care":
                continue
            c["return_tick"] = min(c.get("return_tick") or world.get("tick", 0), world.get("tick", 0) + 60)
            del c["_child_welfare_placement"]


def process_cps_care_return(child, world):
    """Called from offgrid.py::process_return()'s "cps_care" branch --
    the child simply comes home once their off-grid clock runs out,
    exactly like any other off-grid trip resolving. An early caregiver
    release no longer leaves this stale -- _review_existing_placements()
    above pulls return_tick forward the moment the triggering caregiver
    becomes available again, so this still fires (just sooner)."""
    from brain.memory import store_memory
    store_memory(child, "Came home after a stretch of time in care.", 0.7,
                 ["cps", "child_welfare", "return"], "child_welfare", world.get("tick", 0))
