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

    from systems.diary import sync_diary_hobby
    sync_diary_hobby(c, world)


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
    Propose a group hobby session as a real systems/social_projects.py
    project. Invitees are contacts who share the hobby first; falls back
    to the general social network if not enough sharers are found. The
    character is expected to reach out via computer or phone before
    calling this (intention: organize_hobby_session).

    Confirmed real bug in the retired systems/social_events.py version
    this replaces: it passed `invitees` as create_event_draft's
    co_organizers (which require approval before the event publishes),
    not as ordinary invited attendees -- and nothing anywhere ever called
    approve_event() (confirmed zero callers), so any hobby session with
    at least one invitee got stuck in "draft" status forever and never
    actually became visible/RSVP-able. propose_project's invitees are
    genuine invited recipients, not approval-gated co-organizers, so this
    fixes it rather than reproducing it.
    """
    from systems.social_projects import propose_project

    defs  = world.get("definitions", {})
    hobby = defs.get("hobby_templates", {}).get(hobby_id)
    if not hobby:
        return None

    min_p = hobby.get("min_participants", 1)
    if min_p <= 1:
        return None

    # Contacts who share the hobby (+ fallback)
    contact_ids = find_hobby_contacts(c, world, hobby_id, max_results=20)
    needed      = min_p - 1           # already counting the initiator
    chars       = world.get("characters", {})
    invitees    = [chars[cid] for cid in contact_ids[:needed] if cid in chars]

    # Duration
    if hobby.get("overnight"):
        days          = hobby.get("min_days") or 1
        duration_secs = days * 86400
    else:
        duration_secs = 3 * 3600      # 3 h default

    from core.tick_schedule import TICK_RATE_SECONDS
    tick       = world.get("tick", 0)
    start_tick = tick + int(start_offset_hours * 3600 / TICK_RATE_SECONDS)
    end_tick   = start_tick + int(duration_secs / TICK_RATE_SECONDS)

    # Location / type
    at_home, loc = resolve_hobby_location(c, world, hobby_id)
    if at_home:
        location      = "home"
        location_type = "home"
    else:
        location      = loc or hobby.get("location") or "venue"
        location_type = "outdoor" if hobby.get("off_grid") else "venue"

    return propose_project(
        c, world, invitees, "social_activity",
        title       = hobby["name"] + " session",
        description = (
            "Come join me for " + hobby["name"] + ". We need at least "
            + str(min_p) + " people."
        ),
        planned_start_tick = start_tick,
        planned_end_tick   = end_tick,
        location            = location,
        location_type       = location_type,
        tags                = [hobby["category"], "hobby", hobby_id],
    )


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


def spawn_hobby_guests(world, project):
    """
    Spawn temporary NPC guests for an at-home hobby session.
    Called when project["planned_start_tick"] is reached.
    Skips if guests already spawned (guest_ids present on the project).

    Ported from the retired systems/social_events.py-backed version --
    reads systems/social_projects.py's SocialProject/ProjectParticipant
    shape instead. In practice this rarely spawns anyone for a hobby
    session specifically, same as before the port: invitees always come
    from find_hobby_contacts() (real existing characters), and the
    "already a real character, don't spawn a ghost" skip below always
    applies to them -- kept faithfully rather than silently dropped,
    since a caller with genuinely unresolvable attendees could still
    reach this.
    """
    if project.get("hobby_guests_spawned"):
        return

    hobby_id  = None
    for tag in project.get("tags", []):
        defs = world.get("definitions", {})
        if tag in defs.get("hobby_templates", {}):
            hobby_id = tag
            break

    # Find the organizer's home position
    organizer = world.get("characters", {}).get(project.get("organizer_id", ""))
    if not organizer:
        return

    home_x = organizer.get("x", 5)
    home_y = organizer.get("y", 5)

    # Spawn one guest per accepted participant (excluding the organizer)
    guest_ids    = []
    spawned_names = set()

    for participant_id in project.get("participant_ids", []):
        if participant_id == project.get("organizer_id"):
            continue
        # If participant exists as a real character, don't spawn a ghost
        if participant_id in world.get("characters", {}):
            continue

        name = random.choice([n for n in _GUEST_NAMES if n not in spawned_names] or _GUEST_NAMES)
        spawned_names.add(name)

        gid = "guest_{}_{}".format(project["project_id"][:6], uuid.uuid4().hex[:4])
        # Real, resolvable character_templates id -- see systems/
        # service_npc.py. "adult_base" doesn't exist in definitions.json's
        # character_templates registry, so this real, live NPC spawn
        # silently fell back to the plain fallback-primitive renderer,
        # same bug class as services.py::_spawn_worker() / systems/
        # child_welfare.py's CPS worker (both already fixed).
        from systems.service_npc import pick_worker_template
        guest_template, guest_sex = pick_worker_template("hobby_guest")
        world.setdefault("characters", {})[gid] = {
            "id":               gid,
            "name":             name,
            "x":                home_x + random.uniform(-3, 3),
            "y":                home_y - 4,     # approach from outside
            "rotation":         0,
            "facing":           "south",
            "template":         guest_template,
            "sex":              guest_sex,
            "is_hobby_guest":   True,
            "hobby_session_id": project["project_id"],
            "hobby_id":         hobby_id,
            "animation_state":  {"base": "walk", "upper": None},
            "body": {
                "hunger": 30, "hydration": 75, "bladder": 10, "bowels": 5,
                "fatigue": 15, "sleep_debt": 0, "hygiene": 90, "odor": 0,
                "mouth_hygiene": 90, "recent_intake": 20,
                "stomach_discomfort": 0, "sickness": 0,
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

    project["hobby_guests_spawned"] = True
    project["guest_ids"]            = guest_ids


def despawn_hobby_guests(world, project):
    """
    Remove all hobby guest NPCs for a session that has ended.
    """
    for gid in project.get("guest_ids", []):
        world.get("characters", {}).pop(gid, None)
    project["guest_ids"] = []


# ----------------------------------------------------------
# SESSION LIFECYCLE CHECK
# ----------------------------------------------------------

def check_hobby_sessions(world):
    """
    Called periodically from sim_loop. Manages hobby session
    project lifecycle (systems/social_projects.py):
      - planned_start_tick reached + location_type==home → spawn guests
      - planned_end_tick reached                          → despawn guests
    """
    tick     = world.get("tick", 0)
    projects = world.get("social_projects", {})

    for project in list(projects.values()):
        if project.get("project_type") != "social_activity" or "hobby" not in project.get("tags", []):
            continue
        if project.get("status") not in ("scheduled", "active"):
            continue

        start_tick = project.get("planned_start_tick", 0) or 0
        end_tick   = project.get("planned_end_tick", 0) or 0
        loc_type   = project.get("location_type", "")

        # Spawn guests when session starts and it's at home
        if (tick >= start_tick
                and loc_type == "home"
                and not project.get("hobby_guests_spawned")):
            spawn_hobby_guests(world, project)

        # Despawn when session ends
        if end_tick and tick >= end_tick and project.get("hobby_guests_spawned"):
            despawn_hobby_guests(world, project)
            project["status"] = "completed"
            project["actual_end_tick"] = tick
