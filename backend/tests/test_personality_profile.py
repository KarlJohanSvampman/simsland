"""
A character's persona (systems/personality_profile.py, api/persona.py): the trait change log, traits that show in a
mood, speech quirks, insecurities and what their confidence rests on.

    - any change to a character's traits is logged -- with the reason when the system that made it says why (picked up
      from a friend, conditioning, pushed out by a newer one), and as "the cause wasn't recorded" otherwise
    - a change by hand (the inspector's Persona tab) is logged as such
    - the model is told the mood's traits only while the character is in that mood, plus the quirks, insecurities and
      confidence sources
    - a character made from a template starts with the template's

Run inside the backend container:   python tests/test_personality_profile.py
"""

import os
import sys

os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


from house_world import make_world
from systems.schema_defaults import ensure_world_defaults
from systems import personality_profile as pp

w = make_world()
w["tick"] = 5000
w["calendar"] = {"year": 2026, "month": 11, "day": 2, "hour": 14, "minute": 5, "second": 0, "minute_of_day": 845, "weekday": "Monday"}
ensure_world_defaults(w)
j = w["characters"]["joseph"]
j["traits"] = ["shy", "honest"]

# ---- the log ---------------------------------------------------------------------------------------------------------
pp.track(j, w)
check("first look at a character: what they start with is not a change", not j.get("trait_log"))
j["traits"].append("grumpy")
j["traits"].remove("shy")
w["tick"] += 10
pp.track(j, w)
e = (j.get("trait_log") or [{}])[-1]
check("a change made without saying why is still caught", e.get("added") == ["grumpy"] and e.get("removed") == ["shy"]
      and "wasn't recorded" in e.get("why", "") and e.get("when", "").startswith("Monday 2026-11-02 14:05"), str(e))
pp.track(j, w)
check("... and logged once", len(j["trait_log"]) == 1)

# peer influence says why (systems/peer_influence.py)
from systems import peer_influence as pi
s = w["characters"]["susan"]
j["personality_traits"] = []
entry = {"source_person_id": "susan", "trait": "sarcastic", "strength": 1.0, "exposure_count": 12, "last_tick": w["tick"]}
pi._make_room_for_trait = lambda observer, trait, world: True
import systems.trait_budget as tb
tb.try_consume_learn_slot = lambda observer: True
pi._finalize_trait_promotion(j, entry, w)
e = j["trait_log"][-1]
check("picked up from a friend: logged, saying from whom", e.get("added") == ["sarcastic"] and e.get("list") == "personality_traits"
      and "Susan" in e.get("why", ""), str(e))
pp.track(j, w)
check("... and the watcher doesn't log it a second time", len(j["trait_log"]) == 2, str(j["trait_log"]))

# by hand
out = pp.update(j, w, {"traits": ["grumpy", "honest", "witty"]})
e = j["trait_log"][-1]
check("changed by hand in the Persona tab: logged as set by hand", e.get("added") == ["witty"] and e.get("why") == "set by hand"
      and out["traits"] == ["grumpy", "honest", "witty"], str(e))

# ---- mood traits and the other lists in the prompt -------------------------------------------------------------------
pp.update(j, w, {"mood_traits": {"irritable": ["snappy", "sarcastic"], "cheerful": ["silly"]},
                 "speech_quirks": ["says 'basically' a lot"], "insecurities": ["his receding hairline"],
                 "confidence_sources": ["being good at his job"]})
j["mood"] = None
lines = " ".join(pp.prompt_lines(j))
check("no mood: no mood traits in the prompt, but the quirks, insecurities and confidence are",
      "snappy" not in lines and "basically" in lines and "receding hairline" in lines and "good at his job" in lines, lines)
j["mood"] = {"id": "irritable", "name": "Irritable"}
lines = " ".join(pp.prompt_lines(j))
check("irritable: the model is told he is also snappy and sarcastic", "irritable mood" in lines and "snappy, sarcastic" in lines, lines)
check("... and his effective traits include them", "snappy" in pp.effective_traits(j) and "honest" in pp.effective_traits(j))
data = pp.read(j, w)
check("the editor gets every mood there is, with the current one marked",
      len(data["moods"]) == len(w["definitions"].get("mood_templates") or {}) > 10 and data["current_mood"] == "irritable")

# ---- templates -------------------------------------------------------------------------------------------------------
c = {"id": "new"}
pp.apply_template(c, {"speech_quirks": ["lisps"], "insecurities": ["height"], "mood_traits": {"sad": ["withdrawn"], "content": []}})
check("a character from a template starts with its persona", c["speech_quirks"] == ["lisps"] and c["mood_traits"] == {"sad": ["withdrawn"]}, str(c))

from core.entity_versions import COLD_KEYS
check("the trait log is not sent with every update (read on demand)", "trait_log" in COLD_KEYS)

print()
if failures:
    print(f"FAILED: {len(failures)}")
    sys.exit(1)
print("all passed")
