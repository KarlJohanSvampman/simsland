"""
social/discourse.py -- conversations as the core social object (design sections 5, 17, 19).

Two moments, both decided by the AI and applied here (the AI never holds the state itself):

  on_line   each line someone says (systems/action_router.py emits "social_line"; handled on the main thread). The
            speaker's own AI turn says what the line does (speech.social: intent, issue, position, desired outcome,
            escalation, side, continue). Here: the conversation's subject and interaction tags, the speaker's
            initiative (the opening line of a talk is reaching out), a confrontation started or carried on
            (social/confrontations.py), and a conversation ended when someone says they're done.

  after     the finished conversation, read by the AI as a whole (llm/conversation_tags.py via
            systems/conversation_archive.py). Here: subject, topic and interaction tags, tone; the issues it raised or
            continued, with each person's position; how a confrontation in it ended (or that one happened); an
            agreement or a renegotiation (social/contracts.py); broken agreements (disputed or not); how the opener's
            approach was received (social/initiative.py); what was said about people who weren't there
            (social/rumours.py); and what each one now makes of the other (social/standing.py).

Nothing here guesses: an untagged line changes nothing but the conversation's own record, and a conversation the AI
couldn't read is tried again (conversation_archive) and otherwise left as it is.
"""

from core.event_bus import subscribe
from social.core import chars, emit, id_by_name, name, now

INTENTS = ("chat", "inform", "ask", "suggest", "request_change", "remind_obligation", "criticise", "complain", "accuse",
           "provoke", "ridicule", "bully", "power_play", "negotiate", "propose_agreement", "accept", "refuse",
           "apologise", "forgive", "defend", "mediate", "reconcile", "gossip", "threaten", "end")
CONFRONTING = {"request_change", "remind_obligation", "criticise", "complain", "accuse", "provoke", "ridicule",
               "bully", "power_play", "negotiate", "propose_agreement", "threaten", "defend"}
REPAIRING = {"apologise", "reconcile", "negotiate", "propose_agreement", "suggest", "request_change", "forgive",
             "remind_obligation"}
# interaction tags (design 5.1) a line's intent stands for
INTENT_TAG = {"chat": "casual", "inform": "information_exchange", "ask": "inquiry", "suggest": "advice",
              "request_change": "negotiation", "remind_obligation": "complaint", "criticise": "criticism",
              "complain": "complaint", "accuse": "accusation", "provoke": "provocation", "ridicule": "provocation",
              "bully": "provocation", "power_play": "confrontation", "negotiate": "negotiation",
              "propose_agreement": "negotiation", "apologise": "apology", "forgive": "reconciliation",
              "defend": "disagreement", "mediate": "reconciliation", "reconcile": "reconciliation", "gossip": "gossip",
              "threaten": "confrontation", "refuse": "disagreement", "accept": "friendly"}
INTERACTION_TAGS = ("casual", "friendly", "introductory", "affectionate", "supportive", "flirtatious",
                    "information_exchange", "inquiry", "explanation", "advice", "gossip", "rumour", "news_discussion",
                    "complaint", "venting", "reassurance", "apology", "disappointment", "accusation",
                    "disagreement", "criticism", "provocation", "confrontation", "negotiation", "reconciliation")
TONES = ("warm", "friendly", "neutral", "awkward", "tense", "hostile", "playful", "sad", "formal")


def clean_social(raw):
    """The speaker's AI's account of a line, validated; {} if there is nothing usable."""
    if not isinstance(raw, dict):
        return {}
    out = {}
    intent = str(raw.get("intent") or "").strip().lower().replace(" ", "_")
    if intent in INTENTS:
        out["intent"] = intent
    for k, n in (("issue", 90), ("position", 240), ("desired_outcome", 200)):
        v = raw.get(k)
        if isinstance(v, str) and v.strip() and v.strip().lower() not in ("null", "none", "n/a"):
            out[k] = v.strip()[:n]
    esc = str(raw.get("escalation") or "").strip().lower().replace("_", "-")
    out["escalation"] = esc if esc in ("escalate", "hold", "de-escalate") else "hold"
    side = str(raw.get("side") or "").strip().lower()
    if side in ("initiator", "target", "mediator", "neutral"):
        out["side"] = side
    if raw.get("continue") is False or str(raw.get("continue")).lower() == "false" or intent == "end":
        out["continue"] = False
    return out


# =========================================================
# EACH LINE
# =========================================================

def on_line(data, world):
    convs = world.get("conversations") or {}
    conv = convs.get(data.get("conversation_id")) if isinstance(convs, dict) else None
    speaker_id = data.get("speaker_id")
    if not conv or speaker_id not in chars(world):
        return
    social = clean_social(data.get("social"))
    cs = chars(world)
    others = [p for p in conv.get("participants") or [] if p != speaker_id]
    target_id = data.get("target_id") if data.get("target_id") in others else (others[0] if others else None)
    from social import standing, initiative
    speaker = cs[speaker_id]
    for o in others:
        standing.touch(speaker, o, world)
    conv.setdefault("target_id", target_id if len(conv.get("history") or []) <= 1 else conv.get("target_id"))
    conv.setdefault("initiator_id", (conv.get("history") or [{}])[0].get("speaker") or speaker_id)
    conv.setdefault("location_id", speaker.get("room_id") or speaker.get("building_id"))
    conv["status"] = "active" if len(conv.get("history") or []) <= 2 else "developing"
    if social.get("intent"):
        tag = INTENT_TAG.get(social["intent"])
        tags = conv.setdefault("interaction_tags", [])
        if tag and tag not in tags:
            tags.append(tag)

    # the opening line of a talk is reaching out to someone
    hist = conv.get("history") or []
    if len(hist) == 1 and target_id:
        initiative.took(speaker, target_id, world, social.get("intent") or "approach", ref=conv.get("id"))

    # a confrontation: carried on, or started by this line
    from social import confrontations as X
    conf = X.get(world, conv.get("related_confrontation_id")) if conv.get("related_confrontation_id") else None
    if conf is None and target_id:
        conf = X.active_between(world, speaker_id, target_id)
        if conf is None:
            for o in others:
                conf = next((x for x in X.active_for(world, o) if x.get("conversation_id") in (None, conv.get("id"))
                             and conv.get("id") in (x.get("conversation_id"), None)), None)
                if conf:
                    break
    rift = ((speaker.get("rifts") or {}).get(target_id) or {}) if target_id else {}
    their_rift = (((cs.get(target_id) or {}).get("rifts") or {}).get(speaker_id) or {}) if target_id else {}
    if target_id and their_rift.get("notice") and social.get("intent") in REPAIRING:
        # they've said they're leaving because of the speaker, and the speaker is trying: a day's grace
        from systems.rifts import note_attempt
        note_attempt(world, speaker_id, target_id)
        if not rift.get("status") == "open":
            rift = their_rift
    if conf is None and target_id and rift.get("status") == "open" and social.get("intent") in REPAIRING:
        conf = X.start(world, speaker_id, target_id, ctype="negotiation", conversation_id=conv.get("id"),
                       problem=social.get("issue") or (rift.get("topics") or [None])[-1],
                       desired=social.get("desired_outcome") or "to make peace", reconciliation=True)
    if conf is None and social.get("intent") in CONFRONTING and target_id:
        conf = X.start(world, speaker_id, target_id, ctype=X.INTENT_TYPE.get(social["intent"]),
                       conversation_id=conv.get("id"), problem=social.get("issue"),
                       desired=social.get("desired_outcome"))
    if conf is not None:
        if not conf.get("conversation_id"):
            conf["conversation_id"] = conv.get("id")
        conv["related_confrontation_id"] = conf["id"]
        if conf["issue_id"] not in conv.setdefault("related_issue_ids", []):
            conv["related_issue_ids"].append(conf["issue_id"])
        X.on_line(world, conf, speaker_id, social, utterance=data.get("utterance"),
                  listeners=data.get("listeners") or [])

    # done talking
    if social.get("continue") is False and conv.get("active"):
        conv["_wants_to_end"] = speaker_id
        from systems.conversation_outcome import end
        end(world, conv, "ended")
    emit("ConversationMessageAdded", {"conversation_id": conv.get("id"), "speaker_id": speaker_id,
                                      "intent": social.get("intent")})


def on_ended(world, conv):
    """systems/conversation_floor.py closed it: an opener nobody answered was ignored."""
    hist = conv.get("history") or []
    speakers = {h.get("speaker") for h in hist}
    if hist and len(speakers) == 1 and conv.get("end_reason") in ("no_response", "ignored"):
        opener = chars(world).get(hist[0].get("speaker"))
        other = next((p for p in conv.get("participants") or [] if p != hist[0].get("speaker")), None)
        if opener and other:
            from social import initiative
            initiative.answered(opener, other, world, "ignored", kind="approach", ref=conv.get("id"))
    emit("ConversationEnded", {"conversation_id": conv.get("id"), "reason": conv.get("end_reason")})


# =========================================================
# THE WHOLE CONVERSATION, READ BY THE AI
# =========================================================

def context_for_reader(world, entry):
    """What the AI reading a finished conversation is told besides the transcript: what's open between these
    people, and what it can refer back to by id."""
    from social import issues as I, contracts as K, confrontations as X, rumours as R
    ps = entry["participants"]
    issues = {}
    for i, a in enumerate(ps):
        for b in ps[i + 1:]:
            for iss in I.between(world, a, b, status=("open", "reopened", "dormant")):
                issues[iss["id"]] = {"id": iss["id"], "subject": iss["subject"], "category": iss["category"]}
    conf = X.get(world, entry.get("confrontation_id")) or next(
        (x for x in X.active(world) if x.get("conversation_id") == entry["id"]), None)
    contracts = [{"id": k["id"], "title": k.get("title"), "terms": [t.get("obligation") or t.get("commitment")
                                                                     for t in k.get("terms") or []]}
                 for k in K.between(world, ps)]
    rumours = []
    for p in ps:
        rumours += [{"id": r["id"], "about": name(world, r["subject_id"]), "claim": r["claim"]}
                    for r in R.known_by(world, p)][:6]
    return {"issues": list(issues.values())[:8],
            "confrontation": {"id": conf["id"], "type": conf["confrontation_type"], "problem": conf["problem_statement"],
                              "initiator": name(world, conf["initiator_id"]),
                              "target": name(world, conf["primary_target_id"])} if conf else None,
            "contracts": contracts[:6], "rumours": rumours[:10]}


def after(world, entry, tags):
    """Apply the AI's reading of a finished conversation."""
    from social import issues as I, confrontations as X, initiative, standing, contracts as K, rumours as R
    cs = chars(world)
    ps = [p for p in entry["participants"] if p in cs]
    names = entry.get("names") or {}

    def pid(nm):
        return id_by_name(world, nm, among=ps)

    entry["subject"] = tags.get("subject") or entry.get("subject")
    entry["topic_tags"] = tags.get("tags") or []
    entry["interaction_tags"] = [t for t in tags.get("interaction_tags") or [] if t in INTERACTION_TAGS]
    entry["tone"] = tags.get("tone") if tags.get("tone") in TONES else entry.get("tone")
    entry["status"] = "completed"
    entry["target_id"] = entry.get("target_id") or next((p for p in ps if p != entry.get("initiator")), None)

    # issues: continued or raised, each person's position
    issue_by_ref = {}
    for it in tags.get("issues") or []:
        involved = [pid(n) for n in it.get("between") or []] or ps[:2]
        involved = [p for p in involved if p] or ps[:2]
        same = I.get(world, it.get("same_as")) if it.get("same_as") else None
        if same is None:
            same, _ = I.find_or_open(world, involved, it["subject"], it.get("category") or "other",
                                     created_by=pid(it.get("raised_by")) or entry.get("initiator"),
                                     description=it.get("description"))
        I.file_conversation(world, same, entry)
        for nm, pos in (it.get("positions") or {}).items():
            who = pid(nm)
            if who and isinstance(pos, dict) and pos.get("position"):
                I.set_position(world, same, who, pos.get("position"), stance=pos.get("stance"),
                               confidence=pos.get("confidence"), basis="concluded", said_to=ps)
        if it.get("status") == "resolved":
            I.resolve(world, same, f"talked through: {entry.get('subject')}")
        issue_by_ref[it["subject"]] = same
    entry["issue_ids"] = sorted(set(entry.get("issue_ids") or []))

    # the confrontation in it: how it ended (or that there was one at all)
    ct = tags.get("confrontation")
    conf = X.get(world, entry.get("confrontation_id")) or next(
        (x for x in X.active(world) if x.get("conversation_id") == entry["id"]), None)
    if ct:
        ini, tgt = pid(ct.get("initiator")), pid(ct.get("target"))
        if conf is None and ini and tgt and ini != tgt:
            issue = issue_by_ref.get(ct.get("issue")) or next(iter(issue_by_ref.values()), None)
            conf = X.start(world, ini, tgt, ctype=ct.get("type"), conversation_id=entry["id"], issue=issue,
                           problem=ct.get("problem_statement"), desired=ct.get("desired_outcome"))
        if conf is not None and conf["status"] == "active":
            if ct.get("problem_statement"):
                conf["problem_statement"] = ct["problem_statement"][:240]
            if ct.get("desired_outcome"):
                conf["desired_outcome"] = ct["desired_outcome"][:200]
            sides = {}
            for nm, side in (ct.get("sides") or {}).items():
                who = pid(nm)
                if who:
                    sides[who] = side
            X.end(world, conf, ct.get("outcome") or "unresolved", summary=ct.get("summary"),
                  by=pid(ct.get("ended_by")), sides=sides)
    elif conf is not None and conf["status"] == "active":
        X.end(world, conf, "unresolved", summary="it fizzled out")
    if conf is not None:
        entry["confrontation_id"] = conf["id"]

    # an agreement made, or one renegotiated; agreements broken
    ag = tags.get("agreement")
    if ag and ag.get("terms"):
        terms = []
        for t in ag["terms"]:
            who = pid(t.get("responsible"))
            if who and t.get("obligation"):
                terms.append({"responsible_party": who, "obligation": t["obligation"], "frequency": t.get("frequency")})
        if terms:
            k = K.renegotiate(world, ag["renegotiates"], terms, conversation_id=entry["id"], by=entry.get("initiator")) \
                if ag.get("renegotiates") and K.get(world, ag["renegotiates"]) else \
                K.create(world, ps, terms, title=ag.get("title"), created_by=entry.get("initiator"),
                         conversation_id=entry["id"], confrontation_id=(conf or {}).get("id"),
                         issue_id=(conf or {}).get("issue_id") or next((i["id"] for i in issue_by_ref.values()), None))
            if k:
                entry.setdefault("contract_ids", []).append(k["id"])
    for v in tags.get("violations") or []:
        k = K.get(world, v.get("contract_id"))
        who = pid(v.get("responsible"))
        if k and who:
            K.violation(world, k, who, v.get("what") or "didn't do what was agreed",
                        observed_by=[p for p in ps if p != who], disputed=bool(v.get("disputed")),
                        evidence=f"said in conversation {entry['id']}")

    # how the opener's approach was received
    resp = tags.get("initiative_response")
    opener = cs.get(entry.get("initiator"))
    if resp and opener and resp in initiative.OUTCOMES:
        for o in ps:
            if o != opener["id"] and not (conf and conf.get("initiator_id") == opener["id"]):
                initiative.answered(opener, o, world, resp, kind=tags.get("opening"), ref=entry["id"])

    # what each now makes of the other
    for ev in tags.get("standing_events") or []:
        obs, subj = pid(ev.get("observer")), pid(ev.get("subject"))
        if obs and subj and obs != subj and ev.get("kind") in standing.DELTAS:
            standing.change(cs[obs], subj, world, ev["kind"], cause=ev.get("why") or entry.get("subject"))

    _told_subjects(world, entry, tags, pid)

    # what was said about people who weren't there
    for item in tags.get("about_others") or []:
        subject_id = id_by_name(world, item.get("name"))
        speaker_id = pid(item.get("said_by")) or entry.get("initiator")
        if not subject_id or subject_id in ps or not speaker_id:
            continue
        for listener_id in ps:
            if listener_id != speaker_id:
                R.transmit(world, speaker_id, listener_id, subject_id, item.get("claim") or "",
                           tone=item.get("tone", 0), rumour=item.get("rumour", True),
                           same_as=item.get("same_as"), conv_id=entry["id"])


def _told_subjects(world, entry, tags, pid):
    from social import rumours as R
    for t in tags.get("told_about_themselves") or []:
        r = R.get(world, t.get("rumour_id"))
        teller = pid(t.get("told_by"))
        if r and teller and r["subject_id"] in entry["participants"] and teller != r["subject_id"]:
            R.tell_subject(world, r, teller)


subscribe("social_line", on_line)
