

from systems.templates import get_prop_template

from systems.transforms import (
    transform_footprint
)

from systems.anchors import (
    get_world_anchor
)
# =========================
# GRID NEIGHBORS
# =========================
def neighbors(x, y):

    return [
        (x + 1, y),
        (x - 1, y),
        (x, y + 1),
        (x, y - 1)
    ]


# =========================
# FOOTPRINT → WORLD TILES
# =========================

def get_prop_tiles(

    world,

    prop
):

    template = get_prop_template(
        world,
        prop
    )

    if not template:

        return [(
            prop["x"],
            prop["y"]
        )]

    footprint = template.get(

        "footprint",

        [{
            "dx": 0,
            "dy": 0
        }]
    )

    rotation = prop.get(
        "rotation",
        0
    )

    return transform_footprint(

        prop["x"],

        prop["y"],

        footprint,

        rotation
    )


# =========================
# ANCHOR CHECK
# =========================
def is_anchor_tile(x, y, world):

    for p in world.get(
        "props",
        []
    ):

        for a in p.get(
            "anchors",
            []
        ):

            wa = get_world_anchor(
                p,
                a
            )

            if (
                x,
                y
            ) == (
                wa["x"],
                wa["y"]
            ):
                return True

    return False


# =========================
# BLOCKED SET
# =========================
def build_blocked_set(world):

    blocked = set()

    # -----------------
    # PROPS
    # -----------------
    for p in world.get("props", []):

        for (px, py) in get_prop_tiles(world, p):
            blocked.add((px, py))

    # -----------------
    # DOORS
    # -----------------
    for b in world.get("buildings", []):

        for d in b.get("doors", []):

            if d.get("state", "closed") != "open":
                blocked.add((d["x"], d["y"]))

    # -----------------
    # ACTIVE INTERACTIONS
    # -----------------
    for c in world.get("characters", {}).values():

        act = c.get("activity")

        if not act:
            continue

        prop_id = act.get("prop_id")
        phase = act.get("phase")

        if phase in ["start", "stop"]:

            prop = next(
                (
                    p for p in world.get("props", [])
                    if p["id"] == prop_id
                ),
                None
            )

            if not prop:
                continue

            for (px, py) in get_prop_tiles(world, prop):
                blocked.add((px, py))

    return blocked


# =========================
# WALKABILITY
# =========================
def is_walkable(x, y, world, blocked):

    # allow anchors
    if is_anchor_tile(x, y, world):
        return True

    return (x, y) not in blocked