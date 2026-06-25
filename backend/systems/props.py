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

    if not template:
        return []

    return template.get("tags", [])


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
                "interactionName"
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

            if (

                anchor.get(
                    "interactionName"
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

                best_anchor = wa

    if not best_prop:
        return None

    return (

        best_prop,

        best_anchor
    )
    