import random, uuid
from brain.memory import store_memory
from core.event_bus import emit
from systems.offgrid import send_offgrid


# Real day-scale timing, mirroring jobs.py's own _days_to_ticks() /
# TICKS_PER_DAY convention (1 tick = 1 real second, TICK_RATE_SECONDS=1.0)
# -- law.py's old constants (40-400) were bare small ints left over from an
# earlier, different tick scale, making the whole arrest-to-release cycle
# take ~2-3 real MINUTES instead of the real days/weeks it should.
TICKS_PER_DAY = 86400


def _days_to_ticks(lo_days, hi_days):
    return int(random.randint(lo_days, hi_days) * TICKS_PER_DAY)


# Real day-count ranges per crime type -- preserves this table's original
# relative severity ordering (domestic_disturbance shortest, murder_for_hire
# longest) but now lands on plausible real-world day counts instead of
# straight-line-scaled seconds. Sentence length is rolled once, at the
# guilty verdict (see process_trials()), not re-rolled per lookup.
_SENTENCE_DAYS = {
    "domestic_disturbance": (1, 2),
    "property_damage":      (2, 5),
    "assault":               (5, 14),
    # Criminal-career crime types (see systems/crime.py) -- proportional
    # to real-world severity, matching this table's existing spirit.
    "burglary":              (7, 20),
    "car_theft":             (5, 15),
    "robbery":               (15, 40),
    "drug_dealing":          (3, 10),
    "fraud":                 (2, 8),
    "hacking":               (1, 6),
    "arson":                 (30, 80),
    "murder_for_hire":       (60, 120),
    "gang_violence":         (20, 50),
    "drug_production":       (15, 45),
    "smuggling":              (7, 20),
    "counterfeit_money":      (3, 10),
    "bribery":               (10, 30),
    # Tier 3 of systems/government_debt.py's tax-filing escalation (a
    # missed filing deadline, ignored through a mail notice and an
    # in-person IRS visit) -- modest relative to the career-crime types
    # above, matching real-world tax-evasion sentencing being on the
    # lighter end.
    "tax_evasion":            (1, 5),
}
_DEFAULT_SENTENCE_DAYS = (2, 8)


def _roll_sentence_ticks(crime):
    lo, hi = _SENTENCE_DAYS.get(crime, _DEFAULT_SENTENCE_DAYS)
    return _days_to_ticks(lo, hi)

# Crime types systems/crime.py's shared shift framework (and its bespoke
# mechanics) can produce -- fed into the same incident/arrest pipeline
# every other crime type already uses below. "tax_evasion" is the one
# exception, sourced from systems/government_debt.py's escalation
# instead of crime.py, but reaching this exact same pipeline.
_CRIME_CAREER_TYPES = (
    "burglary", "car_theft", "robbery", "drug_dealing",
    "fraud", "hacking", "arson", "murder_for_hire",
    "gang_violence", "drug_production", "smuggling", "counterfeit_money",
    "bribery", "tax_evasion",
)


# No-bail crime types -- violent/severe enough that the character is held
# in custody the whole way to trial instead of walking free. Everything
# else is bailable (stays free, a real flat cost is deducted, forfeited on
# failure to appear -- see process_prison_reporting()). "failure_to_appear"
# itself always lands here too, regardless of the original crime's own
# bail eligibility -- see process_prison_reporting()'s own comment.
_NO_BAIL_CRIMES = ("assault", "robbery", "arson", "murder_for_hire", "gang_violence",
                    "failure_to_appear")

# Flat bail amount per bailable crime type -- a documented approximation,
# not a bail-bondsman economy. Anything not listed (including every
# no-bail type, which never reaches this table) falls back to
# _DEFAULT_BAIL.
_BAIL_AMOUNT = {
    "domestic_disturbance": 500,
    "property_damage":      800,
    "burglary":              2500,
    "car_theft":             2000,
    "drug_dealing":          1500,
    "fraud":                 3000,
    "hacking":               2000,
    "drug_production":       5000,
    "smuggling":             4000,
    "counterfeit_money":     2500,
    "bribery":               5000,
    "tax_evasion":           1000,
}
_DEFAULT_BAIL = 1000


def schedule_trial(c, world, crime):
    trial_wait = _days_to_ticks(3, 14)
    case = {
        "id":           f"case_{uuid.uuid4().hex[:6]}",
        "character_id": c["id"],
        "crime":        crime,
        "trial_tick":   world["tick"] + trial_wait,
        "status":       "scheduled",
    }
    world.setdefault("court_cases", []).append(case)

    if crime in _NO_BAIL_CRIMES:
        # Real custody at the actual arrest moment -- held, not free,
        # until the verdict. send_offgrid() re-stamps this same off-grid
        # span straight into the sentence on a guilty verdict (see
        # process_trials()) rather than calling it a second time, since
        # it no-ops if already off-grid.
        send_offgrid(c, world, "held_pending_trial", trial_wait // 60)
        c["legal"]["status"] = "held_pending_trial"
        store_memory(c, f"Was arrested for {crime} and held in custody pending trial.", .9,
                     ["law", "arrest", "custody"], "legal", world["tick"])
    else:
        bail = _BAIL_AMOUNT.get(crime, _DEFAULT_BAIL)
        household = world.get("households", {}).get(c.get("household_id"))
        if household:
            household["wealth"] = household.get("wealth", 0) - bail
        case["bail_amount"] = bail
        c["legal"]["status"] = "awaiting_trial_bail"
        store_memory(c, f"Was charged with {crime}, posted ${bail} bail, and released pending trial.", .9,
                     ["law", "arrest", "bail"], "legal", world["tick"])

    c["legal"]["trial_tick"] = case["trial_tick"]
    # This is the actual arrest moment (being charged, held or bailed) --
    # previously nothing ever emitted character_arrested, so the reputation
    # system's "-0.12 arrested" weight (and its already-subscribed handler,
    # core/event_handlers.py::_on_character_arrested) was unreachable.
    emit("character_arrested", {"character_id": c["id"], "crime": crime})
    emit("trial_scheduled", {"character_id": c["id"], "case_id": case["id"], "crime": crime})

    # Criminal-career fallout (see systems/crime.py) -- an arrest is a
    # real setback for standing, not just jail time.
    try:
        from systems.crime import apply_arrest_penalty
        apply_arrest_penalty(c, world)
    except Exception:
        pass


def maybe_arrest_from_incidents(world):
    for inc in world.get("incidents", []):
        if inc.get("arrest_checked"):
            continue
        itype = inc["type"]
        if itype in ("assault", "domestic_disturbance"):
            # These two route through emergency.py::auto_report_incidents'
            # real witness/self-report roll -- no call means no police
            # response at all (a genuinely unwitnessed incident can just
            # stay quiet), so arrest can't be checked until it's actually
            # been reported, or confirmed nobody ever will.
            if inc.get("unreported_final"):
                inc["arrest_checked"] = True
                continue
            if not inc.get("reported"):
                continue
        inc["arrest_checked"] = True
        # "crime" dropped -- nothing in the codebase ever creates an
        # incident of that type (see systems/emergency.py's incident
        # producers); "property_damage" added so vandalism reported via the
        # destroy action can actually lead to an arrest, not just a logged,
        # consequence-free incident.
        if inc["type"] in ("domestic_disturbance", "assault", "property_damage") + _CRIME_CAREER_TYPES:
            solve_rate = world["environment"].get("crime_solve_rate", .5)
            if inc["type"] == "bribery":
                # More likely to get caught the more corrupt they already
                # are (Confirmed Decision #11b of the drug-economy plan) --
                # a deeper paper/leverage trail, not a flat rate.
                suspect_id = inc.get("participants", [None])[0]
                suspect = world["characters"].get(suspect_id) if suspect_id else None
                if suspect:
                    solve_rate = min(0.95, solve_rate + suspect.get("corruption", 0.0) / 200.0)
            if random.random() < solve_rate:
                for cid in inc.get("participants", [])[:1]:
                    c = world["characters"].get(cid)
                    if c and c["legal"]["status"] == "free":
                        schedule_trial(c, world, inc["type"])


def process_trials(world):
    for case in list(world.get("court_cases", [])):
        if world["tick"] < case["trial_tick"] or case.get("status") != "scheduled":
            continue
        c = world["characters"].get(case["character_id"])
        if not c:
            continue
        guilty = random.random() < world["environment"].get("crime_solve_rate", .5)
        if guilty:
            sentence = _roll_sentence_ticks(case["crime"])
            was_held = c["legal"].get("status") == "held_pending_trial"
            if was_held:
                # Already off-grid on "held_pending_trial" -- send_offgrid()
                # no-ops if already off-grid, so the SAME span is re-stamped
                # straight into the sentence rather than called a second
                # time. Must run before legal.status flips to "jailed" so
                # process_return()'s own "jail" branch (which fires on
                # return_tick) sees a consistent reason the whole way.
                c["off_grid_reason"] = "jail"
                c["return_tick"]     = world["tick"] + sentence
                c["legal"]["status"]    = "jailed"
                c["legal"]["jail_until"] = world["tick"] + sentence
                c["status"]["reputation"] -= .25
                c["legal"].setdefault("record", []).append({"crime": case["crime"], "tick": world["tick"]})
                store_memory(c, f"Was found guilty of {case['crime']} and sent to jail.", .95,
                             ["law", "jail", "shame"], "legal", world["tick"])
                emit("character_jailed", {"character_id": c["id"], "crime": case["crime"],
                                          "jail_until": c["legal"]["jail_until"]})
            else:
                # Was out on bail -- stays free a little longer, gets a
                # real mail notice telling them which day to report,
                # instead of an instant teleport to jail.
                report_by_tick = world["tick"] + _days_to_ticks(3, 10)
                c["legal"]["status"]         = "sentenced_awaiting_report"
                c["legal"]["report_by_tick"] = report_by_tick
                c["legal"]["report_sentence"] = sentence
                c["status"]["reputation"] -= .25
                c["legal"].setdefault("record", []).append({"crime": case["crime"], "tick": world["tick"]})
                store_memory(c, f"Was found guilty of {case['crime']} and must report to prison.", .95,
                             ["law", "jail", "shame"], "legal", world["tick"])
                household = world.get("households", {}).get(c.get("household_id"))
                if household:
                    from systems.mail import create_personal_letter
                    create_personal_letter(
                        household, world, c["id"], "prison_report_notice",
                        {
                            "crime": case["crime"],
                            "sentence_days": round(sentence / TICKS_PER_DAY, 1),
                            "report_by_tick": report_by_tick,
                            "facility": "the county correctional facility",
                        },
                        sender_label="Department of Corrections",
                        requires_response=True,
                        reply_by_tick=report_by_tick,
                    )
                emit("character_sentenced_awaiting_report", {
                    "character_id": c["id"], "crime": case["crime"], "report_by_tick": report_by_tick,
                })
        else:
            was_held = c["legal"].get("status") == "held_pending_trial"
            c["legal"]["status"] = "free"
            if was_held:
                # Was held in custody the whole way to a not-guilty verdict
                # -- release immediately rather than leaving them off-grid
                # on a "held_pending_trial" span with no one left to
                # advance it.
                c["off_grid"]        = False
                c["off_grid_reason"] = None
                c["return_tick"]     = None
            store_memory(c, f"Was found not guilty of {case['crime']}.", .75,
                         ["law", "relief"], "legal", world["tick"])
            emit("character_acquitted", {"character_id": c["id"], "crime": case["crime"]})
        case["status"] = "resolved"


def process_jail(c, world):
    if (c["legal"].get("status") == "jailed" and
            world["tick"] >= (c["legal"].get("jail_until") or 0)):
        c["legal"]["status"] = "free"
        c["off_grid"]        = False
        c["off_grid_reason"] = None
        store_memory(c, "Was released from jail.", .9,
                     ["law", "jail", "release"], "legal", world["tick"])
        emit("character_released", {"character_id": c["id"]})


# How much longer, past report_by_tick, a sentenced-and-bailed character can
# go unreachable before this counts as fleeing rather than just a delay.
_REPORT_GRACE_TICKS = _days_to_ticks(2, 5)


def process_prison_reporting(world):
    """Day-gated sweep (mirrors reminders.py's own shape) -- checks every
    'sentenced_awaiting_report' character past their report_by_tick and
    actually sends them off to serve the sentence, exactly like jail
    itself finally teleporting someone did before this plan, just now on
    the real, mail-notified day instead of the instant of conviction. A
    character who blows straight past the deadline PLUS a real grace
    period creates a real failure_to_appear incident, feeding the same
    arrest pipeline as any other crime -- their next arrest always lands
    in the no-bail custody path regardless of the original crime."""
    stamp_key = "_last_prison_reporting_day"
    today = (world.get("calendar") or {}).get("day_of_year") or (world["tick"] // TICKS_PER_DAY)
    if world.get(stamp_key) == today:
        return
    world[stamp_key] = today

    for c in world.get("characters", {}).values():
        if c.get("legal", {}).get("status") != "sentenced_awaiting_report":
            continue
        report_by = c["legal"].get("report_by_tick") or 0
        if world["tick"] < report_by:
            continue
        if c.get("off_grid"):
            # Off-grid on something else at this exact moment (rare,
            # self-resolving) -- retry on the next day-gated pass.
            continue
        if world["tick"] >= report_by + _REPORT_GRACE_TICKS:
            # Blew clean past the deadline and the grace period -- a real
            # failure-to-appear incident, feeding maybe_arrest_from_incidents
            # exactly like any other crime type.
            inc = {
                "id":           f"inc_{uuid.uuid4().hex[:6]}",
                "type":         "failure_to_appear",
                "offender_id":  c["id"],
                "participants": [c["id"]],
                "location":     {"x": c.get("x", 0), "y": c.get("y", 0)},
                "reported":     True,
                "arrest_checked": False,
                "tick":         world["tick"],
            }
            world.setdefault("incidents", []).append(inc)
            c["legal"]["status"] = "free"
            c["legal"]["fled_sentence"] = True
            store_memory(c, "Never showed up to serve their sentence.", .9,
                         ["law", "jail", "fugitive"], "legal", world["tick"])
            emit("incident_created", {"incident_id": inc["id"], "type": inc["type"]})
            continue
        sentence = c["legal"].get("report_sentence") or _DEFAULT_SENTENCE_DAYS[0] * TICKS_PER_DAY
        send_offgrid(c, world, "jail", sentence // 60)
        c["legal"]["status"]    = "jailed"
        c["legal"]["jail_until"] = world["tick"] + sentence
        store_memory(c, "Reported to prison to serve their sentence.", .9,
                     ["law", "jail"], "legal", world["tick"])
        emit("character_jailed", {"character_id": c["id"], "crime": c["legal"].get("record", [{}])[-1].get("crime"),
                                  "jail_until": c["legal"]["jail_until"]})


# So maybe_arrest_from_incidents()'s type filter also recognizes a real
# failure_to_appear incident (see process_prison_reporting() above).
_CRIME_CAREER_TYPES = _CRIME_CAREER_TYPES + ("failure_to_appear",)
