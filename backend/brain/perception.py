import math


# =========================================================
# DISTANCE
# =========================================================

def manhattan(a, b):

    return (
        abs(a["x"] - b["x"])
        +
        abs(a["y"] - b["y"])
    )


# =========================================================
# VISUAL RANGE
# =========================================================

def visual_range(c, world):

    if c.get("inside"):
        return 8

    return 14


# =========================================================
# HEARING RANGE
# =========================================================

def hearing_range(c):

    return 10


# =========================================================
# LINE OF SIGHT
# =========================================================

def line_of_sight(a, b, world):

    x0, y0 = a["x"], a["y"]
    x1, y1 = b["x"], b["y"]

    dx = abs(x1 - x0)
    dy = abs(y1 - y0)

    x, y = x0, y0

    n = 1 + dx + dy

    x_inc = 1 if x1 > x0 else -1
    y_inc = 1 if y1 > y0 else -1

    error = dx - dy

    dx *= 2
    dy *= 2

    blockers = set()

    # =====================================
    # PROP LOS BLOCKERS
    # =====================================

    for p in world.get(
        "props",
        []
    ):

        if p.get("blocks_los"):

            blockers.add(
                (
                    p["x"],
                    p["y"]
                )
            )

    # =====================================
    # CLOSED DOORS
    # =====================================

    for bld in world.get(
        "buildings",
        []
    ):

        for d in bld.get(
            "doors",
            []
        ):

            if not d.get(
                "is_open",
                True
            ):

                blockers.add(
                    (
                        d["x"],
                        d["y"]
                    )
                )

    for _ in range(n):

        if (x, y) in blockers:
            return False

        if error > 0:

            x += x_inc
            error -= dy

        else:

            y += y_inc
            error += dx

    return True


# =========================================================
# PERCEIVED EMOTION
# =========================================================

def perceived_emotion(other):

    emotion = other.get(
        "emotion",
        "neutral"
    )

    mapping = {

        "angry":
            "tense",

        "fear":
            "anxious",

        "sad":
            "withdrawn",

        "happy":
            "positive",

        "calm":
            "relaxed"
    }

    return mapping.get(
        emotion,
        "neutral"
    )


# =========================================================
# CHARACTER VISIBILITY SCORE
# =========================================================

def visibility_score(

    c,

    other,

    world
):

    d = manhattan(c, other)

    base = max(
        0,
        1 - (
            d / visual_range(
                c,
                world
            )
        )
    )

    if other.get(
        "current_speech"
    ):

        base += 0.2

    if other.get(
        "emotion"
    ) in [

        "angry",

        "fear"

    ]:

        base += 0.15

    return min(
        1,
        base
    )


# =========================================================
# VISIBLE PEOPLE
# =========================================================

def perceive_people(

    c,

    world,

    max_people=8
):

    results = []

    vrange = visual_range(
        c,
        world
    )

    for other in world.get(
        "characters",
        {}
    ).values():

        if other["id"] == c["id"]:
            continue

        if other.get("off_grid"):
            continue

        d = manhattan(
            c,
            other
        )

        if d > vrange:
            continue

        if not line_of_sight(
            c,
            other,
            world
        ):
            continue

        vis = visibility_score(
            c,
            other,
            world
        )

        results.append({

            "id":
                other["id"],

            "name":
                other.get(
                    "name"
                ),

            "distance":
                d,

            "visibility":
                vis,

            "appears":
                perceived_emotion(
                    other
                ),

            "activity":
                other.get(
                    "activity",
                    {}
                ).get(
                    "type"
                ),

            "speaking":
                bool(
                    other.get(
                        "current_speech"
                    )
                )
        })

    results.sort(

        key=lambda x: (

            x["visibility"]
            -
            x["distance"] * 0.05
        ),

        reverse=True
    )

    return results[:max_people]


# =========================================================
# AUDIBLE EVENTS
# =========================================================

def perceive_audio(

    c,

    world
):

    heard = []

    hrange = hearing_range(c)

    for other in world.get(
        "characters",
        {}
    ).values():

        if other["id"] == c["id"]:
            continue

        speech = other.get(
            "current_speech"
        )

        if not speech:
            continue

        d = manhattan(
            c,
            other
        )

        if d > hrange:
            continue

        heard.append({

            "type":
                "speech",

            "speaker":
                other["name"],

            "topic":
                speech.get(
                    "topic"
                ),

            "tone":
                speech.get(
                    "speech_act"
                ),

            "distance":
                d
        })

    return heard


# =========================================================
# VISIBLE PROPS
# =========================================================

def perceive_props(

    c,

    world,

    max_props=12
):

    results = []

    vrange = visual_range(
        c,
        world
    )

    for p in world.get(
        "props",
        []
    ):

        d = abs(
            p["x"] - c["x"]
        ) + abs(
            p["y"] - c["y"]
        )

        if d > vrange:
            continue

        results.append({

            "id":
                p["id"],

            "template":
                p.get(
                    "template"
                ),

            "category":
                p.get(
                    "category"
                ),

            "distance":
                d
        })

    results.sort(
        key=lambda x: x["distance"]
    )

    return results[:max_props]


# =========================================================
# ENVIRONMENT
# =========================================================

def perceive_environment(

    c,

    world
):

    return {

        "location":
            c.get(
                "building_id"
            ),

        "room":
            c.get(
                "room_id"
            ),

        "tick":
            world.get(
                "tick"
            ),

        "weather":
            world.get(
                "weather"
            ),

        "time_of_day":
            world.get(
                "time_of_day"
            )
    }


# =========================================================
# FOCUS SELECTION
# =========================================================

def select_focus(

    perception
):

    people = perception.get(
        "visible_people",
        []
    )

    if people:
        return {

            "type":
                "person",

            "target":
                people[0]["id"]
        }

    audio = perception.get(
        "audible_events",
        []
    )

    if audio:
        return {

            "type":
                "sound",

            "target":
                audio[0]
        }

    return None


# =========================================================
# MAIN
# =========================================================

def perceive(

    c,

    world
):

    perception = {

        "visible_people":
            perceive_people(
                c,
                world
            ),

        "audible_events":
            perceive_audio(
                c,
                world
            ),

        "visible_props":
            perceive_props(
                c,
                world
            ),

        "environment":
            perceive_environment(
                c,
                world
            ),

        "news":
            world.get(
                "news_feed",
                []
            )[-5:],

        "events":
            world.get(
                "active_events",
                []
            )[-5:]
    }

    perception["focus"] = select_focus(
        perception
    )

    c["perception"] = perception

    return perception