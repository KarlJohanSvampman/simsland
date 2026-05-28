import math
import random


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
# SOUND MODIFIER
# =========================================================

def sound_modifier(

    c,

    other
):

    if c.get(
        "building_id"
    ) != other.get(
        "building_id"
    ):

        return 0.5

    if c.get(
        "room_id"
    ) != other.get(
        "room_id"
    ):

        return 0.7

    return 1.0


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
    # PROP BLOCKERS
    # =====================================

    for p in world.get(
        "props",
        []
    ):

        if p.get(
            "blocks_los"
        ):

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

    actual = other.get(
        "emotion",
        "neutral"
    )

    guesses = {

        "angry": [
            "tense",
            "agitated",
            "frustrated"
        ],

        "fearful": [
            "anxious",
            "uneasy",
            "nervous"
        ],

        "sad": [
            "withdrawn",
            "quiet",
            "low-energy"
        ],

        "calm": [
            "relaxed",
            "comfortable",
            "neutral"
        ],

        "annoyed": [
            "irritated",
            "impatient",
            "tense"
        ]
    }

    pool = guesses.get(
        actual,
        ["neutral"]
    )

    return random.choice(pool)


# =========================================================
# PERCEIVED ACTIVITY
# =========================================================

def perceived_activity(other):

    activity = other.get(
        "activity",
        {}
    )

    atype = activity.get(
        "type"
    )

    if not atype:
        return None

    mapping = {

        "cook_food":
            "cooking",

        "eat":
            "eating",

        "watch_tv":
            "watching television",

        "sleep":
            "sleeping",

        "socialize":
            "talking with someone",

        "pay_bills":
            "working on paperwork",

        "sort_mail":
            "sorting through mail",

        "clean":
            "cleaning",

        "exercise":
            "exercising",

        "shop_online":
            "shopping online",

        "argue":
            "arguing",

        "wander":
            "wandering around"
    }

    return mapping.get(
        atype,
        "doing something"
    )


# =========================================================
# VISIBILITY SCORE
# =========================================================

def visibility_score(

    c,

    other,

    world
):

    d = manhattan(
        c,
        other
    )

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

    attention = c.get(
        "attention",
        {}
    )

    focus = attention.get(
        "focus"
    )

    fkey = None

    if focus:

        fkey = focus.get(
            "key"
        )

    for other in world.get(
        "characters",
        {}
    ).values():

        if other["id"] == c["id"]:
            continue

        if other.get(
            "off_grid"
        ):
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

        # =====================================
        # ATTENTION REINFORCEMENT
        # =====================================

        if fkey == f"person:{other['id']}":

            vis += 0.25

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
                round(vis, 2),

            "appears":
                perceived_emotion(
                    other
                ),

            "activity":
                perceived_activity(
                    other
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

    # =====================================
    # SPEECH
    # =====================================

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

        modifier = sound_modifier(
            c,
            other
        )

        effective = d / modifier

        if effective > hrange:
            continue

        heard.append({

            "type":
                "speech",

            "speaker":
                other.get(
                    "name"
                ),

            "topic":
                speech.get(
                    "topic"
                ),

            "tone":
                speech.get(
                    "speech_act"
                ),

            "distance":
                round(
                    effective,
                    2
                )
        })

    # =====================================
    # AMBIENT SOUNDS
    # =====================================

    for p in world.get(
        "props",
        []
    ):

        sound = p.get(
            "active_sound"
        )

        if not sound:
            continue

        d = abs(
            p["x"] - c["x"]
        ) + abs(
            p["y"] - c["y"]
        )

        if d > hrange:
            continue

        heard.append({

            "type":
                "ambient",

            "sound":
                sound,

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

    room = c.get(
        "room_id"
    )

    building = c.get(
        "building_id"
    )

    env = {

        "location":
            building,

        "room":
            room,

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

    nearby_props = 0

    clutter = 0

    for p in world.get(
        "props",
        []
    ):

        if p.get(
            "room_id"
        ) != room:
            continue

        nearby_props += 1

        if p.get(
            "is_trash"
        ):

            clutter += 1

    env["clutter"] = min(
        1,
        clutter / 10
    )

    env["crowded"] = (
        nearby_props > 25
    )

    return env


# =========================================================
# SOCIAL SCENES
# =========================================================

def perceive_social_scenes(

    c,

    world
):

    scenes = []

    for conv in world.get(
        "conversations",
        {}
    ).values():

        if not conv.get(
            "active"
        ):
            continue

        participants = []

        visible = False

        for pid in conv.get(
            "participants",
            []
        ):

            p = world.get(
                "characters",
                {}
            ).get(pid)

            if not p:
                continue

            participants.append(
                p.get("name")
            )

            d = manhattan(
                c,
                p
            )

            if d <= visual_range(
                c,
                world
            ):

                if line_of_sight(
                    c,
                    p,
                    world
                ):

                    visible = True

        if not visible:
            continue

        scenes.append({

            "type":
                "conversation",

            "topic":
                conv.get(
                    "topic"
                ),

            "tone":
                conv.get(
                    "tone"
                ),

            "participants":
                participants,

            "turn_owner":
                conv.get(
                    "turn_owner"
                ),

            "dominant":
                conv.get(
                    "dominant_speaker"
                ),

            "conflict":
                conv.get(
                    "conflict_level",
                    0
                ),

            "warmth":
                conv.get(
                    "warmth",
                    0
                )
        })

    return scenes


# =========================================================
# SOCIAL RELATIONSHIP PERCEPTION
# =========================================================

def perceive_social_relationships(

    c,

    world,

    visible_people
):

    results = []

    social = c.get(
        "social",
        {}
    )

    for p in visible_people:

        pid = p["id"]

        rel = social.get(
            pid,
            {}
        )

        tension = rel.get(
            "tension",
            0
        )

        closeness = rel.get(
            "closeness",
            0
        )

        trust = rel.get(
            "trust",
            0.5
        )

        attraction = rel.get(
            "attraction",
            0
        )

        interpretation = []

        # =====================================
        # TENSION
        # =====================================

        if tension > 0.7:

            interpretation.append(
                "relationship feels strained"
            )

        elif tension > 0.4:

            interpretation.append(
                "some tension exists"
            )

        # =====================================
        # CLOSENESS
        # =====================================

        if closeness > 0.7:

            interpretation.append(
                "you feel emotionally close"
            )

        # =====================================
        # TRUST
        # =====================================

        if trust < 0.3:

            interpretation.append(
                "you feel wary around them"
            )

        # =====================================
        # ATTRACTION
        # =====================================

        if attraction > 0.7:

            interpretation.append(
                "you feel drawn to them"
            )

        if interpretation:

            results.append({

                "target":
                    p["name"],

                "interpretation":
                    interpretation
            })

    return results


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

        strongest = max(

            people,

            key=lambda p: p.get(
                "visibility",
                0
            )
        )

        return {

            "key":
                f"person:{strongest['id']}",

            "strength":
                strongest.get(
                    "visibility",
                    0.5
                )
        }

    scenes = perception.get(
        "social_scenes",
        []
    )

    if scenes:

        s = scenes[0]

        return {

            "key":
                f"scene:{s.get('topic','conversation')}",

            "strength":
                0.5
        }

    audio = perception.get(
        "audible_events",
        []
    )

    if audio:

        return {

            "key":
                "sound:ambient",

            "strength":
                0.3
        }

    return None


# =========================================================
# MAIN PERCEPTION
# =========================================================

def perceive(

    c,

    world
):

    perception_people = perceive_people(
        c,
        world
    )

    perception = {

        "visible_people":
            perception_people,

        "social_relations":
            perceive_social_relationships(

                c,

                world,

                perception_people
            ),

        "social_scenes":
            perceive_social_scenes(
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

    perception["focus"] = (
        select_focus(
            perception
        )
    )

    c["perception"] = perception

    c["last_perception_tick"] = (
        world.get(
            "tick",
            0
        )
    )

    c["recent_perception_memory"] = (

        perception.get(
            "visible_people",
            []
        )[:5]
    )

    return perception