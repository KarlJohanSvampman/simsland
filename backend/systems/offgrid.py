import random, uuid
from brain.memory import store_memory
from core.event_bus import emit
from core.tick_schedule import TICK_RATE_SECONDS
from systems.offgrid_narrative import request_offgrid_summary, roll_normalcy, _find_trip_cover_lie

# Every send_offgrid()/_send_offgrid_immediate() "duration" argument across
# the codebase (maybe_go_offgrid, law.py's jail sentences, emergency.py's
# ambulance hospital stay, appointments-driven doctor/hospital/pharmacy
# visits) was always authored as a plausible number of MINUTES (15-120) --
# but _send_offgrid_immediate() was setting return_tick = tick + duration
# directly, silently treating that number as raw ticks instead. At 1 tick =
# 1 TICK_RATE_SECONDS (see core/tick_schedule.py), that made every off-grid
# trip resolve in seconds. Converting once here, at the single lowest-level
# function that actually sets return_tick, fixes every call site at once
# without needing to touch any of their already-correctly-scaled numbers.
_TICKS_PER_MINUTE = 60 / TICK_RATE_SECONDS


def _minutes_to_ticks(minutes):
    return round(minutes * _TICKS_PER_MINUTE)


# Explicit user direction: no discretionary off-grid trip should eat more
# than 2 hours of sim time -- a work shift, a school day, a hospital
# admission, or a jail sentence are all legitimately long by nature; a
# cafe/shopping/leisure/errand trip is not. Enforced as a hard ceiling
# inside _send_offgrid_immediate() itself (not just at each call site) so
# it holds regardless of caller, present or future.
MAX_OFFGRID_MINUTES = 120
_UNCAPPED_DURATION_REASONS = {"work", "school", "hospital", "hospital_treatment", "surgery", "jail"}

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


def send_offgrid(c, world, reason, duration_minutes):
    """duration_minutes: how long this trip should take, in minutes (see
    _minutes_to_ticks/MAX_OFFGRID_MINUTES above) -- converted to ticks and
    capped at the single lowest-level function that actually sets
    return_tick (_send_offgrid_immediate), so every call site here just
    authors a plausible real-world duration and doesn't need to think about
    ticks at all."""
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
        return begin_travel(c, world, reason, duration_minutes)

    return _send_offgrid_immediate(c, world, reason, duration_minutes)


def send_offgrid_chain(c, world, stops):
    """Send a character off-grid through multiple stops in a row -- e.g. the
    bank, then the grocery store, then home -- without walking back in
    between each one. stops: a list of (reason, duration_minutes) pairs,
    run in order. Only the FIRST stop's physical trip (bus/car, see
    travel.py) is actually simulated; process_return() below chains
    straight into each subsequent stop's own off-grid clock the moment the
    previous one's story resolves (skipping the "go home" leg), and only
    does the real drive/bus-ride home once every stop is done."""
    if not stops:
        return False
    first_reason, first_minutes = stops[0]
    if not send_offgrid(c, world, first_reason, first_minutes):
        return False
    c["offgrid_queue"] = list(stops[1:])
    return True


def _send_offgrid_immediate(c, world, reason, duration_minutes):
    if c.get("off_grid") or c.get("legal", {}).get("status") == "jailed":
        return False
    if reason not in _UNCAPPED_DURATION_REASONS:
        duration_minutes = min(duration_minutes, MAX_OFFGRID_MINUTES)
    c["off_grid"]      = True
    c["off_grid_reason"] = reason
    c["return_tick"]   = world["tick"] + _minutes_to_ticks(duration_minutes)
    world.setdefault("offmap", []).append({
        "character_id": c["id"], "reason": reason, "return_tick": c["return_tick"],
    })
    return True


_ERRAND_CHAIN_POOL = ("shopping", "leisure", "gym", "cafe", "job_search")


def _send_errand(c, world, reason, minutes):
    """Sends a single errand off-grid, with a modest chance of chaining one
    more short stop onto it (see send_offgrid_chain) -- e.g. "went shopping,
    then swung by a cafe" as one continuous trip instead of two separate
    round trips home in between."""
    stops = [(reason, minutes)]
    if random.random() < 0.25:
        extra = random.choice([r for r in _ERRAND_CHAIN_POOL if r != reason])
        stops.append((extra, random.randint(20, 45)))
    send_offgrid_chain(c, world, stops)


def maybe_go_offgrid(c, world):
    if c.get("off_grid") or c.get("conversation"):
        return
    r = random.random()
    if c.get("employed") and world["calendar"]["minute_of_day"] in [480, 490]:
        send_offgrid(c, world, "work", 8 * 60)
    elif not c.get("employed") and r < 0.01:
        send_offgrid(c, world, "job_search", 60)
    else:
        # Depression reduces (not zeroes) the chance of a leisure-flavored
        # trip specifically -- work/job-search stay unaffected (systems/
        # mental_health_effects.py::home_leaving_multiplier, feeding
        # systems/withdrawal_concern.py's "staying home too much" drama).
        from systems.mental_health_effects import home_leaving_multiplier
        leave_mult = home_leaving_multiplier(c)
        if r < 0.004 * leave_mult:
            _send_errand(c, world, "shopping", 45)
        elif r < 0.008 * leave_mult:
            _send_errand(c, world, random.choice(["leisure", "gym", "cafe"]), random.randint(30, 60))


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
    if c.get("alive") is False or c.get("posture") in ("incapacitated", "crawling"):
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
            duration = 4 * 60 if reason == "hospital" else 45
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


# Reasons owned by a dedicated scheduler (maybe_schedule_doctor_visit above)
# that decides on the character's own behalf, rather than the character/AI
# consciously choosing to book -- excluded from resolve_due_appointments so
# the two pollers never double-fire the same appointment.
_DEDICATED_SCHEDULER_REASONS = {"doctor", "hospital"}


def resolve_due_appointments(c, world):
    """Generic appointment-due -> off-grid-trip trigger. Every reason NOT
    already owned by a dedicated scheduler (doctor/hospital) reaches this
    point purely through action_router.py::_route_book_appointment (the
    character/AI actively chose to call and book, e.g. a bank visit for
    "credit_card_application") -- nothing else currently polls those for
    fulfillment, so without this they'd sit "booked" forever. Mirrors
    maybe_schedule_doctor_visit's due-check, minus the need-driven booking
    half (that already happened via the phone call)."""
    if c.get("off_grid") or c.get("conversation"):
        return
    from systems.appointments import is_appointment_due
    for appt in c.get("appointments", []):
        if appt.get("fulfilled") or appt.get("reason") in _DEDICATED_SCHEDULER_REASONS:
            continue
        if is_appointment_due(appt, world):
            appt["fulfilled"] = True
            c["_pending_appointment_business"] = appt.get("business")
            send_offgrid(c, world, appt.get("reason", "outing"), 30)
            return


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


_RETURN_MODE_WEIGHTS = {"bus": 0.65, "taxi": 0.20, "friend": 0.15}


def _has_available_ride_contact(c, world):
    """Loose proxy for "someone who could plausibly come get them" -- this
    sim doesn't actually simulate who's physically present at an
    off-grid destination (it's narrated, not simulated), so this checks
    for a real close contact who's currently free (not off-grid
    themselves) rather than trying to track true co-presence."""
    chars = world.get("characters", {})
    for oid, rel in c.get("relationships", {}).items():
        other = chars.get(oid)
        if not other or other.get("off_grid"):
            continue
        if rel.get("friendship", 0) > 50 or rel.get("kinship") in ("parent", "spouse", "sibling"):
            return oid
    return None


def _resolve_return_mode(c, world):
    """Weighted roll among bus/taxi/friend for a non-car departure.
    Household members returning together (same household, same
    off_grid_reason, resolved this same tick) share ONE roll rather than
    each rolling independently -- see the shared cache below."""
    household_id = c.get("household_id")
    reason = c.get("off_grid_reason")
    tick = world.get("tick", 0)
    cache = world.setdefault("_return_mode_cache", {})
    key = (household_id, reason, tick)
    if key in cache:
        return cache[key]

    weights = dict(_RETURN_MODE_WEIGHTS)
    if not _has_available_ride_contact(c, world):
        weights["friend"] = 0.0
    total = sum(weights.values()) or 1.0
    roll = random.random() * total
    upto = 0.0
    mode = "bus"
    for m, w in weights.items():
        upto += w
        if roll <= upto:
            mode = m
            break

    cache[key] = mode
    return mode


def _return_via_taxi(c, world):
    from systems.vehicles import household_home_entrance
    from systems.rideshare import request_pickup
    home = household_home_entrance(world, c.get("household_id"))
    if not home:
        return False
    from systems.vehicles import bus_stop
    stop = bus_stop(world)
    pickup = stop or {"x": c.get("x", 0), "y": c.get("y", 0)}
    result = request_pickup(c, world, {"x": pickup["x"], "y": pickup["y"]},
                             method="taxi", destination={"x": home[0], "y": home[1]})
    if not result.get("ok"):
        return False
    c["x"], c["y"] = pickup["x"], pickup["y"]
    c["travel_hidden"] = False
    c["travel_state"] = None
    c["travel_mode"] = None
    return True


def _return_via_friend(c, world):
    """propose_request() is asynchronous (resolved by the contact's own
    AI turn later, not synchronously here), so this can't just wait for
    the real proposal to resolve before deciding the return trip -- it
    resolves willingness with the same lightweight, synchronous roll
    systems/sexual_release.py::_booty_call_accepted() uses (attraction/
    trust-driven), and still opens a real proposal via
    systems/rideshare.py::request_pickup for the narrative/ledger
    record. Consistent with sexual_release.py's _bring_together(): no
    real "drive to and pick up from an off-grid destination" pathing
    exists yet, so an accepted ride relocates the character home
    directly rather than simulating the drive."""
    contact_id = _has_available_ride_contact(c, world)
    contact = world.get("characters", {}).get(contact_id) if contact_id else None
    if not contact:
        return False

    rel = contact.get("relationships", {}).get(c["id"], {})
    willingness = rel.get("friendship", 0) / 100.0 * 0.7 + rel.get("trust", 0) / 100.0 * 0.3
    if random.random() >= max(0.15, min(0.95, willingness)):
        return False

    from systems.rideshare import request_pickup
    request_pickup(c, world, {"x": c.get("x", 0), "y": c.get("y", 0)},
                    method="friend", contact_id=contact_id)

    from systems.vehicles import household_home_entrance
    home = household_home_entrance(world, c.get("household_id"))
    if home:
        c["x"], c["y"] = home
    c["travel_hidden"] = False
    c["travel_state"] = None
    c["travel_mode"] = None
    return True


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

        from systems.crime import resolve_criminal_shift
        crime_note = resolve_criminal_shift(c, world)
        if crime_note:
            story["summary"] += crime_note
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
        # per-bodypart hazards and blood-loss signals previously had
        # zero connection to this mechanic, so a character rushed to
        # hospital for a stabbing came back just as stabbed. Only the
        # acute-trauma cluster is touched here (unconscious/bleeding/
        # severe_trauma, plus every body part's hazards) -- heart_attack/
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
            from systems.health import treat_body_part
            hs = c.setdefault("health_state", {})
            em = hs.setdefault("active_emergencies", {})
            for key in ("unconscious", "bleeding", "severe_trauma"):
                if em.pop(key, None) is not None:
                    acute_treated = True
            for part in list(hs.get("body_parts", {}).keys()):
                if treat_body_part(c, world, part, method="hospital"):
                    acute_treated = True
            if hs.get("total_blood_lost", 0) > 0:
                hs["total_blood_lost"] = max(0, hs["total_blood_lost"] - 0.5)
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
            defs = world.get("definitions", {})
            hazard_registry = defs.get("health_hazard_templates", {})
            hazard_tmpl = hazard_registry.get(hazard_key)
            if hazard_tmpl:
                from systems.health import BODY_PARTS, _blank_body_part, _functional_status_for, _hazard_locality
                hs = c.setdefault("health_state", {})
                locality = _hazard_locality(hazard_tmpl)
                instance = {
                    "tick_applied": world.get("tick", 0), "last_ticked": world.get("tick", 0),
                    "treated": False, "hazard_template": hazard_key,
                    "expires_tick": None, "current_stage": None,
                }
                if locality in BODY_PARTS:
                    bp = hs.setdefault("body_parts", {}).setdefault(locality, _blank_body_part())
                    bp["hazards"][hazard_key] = instance
                    if not bp.get("severity_level"):
                        bp["severity_level"] = "low"
                    bp["functional_status"] = _functional_status_for(bp["severity_level"], bp["hazards"])
                else:
                    hs.setdefault("systemic_hazards", {})[hazard_key] = instance
            story.setdefault("tags", []).append(f"side_effect:{hazard_key}")

        if died:
            story["summary"] += " Complications proved fatal."
        elif cost:
            story["summary"] += f" Cost ${cost:.0f}."
    elif reason == "shopping":
        # choose_from_catalog()/purchase_from_catalog() (procurement.py)
        # already existed as real, working infrastructure but had zero
        # callers anywhere -- a "shopping" trip was pure narrative flavor
        # text with no effect on money or inventory. This is that missing
        # caller.
        household = world.get("households", {}).get(c.get("household_id"))
        if household:
            from systems.procurement import choose_from_catalog, purchase_from_catalog
            entry = choose_from_catalog(c, world, category=None, budget=c.get("money", 0))
            if entry and purchase_from_catalog(c, household, world, entry["id"], method="in_person"):
                from systems.validation import queue_choice_for_validation
                queue_choice_for_validation(c, world, "purchase", entry.get("name", entry["id"]))
                story["summary"] += f" Bought {entry.get('name', 'something')} for ${entry['current_price']:.0f}."
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
    elif reason in ("credit_card_application", "account_setup", "loan_application"):
        # _pending_appointment_business was stashed by
        # resolve_due_appointments() right before send_offgrid() -- the
        # book_appointment action only ever records reason+business on
        # the appointment itself, not on the character, so this is the
        # only way process_return() (which only gets `reason`) still
        # knows which bank was actually called.
        business_key = c.pop("_pending_appointment_business", None)
        defs = world.get("definitions", {})
        business = (defs.get("company_templates") or {}).get(business_key or "")
        bank_name = business.get("name") if business else None

        if reason == "credit_card_application" and bank_name:
            from systems.credit import apply_for_credit_card, is_eligible
            approved = apply_for_credit_card(c, world, bank_name)
            if approved:
                story["summary"] += f" Approved for a {bank_name} credit card (${approved['max_credit']:.0f} limit)."
            elif is_eligible(c):
                story["summary"] += f" Already had a {bank_name} credit card on file."
            else:
                story["summary"] += f" {bank_name} declined the application -- credit score too low."
        elif reason == "account_setup" and bank_name:
            from systems.banking import bank_key_for_name, open_account
            from systems.personal_items import make_bank_card, add_item, get_item
            bank_key = bank_key_for_name(bank_name)
            if bank_key:
                account_number = open_account(world, bank_key, c["id"], initial_balance=0.0)
                card = make_bank_card(bank=bank_name, account_number=account_number, owner_id=c["id"])
                wallet = get_item(c, "wallet")
                if wallet:
                    from systems.containers import add_to_container
                    add_to_container(wallet, card)
                else:
                    add_item(c, card)
                story["summary"] += f" Opened a new account at {bank_name}."
        elif reason == "loan_application" and bank_name:
            # Solo, unsecured application, requesting the max this
            # character alone qualifies for. book_appointment's action
            # shape (target + free-text reason, see action_registry.py)
            # has no field for a requested amount, a co-borrower, or
            # pledged collateral -- so neither a true joint application
            # nor a secured loan (loans.py::take_loan() supports both)
            # can reach the AI through this generic booking flow yet;
            # this is the solo/unsecured path that's actually wired end
            # to end today.
            from systems.loans import take_loan, max_loan_amount, _eligible as loan_eligible
            from systems.personal_items import get_item
            amount = max_loan_amount([c], "unsecured")
            wallet = get_item(c, "wallet")
            target = next((i for i in (wallet.get("items", []) if wallet else [])
                           if i.get("object_type") == "bank_card"), None)
            loan = None
            if target and amount > 0 and loan_eligible([c], "unsecured"):
                from systems.banking import bank_key_for_name
                loan = take_loan(world, [c], bank_name, "unsecured", amount,
                                  bank_key_for_name(target["bank"]), target["account_number"])
            if loan:
                story["summary"] += (f" Took out a ${amount:.0f} loan from {bank_name} "
                                      f"(${loan['monthly_payment']:.0f}/month).")
            else:
                story["summary"] += f" {bank_name} declined the loan application."
    elif reason in ("attend_game", "play_local_match"):
        from systems.sports import resolve_attendee_return
        note = resolve_attendee_return(c, world)
        if note:
            story["summary"] += " " + note

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

    # Chained multi-stop outing (see send_offgrid_chain()): this leg's story/
    # money/treatment effects just applied above like any other, but instead
    # of heading home, go straight from this stop to the next one -- still
    # off the grid, no drive/bus-ride home in between. travel_mode/
    # travel_state are left exactly as they are (still "car"/"bus", still
    # hidden) so the eventual real trip home, once the queue empties, is the
    # only physical leg simulated.
    queue = c.get("offgrid_queue")
    if queue:
        next_reason, next_minutes = queue[0]
        c["offgrid_queue"] = queue[1:]
        _send_offgrid_immediate(c, world, next_reason, next_minutes)
        return
    c.pop("offgrid_queue", None)

    # Errand is narratively complete, but a travel-mode character (see
    # travel.py) isn't home yet.
    if c.get("travel_mode") == "car":
        # Driving back still defers the visible reveal to that leg --
        # nowhere sensible to place them mid-drive. A character who drove
        # themselves off-grid always returns via that same car (there's
        # only ever one car per household, claimed exclusively for the
        # whole trip -- see travel.py::begin_travel()) -- no change here.
        from systems.travel import _start_driving_back
        _start_driving_back(c, world)
    elif c.get("travel_mode") == "bus":
        # A bus/no-car departure gets a real return-mode evaluation
        # (taxi / a contact's car / the default bus) instead of always
        # assuming the bus back -- see _resolve_return_mode() below.
        mode = _resolve_return_mode(c, world)
        if mode == "taxi" and _return_via_taxi(c, world):
            pass
        elif mode == "friend" and _return_via_friend(c, world):
            pass
        else:
            # Default/fallback -- unchanged existing behavior.
            from systems.vehicles import bus_stop
            stop = bus_stop(world)
            if stop:
                c["x"], c["y"] = stop["x"], stop["y"]
                c["travel_hidden"] = False
            c["travel_state"] = "awaiting_bus_arrival"
