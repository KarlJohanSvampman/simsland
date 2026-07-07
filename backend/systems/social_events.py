"""
social_events.py — social event scheduling, discovery, and attendance

World state: world["social_events"] = { event_id: event_dict }

Event schema:
  id            str   unique identifier
  title         str
  category      str   party | dinner | concert | sports | meetup | trip |
                      online_event | festival | exhibition | screening | other
  description   str
  initiator     str   character id who created the draft
  organizers    list  character ids (all must approve before publishing)
  status        str   draft | pending_approval | published | cancelled | completed
  draft_approvals  dict  {char_id: "approved"|"pending"|"changes_requested"}
  pending_changes  list  [{from_char, field, old_val, new_val, note}]
  location      str   "home:<char_id>" | "online" | free text venue name
  location_type str   "home" | "online" | "venue" | "outdoor"
  start_ts      float unix timestamp
  end_ts        float unix timestamp | None
  max_attendees int | None
  tags          list  str
  invited       list  char ids who received an invitation
  attendees     dict  {char_id: "yes"|"no"|"maybe"}
  maybe_decide_ts dict {char_id: float}  timestamp by which maybe must decide
  comments      list  {char_id, text, ts, likes:[char_id], dislikes:[char_id]}
  visible_to    list  char ids who can see this on social media ([] = public)
  cost_per_person float  0.0 = free
  min_age        int | None   e.g. 18 for alcohol events
  max_age        int | None   e.g. 12 for children's events
  popularity     int   0–100, affects discovery weight (100=viral, 20=niche)
  created_ts    float
"""

import uuid
import time
import random


# =========================================================
# HELPERS
# =========================================================

def _now():
    return time.time()

def _event_id():
    return "evt_" + uuid.uuid4().hex[:8]

def get_event(world, event_id):
    return world.get("social_events", {}).get(event_id)

def get_events_for_character(c, world):
    """Return all events this character can see (invited or organizer or public)."""
    cid    = c["id"]
    result = []
    for evt in world.get("social_events", {}).values():
        if evt["status"] == "cancelled":
            continue
        visible = evt.get("visible_to", [])
        if (cid in evt.get("invited", [])
                or cid in evt.get("organizers", [])
                or not visible          # empty = public
                or cid in visible):
            result.append(evt)
    result.sort(key=lambda e: e.get("start_ts", 0))
    return result

def get_my_events(c, world):
    """Events the character is attending (yes) or organising."""
    cid = c["id"]
    out = []
    for evt in world.get("social_events", {}).values():
        if (cid in evt.get("organizers", [])
                or evt.get("attendees", {}).get(cid) == "yes"):
            out.append(evt)
    out.sort(key=lambda e: e.get("start_ts", 0))
    return out


# =========================================================
# CREATE / DRAFT
# =========================================================

def create_event_draft(c, world, title, category="other", description="",
                       location="", location_type="venue",
                       start_ts=None, end_ts=None,
                       co_organizers=None, max_attendees=None,
                       cost_per_person=0.0,
                       min_age=None, max_age=None,
                       popularity=50,
                       dress_code=None,
                       prep_requirements=None,
                       tags=None, visible_to=None):
    """
    Initiator creates a draft event. If co_organizers are listed the event
    stays in status="draft" until all approve. Otherwise it goes straight
    to "published" on creation.

    dress_code: None | "casual" | "smart_casual" | "formal" | "black_tie" |
                "costume" | "athletic" | "themed:<theme>"
    prep_requirements: list of prep types attendees should do beforehand
        e.g. ["buy_supplies", "book_transport", "get_outfit"]
    """
    cid  = c["id"]
    eid  = _event_id()
    now  = _now()
    orgs = [cid] + (co_organizers or [])

    approvals = {o: ("approved" if o == cid else "pending") for o in orgs}

    status = "draft" if len(orgs) > 1 else "published"

    evt = {
        "id":               eid,
        "title":            title,
        "category":         category,
        "description":      description,
        "initiator":        cid,
        "organizers":       orgs,
        "status":           status,
        "draft_approvals":  approvals,
        "pending_changes":  [],
        "location":         location,
        "location_type":    location_type,
        "start_ts":         start_ts or (now + 7 * 86400),
        "end_ts":           end_ts,
        "max_attendees":    max_attendees,
        "cost_per_person":  cost_per_person,
        "min_age":          min_age,
        "max_age":          max_age,
        "popularity":       popularity,
        "dress_code":       dress_code,
        "prep_requirements": prep_requirements or [],
        "tags":             tags or [],
        "invited":          list(orgs),
        "attendees":        {cid: "yes"},
        "maybe_decide_ts":  {},
        "comments":         [],
        "visible_to":       visible_to or [],
        "created_ts":       now,
    }

    world.setdefault("social_events", {})[eid] = evt

    # If published immediately, auto-send to organizers' network
    if status == "published":
        _auto_distribute(evt, c, world)
    else:
        # Notify co-organizers of draft
        _notify_co_organizers(evt, world)

    return evt


def _notify_co_organizers(evt, world):
    """Add a notification to each pending co-organizer's inbox."""
    chars = world.get("characters", {})
    for org_id, approval in evt["draft_approvals"].items():
        if approval == "pending":
            org = chars.get(org_id)
            if org:
                org.setdefault("notifications", []).append({
                    "type":     "event_draft",
                    "event_id": evt["id"],
                    "title":    evt["title"],
                    "from":     evt["initiator"],
                    "ts":       _now(),
                })


def _auto_distribute(evt, initiator_c, world):
    """Mark event visible to the initiator's social network."""
    # Everyone in relationships is potentially in the network
    network = list(initiator_c.get("relationships", {}).keys())
    evt["visible_to"] = network   # empty [] already means public; use network list


# =========================================================
# CO-ORGANIZER APPROVAL FLOW
# =========================================================

def approve_event(c, world, event_id):
    """Co-organizer approves the draft as-is."""
    evt = get_event(world, event_id)
    if not evt or c["id"] not in evt.get("organizers", []):
        return False

    evt["draft_approvals"][c["id"]] = "approved"
    _check_all_approved(evt, world)
    return True


def suggest_event_change(c, world, event_id, field, new_value, note=""):
    """Co-organizer requests a change. Puts event back to pending."""
    evt = get_event(world, event_id)
    if not evt or c["id"] not in evt.get("organizers", []):
        return False

    change = {
        "from_char": c["id"],
        "field":     field,
        "old_value": evt.get(field),
        "new_value": new_value,
        "note":      note,
        "ts":        _now(),
        "status":    "pending",   # accepted | rejected | pending
    }
    evt["pending_changes"].append(change)
    evt["draft_approvals"][c["id"]] = "changes_requested"
    evt["status"] = "draft"

    # Notify initiator
    initiator = world.get("characters", {}).get(evt["initiator"])
    if initiator:
        initiator.setdefault("notifications", []).append({
            "type":     "event_change_requested",
            "event_id": event_id,
            "title":    evt["title"],
            "from":     c["id"],
            "field":    field,
            "note":     note,
            "ts":       _now(),
        })
    return True


def accept_change(initiator_c, world, event_id, change_idx):
    """Initiator accepts a suggested change, applies it, re-sends for approval."""
    evt = get_event(world, event_id)
    if not evt or initiator_c["id"] != evt["initiator"]:
        return False

    changes = evt.get("pending_changes", [])
    if change_idx >= len(changes):
        return False

    ch = changes[change_idx]
    ch["status"] = "accepted"
    evt[ch["field"]] = ch["new_value"]

    # Reset all approvals except initiator
    for org in evt["organizers"]:
        evt["draft_approvals"][org] = "approved" if org == initiator_c["id"] else "pending"

    _notify_co_organizers(evt, world)
    return True


def reject_change(initiator_c, world, event_id, change_idx, reason=""):
    """Initiator rejects a suggested change — notifies the requester."""
    evt = get_event(world, event_id)
    if not evt or initiator_c["id"] != evt["initiator"]:
        return False

    changes = evt.get("pending_changes", [])
    if change_idx >= len(changes):
        return False

    ch = changes[change_idx]
    ch["status"]  = "rejected"
    ch["reject_reason"] = reason

    requester = world.get("characters", {}).get(ch["from_char"])
    if requester:
        requester.setdefault("notifications", []).append({
            "type":     "event_change_rejected",
            "event_id": event_id,
            "title":    evt["title"],
            "field":    ch["field"],
            "reason":   reason,
            "ts":       _now(),
        })

    # Re-set this co-organizer to pending so they can re-approve
    evt["draft_approvals"][ch["from_char"]] = "pending"
    _notify_co_organizers(evt, world)
    return True


def _check_all_approved(evt, world):
    """Publish the event when every organizer has approved."""
    if all(v == "approved" for v in evt["draft_approvals"].values()):
        publish_event(evt, world)


def publish_event(evt, world):
    evt["status"] = "published"
    # Notify all organizers
    chars = world.get("characters", {})
    for org_id in evt["organizers"]:
        org = chars.get(org_id)
        if org:
            org.setdefault("notifications", []).append({
                "type":     "event_published",
                "event_id": evt["id"],
                "title":    evt["title"],
                "ts":       _now(),
            })
    # Distribute to network
    initiator = chars.get(evt["initiator"])
    if initiator:
        _auto_distribute(evt, initiator, world)


# =========================================================
# RSVP
# =========================================================

_MAYBE_DECIDE_WINDOW = 86400 * 2  # 2 days before event, must decide

def rsvp(c, world, event_id, response, decide_ts=None):
    """
    response: "yes" | "no" | "maybe"
    For maybe: decide_ts is the timestamp by which the character commits.
    Defaults to 2 days before the event start.
    """
    evt = get_event(world, event_id)
    if not evt or evt["status"] not in ("published",):
        return False

    cid = c["id"]
    evt.setdefault("attendees", {})[cid] = response

    if cid not in evt["invited"]:
        evt["invited"].append(cid)

    if response == "maybe":
        deadline = decide_ts or max(_now(), evt["start_ts"] - _MAYBE_DECIDE_WINDOW)
        evt["maybe_decide_ts"][cid] = deadline
    elif cid in evt.get("maybe_decide_ts", {}):
        del evt["maybe_decide_ts"][cid]

    # Notify organizers
    chars = world.get("characters", {})
    for org_id in evt.get("organizers", []):
        if org_id != cid:
            org = chars.get(org_id)
            if org:
                org.setdefault("notifications", []).append({
                    "type":       "event_rsvp",
                    "event_id":   event_id,
                    "title":      evt["title"],
                    "from":       cid,
                    "response":   response,
                    "ts":         _now(),
                })
    return True


def check_maybe_deadlines(world):
    """
    Called periodically. For any 'maybe' past their decide_ts, nudge the
    character with a notification so the LLM can decide.
    """
    now   = _now()
    chars = world.get("characters", {})
    for evt in world.get("social_events", {}).values():
        if evt["status"] != "published":
            continue
        for cid, deadline in list(evt.get("maybe_decide_ts", {}).items()):
            if now >= deadline:
                c = chars.get(cid)
                if c:
                    c.setdefault("notifications", []).append({
                        "type":     "event_decide_now",
                        "event_id": evt["id"],
                        "title":    evt["title"],
                        "start_ts": evt.get("start_ts"),
                        "ts":       now,
                    })
                # Remove deadline so we don't spam
                del evt["maybe_decide_ts"][cid]


# =========================================================
# INVITATIONS
# =========================================================

def invite_characters(c, world, event_id, char_ids, channel="social_media"):
    """
    Organizer explicitly invites one or more characters.
    channel: "social_media" | "in_person" | "phone" | "text" | "email" | "mail"
    """
    evt = get_event(world, event_id)
    if not evt or c["id"] not in evt.get("organizers", []):
        return False

    chars = world.get("characters", {})
    for cid in char_ids:
        if cid not in evt["invited"]:
            evt["invited"].append(cid)
        target = chars.get(cid)
        if target:
            target.setdefault("notifications", []).append({
                "type":     "event_invitation",
                "event_id": event_id,
                "title":    evt["title"],
                "from":     c["id"],
                "channel":  channel,
                "ts":       _now(),
                "summary":  _event_summary(evt),
            })
    return True


def _event_summary(evt):
    """Compact dict suitable for embedding in notifications or LLM context."""
    return {
        "id":           evt["id"],
        "title":        evt["title"],
        "category":     evt["category"],
        "location":     evt["location"],
        "start_ts":     evt.get("start_ts"),
        "end_ts":       evt.get("end_ts"),
        "organizers":   evt.get("organizers", []),
        "tags":         evt.get("tags", []),
        "attendee_yes": sum(1 for v in evt.get("attendees", {}).values() if v == "yes"),
        "description":  evt.get("description", ""),
    }


# =========================================================
# COMMENTS / REACTIONS
# =========================================================

def add_comment(c, world, event_id, text):
    evt = get_event(world, event_id)
    if not evt:
        return False
    evt.setdefault("comments", []).append({
        "char_id": c["id"],
        "text":    text,
        "ts":      _now(),
        "likes":   [],
        "dislikes":[],
    })
    return True


def react_comment(c, world, event_id, comment_idx, reaction):
    """reaction: 'like' | 'dislike'"""
    evt = get_event(world, event_id)
    if not evt:
        return False
    comments = evt.get("comments", [])
    if comment_idx >= len(comments):
        return False
    cmt = comments[comment_idx]
    cid = c["id"]
    if reaction == "like":
        if cid not in cmt["likes"]:
            cmt["likes"].append(cid)
        if cid in cmt["dislikes"]:
            cmt["dislikes"].remove(cid)
    else:
        if cid not in cmt["dislikes"]:
            cmt["dislikes"].append(cid)
        if cid in cmt["likes"]:
            cmt["likes"].remove(cid)
    return True


# =========================================================
# EVENT COMPLETION (off-grid → summary)
# =========================================================

def check_event_completions(world):
    """
    Called each tick. For published events whose end time has passed,
    move to completed and generate a memory summary for attending sims.
    Also handles events with no end_ts: complete 3h after start.
    """
    now   = _now()
    chars = world.get("characters", {})

    for evt in world.get("social_events", {}).values():
        if evt["status"] != "published":
            continue

        start_ts = evt.get("start_ts", 0)
        end_ts   = evt.get("end_ts") or (start_ts + 3 * 3600)  # default 3h

        if now < end_ts:
            continue

        evt["status"] = "completed"

        # Give attending sims a memory
        summary = (
            f"Attended '{evt['title']}' ({evt['category']}) "
            f"at {evt.get('location', 'unknown location')}. "
            f"{sum(1 for v in evt.get('attendees',{}).values() if v=='yes')} people attended."
        )
        for cid, resp in evt.get("attendees", {}).items():
            if resp != "yes":
                continue
            c = chars.get(cid)
            if not c:
                continue
            from brain.memory import store_memory
            store_memory(c, text=summary, tags=["social_event", evt["category"]],
                         importance=40, source="event")
            # Return from off-grid if they went
            if c.get("off_grid") and c.get("off_grid_reason") == f"event:{evt['id']}":
                c["off_grid"] = False
                c.pop("off_grid_reason", None)


# =========================================================
# SOCIAL MEDIA DISCOVERY
# =========================================================

_DISCOVERY_CHANCE = 0.25   # per social-media session

def maybe_discover_events(c, world, channel="social_media"):
    """
    Called during social media browsing or phone scrolling. Small chance
    of discovering a published event from the character's network.
    Returns list of event summaries shown to the character.
    """
    if random.random() > _DISCOVERY_CHANCE:
        return []

    c_age = c.get("age")
    visible = [
        evt for evt in world.get("social_events", {}).values()
        if evt["status"] == "published"
        and c["id"] not in evt.get("invited", [])
        and (not evt.get("visible_to") or c["id"] in evt.get("visible_to", []))
        and evt.get("start_ts", 0) > _now()
        and (c_age is None or evt.get("min_age") is None or c_age >= evt["min_age"])
        and (c_age is None or evt.get("max_age") is None or c_age <= evt["max_age"])
    ]

    if not visible:
        return []

    # Pick 1-3 to show
    # Weight discovery by event popularity
    weights = [e.get("popularity", 50) for e in visible]
    k = min(3, len(visible))
    shown = random.choices(visible, weights=weights, k=k)
    seen_ids = set()
    shown = [e for e in shown if not (e["id"] in seen_ids or seen_ids.add(e["id"]))]

    # Mark them as discovered — character now knows about them
    for evt in shown:
        if c["id"] not in evt["invited"]:
            evt["invited"].append(c["id"])
        c.setdefault("notifications", []).append({
            "type":     "event_discovered",
            "event_id": evt["id"],
            "channel":  channel,
            "ts":       _now(),
            "summary":  _event_summary(evt),
        })

    return [_event_summary(e) for e in shown]


def suggest_event_in_person(speaker_c, listener_c, world, event_id):
    """
    A character mentions an event in conversation. Delivers full event
    details to the listener as if they had discovered it on social media.
    """
    evt = get_event(world, event_id)
    if not evt or evt["status"] not in ("published", "draft"):
        return False

    if listener_c["id"] not in evt["invited"]:
        evt["invited"].append(listener_c["id"])

    listener_c.setdefault("notifications", []).append({
        "type":     "event_invitation",
        "event_id": event_id,
        "title":    evt["title"],
        "from":     speaker_c["id"],
        "channel":  "in_person",
        "ts":       _now(),
        "summary":  _event_summary(evt),
    })
    return True


# =========================================================
# CONTEXT FOR LLM
# =========================================================

def build_events_context(c, world, limit=8):
    """
    Returns a compact list of events the character knows about,
    with their RSVP status, for inclusion in the LLM context.
    Also includes a social_disposition hint to guide the agent's RSVP decisions.
    """
    cid    = c["id"]
    events = get_events_for_character(c, world)
    now    = _now()
    out    = []
    for evt in events[:limit]:
        if evt.get("start_ts", 0) < now - 86400:  # skip events > 1 day in the past
            continue
        out.append({
            "id":            evt["id"],
            "title":         evt["title"],
            "category":      evt["category"],
            "status":        evt["status"],
            "my_rsvp":       evt.get("attendees", {}).get(cid, "no_response"),
            "i_organise":    cid in evt.get("organizers", []),
            "location":      evt.get("location", ""),
            "start_ts":      evt.get("start_ts"),
            "attending_yes": sum(1 for v in evt.get("attendees", {}).values() if v == "yes"),
            "tags":          evt.get("tags", []),
            "pending_approval": evt.get("draft_approvals", {}).get(cid) == "pending",
            "has_pending_changes": bool(evt.get("pending_changes")),
        })

    # Social disposition hint — tells the LLM how likely this character is to want to go out
    profile = c.get("attraction_profile", {})
    pd      = profile.get("party_disposition", 0.3)
    cr      = profile.get("casual_reluctance", 0.5)
    repr_sc = c.get("repression_state", {}).get("repression_score", 0.0)

    if pd >= 0.60:
        disposition_hint = (
            f"Social butterfly (party_disposition={pd:.2f}): strongly inclined to attend "
            f"parties, go out, and meet new people. Open to casual encounters "
            f"(casual_reluctance={cr:.2f})."
        )
    elif pd >= 0.40:
        disposition_hint = (
            f"Socially active (party_disposition={pd:.2f}): enjoys going out when the "
            f"opportunity fits."
        )
    elif repr_sc >= 0.40:
        disposition_hint = (
            f"Socially reserved due to sexual repression (party_disposition={pd:.2f}, "
            f"repression={repr_sc:.2f}): tends to avoid parties and casual intimacy."
        )
    else:
        disposition_hint = (
            f"Homebody/reserved (party_disposition={pd:.2f}): prefers staying in or "
            f"small gatherings; unlikely to seek out parties or casual encounters."
        )

    return {"events": out, "social_disposition": disposition_hint}


# =========================================================
# AUTO-GENERATED WORLD EVENTS
# =========================================================

_EVENT_TEMPLATES = [
    # (category, titles, tags, loc_type, cost_range, dur_h, desc,
    #  min_age, max_age, popularity_range, dress_code, prep_requirements)
    ("party",
     ["House Party", "Birthday Bash", "Block Party", "Garden Party"],
     ["social", "alcohol", "music"], "home", (0, 20), 4,
     "A casual gathering with drinks, music and good company.",
     18, None, (30, 70), "casual", ["buy_supplies"]),

    ("dinner",
     ["Dinner Night", "Potluck Dinner", "BBQ Night", "Wine & Dine"],
     ["food", "wine", "social"], "home", (0, 40), 3,
     "An intimate dinner get-together. Bring your appetite.",
     None, None, (20, 60), "smart_casual", ["cook_meal", "buy_supplies"]),

    ("concert",
     ["Live Music Night", "Open Mic", "Jazz Evening", "DJ Set"],
     ["music", "nightlife"], "venue", (10, 80), 3,
     "Live performances from local and visiting artists.",
     18, None, (40, 90), "smart_casual", ["book_transport", "get_outfit"]),

    ("sports",
     ["Football Match", "Tennis Doubles", "Running Club", "Pickup Basketball"],
     ["sports", "fitness", "outdoor"], "outdoor", (0, 15), 2,
     "Friendly match — all skill levels welcome.",
     None, None, (20, 55), "athletic", []),

    ("meetup",
     ["Neighbourhood Meetup", "Book Club", "Tech Talk", "Startup Night"],
     ["networking", "community"], "venue", (0, 25), 2,
     "Connect with like-minded people in the area.",
     None, None, (10, 40), "casual", []),

    ("festival",
     ["Street Food Festival", "Craft Beer Fest", "Art Market", "Film Screening"],
     ["culture", "outdoor", "food"], "outdoor", (0, 30), 6,
     "A public event celebrating local culture and community.",
     None, None, (50, 95), "casual", ["buy_supplies"]),

    ("exhibition",
     ["Gallery Opening", "Photography Show", "Art Exhibition"],
     ["art", "culture"], "venue", (0, 20), 3,
     "Opening night for a new collection. Free drinks on arrival.",
     None, None, (20, 60), "smart_casual", ["get_outfit"]),

    ("online_event",
     ["Webinar", "Virtual Game Night", "Online Quiz", "Watch Party"],
     ["online", "tech", "social"], "online", (0, 10), 2,
     "Join from home — link shared in the event details.",
     None, None, (15, 50), None, []),

    ("trip",
     ["Day Trip", "Hiking Excursion", "Beach Day", "Road Trip"],
     ["outdoor", "adventure", "travel"], "outdoor", (10, 60), 8,
     "A group outing — meet at the departure point.",
     None, None, (25, 65), "casual", ["book_transport", "buy_supplies"]),
]

_MAX_WORLD_EVENTS = 12   # never generate more than this many published events at once


def generate_world_events(world):
    """
    Called periodically (e.g. every 300 ticks) to ensure there are always
    some published events visible in the world that sims can discover.
    Events are attributed to random NPC organisers from the character pool.
    """
    import random, time

    events  = world.setdefault("social_events", {})
    chars   = world.get("characters", {})
    if not chars:
        return

    published = sum(1 for e in events.values() if e["status"] == "published")
    to_create = max(0, _MAX_WORLD_EVENTS - published)

    char_ids = list(chars.keys())
    now      = time.time()

    for _ in range(to_create):
        # Weight selection by popularity_range upper bound so high-pop events appear more
        weights = [t[9][1] for t in _EVENT_TEMPLATES]
        tmpl = random.choices(_EVENT_TEMPLATES, weights=weights, k=1)[0]
        cat, titles, tags, loc_type, cost_range, dur_h, desc, min_age, max_age, pop_range, dress_code, prep_req = tmpl

        organiser_id = random.choice(char_ids)
        organiser    = chars[organiser_id]

        title = random.choice(titles)
        # Start time: 1–14 days from now
        start_ts = now + random.uniform(86400, 86400 * 14)
        end_ts   = start_ts + dur_h * 3600

        location = "online" if loc_type == "online" else f"Near {organiser.get('name','someone')}'s area"

        cost = round(random.uniform(*cost_range), 2) if cost_range[1] > 0 else 0.0
        # ~30% chance of free even for paid templates
        if random.random() < 0.3:
            cost = 0.0

        eid = _event_id()
        evt = {
            "id":               eid,
            "title":            title,
            "category":         cat,
            "description":      desc,
            "initiator":        organiser_id,
            "organizers":       [organiser_id],
            "status":           "published",
            "draft_approvals":  {organiser_id: "approved"},
            "pending_changes":  [],
            "location":         location,
            "location_type":    loc_type,
            "start_ts":         start_ts,
            "end_ts":           end_ts,
            "max_attendees":    random.choice([None, 10, 20, 30, 50, 100]),
            "cost_per_person":  cost,
            "min_age":          min_age,
            "max_age":          max_age,
            "popularity":       random.randint(*pop_range),
            "dress_code":       dress_code,
            "prep_requirements": list(prep_req),
            "tags":             tags + [cat],
            "invited":          [organiser_id],
            "attendees":        {organiser_id: "yes"},
            "maybe_decide_ts":  {},
            "comments":         [],
            "visible_to":       [],   # public
            "created_ts":       now,
        }
        events[eid] = evt
