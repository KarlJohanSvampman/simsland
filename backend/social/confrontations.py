"""
social/confrontations.py -- a structured attempt to address a perceived problem (design sections 7, 12, 13, 14).

A confrontation lives inside a conversation (the conversation stays the parent and keeps the history) and is about an
issue (social/issues.py). It is not necessarily aggressive: a polite request is one, so is a power play.

    world["confrontations"][id] = {
        "id", "conversation_id", "issue_id", "initiator_id", "primary_target_id",
        "participants": {character id: {role, side, position, motivation, involvement, influence, joined_at, left_at}},
        "confrontation_type", "original_type", "type_history",
        "problem_statement", "desired_outcome", "initiator_position", "target_position",
        "emotional_intensity" 0..100, "aggression" 0..100, "public_visibility" 0..1,
        "stage_idx", "stage", "peak_stage", "pressure", "streak" {character id: escalations in a row},
        "status": active | resolved, "escalation_history": [{tick, from, to, by, why}],
        "resolution": {outcome, summary, tick, by}, "started_at", "ended_at", "reconciliation",
        -- read by older code that knew "conflicts": "parties", "initiator", "topic", "outcome" (legacy outcome once
           resolved, else None), "aggressor", "fight_stage", "log"
    }

Who decides what: the characters' own AI turns say what each line is doing (escalate, hold, de-escalate, which side
they're on -- social/discourse.py), the AI reading the finished conversation says how it ended. This module keeps the
state, enforces the escalation rules and applies the aftermath:

  - Escalation is weighed, not rolled: each "escalate" line adds pressure scaled by the speaker's escalation score
    (frustration, negative standing, intensity, aggression, provocation received, situational pressure, hostility --
    each with a weight, ESCALATION_WEIGHTS); a stage is reached when pressure fills up. It is slow on purpose: going
    from a verbal confrontation to a hostile one needs one side to have pushed PROVOCATIONS_TO_HOSTILE times in a row.
    Physical stages are only ever reached by someone actually doing it (a shove, a punch, a threat -- hostile actions,
    which the character's AI chose); whoever considers it gets the 13.3 considerations in their prompt (context.py).
  - More people can join: each with a role (supporter, defender, mediator, witness, bystander, provocateur) and a
    side. Nobody takes a side automatically -- a character's own line says it. Anger spills onto those who take the
    other side.
  - The outcome updates frustration, standing and initiative for everyone in it, may set up a contract, resolve or
    keep open the issue, and can leave new issues behind. Not every confrontation resolves anything.
"""

import uuid

from social.core import clamp, emit, now, chars, name, first, rel

TYPES = ("provocation", "bullying", "ridicule", "criticism", "behavioural_request", "expectations_dispute",
         "power_play", "negotiation", "contract_proposal", "defence")
STAGES = ("disagreement", "heated_discussion", "verbal_confrontation", "hostile_confrontation",
          "threatening_behaviour", "physical_intimidation", "physical_aggression", "physical_fight")
VERBAL_MAX = 3                      # hostile_confrontation: as far as words alone take it
PROVOCATIONS_TO_HOSTILE = 3         # escalations in a row from one side before it turns hostile
ROLES = ("initiator", "target", "supporter", "defender", "mediator", "witness", "bystander", "provocateur")
SIDES = ("initiator", "target", "neutral")
OUTCOMES = ("mutual_understanding", "apology_accepted", "apology_rejected", "behaviour_change_accepted",
            "contract_established", "contract_renegotiated", "unresolved", "withdrew", "refused_discussion",
            "public_humiliation", "relationship_deterioration", "physical_fight", "third_party_intervention")
GOOD = {"mutual_understanding", "apology_accepted", "behaviour_change_accepted", "contract_established",
        "contract_renegotiated"}
BAD = {"apology_rejected", "unresolved", "withdrew", "refused_discussion", "public_humiliation",
       "relationship_deterioration", "physical_fight"}
LEGACY_OUTCOME = {
    "mutual_understanding": "de_escalated", "apology_accepted": "de_escalated", "behaviour_change_accepted": "agreement",
    "contract_established": "agreement", "contract_renegotiated": "agreement", "apology_rejected": "cold_shoulder",
    "unresolved": "cold_shoulder", "withdrew": "storm_off", "refused_discussion": "cold_shoulder",
    "public_humiliation": "cold_shoulder", "relationship_deterioration": "cold_shoulder",
    "physical_fight": "physical_resolved", "third_party_intervention": "intervention",
}
ESCALATION_WEIGHTS = {"frustration": 0.25, "standing": 0.15, "intensity": 0.15, "aggression": 0.15,
                      "provocation": 0.15, "situation": 0.05, "hostility": 0.10}
HOSTILE_STAGE = {"threaten": 4, "shove": 5, "catch_and_hold": 5, "hold_down": 6, "punch": 6, "kick": 6,
                 "slap": 6, "tackle": 7, "choke": 7}
NEVER_SPOKEN_TICKS = 900            # confronted nobody in the end
UNREAD_GRACE_TICKS = 1200           # the conversation ended and the AI never said how it went

# what each intent of a line (social/discourse.py) means for the confrontation type, when it starts one
INTENT_TYPE = {"criticise": "criticism", "complain": "criticism", "accuse": "criticism", "provoke": "provocation",
               "ridicule": "ridicule", "bully": "bullying", "threaten": "bullying", "power_play": "power_play",
               "request_change": "behavioural_request", "remind_obligation": "expectations_dispute",
               "negotiate": "negotiation", "propose_agreement": "contract_proposal", "defend": "defence"}


def store(world):
    return world.setdefault("confrontations", {})


def get(world, cid):
    return (world.get("confrontations") or {}).get(cid)


def active(world):
    return [x for x in store(world).values() if x["status"] == "active"]


def active_for(world, cid):
    return [x for x in active(world) if cid in x["participants"]]


def active_between(world, a, b):
    for x in active(world):
        if a in x["participants"] and b in x["participants"]:
            return x
    return None


def _participant(world, conf, cid, role, side, motivation=None):
    p = conf["participants"].get(cid)
    if p is None:
        p = conf["participants"][cid] = {"character_id": cid, "role": role, "side": side, "position": None,
                                         "motivation": motivation, "involvement": 1.0 if role in ("initiator", "target") else 0.5,
                                         "influence": 0.5, "joined_at": now(world), "left_at": None}
        if role not in ("initiator", "target"):
            emit("ConfrontationParticipantJoined", {"confrontation_id": conf["id"], "character_id": cid, "role": role,
                                                    "side": side})
            _history(world, conf, "joined", by=cid, why=f"{name(world, cid)} joined as {role}"
                     + (f" on {_side_name(world, conf, side)}'s side" if side in ("initiator", "target") else ""))
    return p


def _side_name(world, conf, side):
    return name(world, conf["initiator_id"] if side == "initiator" else conf["primary_target_id"])


def _history(world, conf, what, by=None, why=None, frm=None, to=None):
    conf["escalation_history"].append({"tick": now(world), "what": what, "by": by, "why": str(why or "")[:200],
                                       "from": frm, "to": to})
    del conf["escalation_history"][:-80]
    conf["log"] = conf["escalation_history"]
    _sync(world, conf)


def _sync(world, conf):
    """Each person in it keeps a copy (the Inspector)."""
    import copy
    for cid in conf["participants"]:
        c = chars(world).get(cid)
        if not c:
            continue
        log = [x for x in c.get("confrontation_log") or [] if x["id"] != conf["id"]]
        log.append(copy.deepcopy(conf))
        log.sort(key=lambda x: x.get("started_at") or 0)
        c["confrontation_log"] = log[-30:]


# =========================================================
# STARTING
# =========================================================

def start(world, initiator_id, target_id, ctype=None, conversation_id=None, issue=None, problem=None, desired=None,
          reconciliation=False, category=None):
    """initiator means to take something up with target. Returns the confrontation (an active one between them is
    reused: it's the same disagreement going on)."""
    cs = chars(world)
    if initiator_id not in cs or target_id not in cs or initiator_id == target_id:
        return None
    existing = active_between(world, initiator_id, target_id)
    if existing:
        if conversation_id and not existing.get("conversation_id"):
            existing["conversation_id"] = conversation_id
        return existing
    from social import issues as I
    if issue is None:
        subject = problem or "what's been bothering them"
        issue, _ = I.find_or_open(world, [initiator_id, target_id], subject, category or "other", created_by=initiator_id)
    ctype = ctype if ctype in TYPES else ("negotiation" if reconciliation else "criticism")
    conf = {
        "id": f"confr_{uuid.uuid4().hex[:8]}", "conversation_id": conversation_id, "issue_id": issue["id"],
        "initiator_id": initiator_id, "primary_target_id": target_id, "participants": {},
        "confrontation_type": ctype, "original_type": ctype, "type_history": [ctype],
        "problem_statement": str(problem or issue["subject"])[:240], "desired_outcome": str(desired or "")[:200],
        "initiator_position": None, "target_position": None,
        "emotional_intensity": 15.0, "aggression": 5.0, "public_visibility": 0.0,
        "stage_idx": 0, "stage": STAGES[0], "peak_stage": STAGES[0], "pressure": 0.0, "streak": {},
        "status": "active", "escalation_history": [], "resolution": None,
        "started_at": now(world), "ended_at": None, "reconciliation": bool(reconciliation),
        "parties": [initiator_id, target_id], "initiator": initiator_id, "topic": issue["subject"],
        "outcome": None, "aggressor": None, "fight_stage": STAGES[0], "log": [],
    }
    _participant(world, conf, initiator_id, "initiator", "initiator")
    _participant(world, conf, target_id, "target", "target")
    store(world)[conf["id"]] = conf
    issue["confrontation_ids"].append(conf["id"])
    I.event(world, issue, "confrontation", f"{name(world, initiator_id)} took it up with {name(world, target_id)} "
            f"({ctype.replace('_', ' ')})", ref=conf["id"])
    _history(world, conf, "started", by=initiator_id, why=conf["problem_statement"])
    emit("ConfrontationStarted", {"confrontation_id": conf["id"], "initiator_id": initiator_id, "target_id": target_id,
                                  "type": ctype, "issue_id": issue["id"]})
    emit("conflict_started", {"conflict_id": conf["id"], "parties": conf["parties"]})
    return conf


# =========================================================
# ESCALATION
# =========================================================

def escalation_score(world, conf, cid):
    """0..1: how much this character is primed to push it further (design 13.2). Not a guarantee of anything."""
    c = chars(world).get(cid)
    if not c:
        return 0.0
    from social import frustration, standing
    others = [p for p, x in conf["participants"].items() if p != cid and x["side"] != conf["participants"].get(cid, {}).get("side")]
    if not others:
        others = [p for p in conf["participants"] if p != cid]
    other = others[0] if others else None
    f = frustration.value(c, other, world, conf["issue_id"]) if other else {"score": 0, "intensity": 0}
    g = frustration.value(c, other, world) if other else {"score": 0, "intensity": 0}
    s = standing.score(c, other) if other else 0
    r = rel(c, other, create=False) if other else {}
    traits = set(c.get("traits") or [])
    aggression = 0.6 if traits & {"hot_headed", "aggressive", "volatile", "violent"} else \
        0.1 if traits & {"calm", "gentle", "conflict_averse", "patient"} else 0.3
    last_against = next((h for h in reversed(conf["escalation_history"])
                         if h["what"] == "line" and h["by"] in others), None)
    provoked = 1.0 if last_against and last_against.get("to") == "escalate" else 0.0
    allies = sum(1 for p, x in conf["participants"].items()
                 if p != cid and x["side"] == conf["participants"].get(cid, {}).get("side"))
    situation = clamp(conf["public_visibility"] * 0.6 + allies * 0.2, 0, 1)
    parts = {
        "frustration": clamp(max(f["score"], g["score"] * 0.7) / 100, 0, 1),
        "standing": clamp(-s / 100, 0, 1),
        "intensity": clamp(max(f["intensity"], g["intensity"], conf["emotional_intensity"]) / 100, 0, 1),
        "aggression": aggression,
        "provocation": provoked,
        "situation": situation,
        "hostility": clamp((r.get("hostility") or 0) / 100, 0, 1),
    }
    return round(sum(ESCALATION_WEIGHTS[k] * v for k, v in parts.items()), 3)


def _set_stage(world, conf, idx, by, why):
    idx = int(clamp(idx, 0, len(STAGES) - 1))
    if idx == conf["stage_idx"]:
        return
    frm = conf["stage"]
    conf["stage_idx"], conf["stage"] = idx, STAGES[idx]
    conf["fight_stage"] = conf["stage"]
    if idx > STAGES.index(conf["peak_stage"]):
        conf["peak_stage"] = conf["stage"]
    conf["pressure"] = 0.0
    up = STAGES.index(frm) < idx
    _history(world, conf, "escalated" if up else "de-escalated", by=by, why=why, frm=frm, to=conf["stage"])
    emit("ConfrontationEscalated", {"confrontation_id": conf["id"], "stage": conf["stage"], "from": frm, "by": by,
                                    "direction": "up" if up else "down"})
    if up:
        emit("conflict_escalated", {"conflict_id": conf["id"], "stage": conf["stage"], "parties": conf["parties"]})


def on_line(world, conf, speaker_id, social, utterance=None, listeners=None):
    """One line said inside the confrontation; `social` is what the speaker's AI said the line does
    (validated by social/discourse.py)."""
    if conf["status"] != "active":
        return
    p = conf["participants"].get(speaker_id)
    if p is None:
        side_name = social.get("side")
        side = "neutral"
        role = "bystander"
        if side_name == "mediator":
            role = "mediator"
        elif side_name in ("initiator", "target"):
            side = side_name
            role = "supporter" if side == "initiator" else "defender"
            if social.get("escalation") == "escalate" and social.get("intent") in ("provoke", "ridicule", "bully"):
                role = "provocateur"
        p = _participant(world, conf, speaker_id, role, side, motivation=social.get("position"))
    if social.get("position"):
        p["position"] = social["position"]
        if speaker_id == conf["initiator_id"]:
            conf["initiator_position"] = social["position"]
        elif speaker_id == conf["primary_target_id"]:
            conf["target_position"] = social["position"]
        from social import issues as I
        issue = I.get(world, conf["issue_id"])
        if issue:
            I.set_position(world, issue, speaker_id, social["position"],
                           stance=social.get("stance"), basis="concluded", said_to=list(conf["participants"]))
    if social.get("desired_outcome") and speaker_id == conf["initiator_id"]:
        conf["desired_outcome"] = social["desired_outcome"][:200]
    new_type = INTENT_TYPE.get(social.get("intent"))
    if new_type and new_type != conf["confrontation_type"] and speaker_id in (conf["initiator_id"], conf["primary_target_id"]):
        conf["confrontation_type"] = new_type
        conf["type_history"].append(new_type)          # the original intention stays recorded in original_type

    # who could see it (design: public_visibility)
    present = [x for x in (listeners or []) if x not in conf["participants"]]
    conf["public_visibility"] = round(clamp(len(present) * 0.25, 0, 1), 2)

    esc = social.get("escalation") or "hold"
    score = escalation_score(world, conf, speaker_id)
    streak = conf["streak"]
    if esc == "escalate":
        streak[speaker_id] = streak.get(speaker_id, 0) + 1
        conf["pressure"] = round(conf["pressure"] + 0.35 + 0.65 * score, 3)
        conf["emotional_intensity"] = round(clamp(conf["emotional_intensity"] + 6 + 10 * score, 0, 100), 1)
        conf["aggression"] = round(clamp(conf["aggression"] + 8 * score, 0, 100), 1)
    elif esc == "de-escalate":
        streak[speaker_id] = 0
        conf["pressure"] = round(conf["pressure"] - (0.9 if p["role"] == "mediator" else 0.6), 3)
        conf["emotional_intensity"] = round(clamp(conf["emotional_intensity"] - 8, 0, 100), 1)
        conf["aggression"] = round(clamp(conf["aggression"] - 5, 0, 100), 1)
    else:
        streak[speaker_id] = 0
        conf["pressure"] = round(conf["pressure"] - 0.1, 3)
    _history(world, conf, "line", by=speaker_id, why=(utterance or "")[:120], to=esc)

    idx = conf["stage_idx"]
    if conf["pressure"] >= 1.0 and idx < VERBAL_MAX:
        if idx + 1 < VERBAL_MAX or streak.get(speaker_id, 0) >= PROVOCATIONS_TO_HOSTILE:
            _set_stage(world, conf, idx + 1, speaker_id, f"{first(world, speaker_id)} pushed it further")
        else:
            conf["pressure"] = 1.0                      # full, but it takes more than this to turn hostile
    elif social.get("intent") == "threaten" and idx < 4:
        _set_stage(world, conf, 4, speaker_id, f"{first(world, speaker_id)} made a threat")
    elif conf["pressure"] <= -1.0 and idx > 0:
        _set_stage(world, conf, idx - 1, speaker_id, f"{first(world, speaker_id)} calmed it down")


def on_hostile_act(world, actor_id, target_id, action):
    """A shove, a punch, a threat between people in a confrontation: it is now that physical."""
    conf = active_between(world, actor_id, target_id)
    if not conf:
        return
    idx = HOSTILE_STAGE.get(str(action), 6)
    if idx > conf["stage_idx"]:
        conf["aggressor"] = conf.get("aggressor") or actor_id
        _set_stage(world, conf, idx, actor_id, f"{first(world, actor_id)}: {str(action).replace('_', ' ')}")


# =========================================================
# RESOLUTION AND AFTERMATH
# =========================================================

def end(world, conf, outcome, summary=None, by=None, sides=None):
    """It's over (the AI read the conversation and said how, or it petered out). Apply what it leads to."""
    if conf["status"] != "active":
        return conf
    if outcome not in OUTCOMES:
        outcome = "unresolved"
    if conf["stage_idx"] >= 5 and outcome not in GOOD | {"physical_fight", "third_party_intervention"}:
        outcome = "physical_fight"
    for cid, side in (sides or {}).items():
        if cid in conf["participants"] and side in SIDES:
            conf["participants"][cid]["side"] = side
        elif cid not in conf["participants"] and side in SIDES + ("mediator",):
            _participant(world, conf, cid, "mediator" if side == "mediator" else
                         "supporter" if side == "initiator" else "defender" if side == "target" else "witness",
                         side if side in SIDES else "neutral")
    conf["status"] = "resolved"
    conf["ended_at"] = now(world)
    conf["resolution"] = {"outcome": outcome, "summary": str(summary or "")[:240], "tick": now(world), "by": by}
    conf["outcome"] = LEGACY_OUTCOME[outcome]
    if outcome == "withdrew" and by:
        _history(world, conf, "storm_off", by=by, why=summary)
        conf["escalation_history"][-1]["event"] = "storm_off"
    if outcome == "third_party_intervention":
        mediator = by or next((p for p, x in conf["participants"].items() if x["role"] == "mediator"), None)
        _history(world, conf, "intervention", by=mediator, why=summary)
        conf["escalation_history"][-1]["event"] = "intervention"
    _history(world, conf, "resolved", by=by, why=f"{outcome.replace('_', ' ')}" + (f": {summary}" if summary else ""))
    _aftermath(world, conf, outcome)
    emit("ConfrontationResolved", {"confrontation_id": conf["id"], "outcome": outcome, "issue_id": conf["issue_id"]})
    emit("conflict_resolved", {"conflict_id": conf["id"], "outcome": conf["outcome"], "parties": conf["parties"],
                               "contract_id": conf.get("contract_id")})
    return conf


def _aftermath(world, conf, outcome):
    from social import frustration, standing, initiative, issues as I
    cs = chars(world)
    a, b = conf["initiator_id"], conf["primary_target_id"]
    issue = I.get(world, conf["issue_id"])
    iid = conf["issue_id"]
    what = outcome.replace("_", " ")
    subject = issue["subject"] if issue else conf["problem_statement"]

    for me, other in ((a, b), (b, a)):
        c = cs.get(me)
        if not c:
            continue
        if outcome in GOOD:
            frustration.calm(c, other, world, 25 if outcome != "apology_accepted" else 15, issue_id=iid,
                             kind="apology" if outcome == "apology_accepted" and me == a else
                             "renegotiated" if outcome.startswith("contract") else "acknowledged",
                             cause=f"{subject}: {what}")
            standing.change(c, other, world, "reconciliation" if conf["reconciliation"] else "agreement",
                            cause=f"we sorted out {subject}")
        elif outcome in BAD:
            amount = {"physical_fight": 25, "public_humiliation": 20, "relationship_deterioration": 18}.get(outcome, 10)
            frustration.raise_(c, other, world, amount, issue_id=iid, kind="repeat",
                               cause=f"{subject}: {what}")
            kind = "physical_aggression" if outcome == "physical_fight" and conf.get("aggressor") == other else \
                "public_humiliation" if outcome == "public_humiliation" and me != conf.get("humiliator", a) else \
                "dismissed_me"
            standing.change(c, other, world, kind, cause=f"{subject}: {what}")
        else:   # third-party intervention: stopped, not settled
            frustration.raise_(c, other, world, 5, issue_id=iid, cause=f"{subject}: broken up before it was settled")

    # the one who brought it up: how their initiative was received
    ca = cs.get(a)
    if ca:
        resp = {"mutual_understanding": "accepted_positively", "apology_accepted": "accepted_positively",
                "behaviour_change_accepted": "accepted_positively", "contract_established": "accepted_positively",
                "contract_renegotiated": "counter_proposal", "apology_rejected": "rejected", "unresolved": "rejected",
                "withdrew": "interrupted", "refused_discussion": "ignored", "public_humiliation": "hostile",
                "relationship_deterioration": "hostile", "physical_fight": "hostile",
                "third_party_intervention": "interrupted"}[outcome]
        if conf["reconciliation"] and outcome in GOOD:
            resp = "reconciliation"
        initiative.answered(ca, b, world, resp, kind=conf["confrontation_type"], ref=conf["id"])

    # sides: anger spills onto whoever took the other side, and those who stood by you count for something
    for pid, p in conf["participants"].items():
        if p["role"] in ("initiator", "target") or p["side"] == "neutral":
            continue
        principal = a if p["side"] == "initiator" else b
        opponent = b if principal == a else a
        cp, co = cs.get(principal), cs.get(opponent)
        if co:
            standing.change(co, pid, world, "took_other_side", cause=f"sided with {first(world, principal)} over {subject}")
            frustration.raise_(co, pid, world, 6 + conf["emotional_intensity"] / 10, issue_id=iid,
                               cause=f"took {first(world, principal)}'s side over {subject}")
        if cp:
            standing.change(cp, pid, world, "took_my_side", cause=f"stood by me over {subject}")
    for pid, p in conf["participants"].items():
        if p["role"] == "mediator" and outcome in GOOD | {"third_party_intervention"}:
            for x in (a, b):
                if cs.get(x):
                    standing.change(cs[x], pid, world, "support", delta=3, cause=f"helped calm things over {subject}")

    if issue:
        if outcome in ("mutual_understanding", "behaviour_change_accepted", "contract_established",
                       "contract_renegotiated"):
            I.resolve(world, issue, f"{what}" + (f": {conf['resolution']['summary']}" if conf["resolution"]["summary"] else ""))
        elif outcome == "apology_accepted" and issue["category"] in ("disrespect", "misunderstanding", "dishonesty"):
            I.resolve(world, issue, "apology accepted")
        else:
            I.event(world, issue, "confrontation ended", what, ref=conf["id"])
        if outcome == "public_humiliation":
            humiliated = b if conf["confrontation_type"] in ("ridicule", "bullying", "provocation", "power_play") else a
            other = a if humiliated == b else b
            I.find_or_open(world, [humiliated, other], f"being humiliated in front of others by {name(world, other)}",
                           "public_reputation", created_by=humiliated)
    # a bad ending is something to tell someone about (confiding / gossip): the character's prompt mentions it
    if outcome in BAD:
        for x in (a, b):
            c = cs.get(x)
            if c:
                c.setdefault("_wants_to_vent", []).append({"tick": now(world), "about": b if x == a else a,
                                                           "what": f"{subject} ({what})"})
                c["_wants_to_vent"] = c["_wants_to_vent"][-3:]


def tick(world):
    """Confrontations that never got said, or whose conversation ended without the AI ever saying how it went."""
    t = now(world)
    archive = world.get("conversation_archive") or {}
    convs = world.get("conversations") or {}
    for conf in active(world):
        cid = conf.get("conversation_id")
        if not cid:
            if t - conf["started_at"] > NEVER_SPOKEN_TICKS:
                end(world, conf, "unresolved", summary="it was never actually brought up")
            continue
        live = convs.get(cid) if isinstance(convs, dict) else None
        if live and live.get("active", True) and not live.get("_archived"):
            continue
        entry = archive.get(cid) or {}
        ended = entry.get("ended_tick") or conf["started_at"]
        if t - ended > UNREAD_GRACE_TICKS:
            end(world, conf, "unresolved", summary="the conversation ended without it being settled")


def lookup(world, cid):
    """An id from either era: a confrontation, or one of the old pipeline's conflicts."""
    return get(world, cid) or (world.get("conflicts") or {}).get(cid)
