"""
systems/police_report.py -- what the police write down when they arrive, and what each person tells them.

When a responder of type "police" gets to the scene (systems/emergency.py::resolve) it files a report for the incident:

    {"id", "case_number", "tick", "when", "incident_id", "call_id", "type", "place", "officer", "caller_id", "offender_id",
     "victim_id", "topic", "fight_id", "summary", "findings", "evidence", "outcome", "interrogations": [...]}

`interrogations` holds one entry per person spoken to at the scene -- the offender, the victim, whoever saw or heard it, the person who
called it in: {"person_id", "name", "role", "stage", "tick", "stance", "statement"}. How each of them answers comes from who they are:
an offender admits, plays it down or denies by their own resolve (systems/offense_rationalization.py), a victim presses the case, or
declines to (more likely at home, with someone they care about) or is too frightened to say much, a witness saw it, only heard it,
or looks away from someone they like. What came out of it (`evidence`) moves the odds of the arrest and the verdict
(systems/law.py), and an arrested offender is questioned again at the station (`questioned_at_station`). Everyone spoken to keeps a memory
of it, which is what shows in the character's Events.
"""

import random
import uuid

from brain.memory import store_memory
from systems.fights import name_of, place_of, witnesses_of

REPORT_CAP = 200
OFFICERS = ["Svensson", "Lindgren", "Karlsson", "Berg", "Nyberg", "Holm", "Ekstrom", "Sandberg", "Forsberg", "Lund"]
POLICE_INCIDENTS = ("assault", "domestic_disturbance", "property_damage", "burglary")

# how the evidence adds up
ADMITS = 0.40
SAW_IT = 0.12               # per witness who saw it, at most MAX_WITNESS
MAX_WITNESS = 0.24
VICTIM_PRESSES = 0.10
VICTIM_DECLINES = -0.30
VICTIM_FRIGHTENED = -0.15
DENIES = -0.05


def _rng(*parts):
    return random.Random("|".join(str(p) for p in parts))


def _when(world):
    cal = world.get("calendar") or {}
    return f"{cal.get('weekday', '')} {cal.get('day', '')}/{cal.get('month', '')} {cal.get('hour', 0):02d}:{cal.get('minute', 0):02d}".strip()


def _rel(a, b_id):
    return (a.get("relationships") or {}).get(b_id) or {}


def reports(world):
    return world.setdefault("police_reports", [])


def find_report(world, report_id):
    return next((r for r in reports(world) if r["id"] == report_id), None)


def report_for(world, inc):
    return find_report(world, inc.get("police_report_id")) if inc.get("police_report_id") else None


# ---- how people answer ------------------------------------------------------------------------------------------------------------------
def _offender_says(world, off, victim, topic, rng, inc):
    from systems.offense_rationalization import _compute_resolve
    rat = off.get("_offense_rationalization") or {}
    resolve = rat.get("resolve") if rat.get("incident_id") == inc["id"] else _compute_resolve(off)
    v = name_of(world, victim["id"]) if victim else None
    roll = rng.random()
    if roll < (1 - resolve) * 0.9:
        stance = "admits"
        if v:
            text = rng.choice([
                f"I hit {v}. We were arguing about {topic} and I lost my temper. I won't make excuses.",
                f"Yes, it was me. {topic[:1].upper() + topic[1:]} had been building for a while and I snapped at {v}.",
                f"I put my hands on {v}. I regret it.",
            ])
        else:
            text = "Yes, it was me. I lost my head."
    elif roll < 0.85:
        stance = "minimises"
        if v:
            text = rng.choice([
                f"It got heated, about {topic}. {v} was in my face and it went too far on both sides.",
                f"We argued about {topic}. There was some pushing, that's all. Nobody was really hurt.",
                f"{v} is making more of it than it was. It was an argument that got out of hand.",
            ])
        else:
            text = "It was nothing, it got out of hand and it's over."
    else:
        stance = "denies"
        text = rng.choice([
            f"I never touched {v}. We argued, that's all." if v else "I never laid a hand on anyone.",
            "I don't know what you've been told. I didn't do anything.",
        ])
    return stance, text


def _victim_says(world, victim, off, topic, rng, inc):
    o = name_of(world, off["id"]) if off else "them"
    rel = _rel(victim, off["id"]) if off else {}
    fear = rel.get("fear", 0) or 0
    p_frightened = min(0.5, max(0.0, fear - 20) / 100.0)
    p_declines = 0.15 + (0.25 if off and victim.get("household_id") and victim.get("household_id") == off.get("household_id") else 0.0)
    p_declines += 0.1 if (rel.get("friendship", 0) or 0) > 30 else 0.0
    roll = rng.random()
    if roll < p_frightened:
        return "frightened", rng.choice([
            f"It was {o}. I... I don't want to say more. I just want it to stop.",
            f"{o} did it. Please, I don't want to get into the rest right now.",
        ])
    if roll < p_frightened + p_declines:
        return "declines", rng.choice([
            f"{o} and I were arguing about {topic}. It got out of hand, but I don't want to press charges.",
            f"It was {o}. It's between us and I'd rather leave it. I won't make a complaint.",
        ])
    return "presses", rng.choice([
        f"We were arguing about {topic} and {o} hit me. I want this on record.",
        f"{o} attacked me. It started over {topic}. I'm making a complaint.",
        f"{o} turned violent. I want it taken seriously.",
    ])


def _witness_says(world, w, off, victim, topic, rng):
    o = name_of(world, off["id"]) if off else "someone"
    v = name_of(world, victim["id"]) if victim else "someone"
    fond = off is not None and (_rel(w, off["id"]).get("friendship", 0) or 0) > 40
    roll = rng.random()
    if fond and roll < 0.4:
        return "evasive", "I didn't see what happened. I was looking the other way."
    if roll < 0.7:
        return "saw", rng.choice([
            f"I saw {o} hit {v}. They'd been shouting about {topic} first.",
            f"{o} went for {v}. It was over {topic}, you could hear it.",
        ])
    return "heard", rng.choice([
        f"I heard shouting about {topic}, then something hit the floor. I didn't see who started it.",
        f"I heard {o} and {v} going at each other, then it went quiet. I didn't see the rest.",
    ])


def _caller_says(world, caller, report_text, rng):
    return "caller", rng.choice([
        f"I called it in. {report_text} I thought someone could get hurt.",
        f"I was there and rang you straight away. {report_text}",
    ])


# ---- filing ---------------------------------------------------------------------------------------------------------------------------
def _incident_of(world, responder):
    return next((i for i in world.get("incidents", []) if i["id"] == responder.get("incident_id")), None)


def file_report(world, responder):
    """The police have arrived: write the report and take the statements. One report per incident."""
    inc = _incident_of(world, responder)
    if not inc or inc.get("type") not in POLICE_INCIDENTS:
        return None
    return report_for(world, inc) or _write(world, inc, responder.get("call_id"))


def ensure_report(world, inc):
    """The report for an incident the police have been called to, filing it late if they arrived before reports existed.
    None while they have not arrived."""
    rep = report_for(world, inc)
    if rep or inc.get("type") not in POLICE_INCIDENTS:
        return rep
    call_ids = {c["id"] for c in world.get("calls", []) if c.get("incident_id") == inc["id"]}
    arrived = next((r for r in world.get("responders", []) if r.get("call_id") in call_ids and r.get("type") == "police"
                    and r.get("status") == "resolved"), None)
    return _write(world, inc, arrived.get("call_id")) if arrived else None


def _write(world, inc, call_id):
    chars = world.get("characters") or {}
    call = next((c for c in world.get("calls", []) if c["id"] == call_id), None) or {}
    offender = chars.get(inc.get("offender_id"))
    victim = chars.get(inc.get("victim_id"))
    topic = inc.get("topic") or "something that had been building"
    rng = _rng(inc["id"], "report")
    parties = [p for p in inc.get("participants", []) if p in chars]
    anchor = offender or (chars.get(parties[0]) if parties else None)
    place = place_of(world, anchor) if anchor else "the scene"
    caller_id = inc.get("caller_id") or call.get("caller")
    interviews, findings = [], []
    evidence = 0.0

    def add(person, role, stance, text):
        interviews.append({"person_id": person["id"], "name": person.get("name", "someone"), "role": role, "stage": "scene",
                           "tick": world.get("tick", 0), "stance": stance, "statement": text})

    stances = {}
    if offender:
        stance, text = _offender_says(world, offender, victim, topic, _rng(inc["id"], offender["id"]), inc)
        add(offender, "offender", stance, text)
        stances["offender"] = stance
        evidence += {"admits": ADMITS, "denies": DENIES}.get(stance, 0.0)
        findings.append({"admits": f"{offender['name']} admitted it.", "minimises": f"{offender['name']} played it down.",
                         "denies": f"{offender['name']} denied it."}[stance])
    if victim:
        stance, text = _victim_says(world, victim, offender, topic, _rng(inc["id"], victim["id"]), inc)
        add(victim, "victim", stance, text)
        stances["victim"] = stance
        evidence += {"presses": VICTIM_PRESSES, "declines": VICTIM_DECLINES, "frightened": VICTIM_FRIGHTENED}[stance]
        findings.append({"presses": f"{victim['name']} made a complaint.", "declines": f"{victim['name']} did not want to press charges.",
                         "frightened": f"{victim['name']} was too frightened to say much."}[stance])
    saw = 0
    others = [w for w in (inc.get("witness_ids") or witnesses_of(world, parties)) if w in chars and w not in parties]
    inc["witness_ids"] = others
    for wid in others[:4]:
        w = chars[wid]
        stance, text = _witness_says(world, w, offender, victim, topic, _rng(inc["id"], wid))
        add(w, "witness", stance, text)
        saw += stance == "saw"
    if saw:
        evidence += min(MAX_WITNESS, SAW_IT * saw)
        findings.append(f"{saw} witness{'es' if saw > 1 else ''} saw it happen.")
    if caller_id in chars and caller_id not in parties and caller_id not in others:
        stance, text = _caller_says(world, chars[caller_id], call.get("report") or "Someone was hurt.", _rng(inc["id"], caller_id))
        add(chars[caller_id], "caller", stance, text)
    if offender and victim and stances.get("offender") == "denies" and stances.get("victim") == "presses":
        findings.append("The two accounts conflict.")

    n = len(reports(world)) + 1
    who = f"{offender['name']} and {victim['name']}" if offender and victim else " and ".join(chars[p]["name"] for p in parties[:2]) or "those involved"
    summary = (f"{inc['type'].replace('_', ' ').capitalize()} at {place}: {who}, about {topic}."
               if inc.get("type") == "assault" else f"{inc['type'].replace('_', ' ').capitalize()} at {place}: {who}.")
    report = {
        "id": f"report_{uuid.uuid4().hex[:6]}", "case_number": f"{(world.get('calendar') or {}).get('year', 0)}-{n:04d}",
        "tick": world.get("tick", 0), "when": _when(world), "incident_id": inc["id"], "call_id": call_id, "type": inc["type"],
        "place": place, "officer": f"Officer {rng.choice(OFFICERS)}",
        "caller_id": caller_id, "offender_id": inc.get("offender_id"), "victim_id": inc.get("victim_id"), "topic": topic,
        "fight_id": inc.get("fight_id"), "summary": summary, "findings": findings, "evidence": round(evidence, 2),
        "outcome": "pending", "interrogations": interviews,
    }
    caller_name = name_of(world, caller_id) if caller_id else "a passer-by"
    report["narrative"] = (f"{report['officer']} was called to {place} at {report['when']} after {caller_name} called it in"
                           f"{' (' + call['report'] + ')' if call.get('report') else ''}. " + " ".join(findings))
    reports(world).append(report)
    del reports(world)[:-REPORT_CAP]
    inc["police_report_id"] = report["id"]
    if inc.get("fight_id"):
        fight = next((f for f in world.get("fight_log", []) if f["id"] == inc["fight_id"]), None)
        if fight:
            fight["police_report_id"] = report["id"]
    _remember(world, report, offender, victim, topic)
    return report


def _remember(world, report, offender, victim, topic):
    chars = world.get("characters") or {}
    tick = world.get("tick", 0)
    for it in report["interrogations"]:
        c = chars.get(it["person_id"])
        if not c:
            continue
        stance = it["stance"]
        other = victim if it["role"] == "offender" else offender
        o_name = name_of(world, other["id"]) if other else "someone"
        if it["role"] == "offender":
            line = {"admits": f"The police questioned me about {o_name}. I admitted it.",
                    "minimises": f"The police questioned me about {o_name}. I played it down.",
                    "denies": f"The police questioned me about {o_name}. I denied it."}[stance]
        elif it["role"] == "victim":
            line = {"presses": f"Told the police what {o_name} did to me and made a complaint.",
                    "declines": f"Told the police what happened with {o_name} but said I would not press charges.",
                    "frightened": f"The police asked what {o_name} did. I was too frightened to say much."}[stance]
        elif it["role"] == "witness":
            line = {"saw": f"Told the police what I saw of the fight between {o_name} and the others, over {topic}.",
                    "heard": "Told the police what I heard of the fight; I did not see how it started.",
                    "evasive": "The police asked what I saw. I said I had not seen anything."}[stance]
        else:
            line = "Gave the police my account of why I called."
        store_memory(c, f"{line} (case {report['case_number']})", importance=0.6, tags=["police", "statement", "interview"],
                     kind="memory", tick=tick, people=[o for o in (offender and offender["id"], victim and victim["id"]) if o and o != c["id"]],
                     report_id=report["id"])


# ---- the station ------------------------------------------------------------------------------------------------------------------------
def questioned_at_station(world, c, inc):
    """An arrested offender is interrogated again, shown what the others said. Returns the evidence it adds (to the verdict)."""
    report = report_for(world, inc)
    if not report or report.get("offender_id") != c["id"]:
        return 0.0
    before = next((i for i in report["interrogations"] if i["person_id"] == c["id"] and i["role"] == "offender"), None)
    was = (before or {}).get("stance", "denies")
    victim = (world.get("characters") or {}).get(report.get("victim_id"))
    v = name_of(world, victim["id"]) if victim else "the other person"
    rng = _rng(inc["id"], c["id"], "station")
    pressure = 0.1 + (0.3 if any(i["stance"] == "presses" for i in report["interrogations"]) else 0.0) + \
        0.2 * sum(1 for i in report["interrogations"] if i["stance"] == "saw")
    if was == "admits":
        stance, text, added = "admits", f"Confirmed what I said at the scene and went through it step by step: {v}, the argument, and how it ended.", 0.1
    elif rng.random() < min(0.7, pressure) * (0.6 if was == "denies" else 1.0):
        stance, text, added = "admits", f"Shown that {v} and the witnesses had given statements, I stopped denying it and admitted what happened.", 0.25
    else:
        stance, text, added = "denies" if was == "denies" else "minimises", "Kept to my story through hours of questions and asked for a lawyer.", 0.0
    report["interrogations"].append({"person_id": c["id"], "name": c.get("name", "someone"), "role": "offender", "stage": "station",
                                     "tick": world.get("tick", 0), "stance": stance, "statement": text})
    report["evidence"] = round(report["evidence"] + added, 2)
    report["outcome"] = "arrested"
    report["findings"].append(f"{c['name']} was arrested and questioned at the station" + (" and admitted it." if stance == "admits" and added else "."))
    store_memory(c, f"Was questioned for hours at the station about {v}. " + text, importance=0.7, tags=["police", "interrogation"],
                 kind="memory", tick=world.get("tick", 0), people=[victim["id"]] if victim else [], report_id=report["id"])
    return added


def closed_without_charge(world, inc):
    """The police looked into it and nobody was arrested: say why on the report."""
    report = report_for(world, inc)
    if not report or report["outcome"] != "pending":
        return
    declined = any(i["role"] == "victim" and i["stance"] in ("declines", "frightened") for i in report["interrogations"])
    report["outcome"] = "no_charges"
    report["findings"].append("No arrest: the complainant would not go on with it." if declined else "No arrest: not enough to charge anyone.")
