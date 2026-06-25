# =====================================================
# GENERIC TEMPLATE LOOKUP
# =====================================================

def get_template(
    world,
    category,
    template_id
):

    return (
        world
        .get("definitions", {})
        .get(category, {})
        .get(template_id)
    )


# =====================================================
# PROP TEMPLATES
# =====================================================

def get_prop_template(world, prop):

    return get_template(
        world,
        "prop_templates",
        prop.get("template")
    )


# =====================================================
# ITEM TEMPLATES
# =====================================================

def get_item_template(world, item):

    return get_template(
        world,
        "item_templates",
        item.get("template")
    )


# =====================================================
# CHARACTER TEMPLATES
# =====================================================

def get_character_template(world, character):

    return get_template(
        world,
        "character_templates",
        character.get("template")
    )


# =====================================================
# INTERACTION TEMPLATES
# =====================================================

def get_interaction_template(
    world,
    interaction_name
):

    return get_template(
        world,
        "interaction_templates",
        interaction_name
    )


# =====================================================
# ACTIVITY TEMPLATES
# =====================================================

def get_activity_template(
    world,
    activity_name
):

    return get_template(
        world,
        "activity_templates",
        activity_name
    )


# =====================================================
# TILE TEMPLATES
# =====================================================

def get_tile_template(
    world,
    tile_name
):

    return get_template(
        world,
        "tile_templates",
        tile_name
    )

# =====================================================
# MERGED TEMPLATE + INSTANCE
# =====================================================

def resolve_instance(

    world,

    category,

    instance
):

    template = get_template(

        world,

        category,

        instance.get("template")
    )

    if not template:

        return instance

    return {

        **template,

        **instance
    }

    # =====================================================
# RESOLVED PROP
# =====================================================

def resolve_prop(
    world,
    prop
):

    return resolve_instance(

        world,

        "prop_templates",

        prop
    )


# =====================================================
# RESOLVED CHARACTER
# =====================================================

def resolve_character(
    world,
    character
):

    return resolve_instance(

        world,

        "character_templates",

        character
    )


# =====================================================
# RESOLVED ITEM
# =====================================================

def resolve_item(
    world,
    item
):

    return resolve_instance(

        world,

        "item_templates",

        item
    )

# =====================================================
# FLOORPLAN TEMPLATE
# =====================================================

def get_floorplan_template(
    world,
    building
):

    return get_template(

        world,

        "floorplan_templates",

        building.get("template")
    )


# =====================================================
# RESOLVED FLOORPLAN
# =====================================================

def resolve_floorplan(
    world,
    building
):

    return resolve_instance(

        world,

        "floorplan_templates",

        building
    )