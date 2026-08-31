import random, uuid
from brain.memory import store_memory
from core.event_bus import emit
from systems.offgrid import send_offgrid


# Flat per-crime-type jail sentence (ticks), replacing the previous
# hardcoded-80-for-everything constant -- still not per-incident-severity
# (that would need the incident's own severity/injury data threaded through
# schedule_trial/court_cases, a bigger data-model change), but at least a
# property_damage conviction no longer costs the same time as an assault.
_SENTENCE_LENGTH = {
    "domestic_disturbance": 40,
    "property_damage":      60,
    "assault":               120,
    # Criminal-career crime types (see systems/crime.py) -- proportional
    # to real-world severity, matching this table's existing spirit.
    "burglary":              90,
    "car_theft":             80,
    "robbery":               150,
    "drug_dealing":          70,
    "fraud":                 60,
    "hacking":               50,
    "arson":                 200,
    "murder_for_hire":       400,
    "gang_violence":         180,
    "drug_production":       150,
    "smuggling":              90,
    "counterfeit_money":      70,
    "bribery":               110,
}
_DEFAULT_SENTENCE = 80

# Crime types systems/crime.py's shared shift framework (and its bespoke
# mechanics) can produce -- fed into the same incident/arrest pipeline
# every other crime type already uses below.
_CRIME_CAREER_TYPES = (
    "burglary", "car_theft", "robbery", "drug_dealing",
    "fraud", "hacking", "arson", "murder_for_hire",
    "gang_violence", "drug_production", "smuggling", "counterfeit_money",
    "bribery",
)


def schedule_trial(c, world, crime):
    case = {
        "id":           f"case_{uuid.uuid4().hex[:6]}",
        "character_id": c["id"],
        "crime":        crime,
        "trial_tick":   world["tick"] + 40,
        "status":       "scheduled",
    }
    world.setdefault("court_cases", []).append(case)
    c["legal"]["status"]     = "awaiting_trial"
    c["legal"]["trial_tick"] = case["trial_tick"]
    store_memory(c, f"Was charged with {crime} and scheduled for trial.", .9,
                 ["law", "trial"], "legal", world["tick"])
    # This is the actual arrest moment (being charged and awaiting trial) --
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
            sentence = _SENTENCE_LENGTH.get(case["crime"], _DEFAULT_SENTENCE)
            # Must run before legal.status flips to "jailed" -- send_offgrid's
            # own guard no-ops if it's already "jailed", which previously
            # meant return_tick never got set here at all (process_return()
            # would then fire one tick after sentencing instead of waiting
            # out the sentence).
            send_offgrid(c, world, "jail", sentence)
            c["legal"]["status"]    = "jailed"
            c["legal"]["jail_until"] = world["tick"] + sentence
            c["status"]["reputation"] -= .25
            c["legal"].setdefault("record", []).append({"crime": case["crime"], "tick": world["tick"]})
            store_memory(c, f"Was found guilty of {case['crime']} and sent to jail.", .95,
                         ["law", "jail", "shame"], "legal", world["tick"])
            emit("character_jailed", {"character_id": c["id"], "crime": case["crime"],
                                      "jail_until": c["legal"]["jail_until"]})
        else:
            c["legal"]["status"] = "free"
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
