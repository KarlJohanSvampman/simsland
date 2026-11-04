"""
social/rumours.py -- claims about people, passed on (design section 10).

Gossip is social information, not world state: nothing here changes what happened, only what people believe.

    world["rumors"][id] = {"id", "subject_id", "claim", "originating_event_id", "originator_id",
                           "information_status": verified | unverified | false | disputed | unknown,
                           "original_context", "created_at", "polarity" (-1, 0, 1), "last_activity",
                           "transmissions": [RumourTransmission]}
    RumourTransmission = {"id", "rumour_id", "sender_id", "receiver_id", "timestamp", "claim_as_told",
                          "perceived_credibility", "perceived_intent", "interpretation",
                          "confidence_after_transmission", "conv_id"}
    c["known_rumours"][rumour id] = {"confidence", "heard_from": [...], "interpretation", "first_heard", "last_heard"}

A claim is not simply believed. How much a listener takes from it depends on their trust in whoever told them, what
they already think of the person it's about, what they've seen for themselves, the evidence (its status), how easily
they're swayed, and whether other people they trust have said the same. Retold claims can drift: each transmission
keeps the words as told, next to the original claim.

Who tells whom is the characters' own doing (their AI, in conversation); the AI reading the conversation says what
was claimed and about whom (social/discourse.py) and, if it's a rumour they had already heard, which one.
"""

import uuid

from social.core import DAY, chars, clamp, emit, now, name, rel

LAPSE_DAYS = 30
CAP = 300
CREDULOUS = {"gullible", "naive", "trusting", "impressionable"}
SCEPTICAL = {"skeptical", "sceptical", "cynical", "analytical", "suspicious", "logical"}


def store(world):
    return world.setdefault("rumors", {})


def get(world, rid):
    return store(world).get(rid) if rid else None


def known_by(world, cid, min_conf=0.25):
    c = chars(world).get(cid) or {}
    out = []
    for rid, k in (c.get("known_rumours") or {}).items():
        r = get(world, rid)
        if r and k.get("confidence", 0) >= min_conf:
            out.append(r)
    return out


def _similar(a, b):
    a, b = str(a or "").lower(), str(b or "").lower()
    if a == b or (a and b and (a in b or b in a)):
        return True
    wa, wb = {w for w in a.split() if len(w) > 3}, {w for w in b.split() if len(w) > 3}
    return bool(wa and wb and len(wa & wb) * 2 >= min(len(wa), len(wb)) + 1)


def find(world, subject_id, claim):
    for r in store(world).values():
        if r["subject_id"] == subject_id and _similar(r["claim"], claim):
            return r
    return None


def create(world, subject_id, claim, originator_id=None, polarity=0, context=None, origin_event=None,
           status="unverified"):
    rid = f"rumour_{uuid.uuid4().hex[:8]}"
    r = {"id": rid, "subject_id": subject_id, "claim": str(claim)[:200], "originating_event_id": origin_event,
         "originator_id": originator_id, "information_status": status, "original_context": str(context or "")[:200],
         "created_at": now(world), "polarity": polarity, "last_activity": now(world), "transmissions": []}
    s = store(world)
    s[rid] = r
    if len(s) > CAP:
        for old in sorted(s, key=lambda k: s[k].get("last_activity") or 0)[:len(s) - CAP]:
            s.pop(old, None)
    emit("RumourCreated", {"rumour_id": rid, "subject_id": subject_id, "originator_id": originator_id})
    return r


def credibility(world, receiver, sender_id, subject_id, polarity, rumour):
    """0..1: how believable the receiver finds it, from this sender, now."""
    rs = rel(receiver, sender_id, create=False)
    from social import standing
    cred = 0.35 + (rs.get("trust") or 0) / 160 + (rs.get("friendship") or 0) / 400
    view = standing.score(receiver, subject_id)
    if polarity < 0:
        cred -= max(0, view) / 250            # they think well of the person: harder to believe ill of them
        cred += max(0, -view) / 300           # ... and easier if they already think badly of them
    elif polarity > 0:
        cred += max(0, view) / 400
        cred -= max(0, -view) / 300
    status = rumour.get("information_status")
    cred += {"verified": 0.25, "false": -0.35, "disputed": -0.15}.get(status, 0)
    others = {t["sender_id"] for t in rumour["transmissions"] if t["receiver_id"] == receiver["id"]
              and t["sender_id"] != sender_id and (rel(receiver, t["sender_id"], create=False).get("trust") or 0) > 10}
    cred += 0.12 * min(3, len(others))       # trusted people saying the same
    traits = set(receiver.get("traits") or [])
    if traits & CREDULOUS or (receiver.get("age") or 30) < 10:
        cred += 0.15
    if traits & SCEPTICAL:
        cred -= 0.15
    return round(clamp(cred, 0.05, 0.95), 2)


def _intent(world, receiver, sender_id, subject_id, polarity):
    sender = chars(world).get(sender_id) or {}
    r = rel(sender, subject_id, create=False)
    if polarity > 0:
        return "praise"
    if (r.get("hostility") or 0) > 30 or (r.get("resentment") or 0) > 40:
        return "malicious"
    if (rel(receiver, subject_id, create=False).get("friendship") or 0) > 30:
        return "warning"
    return "gossip" if polarity < 0 else "news"


def transmit(world, sender_id, receiver_id, subject_id, claim, tone=0, rumour=True, same_as=None, conv_id=None,
             via=None, ref=None):
    """sender told receiver something about subject. Returns the transmission."""
    cs = chars(world)
    sender, receiver = cs.get(sender_id), cs.get(receiver_id)
    if not sender or not receiver or not subject_id or sender_id == receiver_id or not str(claim).strip():
        return None
    try:
        tone = max(-2, min(2, int(tone)))
    except (TypeError, ValueError):
        tone = 0
    polarity = (tone > 0) - (tone < 0)
    r = get(world, same_as) or find(world, subject_id, claim)
    if r is None:
        heard = (sender.get("known_rumours") or {})
        originator = sender_id
        r = create(world, subject_id, claim, originator_id=originator, polarity=polarity,
                   context=f"said by {name(world, sender_id)} in conversation" if conv_id else None,
                   status="unverified" if rumour else "unknown")
    if receiver_id == subject_id:
        return tell_subject(world, r, sender_id)
    if ref and any(t.get("ref") == ref and t["receiver_id"] == receiver_id for t in r["transmissions"]):
        return None                                       # the same post read again, the same line counted once
    prior = ((receiver.get("known_rumours") or {}).get(r["id"]) or {}).get("confidence", 0.0)
    cred = credibility(world, receiver, sender_id, subject_id, polarity or r.get("polarity", 0), r)
    conf = round(clamp(prior + (cred - prior) * (0.6 if prior else 1.0), 0, 1), 2)
    intent = _intent(world, receiver, sender_id, subject_id, polarity)
    interpretation = ("believes it" if conf >= 0.65 else "half believes it" if conf >= 0.4 else "doubts it")
    t = {"id": f"tx_{uuid.uuid4().hex[:6]}", "rumour_id": r["id"], "sender_id": sender_id, "receiver_id": receiver_id,
         "timestamp": now(world), "claim_as_told": str(claim)[:200], "perceived_credibility": cred,
         "perceived_intent": intent, "interpretation": interpretation, "confidence_after_transmission": conf,
         "conv_id": conv_id, "via": via, "ref": ref}
    r["transmissions"].append(t)
    del r["transmissions"][:-60]
    r["last_activity"] = now(world)
    k = receiver.setdefault("known_rumours", {}).setdefault(r["id"], {"confidence": 0.0, "heard_from": [],
                                                                     "first_heard": now(world)})
    k["confidence"] = conf
    k["interpretation"] = interpretation
    k["last_heard"] = now(world)
    if sender_id not in k["heard_from"]:
        k["heard_from"].append(sender_id)
    # what it does to the listener's view of the subject: as much as they believe it, and only the change
    from social import standing
    moved = (conf - prior) if conf > prior else 0
    if moved and tone:
        standing.change(receiver, subject_id, world, "rumour", delta=round(tone * 5 * moved, 2),
                        cause=f"heard from {name(world, sender_id)}"
                              f"{' (a rumour)' if rumour else ''}: {claim} -- {interpretation}")
    if moved and tone:
        try:
            from systems.rumors import _shift_listener
            _shift_listener(receiver, subject_id, 1 if tone > 0 else -1, abs(tone) * 5 * moved)
        except Exception:
            pass
    if intent == "malicious" and conf < 0.4:
        standing.change(receiver, sender_id, world, "rumour", delta=-2, cause=f"{name(world, sender_id)} was badmouthing {name(world, subject_id)}")
    try:
        from brain.memory import store_memory
        doubt = "" if conf >= 0.65 else " I'm not sure I believe it." if conf >= 0.4 else " I doubt it's true."
        if via == "post":
            what = "posted nice things about" if tone > 0 else "posted about"
            text = f"I read that {name(world, sender_id)} {what} {name(world, subject_id)}: \"{claim}\".{doubt}"
        else:
            text = f"{name(world, sender_id)} told me that {name(world, subject_id)}: {claim}.{doubt}"
        store_memory(receiver, text,
                     importance=0.45 if conf >= 0.4 else 0.3, tags=["gossip", "rumor"],
                     people=[sender_id, subject_id], tick=now(world), source="heard")
    except Exception:
        pass
    emit("RumourTransmitted", {"rumour_id": r["id"], "sender_id": sender_id, "receiver_id": receiver_id,
                               "confidence": conf})
    return t


def tell_subject(world, r, teller_id):
    """Someone tells the person a rumour is about what's being said about them."""
    cs = chars(world)
    subject, teller = cs.get(r["subject_id"]), cs.get(teller_id)
    if not subject or not teller:
        return None
    source = r.get("originator_id") or teller_id
    t = {"id": f"tx_{uuid.uuid4().hex[:6]}", "rumour_id": r["id"], "sender_id": teller_id, "receiver_id": subject["id"],
         "timestamp": now(world), "claim_as_told": r["claim"], "perceived_credibility": 1.0,
         "perceived_intent": "told_subject", "interpretation": "heard what's said about them",
         "confidence_after_transmission": 1.0, "conv_id": None}
    r["transmissions"].append(t)
    r["told_to_subject"] = True
    if source != subject["id"] and source in cs:
        emit("impact_intent", {
            "source_id": source, "target_id": subject["id"], "kind": "meanness" if r.get("polarity", 0) < 0 else "compliment",
            "magnitude": None, "discretion": 0.1, "channel": "learned_secondhand", "audience": "targets", "volume": "low",
            "text": r["claim"], "ref": {"type": "rumor", "id": r["id"], "told_by": teller_id},
            "mentions": [], "victim_id": None, "memory_refs": [],
        })
        from social import standing, frustration
        if r.get("polarity", 0) < 0:
            standing.change(subject, source, world, "rumour", delta=-8,
                            cause=f"{name(world, teller_id)} told me {name(world, source)} said: {r['claim']}")
            frustration.raise_(subject, source, world, 10, cause=f"what {name(world, source)} has been saying about me")
        elif r.get("polarity", 0) > 0:
            standing.change(subject, source, world, "rumour", delta=4, cause=f"heard {name(world, source)} spoke well of me")
    return t


def set_status(world, r, status):
    if status in ("verified", "unverified", "false", "disputed", "unknown"):
        r["information_status"] = status


def tick(world):
    """Old talk is forgotten."""
    t = now(world)
    s = store(world)
    for rid in list(s):
        r = s[rid]
        if "subject_id" not in r:
            continue
        if t - (r.get("last_activity") or t) > LAPSE_DAYS * DAY:
            s.pop(rid, None)
            for c in chars(world).values():
                (c.get("known_rumours") or {}).pop(rid, None)
