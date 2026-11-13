import random


# =========================================================
# ENSURE DESIRES
# =========================================================

def ensure_desires(c):

    c.setdefault(
        "persistent_desires",
        []
    )


# =========================================================
# ADD DESIRE
# =========================================================

def add_desire(

    c,

    desire_type,

    target=None,

    importance=0.5
):

    ensure_desires(c)

    # =====================================================
    # DUPLICATE CHECK
    # =====================================================

    for d in c[
        "persistent_desires"
    ]:

        if (

            d["type"]
            ==
            desire_type

            and

            d.get("target")
            ==
            target
        ):

            d["importance"] = max(

                d["importance"],

                importance
            )

            return d

    desire = {

        "type":
            desire_type,

        "target":
            target,

        "importance":
            importance,

        "frustration":
            0.0,

        "progress":
            0.0,

        "resolved":
            False,

        "active":
            True
    }

    c[
        "persistent_desires"
    ].append(desire)

    return desire


# =========================================================
# UPDATE DESIRES
# =========================================================

# Unmet persistent desires grow more frustrating over time, and once frustration passes 0.5 they also grow in
# importance. Lazy values of sim time (core/clock.now_ts): brought up to date whenever they are refreshed, with the
# same result however often that is. (They used to grow by a random 0.00001-0.00008 per tick; FRUSTRATION_PER_SECOND
# is that mean, per sim second at the default one tick per second.)
FRUSTRATION_PER_SECOND = 0.000045
IMPORTANCE_PER_SECOND = 0.00002          # while frustration is above 0.5


def update_desires(
    c,
    world
):
    """Bring every unresolved desire up to now (see refresh_desires)."""
    refresh_desires(c, world)


def refresh_desires(c, world):
    from core.clock import now_ts
    ensure_desires(c)
    now = now_ts(world)
    last = c.get("_desires_ts")
    c["_desires_ts"] = now
    if last is None or now <= last:
        return
    for desire in c["persistent_desires"]:
        if desire.get("resolved"):
            continue
        update_desire(c, desire, world, now - last)


def update_desire(
    c,
    desire,
    world,
    dt=1.0
):
    """Advance one desire by dt sim seconds: frustration rises at FRUSTRATION_PER_SECOND (to at most 1), importance at
    IMPORTANCE_PER_SECOND for the part of dt spent with frustration above 0.5."""
    f0 = desire.get("frustration", 0.0)
    f1 = min(1.0, f0 + FRUSTRATION_PER_SECOND * dt)
    desire["frustration"] = f1
    if f1 > 0.5:
        above = dt if f0 > 0.5 else dt - (0.5 - f0) / FRUSTRATION_PER_SECOND
        desire["importance"] = min(1.0, desire.get("importance", 0.0) + IMPORTANCE_PER_SECOND * max(0.0, above))


# =========================================================
# RESOLVE DESIRE
# =========================================================

def resolve_desire(

    c,

    desire_type,

    target=None
):

    for d in c.get(
        "persistent_desires",
        []
    ):

        if d["type"] != desire_type:
            continue

        if d.get(
            "target"
        ) != target:

            continue

        d["resolved"] = True
        d["active"] = False

        return d

    return None


# =========================================================
# ACTIVE DESIRES
# =========================================================

def active_desires(c):

    return [

        d

        for d in c.get(
            "persistent_desires",
            []
        )

        if not d.get(
            "resolved"
        )
    ]