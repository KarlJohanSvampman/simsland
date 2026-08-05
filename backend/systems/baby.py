"""
systems/baby.py
───────────────
Models infant and early-childhood simulation:

  • Baby needs (hunger, sleep, comfort, stimulation)  → crying when unmet
  • Breastfeeding — mother required nearby for first 6 months
  • Maternity leave — mother stays home for ~6 months post-birth
  • Development stages with age milestones:
        newborn   0–3 months
        infant    3–12 months
        crawler   5–10 months  (overlaps infant)
        toddler   12–24 months
        child     2–5 years
        preschool 3–5 years    (if enrolled)
        school    5+  years    (if enrolled)
  • Developmental milestones: first_smile, rolls_over, sits_up, crawls,
        first_steps, first_words, sentences, potty_trained
  • Prenatal prep tasks scheduled during pregnancy:
        - Check-ups per OB schedule (monthly → biweekly → weekly)
        - Anatomy ultrasound at week 20
        - Choose & enroll kindergarten (parents decide during pregnancy)
        - Buy essential baby gear

Tick cadence
────────────
  tick_baby_hourly(world)   — decay needs, trigger/clear crying
  tick_baby_daily(world)    — breastfeeding, maternity leave
  tick_baby_weekly(world)   — dev stage, milestones, enrollment
  tick_prenatal_prep(c, preg, world) — schedule visits (called from tick_pregnancy)
"""

import random
import uuid

TICKS_PER_HOUR   = 60
TICKS_PER_DAY    = TICKS_PER_HOUR * 24
TICKS_PER_WEEK   = TICKS_PER_DAY  * 7
TICKS_PER_MONTH  = TICKS_PER_DAY  * 30

HUNGER_DECAY_PER_HOUR      = 0.12
SLEEP_DECAY_PER_HOUR       = 0.08
COMFORT_DECAY_PER_HOUR     = 0.05
STIMULATION_DECAY_PER_HOUR = 0.04

CRY_THRESHOLD = 0.30

BREASTFEED_HUNGER_RESTORE  = 0.70
BREASTFEED_COMFORT_RESTORE = 0.25
MAX_BF_SESSIONS_DAY        = 10
BREASTFEED_MONTHS          = 6

MATERNITY_LEAVE_MONTHS     = 6

# (min_age_months, stage_id, locomotion_type, move_speed)
DEVELOPMENT_STAGES = [
    (0,   "newborn",   "lie_down", 0.00),
    (3,   "infant",    "lie_down", 0.00),
    (5,   "crawler",   "crawl",    0.01),
    (12,  "toddler",   "walk",     0.02),
    (24,  "child",     "walk",     0.035),
    (60,  "preschool", "walk",     0.040),
]

# (id, min_months, max_months, description)
MILESTONES = [
    ("first_smile",    1,   3,  "Smiled for the first time."),
    ("rolls_over",     3,   5,  "Rolled over unassisted."),
    ("sits_up",        5,   8,  "Sat up without support."),
    ("crawls",         6,   10, "Started crawling."),
    ("pulls_to_stand", 8,   12, "Pulled themselves to standing."),
    ("first_steps",    9,   15, "Took their first steps."),
    ("first_words",    10,  14, "Said their first word."),
    ("sentences",      18,  24, "Started forming short sentences."),
    ("potty_trained",  24,  36, "Became potty trained."),
]

# Prenatal visit schedule (week, visit_type) — deduplicated, sorted
def _build_prenatal_schedule():
    sched = (
        [(w, "routine_checkup")     for w in range(4, 13, 4)]   +
        [(w, "routine_checkup")     for w in range(16, 29, 4)]  +
        [(20, "anatomy_ultrasound")]                             +
        [(w, "routine_checkup")     for w in range(30, 37, 2)]  +
        [(w, "routine_checkup")     for w in range(37, 41, 1)]
    )
    seen, out = set(), []
    for item in sched:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return sorted(out, key=lambda x: x[0])

PRENATAL_SCHEDULE = _build_prenatal_schedule()

# ── Public API ────────────────────────────────────────────────────────────────

def init_baby_state(c):
    c.setdefault("age_months", 0.0)
    c.setdefault("development_stage", "newborn")
    c.setdefault("dev_milestones", {})
    c.setdefault("baby_needs", {
        "hunger": 0.80, "sleep": 0.80, "comfort": 0.80, "stimulation": 0.80,
    })
    c.setdefault("is_crying", False)
    c.setdefault("breastfeeding_state", {
        "active": True, "sessions_today": 0, "weaned": False,
    })


def init_prenatal_prep(c):
    c.setdefault("prenatal_prep", {
        "visits_scheduled":  [],
        "kindergarten_chosen": None,
        "kindergarten_tick": None,
        "gear_bought":  False,
        "gear_tick":    None,
    })


def spawn_child(mother, father_id, world):
    """Creates a newborn, adds to world, registers in family, returns child dict."""
    defs = world.get("definitions", {})

    try:
        from systems.character_gen import generate_character
        father = world.get("characters", {}).get(father_id) if father_id else None
        parent_values = [p["values"] for p in (mother, father) if p and p.get("values")]
        child = generate_character(defs, overrides={
            "age": 0, "age_months": 0.0,
            "sex": random.choice(["male", "female"]),
            "family_id": mother.get("family_id"),
            "parent_values": parent_values or None,
        })
    except Exception:
        child = {
            "id": str(uuid.uuid4()),
            "age": 0, "age_months": 0.0,
            "sex": random.choice(["male", "female"]),
            "family_id": mother.get("family_id"),
        }

    child["id"]               = str(uuid.uuid4())
    child["age"]              = 0
    child["age_months"]       = 0.0
    child["home_id"]          = mother.get("home_id")
    child["current_location"] = mother.get("current_location") or mother.get("home_id")
    child["mother_id"]        = mother.get("id")
    child["father_id"]        = father_id

    _assign_child_name(child, mother, defs)
    init_baby_state(child)

    world.setdefault("characters", {})[child["id"]] = child
    _register_in_family(child, mother, father_id, world)

    try:
        from core.events import emit
        emit("child_born", {
            "child_id":  child["id"],
            "mother_id": mother.get("id"),
            "father_id": father_id,
            "tick":      world.get("tick", 0),
        }, world)
    except Exception:
        pass

    return child


def tick_baby_hourly(world):
    """Decay baby needs + trigger/clear crying. Call every tick."""
    for c in world.get("characters", {}).values():
        if c.get("age", 99) > 3:
            continue
        stage = c.get("development_stage", "child")
        if stage not in ("newborn", "infant", "crawler", "toddler"):
            continue

        needs = c.setdefault("baby_needs", {
            "hunger": 0.80, "sleep": 0.80, "comfort": 0.80, "stimulation": 0.80,
        })
        needs["hunger"]      = max(0.0, needs["hunger"]      - HUNGER_DECAY_PER_HOUR)
        needs["sleep"]       = max(0.0, needs["sleep"]       - SLEEP_DECAY_PER_HOUR)
        needs["comfort"]     = max(0.0, needs["comfort"]     - COMFORT_DECAY_PER_HOUR)
        needs["stimulation"] = max(0.0, needs["stimulation"] - STIMULATION_DECAY_PER_HOUR)

        was_crying = c.get("is_crying", False)
        c["is_crying"] = min(needs.values()) < CRY_THRESHOLD
        if c["is_crying"] and not was_crying:
            _notify_nearby_parents(c, world)


def tick_baby_daily(world):
    """Daily: breastfeeding schedule, maternity leave, auto-feed if caregiver present."""
    tick = world.get("tick", 0)
    for c in world.get("characters", {}).values():
        if c.get("age", 99) > 3:
            continue
        stage = c.get("development_stage", "child")
        if stage not in ("newborn", "infant", "crawler", "toddler"):
            continue

        bf = c.setdefault("breastfeeding_state", {
            "active": True, "sessions_today": 0, "weaned": False,
        })
        bf["sessions_today"] = 0

        if c.get("age_months", 0) >= BREASTFEED_MONTHS and not bf.get("weaned"):
            bf["weaned"] = True
            bf["active"] = False

        mother = _find_mother(c, world)
        if mother:
            _check_maternity_leave(mother, tick)
            # NOTE: actual breastfeeding is an active interaction the mother
            # must choose to perform — see action_router "breastfeed" handler.
            # We only do a passive comfort hold here if mother is co-located.
            needs = c.setdefault("baby_needs", {})
            if c.get("is_crying") and needs.get("comfort", 1.0) < CRY_THRESHOLD:
                same_loc = (mother.get("current_location") == c.get("current_location"))
                if same_loc:
                    needs["comfort"] = min(1.0, needs.get("comfort", 0) + 0.35)


def tick_baby_weekly(world):
    """Weekly: advance age_months, stage transitions, milestones, enrollment."""
    tick = world.get("tick", 0)
    for c in world.get("characters", {}).values():
        if c.get("age", 99) > 6:
            continue
        stage = c.get("development_stage")
        if stage not in ("newborn","infant","crawler","toddler","child","preschool"):
            continue

        c["age_months"] = c.get("age_months", 0.0) + (7.0 / 30.0)
        c["age"]        = round(c["age_months"] / 12.0, 2)

        _check_stage_transition(c, c["age_months"], tick, world)
        _check_milestones(c, c["age_months"], tick, world)
        _check_kindergarten_enrollment(c, c["age_months"], tick, world)


def tick_prenatal_prep(c, preg, world):
    """Weekly: schedule OB visits, prompt gear buying + kindergarten choice."""
    init_prenatal_prep(c)
    prep  = c["prenatal_prep"]
    weeks = preg.get("weeks", 0)
    tick  = world.get("tick", 0)

    for (w, vtype) in PRENATAL_SCHEDULE:
        already = any(v["week"] == w for v in prep["visits_scheduled"])
        if not already and weeks >= w - 1:
            due_tick = tick + TICKS_PER_WEEK
            prep["visits_scheduled"].append({
                "week": w, "type": vtype,
                "tick_due": due_tick, "completed": False,
            })
            _add_calendar_event(c, vtype, due_tick, world)

    if weeks >= 20 and not prep.get("gear_bought"):
        prep["gear_bought"] = True
        prep["gear_tick"]   = tick
        _schedule_baby_gear_shopping(c, world)

    if weeks >= 30 and prep.get("kindergarten_chosen") is None:
        _prompt_kindergarten_choice(c, prep, world)


def get_baby_context(c, world):
    lines = []
    stage = c.get("development_stage")
    if not stage or stage not in ("newborn","infant","crawler","toddler","child","preschool"):
        return lines

    age_months = c.get("age_months", 0.0)
    needs = c.get("baby_needs", {})

    if age_months < 24:
        cry_str = "Currently crying — needs attention." if c.get("is_crying") else "Settled for now."
        lines.append(f"{c.get('name','Baby')} is {age_months:.0f} months old ({stage}). {cry_str}")
        if needs.get("hunger", 1.0) < CRY_THRESHOLD:
            lines.append("Baby is hungry.")
        if needs.get("sleep", 1.0) < CRY_THRESHOLD:
            lines.append("Baby is overtired.")
    else:
        lines.append(f"Child is {age_months/12:.1f} years old, stage: {stage}.")

    milestones = c.get("dev_milestones", {})
    if milestones:
        recent = sorted(milestones.items(), key=lambda x: x[1])[-2:]
        for ms, _ in recent:
            lines.append(f"Recently reached milestone: {ms.replace('_',' ')}.")

    bf = c.get("breastfeeding_state", {})
    if bf.get("active") and not bf.get("weaned"):
        lines.append("Still breastfeeding.")

    return lines


def get_prenatal_context(c, world):
    prep = c.get("prenatal_prep")
    if not prep:
        return []
    lines = []
    upcoming = [v for v in prep.get("visits_scheduled", []) if not v["completed"]]
    if upcoming:
        nv = upcoming[0]
        lines.append(f"Next prenatal appointment: week {nv['week']} ({nv['type'].replace('_',' ')}).")
    if not prep.get("kindergarten_chosen"):
        lines.append("Kindergarten not yet chosen — worth deciding during pregnancy.")
    if not prep.get("gear_bought"):
        lines.append("Baby gear not yet purchased.")
    return lines


# ── Internal helpers ──────────────────────────────────────────────────────────

def _assign_child_name(child, mother, defs):
    name_reg = defs.get("name_registry", {})
    sex = child.get("sex", "male")
    first_list = name_reg.get("male_first" if sex == "male" else "female_first", ["Baby"])
    last_list  = name_reg.get("family_names", [mother.get("last_name", "Unknown")])
    child["first_name"] = random.choice(first_list)
    child["last_name"]  = mother.get("last_name", random.choice(last_list))
    child["name"] = f"{child['first_name']} {child['last_name']}"


def _register_in_family(child, mother, father_id, world):
    families = world.get("families", {})
    fam_id = mother.get("family_id")
    if not fam_id:
        return
    family = families.get(fam_id)
    if not family:
        return
    members = family.setdefault("members", [])
    if child["id"] not in members:
        members.append(child["id"])
    rels = family.setdefault("relations", {})
    m_id = mother.get("id")
    c_id = child["id"]
    rels[f"{m_id}:{c_id}"] = "parent"
    rels[f"{c_id}:{m_id}"] = "child"
    if father_id:
        rels[f"{father_id}:{c_id}"] = "parent"
        rels[f"{c_id}:{father_id}"] = "child"
        if father_id not in members:
            members.append(father_id)


def _find_mother(child, world):
    m_id = child.get("mother_id")
    if not m_id:
        return None
    return world.get("characters", {}).get(m_id)


def do_breastfeed(child, mother, world):
    """Public — called by action_router when mother performs 'breastfeed' interaction."""
    _do_breastfeed_impl(child, mother, world)


def _do_breastfeed_impl(child, mother, world):
    bf = child["breastfeeding_state"]
    if bf.get("weaned") or bf["sessions_today"] >= MAX_BF_SESSIONS_DAY:
        return
    needs = child.setdefault("baby_needs", {})
    needs["hunger"]  = min(1.0, needs.get("hunger",  0) + BREASTFEED_HUNGER_RESTORE)
    needs["comfort"] = min(1.0, needs.get("comfort", 0) + BREASTFEED_COMFORT_RESTORE)
    bf["sessions_today"] = bf.get("sessions_today", 0) + 1
    try:
        from core.events import emit
        emit("breastfeeding", {
            "child_id":  child.get("id"),
            "mother_id": mother.get("id"),
            "tick":      world.get("tick", 0),
        }, world)
    except Exception:
        pass


def _check_maternity_leave(mother, tick):
    until = mother.get("maternity_leave_until", 0)
    if tick < until:
        mother["on_maternity_leave"] = True
    else:
        mother.pop("on_maternity_leave", None)


def _notify_nearby_parents(child, world):
    try:
        from core.events import emit
        emit("baby_crying", {
            "child_id": child.get("id"),
            "location": child.get("current_location"),
            "needs":    child.get("baby_needs", {}),
            "tick":     world.get("tick", 0),
        }, world)
    except Exception:
        pass


def _check_stage_transition(c, age_months, tick, world):
    current = c.get("development_stage", "newborn")
    new_stage = current
    new_loco  = None
    new_speed = None

    for (min_months, stage_id, loco, speed) in reversed(DEVELOPMENT_STAGES):
        if age_months >= min_months:
            new_stage = stage_id
            new_loco  = loco
            new_speed = speed
            break

    if new_stage != current:
        c["development_stage"] = new_stage
        if new_loco:
            c["locomotion_type"] = new_loco
        if new_speed is not None and new_speed > 0:
            c["move_speed"] = new_speed
        try:
            from core.events import emit
            emit("development_stage_change", {
                "child_id":  c.get("id"),
                "old_stage": current,
                "new_stage": new_stage,
                "tick":      tick,
            }, world)
        except Exception:
            pass


def _check_milestones(c, age_months, tick, world):
    milestones = c.setdefault("dev_milestones", {})
    for (ms_id, min_m, max_m, desc) in MILESTONES:
        if ms_id in milestones:
            continue
        if age_months < min_m:
            continue
        window   = max(max_m - min_m, 1)
        progress = (age_months - min_m) / window
        prob     = min(1.0, progress * 0.15)
        if age_months >= max_m:
            prob = 1.0
        if random.random() < prob:
            milestones[ms_id] = tick
            _emit_milestone(c, ms_id, desc, tick, world)


def _emit_milestone(c, ms_id, desc, tick, world):
    try:
        from core.events import emit
        emit("child_milestone", {
            "child_id":    c.get("id"),
            "milestone":   ms_id,
            "description": desc,
            "tick":        tick,
        }, world)
    except Exception:
        pass
    # Joy boost for parents
    for pk in ("mother_id", "father_id"):
        pid = c.get(pk)
        if not pid:
            continue
        parent = world.get("characters", {}).get(pid)
        if parent:
            parent.setdefault("mood_states", {})["joyful_parent_moment"] = {
                "active": True, "intensity": 0.75, "onset_tick": tick,
            }


def _check_kindergarten_enrollment(c, age_months, tick, world):
    prep = _get_parent_prep(c, world)
    if not prep:
        return
    chosen_id = prep.get("kindergarten_chosen")
    if not chosen_id or c.get("school_enrollment"):
        return
    defs   = world.get("definitions", {})
    school = defs.get("school_templates", {}).get(chosen_id, {})
    min_months = school.get("age_range", [3, 5])[0] * 12
    if age_months >= min_months:
        c["school_enrollment"] = chosen_id
        try:
            from core.events import emit
            emit("kindergarten_enrolled", {
                "child_id":  c.get("id"),
                "school_id": chosen_id,
                "tick":      tick,
            }, world)
        except Exception:
            pass


def _get_parent_prep(child, world):
    mother = _find_mother(child, world)
    return mother.get("prenatal_prep") if mother else None


def _add_calendar_event(c, visit_type, tick_due, world):
    try:
        from systems.calendar_events import add_custom_event
        add_custom_event(c, {
            "id":       f"prenatal_{visit_type}_{tick_due}",
            "type":     "prenatal_visit",
            "title":    f"Prenatal: {visit_type.replace('_',' ')}",
            "tick":     tick_due,
            "mandatory": True,
        }, world)
    except Exception:
        pass


def _schedule_baby_gear_shopping(c, world):
    try:
        from core.events import emit
        emit("baby_gear_shopping_needed", {
            "character_id": c.get("id"),
            "items": ["baby_crib", "baby_carriage_a", "baby_clothes", "baby_formula"],
            "tick":  world.get("tick", 0),
        }, world)
    except Exception:
        pass


def _prompt_kindergarten_choice(c, prep, world):
    try:
        from core.events import emit
        defs    = world.get("definitions", {})
        options = list(defs.get("school_templates", {}).keys())
        emit("kindergarten_choice_needed", {
            "character_id": c.get("id"),
            "options":      options,
            "tick":         world.get("tick", 0),
        }, world)
    except Exception:
        pass
