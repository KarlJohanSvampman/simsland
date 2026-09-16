from systems.templates import (
    get_prop_template
)


# ============================================
# BASIC LOOKUPS
# ============================================
def get_prop_by_id(world, prop_id):

    for prop in world.get("props", []):

        if prop["id"] == prop_id:
            return prop

    return None


def get_props_by_template(world, template_id):

    return [

        p for p in world.get("props", [])

        if p.get("template") == template_id
    ]


# ============================================
# TEMPLATE HELPERS
# ============================================
def get_prop_category(world, prop):

    template = get_prop_template(world, prop)

    if not template:
        return None

    return template.get("category")


def get_prop_tags(world, prop):

    template = get_prop_template(world, prop)

    template_tags = template.get("tags", []) if template else []

    # extra_tags are stamped onto this SPECIFIC instance (e.g. "tag THE
    # kitchen table" for cook_prep), distinct from every other instance
    # of the same template -- unioned in here so every already-wired
    # tag consumer (props_with_tag, find_nearest_prop,
    # seating_planner._prop_tags) picks up instance tags for free.
    extra_tags = prop.get("extra_tags", [])

    if not extra_tags:
        return template_tags

    return list(dict.fromkeys(template_tags + extra_tags))


def get_prop_capabilities(world, prop):

    template = get_prop_template(world, prop)

    if not template:
        return []

    return template.get("capabilities", [])


# ============================================
# TEMPLATE FILTERING
# ============================================
def props_with_tag(world, tag):

    results = []

    for prop in world.get("props", []):

        tags = get_prop_tags(world, prop)

        if tag in tags:
            results.append(prop)

    return results


def props_with_capability(world, capability):

    results = []

    for prop in world.get("props", []):

        caps = get_prop_capabilities(world, prop)

        if capability in caps:
            results.append(prop)

    return results


def props_in_category(world, category):

    results = []

    for prop in world.get("props", []):

        cat = get_prop_category(world, prop)

        if cat == category:
            results.append(prop)

    return results


# ============================================
# DISTANCE
# ============================================
def prop_distance(c, prop):

    return (
        abs(c["x"] - prop["x"])
        + abs(c["y"] - prop["y"])
    )


# ============================================
# NEAREST PROP
# ============================================
def find_nearest_prop(

    c,
    world,

    capability=None,
    tag=None,
    category=None,
    template_id=None
):

    candidates = []

    for prop in world.get("props", []):

        # -----------------------------
        # TEMPLATE FILTER
        # -----------------------------
        if template_id:

            if prop.get("template") != template_id:
                continue

        # -----------------------------
        # CATEGORY FILTER
        # -----------------------------
        if category:

            cat = get_prop_category(
                world,
                prop
            )

            if cat != category:
                continue

        # -----------------------------
        # TAG FILTER
        # -----------------------------
        if tag:

            tags = get_prop_tags(
                world,
                prop
            )

            if tag not in tags:
                continue

        # -----------------------------
        # CAPABILITY FILTER
        # -----------------------------
        if capability:

            caps = get_prop_capabilities(
                world,
                prop
            )

            if capability not in caps:
                continue

        candidates.append(prop)

    if not candidates:
        return None

    candidates.sort(

        key=lambda p:
        prop_distance(c, p)
    )

    return candidates[0]


# ============================================
# ANCHORS
# ============================================
from systems.anchors import (
    get_world_anchor
)


# ============================================
# GET ANCHOR
# ============================================

def get_anchor(

    prop,

    anchor_name
):

    for anchor in prop.get(
        "anchors",
        []
    ):

        if anchor["name"] != anchor_name:
            continue

        return get_world_anchor(

            prop,

            anchor
        )

    return None



def get_anchors_by_interaction(

    prop,

    interaction_name
):

    results = []

    for anchor in prop.get(
        "anchors",
        []
    ):

        if (

            anchor.get(
                "interaction"
            )

            != interaction_name
        ):
            continue

        results.append(

            get_world_anchor(

                prop,

                anchor
            )
        )

    return results

# ============================================
# CONTAINERS
# ============================================
def is_container(world, prop):

    template = get_prop_template(world, prop)

    if not template:
        return False

    return "container" in template.get(
        "capabilities",
        []
    )


def get_prop_inventory(prop):

    return prop.setdefault(
        "inventory",
        []
    )


def add_item_to_prop(
    prop,
    item_instance
):

    inv = get_prop_inventory(prop)

    inv.append(item_instance)


def remove_item_from_prop(
    prop,
    item_id
):

    inv = get_prop_inventory(prop)

    for i, item in enumerate(inv):

        if item["id"] == item_id:

            return inv.pop(i)

    return None

# ============================================
# FIND NEAREST INTERACTION ANCHOR
# ============================================


def find_nearest_anchor(

    c,

    world,

    interaction_name
):

    best_prop = None
    best_anchor = None

    best_dist = 999999

    for prop in world.get(
        "props",
        []
    ):

        for anchor in prop.get(
            "anchors",
            []
        ):

            # --------------------------------
            # INTERACTION FILTER
            # --------------------------------

            # anchors store this as "interaction" (matches every prop_template
            # entry in definitions.json) -- "interactionName" was never once
            # written anywhere, so this filter always failed to match and
            # find_nearest_anchor() has never actually found anything.
            if (

                anchor.get(
                    "interaction"
                )

                != interaction_name
            ):
                continue

            # --------------------------------
            # PROJECT TO WORLD
            # --------------------------------

            wa = get_world_anchor(

                prop,

                anchor
            )

            # --------------------------------
            # DISTANCE
            # --------------------------------

            dist = (

                abs(
                    wa["x"] - c["x"]
                )

                +

                abs(
                    wa["y"] - c["y"]
                )
            )

            if dist < best_dist:

                best_dist = dist

                best_prop = prop

                # The REAL anchor dict from prop["anchors"], not `wa` --
                # get_world_anchor() returns dict(anchor) (a shallow copy
                # with world x/y baked in), so reserve_anchor() mutating
                # that copy's occupied_by never touched the actual prop
                # object. That silently made occupancy checks for every
                # find_nearest_anchor()-based interaction (use_toilet,
                # take_shower, wash_hands, ...) always see occupied_by=None
                # no matter how many characters had already reserved it --
                # any number of characters could "use" the same toilet at
                # once. Returning the real object lets reserve_anchor()'s
                # mutation actually stick.
                best_anchor = anchor

    if not best_prop:
        return None

    return (

        best_prop,

        best_anchor
    )


def find_nearest_free_anchor(c, world, interaction_name, exclude_anchor=None):
    """Same scan as find_nearest_anchor(), but skips any anchor already
    occupied by someone else -- and, if given, the specific anchor
    already confirmed occupied so the caller doesn't just find it again.
    Used when the globally-nearest anchor for an interaction is taken:
    per the user's ask, a character should check whether a SECOND
    instance of the same appliance (a different bathroom's toilet, a
    different sink) is free before giving up or queueing."""
    best_prop = None
    best_anchor = None
    best_dist = 999999

    for prop in world.get("props", []):
        for anchor in prop.get("anchors", []):
            if anchor.get("interaction") != interaction_name:
                continue
            if anchor is exclude_anchor:
                continue
            if anchor.get("occupied_by") and anchor["occupied_by"] != c["id"]:
                continue

            wa = get_world_anchor(prop, anchor)
            dist = abs(wa["x"] - c["x"]) + abs(wa["y"] - c["y"])
            if dist < best_dist:
                best_dist = dist
                best_prop = prop
                best_anchor = anchor

    if not best_prop:
        return None
    return (best_prop, best_anchor)


def find_nearest_household_anchor(c, world, interaction_name, household_id):
    """Same scan as find_nearest_free_anchor(), but restricted to props
    that belong to the given household, OR have no household at all (a
    public/community fixture, e.g. a store's or park's). Confirmed live
    bug: begin_interaction()'s search had no household concept whatsoever
    -- a character without a free bed/bathroom at home would happily walk
    into and use a NEIGHBOR's private one instead, unprompted. This is
    the "check my own place (and public spaces) first" half of the fix;
    interactions.py::begin_interaction() only falls through to the
    plain global search when this finds nothing."""
    best_prop = None
    best_anchor = None
    best_dist = 999999

    for prop in world.get("props", []):
        prop_household = prop.get("household_id")
        if prop_household and prop_household != household_id:
            continue
        for anchor in prop.get("anchors", []):
            if anchor.get("interaction") != interaction_name:
                continue
            if anchor.get("occupied_by") and anchor["occupied_by"] != c["id"]:
                continue

            wa = get_world_anchor(prop, anchor)
            dist = abs(wa["x"] - c["x"]) + abs(wa["y"] - c["y"])
            if dist < best_dist:
                best_dist = dist
                best_prop = prop
                best_anchor = anchor

    if not best_prop:
        return None
    return (best_prop, best_anchor)


# ============================================
# PREFERRED SURFACE (tag-based)
# ============================================

# Anchors of a "preferred" tagged prop found farther than this are no
# more useful than just walking to a generic surface -- without a
# cutoff, a table tagged all the way across the map would still "win"
# over the counter right next to the character.
PREFERRED_SURFACE_RADIUS = 10


def find_surface_with_tag(world, tag):
    """Scans every placed prop's RESOLVED template for a real, tagged
    `surfaces` entry (a prop_template field: [{"id", "tags", "center":
    {"x","z"}, "size"}], a square region in continuous model-local
    space -- see the "surfaces" plan). A surface's own `center` gets
    resolved into real world coordinates via the prop's placement
    rotation (transforms.py::rotate_local_point(), the exact same
    90/180/270 convention rotate_local_tile() already uses for
    footprint/anchors, just for continuous coordinates).

    Returns a list of (prop, surface, world_x, world_y) tuples --
    world_x/world_y is the surface's real center in world tile-space
    (a float, not necessarily an integer tile)."""
    from systems.templates import resolve_prop
    from systems.transforms import rotate_local_point

    results = []
    for prop in world.get("props", []):
        resolved = resolve_prop(world, prop)
        for surface in resolved.get("surfaces") or []:
            if tag not in (surface.get("tags") or []):
                continue
            center = surface.get("center") or {}
            rx, rz = rotate_local_point(
                center.get("x", 0), center.get("z", 0), prop.get("rotation", 0)
            )
            results.append((
                prop, surface,
                prop.get("x", 0) + rx, prop.get("y", 0) + rz,
            ))
    return results


def find_preferred_surface(c, world, activity_tag, fallback_interaction=None):
    """Tag-based generalization of the cooking-only "is there a flat
    surface nearby" check. Tries, in order:
    1. A real, distance-sorted SURFACE (find_surface_with_tag() above)
       carrying `activity_tag` -- lets one specific zone on a
       multi-function prop (e.g. a kitchen counter's prep zone vs. its
       built-in stove/oven zones) win independently of the others.
    2. A real, distance-sorted prop whose WHOLE template/instance tags
       carry `activity_tag` (unchanged from before surfaces existed).
    3. The plain nearest-free-anchor search (unchanged behavior) when
       nothing tagged is close enough or nothing is tagged at all.

    Returns a (prop, anchor_or_None) tuple, or None if nothing usable
    exists either way. `anchor` is None for a tag-matched prop with no
    matching anchor of `fallback_interaction` (still a real, usable
    surface -- callers that only need proximity, not an anchor point,
    can ignore it).
    """
    surface_matches = [
        (prop, surface, wx, wy)
        for prop, surface, wx, wy in find_surface_with_tag(world, activity_tag)
        if abs(c.get("x", 0) - wx) + abs(c.get("y", 0) - wy) <= PREFERRED_SURFACE_RADIUS
    ]
    if surface_matches:
        surface_matches.sort(key=lambda m: abs(c.get("x", 0) - m[2]) + abs(c.get("y", 0) - m[3]))
        best_prop = surface_matches[0][0]
        anchor = None
        if fallback_interaction:
            for a in get_anchors_by_interaction(best_prop, fallback_interaction):
                anchor = a
                break
            if anchor:
                for a in best_prop.get("anchors", []):
                    if a.get("name") == anchor.get("name"):
                        anchor = a
                        break
        return (best_prop, anchor)

    tagged = [
        p for p in props_with_tag(world, activity_tag)
        if prop_distance(c, p) <= PREFERRED_SURFACE_RADIUS
    ]

    if tagged:
        tagged.sort(key=lambda p: prop_distance(c, p))
        best = tagged[0]
        anchor = None
        if fallback_interaction:
            for a in get_anchors_by_interaction(best, fallback_interaction):
                anchor = a
                break
            # get_anchors_by_interaction returns world-projected copies --
            # find the real anchor dict (matching find_nearest_anchor's
            # own reasoning) so a caller that reserves it mutates the
            # genuine object, not a throwaway copy.
            if anchor:
                for a in best.get("anchors", []):
                    if a.get("name") == anchor.get("name"):
                        anchor = a
                        break
        return (best, anchor)

    if fallback_interaction:
        return find_nearest_free_anchor(c, world, fallback_interaction)

    return None
