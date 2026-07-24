import random, uuid
from brain.memory import store_memory
from systems.offgrid_narrative import request_offgrid_summary, roll_normalcy, _find_trip_cover_lie

# ── LLM narrator pilot ──────────────────────────────────────────────────────
# First category migrated off the procedural _story() dice-roller onto the
# real narrator pipeline (systems/offgrid_narrative.py) -- chosen because it
# needs no new data plumbing (no coworker/venue/inmate lookups to build),
# so the pipeline itself gets proven before other categories migrate in
# later rounds. Everything else still resolves via _story() below.
_PILOT_CATEGORIES = {"shopping", "leisure", "gym", "cafe", "job_search"}
_PILOT_NORMALCY_WEIGHTS = {"normal": 0.85, "notable": 0.13, "rare": 0.02}
_VENUE_FLAVOR = {
    "shopping":   ["the mall", "a corner store", "a big-box store", "an outdoor market"],
    "leisure":    ["a park", "a movie theater", "downtown", "a friend's neighborhood"],
    "gym":        ["the gym"],
    "cafe":       ["a coffee shop", "a diner"],
    "job_search": ["a job fair", "a few offices downtown", "a staffing agency"],
}


def _shopping_leisure_details(c, world, reason):
    """Stage-1 detail generator for the pilot category -- deliberately thin,
    since no venue/participant data exists for these reasons today
    (maybe_go_offgrid() sends characters off with only a reason string)."""
    return {
        "reason": reason,
        "venue_flavor": random.choice(_VENUE_FLAVOR.get(reason, ["somewhere in town"])),
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


def send_offgrid(c, world, reason, duration):
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
    """Send a character off-grid for a doctor/hospital visit, frequency
    scaled by systems/health.py::_compute_doctor_visits_needed's severity-
    weighted target (see process_return's "doctor"/"hospital" branch below
    for the treatment applied on return)."""
    if c.get("off_grid") or c.get("conversation"):
        return
    if not c.get("alive", True) or c.get("posture") in ("incapacitated", "crawling"):
        return
    needed = c.get("health_state", {}).get("doctor_visits_needed", 0)
    if needed <= 0:
        return
    if random.random() < 0.002 * needed:
        reason = "hospital" if needed >= 4 else "doctor"
        duration = 60 if reason == "hospital" else 20
        send_offgrid(c, world, reason, duration)


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

    if reason in _PILOT_CATEGORIES:
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
        details     = _shopping_leisure_details(c, world, reason)
        normalcy    = roll_normalcy(_PILOT_NORMALCY_WEIGHTS)

        story = request_offgrid_summary(
            c, world, reason, details, normalcy,
            enforced_cover_story=cover_story,
        )
        if story is None:
            # LLM unreachable/failed -- graceful fallback to the existing
            # procedural narrator.
            story = _story(c, world, reason)
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
        # blade/blunt/burn injuries and blood-loss/pain signals previously
        # had zero connection to this mechanic, so a character rushed to
        # hospital for a stabbing came back just as stabbed. Only the
        # acute-trauma cluster is touched here (unconscious/bleeding/
        # agonizing_pain, plus the injuries list itself) -- heart_attack/
        # stroke/coma/cardiac_arrest each have their own dedicated
        # resolution arcs (resolve_heart_attack/tick_stroke/tick_coma) and
        # are left alone so this doesn't short-circuit that narrative.
        # Treatment is substantial but not total, so a severe enough wound
        # can still need a second visit rather than being trivialized.
        acute_treated = False
        if reason == "hospital":
            hs = c.setdefault("health_state", {})
            em = hs.setdefault("active_emergencies", {})
            for key in ("unconscious", "bleeding", "agonizing_pain"):
                if em.pop(key, None) is not None:
                    acute_treated = True
            for inj in hs.get("injuries", []):
                for field in ("bleeding_severity", "force", "severity"):
                    if inj.get(field, 0) > 0:
                        inj[field] = max(0, inj[field] - 0.6)
                        acute_treated = True
            if hs.get("total_blood_lost", 0) > 0:
                hs["total_blood_lost"] = max(0, hs["total_blood_lost"] - 0.5)
                acute_treated = True
            if hs.get("pain", 0) > 0:
                hs["pain"] = max(0, hs["pain"] - 40)
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

    handle_return_transport(c, world)

    # Only the PUBLIC summary goes into shared memory and world events
    public_story = {k: v for k, v in story.items() if k != "private"}
    store_memory(c, story["summary"], .75, ["offgrid"] + story["tags"],
                 "offgrid_story", world["tick"], story=public_story)
    world.setdefault("events", []).append({
        "id":           story["id"],
        "type":         "offgrid_story",
        "character_id": c["id"],
        "tick":         world["tick"],
        "story":        public_story,
    })
