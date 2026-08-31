# =========================================================
# HOBBIES
#
# Manages character hobbies and the social-planning pipeline
# for hobbies that require multiple participants.
#
# Planning flow for group hobbies:
#   1. Character has a hobby intention with min_participants > 1
#   2. An "organize_hobby_session" intention is injected,
#      prompting the character to go to the computer or phone
#   3. The LLM routes this to social media / messaging
#   4. plan_hobby_session() creates a social_event draft,
#      inviting contacts who share the same hobby first,
#      falling back to the general social network
#
# home_props_any: having ANY ONE prop tag from this list lets
#   the character do the hobby at home; otherwise they go
#   off_grid to `location`.
# =========================================================

import random
import time


# ----------------------------------------------------------
# HOBBY ASSIGNMENT
# ----------------------------------------------------------

def assign_hobbies(c, world, count=3):
    """
    Assign `count` random hobby_template IDs to a character.
    Skips hobbies that require more participants than the
    household + a few friends could realistically provide.
    """
    defs            = world.get("definitions", {})
    hobby_templates = defs.get("hobby_templates", {})
    if not hobby_templates:
        return

    eligible = [
        hid for hid, h in hobby_templates.items()
        if h.get("min_participants", 1) <= 12
    ]
    chosen      = random.sample(eligible, min(count, len(eligible)))
    c["hobbies"] = chosen

    from systems.sports import sync_sports_hobbies
    sync_sports_hobbies(c, world)

    from systems.crime import sync_gun_hobbies
    sync_gun_hobbies(c, world)


# ----------------------------------------------------------
# LOCATION RESOLUTION
# ----------------------------------------------------------

def resolve_hobby_location(c, world, hobby_id):
    """
    Return (at_home: bool, location: str|None).
    Checks household props against home_props_any; if the
    household has at least one match the character stays home.
    """
    defs  = world.get("definitions", {})
    hobby = defs.get("hobby_templates", {}).get(hobby_id)
    if not hobby:
        return True, None

    home_props_any = hobby.get("home_props_any", [])
    if not home_props_any:
        at_home = not hobby.get("off_grid", False)
        return at_home, hobby.get("location") if not at_home else None

    placed = world.get("placed_items", {})
    for prop in placed.values():
        for tag in prop.get("tags", []):
            if tag in home_props_any:
                return True, None

    return False, hobby.get("location")


# ----------------------------------------------------------
# FIND HOBBY-COMPATIBLE CONTACTS
# ----------------------------------------------------------

def find_hobby_contacts(c, world, hobby_id, max_results=10):
    """
    Return a list of character IDs who share `hobby_id`,
    ordered by relationship strength (known contacts first).
    Falls back to all known contacts if no one shares the hobby.
    """
    known_ids = set(c.get("relationships", {}).keys())
    sharers   = []
    others    = []

    for other in world.get("characters", {}).values():
        if other["id"] == c["id"] or other.get("is_service_worker"):
            continue
        if hobby_id in other.get("hobbies", []):
            sharers.append(other["id"])
        elif other["id"] in known_ids:
            others.append(other["id"])

    # Shuffle both pools independently
    random.shuffle(sharers)
    random.shuffle(others)

    # Prioritise sharers; pad with known contacts if needed
    combined = sharers + others
    return combined[:max_results]


# ----------------------------------------------------------
# INTENTION INJECTION — ORGANIZE A SESSION
# ----------------------------------------------------------

def inject_organize_intention(c, world, hobby_id):
    """
    Inject an 'organize_hobby_session' intention so the
    character goes online (computer or phone) to plan a
    gathering. Only injects if not already present.
    """
    for intent in c.get("active_intentions", []):
        if (intent.get("type") == "organize_hobby_session"
                and intent.get("hobby_id") == hobby_id):
            return   # already queued

    defs  = world.get("definitions", {})
    hobby = defs.get("hobby_templates", {}).get(hobby_id, {})

    c.setdefault("active_intentions", []).append({
        "type":        "organize_hobby_session",
        "priority":    60,
        "source":      "hobby",
        "hobby_id":    hobby_id,
        "hobby_name":  hobby.get("name", hobby_id),
        "reason":      (
            hobby.get("name", hobby_id)
            + " needs at least "
            + str(hobby.get("min_participants", 2))
            + " participants — go online to invite people who enjoy it."
        ),
    })


# ----------------------------------------------------------
# SOCIAL PLANNING FOR GROUP HOBBIES
# ----------------------------------------------------------

def plan_hobby_session(c, world, hobby_id, start_offset_hours=48):
    """
    Create a social_event draft for a group hobby session.
    Invitees are contacts who share the hobby first; falls back
    to the general social network if not enough sharers are found.
    The character is expected to reach out via computer or phone
    before calling this (intention: organize_hobby_session).
    """
    from systems.social_events import create_event_draft

    defs  = world.get("definitions", {})
    hobby = defs.get("hobby_templates", {}).get(hobby_id)
    if not hobby:
        return None

    min_p = hobby.get("min_participants", 1)
    if min_p <= 1:
        return None

    # Contacts who share the hobby (+ fallback)
    contacts = find_hobby_contacts(c, world, hobby_id, max_results=20)
    needed   = min_p - 1           # already counting the initiator
    invitees = contacts[:needed]

    # Duration
    if hobby.get("overnight"):
        days       = hobby.get("min_days") or 1
        duration_s = days * 86400
    else:
        duration_s = 3 * 3600      # 3 h default

    now      = time.time()
    start_ts = now + start_offset_hours * 3600
    end_ts   = start_ts + duration_s

    # Location / type
    at_home, loc = resolve_hobby_location(c, world, hobby_id)
    if at_home:
        location      = "home"
        location_type = "home"
    else:
        location      = loc or hobby.get("location") or "venue"
        location_type = "outdoor" if hobby.get("off_grid") else "venue"

    prep = (hobby.get("required_items") or [])[:3]

    evt = create_event_draft(
        c, world,
        title             = hobby["name"] + " session",
        category          = "hobby_session",
        description       = (
            "Come join me for "
            + hobby["name"]
            + ". We need at least "
            + str(min_p)
            + " people."
        ),
        location          = location,
        location_type     = location_type,
        start_ts          = start_ts,
        end_ts            = end_ts,
        co_organizers     = invitees,
        prep_requirements = prep,
        dress_code        = None,
        tags              = [hobby["category"], "hobby", hobby_id],
    )
    return evt


# ----------------------------------------------------------
# CONTEXT HELPER
# ----------------------------------------------------------

def build_hobby_context(c, world):
    """
    LLM context: character's hobbies + planning status.
    """
    defs            = world.get("definitions", {})
    hobby_templates = defs.get("hobby_templates", {})
    result          = []

    for hid in c.get("hobbies", []):
        h = hobby_templates.get(hid)
        if not h:
            continue
        at_home, loc = resolve_hobby_location(c, world, hid)
        entry = {
            "id":               hid,
            "name":             h["name"],
            "category":         h["category"],
            "at_home":          at_home,
            "location":         loc,
            "min_participants": h.get("min_participants", 1),
            "needs_planning":   h.get("suggest_to_household", False),
            "off_grid":         h.get("off_grid", False),
            "overnight":        h.get("overnight", False),
        }
        if h.get("overnight"):
            entry["trip_days"] = "{}-{}".format(
                h.get("min_days", 1), h.get("max_days", 1)
            )
        # Surface how many contacts share this hobby
        sharers = find_hobby_contacts(c, world, hid, max_results=5)
        if sharers:
            chars  = world.get("characters", {})
            entry["known_participants"] = [
                chars[sid]["name"]
                for sid in sharers
                if sid in chars
            ]
        result.append(entry)

    return result


# ----------------------------------------------------------
# HOBBY GUEST NPCS
# Temporary characters that arrive for at-home hobby sessions,
# analogous to service worker NPCs. They are spawned when the
# session event's start_ts is reached and removed at end_ts.
# ----------------------------------------------------------

import uuid

_GUEST_NAMES = [
    "Sam", "Riley", "Jordan", "Casey", "Morgan", "Alex", "Taylor",
    "Jamie", "Drew", "Quinn", "Parker", "Avery", "Skylar", "Reese",
    "Blair", "Emery", "Sage", "Rowan", "Harley", "Finley",
]


def spawn_hobby_guests(world, evt):
    """
    Spawn temporary NPC guests for an at-home hobby session.
    Called when evt["start_ts"] is reached.
    Skips if guests already spawned (guest_ids present on event).
    """
    if evt.get("hobby_guests_spawned"):
        return

    hobby_id  = None
    for tag in evt.get("tags", []):
        defs = world.get("definitions", {})
        if tag in defs.get("hobby_templates", {}):
            hobby_id = tag
            break

    # Find the initiator's home position
    initiator = world.get("characters", {}).get(evt.get("initiator", ""))
    if not initiator:
        return

    home_x = initiator.get("x", 5)
    home_y = initiator.get("y", 5)

    # Spawn one guest per confirmed attendee (excluding initiator)
    attendees    = evt.get("attendees", {})
    guest_ids    = []
    spawned_names = set()

    for participant_id, rsvp in attendees.items():
        if rsvp != "yes" or participant_id == evt["initiator"]:
            continue
        # If participant exists as a real character, don't spawn a ghost
        if participant_id in world.get("characters", {}):
            continue

        name = random.choice([n for n in _GUEST_NAMES if n not in spawned_names] or _GUEST_NAMES)
        spawned_names.add(name)

        gid = "guest_{}_{}".format(evt["id"][:6], uuid.uuid4().hex[:4])
        world.setdefault("characters", {})[gid] = {
            "id":               gid,
            "name":             name,
            "x":                home_x + random.uniform(-3, 3),
            "y":                home_y - 4,     # approach from outside
            "rotation":         0,
            "facing":           "south",
            "template":         "adult_base",
            "is_hobby_guest":   True,
            "hobby_session_id": evt["id"],
            "hobby_id":         hobby_id,
            "animation_state":  {"base": "walk", "upper": None},
            "body": {
                "hunger": 30, "hydration": 75, "bladder": 10, "bowels": 5,
                "fatigue": 15, "sleep_debt": 0, "hygiene": 90, "odor": 0,
                "mouth_hygiene": 90, "recent_intake": 20,
                "stomach_discomfort": 0, "pain": 0, "sickness": 0,
            },
            "hobbies":           [hobby_id] if hobby_id else [],
            "traits":            ["friendly"],
            "inventory":         [],
            "worn":              {},
            "money":             0.0,
            "active_intentions": [],
            "relationships":     {},
        }
        guest_ids.append(gid)

    evt["hobby_guests_spawned"] = True
    evt["guest_ids"]            = guest_ids


def despawn_hobby_guests(world, evt):
    """
    Remove all hobby guest NPCs for a session that has ended.
    """
    for gid in evt.get("guest_ids", []):
        world.get("characters", {}).pop(gid, None)
    evt["guest_ids"] = []


# ----------------------------------------------------------
# SESSION LIFECYCLE CHECK
# ----------------------------------------------------------

def check_hobby_sessions(world):
    """
    Called periodically from sim_loop. Manages hobby session
    event lifecycle:
      - start_ts reached + location==home  → spawn guests
      - end_ts reached                     → despawn guests
    """
    now    = time.time()
    events = world.get("social_events", {})

    for evt in list(events.values()):
        if evt.get("category") != "hobby_session":
            continue
        if evt.get("status") != "published":
            continue

        start_ts = evt.get("start_ts", 0)
        end_ts   = evt.get("end_ts", 0)
        loc_type = evt.get("location_type", "")

        # Spawn guests when session starts and it's at home
        if (now >= start_ts
                and loc_type == "home"
                and not evt.get("hobby_guests_spawned")):
            spawn_hobby_guests(world, evt)

        # Despawn when session ends
        if end_ts and now >= end_ts and evt.get("hobby_guests_spawned"):
            despawn_hobby_guests(world, evt)
            evt["status"] = "completed"
