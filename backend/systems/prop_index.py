PROP_INDEX = {}
PROP_LOOKUP = {}

# =========================================================
# BUILD PROP INDEX
# =========================================================
# =========================================================
# REMOVE PROP FROM INDEX
# =========================================================

def remove_prop_from_index(

    sim_id,

    prop_id
):

    sim_index = PROP_INDEX.get(
        sim_id,
        {}
    )

    lookup = PROP_LOOKUP.get(
        sim_id,
        {}
    )

    old_prop = lookup.get(prop_id)

    if not old_prop:
        return

    tags = old_prop.get(
        "_tags",
        []
    )

    for tag in tags:

        if tag not in sim_index:
            continue

        sim_index[tag] = [

            p for p in sim_index[tag]

            if p["id"] != prop_id
        ]

    del lookup[prop_id]

# =========================================================
# INDEX SINGLE PROP
# =========================================================

def index_prop(

    sim_id,

    prop,

    definitions
):

    templates = definitions.get(
        "prop_templates",
        {}
    )

    template = templates.get(
        prop.get("template"),
        {}
    )

    tags = template.get(
        "tags",
        []
    )

    enriched = {

        **prop,

        "_template": template,

        "_tags": tags
    }

    if sim_id not in PROP_INDEX:

        PROP_INDEX[sim_id] = {}

    if sim_id not in PROP_LOOKUP:

        PROP_LOOKUP[sim_id] = {}

    # remove old copy first
    remove_prop_from_index(

        sim_id,

        prop["id"]
    )

    # add fresh
    for tag in tags:

        PROP_INDEX[sim_id].setdefault(
            tag,
            []
        )

        PROP_INDEX[sim_id][tag].append(
            enriched
        )

    PROP_LOOKUP[sim_id][
        prop["id"]
    ] = enriched

def build_prop_index(
    world,
    definitions
):

    index = {}

    templates = definitions.get(
        "prop_templates",
        {}
    )

    for prop in world.get("props", []):

        template_id = prop.get(
            "template"
        )

        template = templates.get(
            template_id,
            {}
        )

        tags = template.get(
            "tags",
            []
        )

        for tag in tags:

            if tag not in index:

                index[tag] = []

            enriched = {

                **prop,

                "_template": template,

                "_tags": tags
            }

            index[tag].append(
                enriched
            )

    return index


# =========================================================
# CACHE
# =========================================================
def cache_prop_index(
    sim_id,
    world,
    definitions
):

    PROP_INDEX[sim_id] = {}

    PROP_LOOKUP[sim_id] = {}

    for prop in world.get(
        "props",
        []
    ):

        index_prop(

            sim_id,

            prop,

            definitions
        )

# =========================================================
# QUERY
# =========================================================

def find_props_by_tag(
    sim_id,
    tag
):

    return (
        PROP_INDEX
        .get(sim_id, {})
        .get(tag, [])
    )


# =========================================================
# NEAREST
# =========================================================

def find_nearest_prop_by_tag(
    sim_id,
    tag,
    x,
    y
):

    props = find_props_by_tag(
        sim_id,
        tag
    )

    if not props:
        return None

    return min(

        props,

        key=lambda p:

        abs(p["x"] - x)
        +
        abs(p["y"] - y)
    )