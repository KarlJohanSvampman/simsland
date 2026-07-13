import math
import random
import systems.perception.descriptions

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
# SENSE TRAITS
# =========================================================
# Plain dict constant, mirroring this file's own _ANCHOR_TAGS and
# reactions.py's REACTION_PRIORITIES — not a new JSON registry.
# definitions.json's trait_templates key exists but is currently empty and
# is for personality traits (c["traits"]), a different purpose from
# sense-related physical traits (c["physical_traits"]).

SENSE_TRAIT_MODIFIERS = {
    "poor_eyesight":  {"vision": 0.6},
    "keen_eyesight":  {"vision": 1.3},
    "poor_hearing":   {"hearing": 0.6},
    "keen_hearing":   {"hearing": 1.3},
}


def _sense_modifier(c, sense):
    """Multiply together every physical_traits modifier for the given
    sense ("vision" or "hearing"). Characters with no matching trait get
    the neutral 1.0 multiplier."""

    modifier = 1.0

    for trait in c.get("physical_traits", []):

        modifier *= SENSE_TRAIT_MODIFIERS.get(trait, {}).get(sense, 1.0)

    return modifier


# =========================================================
# NIGHT
# =========================================================
# Same day/night bucketing _build_room_summary() already uses for its
# time-of-day label, so "night" means the same thing everywhere in the
# narrative.

def _is_night(world):

    hour = world.get("calendar", {}).get("hour", 12)

    return hour < 6 or hour >= 21


# =========================================================
# VISUAL RANGE
# =========================================================

def visual_range(c, world):

    # c.get("inside") is never written anywhere in this codebase — always
    # falsy, so this branch never fired and every character got the
    # outdoor range regardless of actually being indoors. building_id is
    # the one live-maintained spatial field (movement.py, room_assignment.py).
    indoors = bool(c.get("building_id"))

    base = 8 if indoors else 14

    if _is_night(world):
        # No lighting/lamp-state system exists to model per-room darkness,
        # so this is a flat reduction rather than lit/unlit per room — a
        # deliberate simplification, not a hidden gap.
        base *= 0.55 if indoors else 0.35

    return base * _sense_modifier(c, "vision")


# =========================================================
# HEARING RANGE
# =========================================================

def hearing_range(c):

    return 10 * _sense_modifier(c, "hearing")


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

def perceived_emotion(observer, other):
    """Return a stable perceived emotion label for 'other' as seen by 'observer'.
    Uses a deterministic hash of the two character IDs so the reading doesn't
    flicker every tick, while still producing slightly varied descriptions."""

    actual = other.get("emotion", "neutral")

    guesses = {
        "angry":    ["tense", "agitated", "frustrated"],
        "fearful":  ["anxious", "uneasy", "nervous"],
        "sad":      ["withdrawn", "quiet", "low-energy"],
        "calm":     ["relaxed", "comfortable", "neutral"],
        "annoyed":  ["irritated", "impatient", "tense"],
    }

    pool = guesses.get(actual, [actual])

    # Stable index: hash of (observer_id, other_id, emotion) so it only
    # changes when the actual emotion changes, not every tick.
    key = f"{observer.get('id','')}:{other.get('id','')}:{actual}"
    idx = hash(key) % len(pool)
    return pool[idx]


# =========================================================
# PERCEIVED ACTIVITY
# =========================================================

def perceived_activity(other):
    """Return a human-readable description of what 'other' is doing.
    Checks the interaction field first (new system), then the activity
    type (legacy), so both paths produce meaningful descriptions."""

    # Posture overlay — leaning has no activity dict
    if other.get("posture") == "leaning_wall":
        return "leaning against the wall"

    activity = other.get("activity") or {}
    if not activity:
        return None

    # Prefer the specific interaction name (watch_tv, sit, cook, etc.)
    # over the generic activity type (interact, eat, sleep).
    key = (
        activity.get("interaction")
        or activity.get("type")
    )

    if not key:
        return None

    phase = activity.get("phase", "using")

    mapping = {
        # --- interactions (new system) ---
        "watch_tv":     "watching television",
        "sit":             "sitting down",
        "sit_down_seat":   "sitting down",
        "lie_down":        "lying down",
        "lean_against_wall": "leaning against the wall",
        "sleep":        "sleeping",
        "cook":         "cooking",
        "eat":          "eating",
        "take_shower":  "taking a shower",
        "use_toilet":   "using the bathroom",
        "brush_teeth":  "brushing their teeth",
        "wash_hands":   "washing their hands",
        "use_computer": "using a computer",
        "read":         "reading",
        "work":         "working",
        "exercise":     "exercising",
        "clean":        "cleaning",
        "clean_floor":  "mopping the floor",
        "scrub":        "scrubbing",
        "wipe":         "wiping surfaces",
        "wash_dishes":  "washing dishes",
        "examine":      "examining something",
        "search":       "searching through something",
        "carry":        "carrying something",
        "socialize":    "talking with someone",
        "phone":        "on the phone",
        # --- legacy activity types ---
        "cook_food":    "cooking",
        "pay_bills":    "working on paperwork",
        "sort_mail":    "sorting through mail",
        "shop_online":  "shopping online",
        "argue":        "arguing",
        "wander":       "wandering around",
        "conversation": "having a conversation",
        "interact":     "doing something",
        "wait":         "waiting",
    }

    description = mapping.get(key)
    if not description:
        return "doing something"

    # Prefix walking phase so it reads naturally
    if phase == "walking":
        return f"walking somewhere to {description.replace('doing something', 'do something')}"

    return description


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
                    c,
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
# PROP SEMANTIC TAGS
# =========================================================

# Maps anchor name prefixes to human-readable affordance tags
_ANCHOR_TAGS = {
    "anchor_sit":       "seatable",
    "anchor_sleep":     "sleepable",
    "anchor_cook":      "cookable",
    "anchor_eat":       "eatable",
    "anchor_watch":     "watchable",
    "anchor_use":       "usable",
    "anchor_work":      "workable",
    "anchor_shower":    "shower",
    "anchor_toilet":    "toilet",
    "anchor_open":      "openable",
    "anchor_read":      "readable",
    "anchor_exercise":  "exercise",
}


def build_prop_tags(prop, definitions):
    """
    Derive semantic tags for a prop from its template definition.
    Returns a list of plain-English tag strings the LLM can reason over.
    """
    tags = []
    template_id = prop.get("template")
    tpl = (
        definitions
        .get("prop_templates", {})
        .get(template_id, {})
    )

    # --- category ---
    category = tpl.get("category") or prop.get("category")
    if category:
        tags.append(category)

    # --- anchor-derived affordances ---
    interactions = []
    for anchor in tpl.get("anchors", []):
        aname = anchor.get("name", "")
        interaction = anchor.get("interaction")
        if interaction:
            interactions.append(interaction)
        for prefix, tag in _ANCHOR_TAGS.items():
            if aname.startswith(prefix):
                if tag not in tags:
                    tags.append(tag)
                break

    # --- storage ---
    storage = tpl.get("storage")
    if storage:
        accepted = storage.get("accepted_categories", [])
        if "food" in accepted or "drink" in accepted:
            tags.append("food_storage")
        else:
            tags.append("storage")

    # --- occupancy ---
    occupied_by = prop.get("occupied_by")
    if occupied_by:
        tags.append("occupied")
    else:
        tags.append("free")

    return tags, interactions


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

    definitions = world.get("definitions", {})

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

        tags, interactions = build_prop_tags(p, definitions)

        results.append({
            "id":           p["id"],
            "template":     p.get("template"),
            "distance":     round(d, 1),
            "tags":         tags,
            "interactions": interactions,
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

    # --- semantic room summary for LLM ---
    env["room_summary"] = _build_room_summary(
        c, world, env
    )

    return env


def _build_room_summary(c, world, env):
    """
    One-sentence natural language description of the immediate environment.
    Keeps the LLM oriented without forcing it to parse raw field names.
    """
    cal = world.get("calendar", {})
    hour = cal.get("hour", 12)
    if hour < 6:
        time_label = "in the middle of the night"
    elif hour < 12:
        time_label = "in the morning"
    elif hour < 17:
        time_label = "in the afternoon"
    elif hour < 21:
        time_label = "in the evening"
    else:
        time_label = "late at night"

    room = env.get("room") or "a room"
    location = env.get("location") or "somewhere"

    parts = [f"It is {time_label}."]
    parts.append(f"You are in {room} at {location}.")

    if env.get("clutter", 0) > 0.5:
        parts.append("The place is quite messy.")
    if env.get("crowded"):
        parts.append("It feels crowded.")

    weather = env.get("weather")
    if weather:
        parts.append(f"Outside it is {weather}.")

    return " ".join(parts)


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

    visible_people = []

    for other in perception_people:

        target = (
            world["characters"]
            .get(other["id"])
        )

        if not target:
            continue

        enriched = dict(other)

        enriched["description"] = (
            build_visible_person_description(
                c,
                target,
                world.get(
                    "definitions",
                    {}
                )
            )
        )

        # Include body snapshot so context_builder can surface odor/breath cues
        enriched["body"] = {
            "odor":          target.get("body", {}).get("odor", 0),
            "mouth_hygiene": target.get("body", {}).get("mouth_hygiene", 100),
        }

        visible_people.append(
            enriched
        )

    perception = {

        "visible_people":
            visible_people,

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