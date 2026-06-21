# =========================================================
# HOBBY PLANNER
# Orchestrates the multi-step preparation sequence for hobbies
# that require items and/or a specific prop.
#
# Entry points:
#   plan_hobby(c, world, hobby_name) -> bool
#       Builds and enqueues the full task sequence.
#       Returns False if essential prerequisites are completely unmet.
#
#   validate_and_trim_queue(c, world, remaining, session) -> list
#       Re-validates a suspended queue before reloading it,
#       skipping steps that are no longer necessary.
# =========================================================

import random

from systems.hobby_requirements  import HOBBY_REQUIREMENTS
from systems.item_knowledge      import get_known_location, record_item_location, FORGET_THRESHOLD
from systems.household_storage   import find_household_resource, resources_in_container
from systems.activity_queue      import queue_task, ensure_queue


# =========================================================
# HELPERS
# =========================================================

def find_prop_by_tags(world, tags):
    """Return the first world prop whose tags overlap with the given list."""
    props    = world.get("props", {})
    prop_list= list(props.values()) if isinstance(props, dict) else props
    tag_set  = set(tags)
    for prop in prop_list:
        if set(prop.get("tags", [])) & tag_set:
            return prop
    return None


def get_container_props_in_room(world, room_id):
    """Return all container props whose room_id matches."""
    _CONTAINER_TAGS = {
        "container", "cabinet", "drawer", "shelf",
        "storage", "fridge", "closet", "wardrobe", "box",
    }
    props     = world.get("props", {})
    prop_list = list(props.values()) if isinstance(props, dict) else props
    return [
        p for p in prop_list
        if p.get("room_id") == room_id
        and set(p.get("tags", [])) & _CONTAINER_TAGS
    ]


def _get_organized_trait(c):
    return bool(set(c.get("traits", [])) & {"organized", "pragmatic", "meticulous", "tidy"})


def _get_household(c, world):
    return world.get("households", {}).get(c.get("household_id"))


def _plausible_rooms(c, world):
    """
    Return room_ids to search, roughly ordered by how likely the
    item is to be there. Falls back to all rooms if no better info.
    """
    household = _get_household(c, world)
    if not household:
        return []
    home_id = household.get("home_id")
    home    = world.get("homes", {}).get(home_id, {})
    rooms   = list(home.get("rooms", {}).keys())
    if not rooms:
        # Derive from floorplan templates if available
        for fpdata in world.get("definitions", {}).get("floorplan_templates", {}).values():
            for room in fpdata.get("rooms", []):
                rid = room.get("id")
                if rid and rid not in rooms:
                    rooms.append(rid)
    random.shuffle(rooms)
    return rooms


def _item_uses(resource):
    """How many effective uses remain on a resource instance."""
    if resource is None:
        return 0
    return resource.get("uses_remaining", resource.get("quantity", 0))


# =========================================================
# PLAN HOBBY
# =========================================================

def plan_hobby(c, world, hobby_name):
    """
    Build the ordered activity queue for a hobby and push it onto
    c["activity_queue"].

    Queue shape (each block depends on the previous):
      [setup_prop?]
      → [search_room* for unknown items]
      → [retrieve_item for known items]
      → [examine_prop?] [examine_item* for low-use items]
      → [hobby_session]
      → [return_item* for organized characters]

    Returns True if the queue was successfully built, False if a
    hard prerequisite (no prop exists, nothing to buy with) blocks
    the hobby entirely — in that case a desire is added instead.
    """
    reqs = HOBBY_REQUIREMENTS.get(hobby_name)
    if not reqs:
        return False

    household = _get_household(c, world)
    if not household:
        return False

    ensure_queue(c)
    tick = world.get("tick", 0)

    # ── 1. Locate or plan the main prop ───────────────────
    main_prop    = find_prop_by_tags(world, reqs.get("main_prop_tags", []))
    main_prop_id = main_prop["id"] if main_prop else None
    can_proceed  = True

    setup_tasks          = []
    search_tasks         = []
    retrieve_tasks       = []
    examine_prop_tasks   = []
    examine_item_tasks   = []
    shopping_tasks       = []
    return_tasks         = []
    retrieved_item_types = []

    if main_prop is None and reqs.get("main_prop_tags"):
        from systems.persistent_desires import add_desire
        add_desire(c, "buy_prop",
                   target=reqs["main_prop_tags"][0],
                   importance=0.7)
        return False   # can't paint without an easel

    if main_prop and main_prop.get("state") == "folded":
        setup_tasks.append(("setup_prop", {"target_id": main_prop_id}))

    # ── 2. Check each required item ───────────────────────
    for item_req in reqs.get("items", []):
        item_type     = item_req["type"]
        min_uses      = item_req.get("min_uses", 1)
        uses_per_sess = item_req.get("uses_per_session", 1)
        do_examine    = item_req.get("examine", False)

        resource   = find_household_resource(household, item_type)
        uses_avail = _item_uses(resource)

        if uses_avail < min_uses:
            # Out of stock — schedule a shopping trip then bail; the
            # character will re-plan after restocking.
            shopping_tasks.append(("go_shopping", {
                "item_type": item_type,
                "quantity":  max(3, min_uses * 3),
            }))
            can_proceed = False
            continue

        location = get_known_location(c, item_type)

        if location:
            retrieve_tasks.append(("retrieve_item", {
                "item_type":    item_type,
                "container_id": location["container_id"],
                "room_id":      location["room_id"],
                "dest_prop_id": main_prop_id,
                "uses_needed":  uses_per_sess,
            }))
            retrieved_item_types.append(item_type)

            if do_examine or uses_avail <= min_uses + 1:
                examine_item_tasks.append(("examine_item", {
                    "item_type":    item_type,
                    "main_prop_id": main_prop_id,
                    "target_id":    main_prop_id,
                }))
        else:
            # Location forgotten — queue a search in up to 2 rooms
            rooms = _plausible_rooms(c, world)
            if rooms:
                for room_id in rooms[:2]:
                    search_tasks.append(("search_room", {
                        "item_type":    item_type,
                        "room_id":      room_id,
                        "dest_prop_id": main_prop_id,
                    }))
            else:
                shopping_tasks.append(("go_shopping", {
                    "item_type": item_type,
                    "quantity":  3,
                }))
                can_proceed = False

    # ── 3. Examine main prop before starting ──────────────
    if can_proceed and main_prop and reqs.get("examine_prop"):
        examine_prop_tasks.append(("examine_prop", {"target_id": main_prop_id}))

    # ── 4. Return tasks for organized characters ──────────
    is_organized = _get_organized_trait(c)
    if can_proceed and is_organized and reqs.get("put_away"):
        for item_type in retrieved_item_types:
            loc = get_known_location(c, item_type)
            if loc:
                return_tasks.append(("return_item", {
                    "item_type":    item_type,
                    "container_id": loc["container_id"],
                }))

    # ── Hard block: queue shopping and abort ──────────────
    if not can_proceed:
        for task_type, params in shopping_tasks:
            queue_task(c, task_type, params)
        return False

    # ── 5. Build dependency graph ─────────────────────────
    setup_ids = []
    for task_type, params in setup_tasks:
        tid = queue_task(c, task_type, params)
        setup_ids.append(tid)

    search_ids = []
    for task_type, params in search_tasks:
        tid = queue_task(c, task_type, params, depends_on=setup_ids)
        search_ids.append(tid)

    retrieve_ids = []
    for task_type, params in retrieve_tasks:
        tid = queue_task(c, task_type, params, depends_on=setup_ids)
        retrieve_ids.append(tid)

    # Examine tasks depend on everything so far
    gather_deps  = setup_ids + search_ids + retrieve_ids
    examine_ids  = []
    for task_type, params in (examine_prop_tasks + examine_item_tasks):
        tid = queue_task(c, task_type, params, depends_on=gather_deps)
        examine_ids.append(tid)

    # Hobby itself depends on all preparation
    hobby_deps = gather_deps + examine_ids
    hobby_id   = queue_task(c, "hobby_session", {
        "hobby":        hobby_name,
        "activity":     reqs["activity"],
        "target_id":    main_prop_id,
        "items_used":   retrieved_item_types,
        "uses_per_item": {
            req["type"]: req.get("uses_per_session", 1)
            for req in reqs.get("items", [])
        },
    }, depends_on=hobby_deps)

    # Return items after hobby (organized only)
    for task_type, params in return_tasks:
        queue_task(c, task_type, params, depends_on=[hobby_id])

    return True


# =========================================================
# VALIDATE AND TRIM (for suspended session resumption)
# =========================================================

def validate_and_trim_queue(c, world, remaining_queue, session):
    """
    Re-examine a suspended queue before reloading it.
    Tasks that are no longer needed are marked "skipped" rather
    than removed so the dependency graph stays intact.
    """
    household     = _get_household(c, world)
    retrieved     = set(session.get("retrieved_items", []))
    main_prop_id  = session.get("main_prop_id")

    props = world.get("props", {})
    main_prop = (
        props.get(main_prop_id) if isinstance(props, dict)
        else next((p for p in props if p.get("id") == main_prop_id), None)
    ) if main_prop_id else None

    cleaned = []
    for task in remaining_queue:
        t = task["type"]
        p = task.get("params", {})
        task = dict(task)  # don't mutate the original

        # Prop already set up
        if t == "setup_prop" and main_prop and main_prop.get("state") == "setup":
            task["status"] = "skipped"

        # Item already at the prop (retrieved before interruption)
        elif t == "retrieve_item" and p.get("item_type") in retrieved:
            task["status"] = "skipped"

        # Item location now known — skip the search
        elif t == "search_room" and get_known_location(c, p.get("item_type")):
            task["status"] = "skipped"

        # Item now in stock — skip shopping
        elif t == "go_shopping" and household:
            resource = find_household_resource(household, p.get("item_type", ""))
            if resource and _item_uses(resource) > 0:
                task["status"] = "skipped"

        cleaned.append(task)

    return cleaned
