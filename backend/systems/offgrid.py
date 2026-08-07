import random, uuid
from brain.memory import store_memory
from core.event_bus import emit
from systems.offgrid_narrative import request_offgrid_summary, roll_normalcy, _find_trip_cover_lie

# ── LLM narrator ─────────────────────────────────────────────────────────────
# Off-grid categories migrated off the procedural _story() dice-roller onto
# the real narrator pipeline (systems/offgrid_narrative.py). Each category
# owns a stage-1 detail generator (c, world, reason, normalcy) -> dict and
# its own normalcy weights; _NARRATOR_CATEGORIES is the registry
# process_return() dispatches through. Categories not in this registry
# still resolve via _story() below.
_ERRANDS_NORMALCY_WEIGHTS = {"normal": 0.85, "notable": 0.13, "rare": 0.02}
_VENUE_FLAVOR = {
    "shopping":   ["the mall", "a corner store", "a big-box store", "an outdoor market"],
    "leisure":    ["a park", "a movie theater", "downtown", "a friend's neighborhood"],
    "gym":        ["the gym"],
    "cafe":       ["a coffee shop", "a diner"],
    "job_search": ["a job fair", "a few offices downtown", "a staffing agency"],
}


def _shopping_leisure_details(c, world, reason, normalcy):
    """Stage-1 detail generator for the errands categories -- deliberately
    thin, since no venue/participant data exists for these reasons today
    (maybe_go_offgrid() sends characters off with only a reason string)."""
    return {
        "reason": reason,
        "venue_flavor": random.choice(_VENUE_FLAVOR.get(reason, ["somewhere in town"])),
    }


_WORK_NORMALCY_WEIGHTS = {"normal": 0.82, "notable": 0.15, "rare": 0.03}
_WORK_SITUATIONAL_HOOKS = [
    "a customer or client complained about something",
    "a piece of equipment broke down",
    "got praised by a manager for something",
    "a coworker called in sick, leaving things short-staffed",
    "there was an unannounced inspection or visit",
    "a deadline got moved up unexpectedly",
    "there was a mix-up with a delivery or order",
]


def _find_colleagues(c, world, limit=3):
    """
    Best-effort "who else works with this character" -- there is no real
    per-company employee roster in this codebase: c["company_id"] is only
    ever set via jobs.py::process_interview() (characters hired through the
    job-market flow), and c["job"] itself carries no company reference at
    all. Falls back to same-industry characters as a colleague proxy when
    no literal company match exists.
    """
    job = c.get("job") or {}
    my_company = c.get("company_id")
    my_industry = job.get("industry")

    same_company, same_industry = [], []
    for oc in world.get("characters", {}).values():
        if oc.get("id") == c.get("id"):
            continue
        if my_company and oc.get("company_id") == my_company:
            same_company.append(oc)
        elif my_industry and (oc.get("job") or {}).get("industry") == my_industry:
            same_industry.append(oc)

    pool = same_company or same_industry
    random.shuffle(pool)
    return [oc.get("name", "a coworker") for oc in pool[:limit]]


def _work_details(c, world, reason, normalcy):
    """Stage-1 detail generator for work. A situational hook is only
    included on notable/rare normalcy rolls -- a normal day gets none."""
    job = c.get("job") or {}
    details = {
        "reason": "work",
        "job_title": job.get("title", "their job"),
        "industry": job.get("industry"),
        "coworkers_present": _find_colleagues(c, world),
    }
    if normalcy != "normal":
        details["situational_hook"] = random.choice(_WORK_SITUATIONAL_HOOKS)
    return details


_DOCTOR_NORMALCY_WEIGHTS   = {"normal": 0.90, "notable": 0.09, "rare": 0.01}
_HOSPITAL_NORMALCY_WEIGHTS = {"normal": 0.55, "notable": 0.30, "rare": 0.15}
# Riskier than a routine hospital stay -- an operating table is where
# treatments[]' side_effects (including a "death" key, decision #9) can
# actually resolve, so "rare" gets weighted higher than any other category.
_SURGERY_NORMALCY_WEIGHTS  = {"normal": 0.45, "notable": 0.30, "rare": 0.25}
_PHARMACY_NORMALCY_WEIGHTS = {"normal": 0.92, "notable": 0.07, "rare": 0.01}
_MEDICAL_SITUATIONAL_HOOKS = {
    "doctor": [
        "the waiting room was unusually crowded",
        "the doctor ordered an extra test",
        "there was a mix-up with the appointment scheduling",
        "the doctor mentioned something unexpected",
    ],
    "hospital": [
        "the ER was busy when they arrived",
        "a complication came up during treatment",
        "the stay ran longer than expected",
        "a nurse or doctor took extra time to explain things",
    ],
    "hospital_treatment": [
        "the treatment took longer than expected",
        "a nurse checked in more than once to monitor progress",
        "there was a scheduling delay before the treatment began",
        "the care team adjusted the treatment plan partway through",
    ],
    "surgery": [
        "the surgery ran longer than the surgeon expected",
        "the anesthesia took a while to fully wear off afterward",
        "the surgical team explained the risks again beforehand",
        "recovery in the immediate aftermath was rockier than usual",
    ],
    "pharmacy": [
        "the pharmacy was out of the usual brand and had to substitute",
        "there was a short wait for the prescription to be filled",
        "the pharmacist gave an unusually detailed rundown of side effects",
    ],
}


def _medical_details(c, world, reason, normalcy):
    """
    Stage-1 detail generator for doctor/hospital visits. No real clinic or
    hospital identity data exists in this codebase -- company_templates
    isn't populated in this checked-out repo (process_return()'s own
    cost_range lookup already defends against that with a fallback range)
    -- so this stays grounded in what's actually tracked: which conditions
    are being treated and how severe things currently are.
    """
    from core.definitions import load_definitions
    from systems.health import compute_severity

    defs = load_definitions(world.get("sim_id", "default"))
    ph_templates = defs.get("physical_health_templates", {})

    conditions = [
        ph_templates.get(cond_key, {}).get("name", cond_key)
        for cond_key in c.get("physical_health", [])
    ]
    _, tier = compute_severity(c)

    details = {
        "reason": reason,
        "conditions_being_treated": conditions or ["a general checkup"],
        "severity_tier": tier,
    }
    if normalcy != "normal":
        details["situational_hook"] = random.choice(_MEDICAL_SITUATIONAL_HOOKS[reason])
    return details


# Higher variance than the other categories -- jail time has more inherent
# tension than a shopping trip, so "notable"/"rare" are rolled more often.
_JAIL_NORMALCY_WEIGHTS = {"normal": 0.70, "notable": 0.22, "rare": 0.08}
_JAIL_SITUATIONAL_HOOKS = [
    "got into a tense confrontation with another inmate",
    "made an unlikely ally among the other inmates",
    "had a rough encounter with a guard",
    "spent time in solitary for a rule violation",
    "helped someone out and earned a bit of respect",
    "kept mostly to themselves and stayed out of trouble",
]


def _find_fellow_inmates(c, world, limit=2):
    """Best-effort 'who else is in jail right now' proxy -- there is no real
    jail/facility model in this codebase (c["legal"] tracks only status/
    jail_until/record, no location or inmate roster)."""
    pool = [
        oc for oc in world.get("characters", {}).values()
        if oc.get("id") != c.get("id") and oc.get("legal", {}).get("status") == "jailed"
    ]
    random.shuffle(pool)
    return [oc.get("name", "another inmate") for oc in pool[:limit]]


def _jail_details(c, world, reason, normalcy):
    """Stage-1 detail generator for jail. Crime comes from the most recent
    legal.record entry -- schedule_trial()/process_trials() append to it at
    the exact moment this sentence was handed down, so the last entry is
    always this stint's crime."""
    record = c.get("legal", {}).get("record", [])
    crime = record[-1]["crime"] if record else "an offense"
    details = {
        "reason": "jail",
        "crime": crime,
        "fellow_inmates": _find_fellow_inmates(c, world),
    }
    if normalcy != "normal":
        details["situational_hook"] = random.choice(_JAIL_SITUATIONAL_HOOKS)
    return details


# Social events are more eventful than a routine errand -- gatherings are
# where drama/chemistry/conflict actually happens -- so this skews closer
# to jail's variance than the errand categories.
_SOCIAL_EVENT_NORMALCY_WEIGHTS = {"normal": 0.60, "notable": 0.28, "rare": 0.12}
_SOCIAL_EVENT_SITUATIONAL_HOOKS = [
    "had a great conversation with someone new",
    "there was some tension between two attendees",
    "ran into someone unexpected",
    "the event ran later than planned",
    "something about the venue or setup went wrong",
    "made a real connection with someone there",
]


def _social_event_details(c, world, reason, normalcy):
    """
    Stage-1 detail generator for social events. reason is
    f"event:{event_id}" (see action_router.py::_route_social_event_attend)
    -- unlike every other off-grid category, real event data (title,
    category, location, who else is attending) already exists in
    social_events.py, so this is mostly a matter of reading it rather than
    building a proxy.
    """
    from systems.social_events import get_event

    event_id = reason.split(":", 1)[1] if ":" in reason else None
    evt = get_event(world, event_id) if event_id else None
    if not evt:
        return {"reason": "social_event", "title": "a social event"}

    chars = world.get("characters", {})
    other_attendees = [
        chars[cid].get("name", "someone")
        for cid, resp in evt.get("attendees", {}).items()
        if resp == "yes" and cid != c.get("id") and cid in chars
    ]

    details = {
        "reason": "social_event",
        "title": evt.get("title", "a social event"),
        "category": evt.get("category", "other"),
        "location": evt.get("location", "somewhere"),
        "description": evt.get("description", ""),
        "other_attendees": other_attendees[:4],
    }
    if normalcy != "normal":
        details["situational_hook"] = random.choice(_SOCIAL_EVENT_SITUATIONAL_HOOKS)
    return details


# Not a literal off_grid_reason key like the others -- reason for events is
# dynamic (f"event:{event_id}"), matched by prefix in process_return() and
# bucketed under this one stable category name so continuity accumulates
# across every event attended, rather than each unique event id getting
# its own single-use, never-reused memory bucket.
_SOCIAL_EVENT_NARRATOR = (_social_event_details, _SOCIAL_EVENT_NORMALCY_WEIGHTS)


_NARRATOR_CATEGORIES = {
    "shopping":   (_shopping_leisure_details, _ERRANDS_NORMALCY_WEIGHTS),
    "leisure":    (_shopping_leisure_details, _ERRANDS_NORMALCY_WEIGHTS),
    "gym":        (_shopping_leisure_details, _ERRANDS_NORMALCY_WEIGHTS),
    "cafe":       (_shopping_leisure_details, _ERRANDS_NORMALCY_WEIGHTS),
    "job_search": (_shopping_leisure_details, _ERRANDS_NORMALCY_WEIGHTS),
    "work":       (_work_details,             _WORK_NORMALCY_WEIGHTS),
    "doctor":     (_medical_details,          _DOCTOR_NORMALCY_WEIGHTS),
    "hospital":   (_medical_details,          _HOSPITAL_NORMALCY_WEIGHTS),
    "hospital_treatment": (_medical_details,  _HOSPITAL_NORMALCY_WEIGHTS),
    "surgery":    (_medical_details,          _SURGERY_NORMALCY_WEIGHTS),
    "pharmacy":   (_medical_details,          _PHARMACY_NORMALCY_WEIGHTS),
    "jail":       (_jail_details,             _JAIL_NORMALCY_WEIGHTS),
}


# ── Private event catalogue ────────────────────────────────────────────────
# Each entry: (tag_or_trait, activity_key, description_template, fear_tag)
# triggered when character has the matching behavior_tag or trait
_VICE_EVENTS = [
    ("heavy_drinker",  "drink_heavily",  "drank more than intended",         "drinking"),
    ("drug_user",      "use_drugs",      "used drugs while away",            "drugs"),
    ("party_animal",   "party_late",     "stayed out partying much later than planned", "partying"),
    ("gambler",        "gamble",         "gambled and lost money",           "gambling"),
    ("smoker",         "smoke",          "smoked, something they try to hide","smoking"),
    ("troublemaker",   "illegal_activity","got into trouble with the wrong crowd","trouble"),
    ("reckless",       "street_race",    "did something reckless they'd rather not mention","reckless"),
]

# Objectionable activities that can happen based on off-grid reason alone
_REASON_VICE_CHANCE = {
    "leisure":   [("drink_alcohol", "had a drink or two",          "drinking",  0.12)],
    "gym":       [],
    "cafe":      [("smoke",         "had a smoke outside",         "smoking",   0.08)],
    "shopping":  [("gamble",        "stopped by and gambled a bit","gambling",  0.05)],
    "job_search":[],
    "work":      [("drink_alcohol", "had drinks with coworkers",   "drinking",  0.07)],
    "outing":    [("drink_alcohol", "had a drink",                 "drinking",  0.10),
                  ("party_late",    "stayed out far later than usual","partying",0.06)],
}


def _get_household_authorities(c, world):
    """Return characters in the same household who have authority over c."""
    hid   = c.get("household_id")
    if not hid:
        return []
    chars  = world.get("characters", {})
    result = []
    for oc in chars.values():
        if oc["id"] == c["id"] or oc.get("household_id") != hid:
            continue
        rel = oc.get("relationships", {}).get(c["id"], {})
        if rel.get("authority_over"):
            result.append(oc)
        elif any(l in rel.get("labels", []) for l in ("parent", "guardian", "spouse", "partner")):
            result.append(oc)
    return result


def _would_fear_discovery(c, world, activity_key, description):
    """
    True if the character has reason to fear a household member learning
    about this activity. Uses same sensitivity logic as excuses.py.
    """
    try:
        from systems.excuses import _authority_disapproves_of_activity
    except ImportError:
        return activity_key in {
            "drink_heavily", "use_drugs", "gamble", "illegal_activity",
            "street_race", "party_late", "smoke",
        }

    authorities = _get_household_authorities(c, world)
    if not authorities:
        return False

    # Minors always fear drinking/drugs being discovered
    age = c.get("age", 25)
    if age < 21 and activity_key in ("drink_alcohol", "drink_heavily", "use_drugs", "smoke", "party_late"):
        return True

    # Check if any authority would object to this activity
    for auth in authorities:
        if _authority_disapproves_of_activity(auth, activity_key, world):
            return True

    return False


def _private_story(c, world, reason):
    """
    Generate the hidden/secret portion of an off-grid story.
    Returns a list of private event dicts, or [] if nothing to hide.
    """
    traits  = set(c.get("traits", []) + c.get("personality_traits", []) + c.get("behavior_tags", []))
    events  = []

    # 1. Vice-driven events — character's known habits that may surface during outing
    for (tag, activity, desc, fear_tag) in _VICE_EVENTS:
        if tag not in traits:
            continue
        prob = 0.45 if tag in ("heavy_drinker", "drug_user") else 0.30
        if random.random() > prob:
            continue
        if not _would_fear_discovery(c, world, activity, desc):
            continue
        events.append({
            "activity":    activity,
            "description": desc,
            "fear_tag":    fear_tag,
            "source":      "vice",
        })

    # 2. Reason-contextual events — situational temptations based on trip type
    for (activity, desc, fear_tag, base_prob) in _REASON_VICE_CHANCE.get(reason, []):
        if random.random() > base_prob:
            continue
        if not _would_fear_discovery(c, world, activity, desc):
            continue
        if any(e["activity"] == activity for e in events):
            continue  # avoid duplicates
        events.append({
            "activity":    activity,
            "description": desc,
            "fear_tag":    fear_tag,
            "source":      "context",
        })

    # 3. Secret relationship meetings
    for s in c.get("secrets", []):
        if s.get("category") not in ("affair", "forbidden_relationship", "crush_secret"):
            continue
        target_id = s.get("about_character_id") or s.get("target_id")
        if not target_id:
            continue
        target = world.get("characters", {}).get(target_id)
        if not target:
            continue
        if random.random() > 0.35:
            continue
        events.append({
            "activity":    "secret_meeting",
            "description": f"met secretly with {target.get('name', 'someone')}",
            "fear_tag":    "secret_relationship",
            "target_id":   target_id,
            "secret_id":   s["id"],
            "source":      "secret",
        })
        break  # one secret meeting per outing

    # 4. Forbidden venue visit
    if reason in ("leisure", "outing") and random.random() < 0.15:
        for loc_type in c.get("disliked_location_types", []):
            if loc_type in ("bar", "club", "casino"):
                if not any(e["fear_tag"] in ("partying", "drinking") for e in events):
                    if _would_fear_discovery(c, world, "party_late", "visited a restricted venue"):
                        events.append({
                            "activity":    "visit_forbidden_venue",
                            "description": f"went to a {loc_type} without permission",
                            "fear_tag":    "forbidden_venue",
                            "source":      "location",
                        })
                break

    return events


def _seed_lie_for_private_event(c, world, event):
    """
    Pre-seed an active lie so the LLM knows the character already has a cover
    story before anyone confronts them. Uses canonical active_lies schema.
    """
    activity = event.get("activity", "something")
    desc     = event.get("description", "something")
    reason   = c.get("off_grid_reason") or "outing"
    lie = {
        "id":            f"lie_{uuid.uuid4().hex[:6]}",
        "question_type": "what",
        "lie_text":      f"just had a normal {reason} trip",
        "actual_truth":  desc,
        "told_to":       [],   # not told to anyone yet — pre-seeded
        "tick":          world.get("tick", 0),
        "detected":      False,
        "source":        "offgrid_private",
        "activity":      activity,
    }
    c.setdefault("active_lies", []).append(lie)
    c["active_lies"] = c["active_lies"][-20:]
    return lie["id"]


# Reasons routed through a real physical trip (garage/car or bus stop --
# see travel.py) instead of vanishing instantly. jail/hospital are excluded:
# both already imply involuntary transport (police custody / ambulance),
# so routing an incapacitated or arrested character through "walk to the
# garage and drive yourself" would be narratively wrong.
_TRAVEL_ELIGIBLE_REASONS = {
    "work", "job_search", "shopping", "leisure", "gym", "cafe", "doctor", "pharmacy",
}


MAX_OFFGRID_TRIPS_PER_DAY = 3

# jail/hospital are consequences, not discretionary outings -- a character
# facing arrest or a medical emergency must always be able to go, regardless
# of how many voluntary trips they've already taken today. hospital_treatment/
# surgery (treatments[] step types, health.py::advance_treatment_progress)
# join them for the same reason -- a scheduled procedure isn't optional.
_UNCAPPED_REASONS = {"jail", "hospital", "hospital_treatment", "surgery"}


def _offgrid_trips_today(c, world):
    today = world.get("calendar", {}).get("day")
    if c.get("off_grid_trip_day") != today:
        c["off_grid_trip_day"] = today
        c["off_grid_trip_count"] = 0
    return c["off_grid_trip_count"]


def send_offgrid(c, world, reason, duration):
    if c.get("off_grid") or c.get("legal", {}).get("status") == "jailed":
        return False
    if c.get("travel_state"):
        return False
    if reason not in _UNCAPPED_REASONS:
        if _offgrid_trips_today(c, world) >= MAX_OFFGRID_TRIPS_PER_DAY:
            return False
        c["off_grid_trip_count"] += 1

    if reason in _TRAVEL_ELIGIBLE_REASONS or reason.startswith("event:"):
        from systems.travel import begin_travel
        return begin_travel(c, world, reason, duration)

    return _send_offgrid_immediate(c, world, reason, duration)


def _send_offgrid_immediate(c, world, reason, duration):
    if c.get("off_grid") or c.get("legal", {}).get("status") == "jailed":
        return False
    c["off_grid"]      = True
    c["off_grid_reason"] = reason
    c["return_tick"]   = world["tick"] + duration
    world.setdefault("offmap", []).append({
        "character_id": c["id"], "reason": reason, "return_tick": c["return_tick"],
    })
    return True


def maybe_go_offgrid(c, world):
    if c.get("off_grid") or c.get("conversation"):
        return
    r = random.random()
    if c.get("employed") and world["calendar"]["minute_of_day"] in [480, 490]:
        send_offgrid(c, world, "work", 48)
    elif not c.get("employed") and r < 0.01:
        send_offgrid(c, world, "job_search", 20)
    elif r < 0.004:
        send_offgrid(c, world, "shopping", 18)
    elif r < 0.008:
        send_offgrid(c, world, random.choice(["leisure", "gym", "cafe"]), 28)


def maybe_schedule_doctor_visit(c, world):
    """Doctor/hospital visits now go through a real booked appointment
    (systems/appointments.py) instead of an instant teleport -- a
    character doesn't know gp_clinic/hospital's hours in advance any
    more than a real person does, so this can't resolve immediately.
    Frequency of *deciding* they need to be seen is still scaled by
    systems/health.py::_compute_doctor_visits_needed's severity-weighted
    target, same as before; process_return's "doctor"/"hospital" branch
    still applies the treatment once the trip actually happens. True
    emergencies go through emergency.py's 911 dispatch instead and are
    unaffected by this gate."""
    if c.get("off_grid") or c.get("conversation"):
        return
    if c.get("alive") is False or c.get("posture") in ("incapacitated", "incapacitated_pain", "crawling"):
        return
    needed = c.get("health_state", {}).get("doctor_visits_needed", 0)
    if needed <= 0:
        return

    business_key = "hospital" if needed >= 4 else "gp_clinic"
    reason       = "hospital" if needed >= 4 else "doctor"

    from systems.appointments import has_upcoming_appointment, is_appointment_due, book
    appt = has_upcoming_appointment(c, business_key)
    if appt:
        if is_appointment_due(appt, world):
            appt["fulfilled"] = True
            duration = 60 if reason == "hospital" else 20
            send_offgrid(c, world, reason, duration)
        return

    # No appointment booked yet -- same probability gate as before decides
    # *whether* the character now realizes they need to be seen, but the
    # trip itself waits for the booked slot rather than firing instantly.
    if random.random() < 0.002 * needed:
        from core.definitions import load_definitions
        business = (load_definitions("default").get("company_templates") or {}).get(business_key)
        if business:
            book(c, world, business_key, business, reason)


def _story(c, world, reason):
    env    = world["environment"]
    parts  = []
    emotion = "calm"
    impact  = {"stress": 0, "temp": 0}
    tags    = [reason]
    if random.random() > 0.25:
        parts.append(f"had a routine {reason} trip")
    else:
        if random.random() < env.get("crime_rate", .2):
            parts.append("saw something suspicious and felt unsafe")
            emotion = "fearful"; impact["stress"] += 8; tags += ["crime", "fear"]
        if random.random() > env.get("traffic_safety", .7):
            parts.append("was delayed by a traffic scare")
            emotion = "annoyed"; impact["stress"] += 5; tags += ["traffic"]
        if random.random() > env.get("health_quality", .7):
            parts.append("felt unwell while out")
            emotion = "sad"; impact["stress"] += 4; tags += ["health"]
        if reason == "shopping" and random.random() < env.get("cost_of_living_index", 1) - .7:
            parts.append("was shocked by high prices")
            emotion = "annoyed"; impact["stress"] += 5; tags += ["money", "cost_of_living"]
        if not parts:
            parts.append(f"had an unexpectedly meaningful {reason} outing")
            tags += ["positive"]
    return {
        "id":      f"story_{uuid.uuid4().hex[:6]}",
        "summary": f"{c['name']} " + " and ".join(parts) + ".",
        "emotion": emotion,
        "impact":  impact,
        "tags":    tags,
    }


def handle_return_transport(c, world):
    if c.get("transport", {}).get("mode") == "bus":
        bus_id = c["transport"]["bus_id"]
        bus    = world["entities"].get(bus_id)
        if bus:
            pos        = bus["components"]["position"]
            c["x"], c["y"] = pos["x"], pos["y"]
        c["transport"] = None


def process_return(c, world):
    if not c.get("off_grid") or world["tick"] < (c.get("return_tick") or 0):
        return

    reason = c.get("off_grid_reason") or "outing"
    is_event = reason.startswith("event:")

    if reason in _NARRATOR_CATEGORIES or is_event:
        if reason == "jail":
            # law.py::process_jail() only checks jail_until on a cadence
            # (CADENCE["trials"], ~every 60 ticks), while this function
            # checks return_tick every tick -- since Round 0's fix made
            # jail_until and return_tick the same value, this function now
            # reliably wins the race and would otherwise leave
            # legal.status=="jailed" for up to ~60 ticks after off_grid
            # actually clears below. Release immediately so the two never
            # drift apart; process_jail()'s own release becomes a safe
            # no-op afterward (its guard requires status=="jailed").
            c["legal"]["status"] = "free"
            emit("character_released", {"character_id": c["id"]})

        # New LLM narrator pipeline. Private events + lie-seeding run FIRST
        # (unlike the branch below) so the public narration can be made
        # consistent with any cover story that results -- the old order
        # (public story before private/lies) meant no lie existed yet when
        # the public account was built.
        private_events = _private_story(c, world, reason)
        for ev in private_events:
            if ev.get("source") in ("vice", "context", "location"):
                ev["lie_id"] = _seed_lie_for_private_event(c, world, ev)

        cover_story = _find_trip_cover_lie(c, world["tick"])
        if is_event:
            details_fn, weights = _SOCIAL_EVENT_NARRATOR
            category = "social_event"
        else:
            details_fn, weights = _NARRATOR_CATEGORIES[reason]
            category = reason
        normalcy = roll_normalcy(weights)
        details  = details_fn(c, world, reason, normalcy)

        story = request_offgrid_summary(
            c, world, category, details, normalcy,
            enforced_cover_story=cover_story,
        )
        if story is None:
            # LLM unreachable/failed -- graceful fallback to the existing
            # procedural narrator. _story() doesn't recognize the dynamic
            # "event:<id>" reason format (would render it literally, e.g.
            # "had a routine event:evt_a1b2c3 trip"), so events fall back
            # to a clean generic label instead -- same "social_event"
            # framing the success path already uses for tags.
            story = _story(c, world, "social event" if is_event else reason)
        if private_events:
            story["private"] = private_events
    else:
        story = _story(c, world, reason)

        # Generate private events — things that happened but mustn't get out
        private_events = _private_story(c, world, reason)
        if private_events:
            story["private"] = private_events
            # Pre-seed cover lies for vice/context/location events
            for ev in private_events:
                if ev.get("source") in ("vice", "context", "location"):
                    ev["lie_id"] = _seed_lie_for_private_event(c, world, ev)

    c["off_grid"]        = False
    c["off_grid_reason"] = None
    c["return_tick"]     = None
    c.setdefault("off_grid_story_arc", []).append(story)
    c["off_grid_story_arc"] = c["off_grid_story_arc"][-8:]

    # Private history — separate, never shared with observers or in world events
    if private_events:
        entry = {"tick": world["tick"], "reason": reason, "events": private_events}
        c.setdefault("private_off_grid_history", []).append(entry)
        c["private_off_grid_history"] = c["private_off_grid_history"][-12:]

    c["stress"] = max(0, min(100, c.get("stress", 0) + story["impact"]["stress"]))
    if reason == "work" and c.get("employed"):
        h      = world["households"].get(c["household_id"])
        earned = c.get("hourly_wage", 15) * 8
        if h:
            h["wealth"] += earned
        story["summary"] += f" Earned ${earned:.0f}."
    elif reason in ("doctor", "hospital"):
        from core.definitions import load_definitions
        defs = load_definitions(world.get("sim_id", "default"))
        ph_templates = defs.get("physical_health_templates", {})
        meds = c.setdefault("health_state", {}).setdefault("medications_taken", {})
        treated_any = []
        for cond_key in c.get("physical_health", []):
            tmpl = ph_templates.get(cond_key, {})
            for med in tmpl.get("medicine", []):
                if med not in meds:
                    meds[med] = {"tick": world["tick"], "treats": cond_key}
                    treated_any.append(med)
                    break

        # A hospital visit (unlike a routine doctor visit) also addresses
        # acute trauma -- systems/health.py::compute_severity()'s
        # per-bodypart hazards and blood-loss/pain signals previously had
        # zero connection to this mechanic, so a character rushed to
        # hospital for a stabbing came back just as stabbed. Only the
        # acute-trauma cluster is touched here (unconscious/bleeding/
        # agonizing_pain, plus every body part's hazards) -- heart_attack/
        # stroke/coma/cardiac_arrest each have their own dedicated
        # resolution arcs (resolve_heart_attack/tick_stroke/tick_coma) and
        # are left alone so this doesn't short-circuit that narrative.
        # Re-pointed at the per-bodypart damage rework's body_parts/hazards
        # shape (Round 8) -- the old flat injuries[]/bleeding_severity/
        # force/severity fields this used to mutate don't exist anymore.
        # treat_body_part(method="hospital") matches every hazard's
        # treatable_by (hospital treats everything first_aid can plus the
        # hospital-only ones like broken_bone/internal_bleeding) and keeps
        # the same partial-not-full-healing philosophy -- a severe enough
        # wound can still need a second visit rather than being trivialized.
        acute_treated = False
        if reason == "hospital":
            from systems.health import treat_body_part, add_pain
            hs = c.setdefault("health_state", {})
            em = hs.setdefault("active_emergencies", {})
            for key in ("unconscious", "bleeding", "agonizing_pain"):
                if em.pop(key, None) is not None:
                    acute_treated = True
            for part in list(hs.get("body_parts", {}).keys()):
                if treat_body_part(c, world, part, method="hospital"):
                    acute_treated = True
            if hs.get("total_blood_lost", 0) > 0:
                hs["total_blood_lost"] = max(0, hs["total_blood_lost"] - 0.5)
                acute_treated = True
            if hs.get("pain", 0) > 0:
                add_pain(c, -40)
                acute_treated = True

        company = defs.get("company_templates", {}).get(
            "hospital" if reason == "hospital" else "gp_clinic", {})
        lo, hi = company.get("cost_range", [50, 300])
        cost = random.uniform(lo, hi)
        h = world.get("households", {}).get(c.get("household_id"))
        if h:
            h["wealth"] = max(0, h.get("wealth", 0) - cost)
        if treated_any:
            story["summary"] += f" Was prescribed {', '.join(treated_any)}. Cost ${cost:.0f}."
        elif acute_treated:
            story["summary"] += f" Received emergency treatment. Cost ${cost:.0f}."
        else:
            story["summary"] += f" Routine checkup. Cost ${cost:.0f}."
    elif reason in ("hospital_treatment", "surgery"):
        # treatments[] step resolution (health.py::advance_treatment_progress,
        # _drive_appointment_step) -- distinct from the legacy "doctor"/
        # "hospital" branch above, which is keyed off physical_health_
        # templates' own top-level medicine[] list. The step object itself
        # was stashed on health_state["_active_treatment_step"] right before
        # send_offgrid() so it survives the off-grid round trip.
        step = c.setdefault("health_state", {}).pop("_active_treatment_step", None) or {}
        cost = step.get("cost", 0)
        h = world.get("households", {}).get(c.get("household_id"))
        if h and cost:
            h["wealth"] = max(0, h.get("wealth", 0) - cost)

        died = False
        for hazard_key, prob in (step.get("side_effects") or {}).items():
            if random.random() >= prob:
                continue
            if hazard_key == "death":
                from systems.health import _trigger_death
                _trigger_death(c, world, f"{reason}_complication")
                died = True
                break
            from systems.health import add_pain
            add_pain(c, 15)
            story.setdefault("tags", []).append(f"side_effect:{hazard_key}")

        if died:
            story["summary"] += " Complications proved fatal."
        elif cost:
            story["summary"] += f" Cost ${cost:.0f}."
    elif reason == "pharmacy":
        from core.definitions import load_definitions
        defs = load_definitions(world.get("sim_id", "default"))
        company = defs.get("company_templates", {}).get("pharmacy", {})
        lo, hi = company.get("cost_range", [10, 60])
        cost = random.uniform(lo, hi)
        h = world.get("households", {}).get(c.get("household_id"))
        if h:
            h["wealth"] = max(0, h.get("wealth", 0) - cost)
        story["summary"] += f" Cost ${cost:.0f}."

    handle_return_transport(c, world)

    # Only the PUBLIC summary goes into shared memory and world events
    public_story = {k: v for k, v in story.items() if k != "private"}
    store_memory(c, story["summary"], .75, ["offgrid"] + story["tags"],
                 "offgrid_story", world["tick"], story=public_story)
    events = world.setdefault("events", [])
    events.append({
        "id":           story["id"],
        "type":         "offgrid_story",
        "character_id": c["id"],
        "tick":         world["tick"],
        "story":        public_story,
    })
    del events[:-300]  # world["events"] otherwise grows forever

    # Errand is narratively complete, but a travel-mode character (see
    # travel.py) isn't home yet -- defer their visible reveal to the
    # driving-back / bus-arrival leg instead of popping back in place.
    if c.get("travel_mode") == "car":
        from systems.travel import _start_driving_back
        _start_driving_back(c, world)
    elif c.get("travel_mode") == "bus":
        c["travel_state"] = "awaiting_bus_arrival"
