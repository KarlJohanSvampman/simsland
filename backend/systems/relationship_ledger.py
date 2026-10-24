"""
systems/relationship_ledger.py

The relationship-impact ledger: docs/relationship_impact_plan.md.

One ledger per PAIR of characters (world["relationship_ledgers"]["idA|idB"]).
An intentional act is first written as an *intent* entry (the source's side);
each recipient/observer then runs the evaluation ladder (systems/
impact_perception.py) and, only if it registers, a *perceived* entry is written
on the pair. Only perceived entries move scores, ratios and the recipient's
feelings (trust, resentment, hostility, ...).

Producers never touch the ledger directly from an agent worker thread: they call
emit_impact(), which only puts an `impact_intent` event on the bus. The handler
below runs on the main thread at flush(), works out the audience from the world
as it is then, and writes the entries.

Summary per pair (maintained incrementally):
    pos_total / neg_total / balance / engagement(sum of |V|)
    by_char[id]: pos_caused, neg_caused
and summarize() derives the percentages (pair neg ratio, each character's own
neg ratio and their share of the pair's positive / negative impact).
"""

import random

from core.event_bus import emit, subscribe
from systems import impact_kinds
from systems.impact_perception import (
    CHECKS_TOTAL, evaluate, final_value, strain, threshold,
)

ENTRY_CAP = 400
WITNESS_SCALE = 0.6          # a neutral observer's entry for something done to someone else
ASSUMED_SCALE = 0.5          # "that was aimed at me" assumed from strain alone

_NEGATIVE_DEFAULT_DISCRETION = 0.3
_SUBTLE = {"sly", "cunning", "manipulative", "calm", "patient", "calculating", "diplomatic", "secretive"}
_IMPULSIVE = {"impulsive", "hot_tempered", "temperamental", "reckless", "aggressive", "blunt"}


def pair_key(a, b):
    return "|".join(sorted((a, b)))


def get_ledger(world, a, b, create=True):
    ledgers = world.setdefault("relationship_ledgers", {})
    key = pair_key(a, b)
    led = ledgers.get(key)
    if led is None and create:
        ids = sorted((a, b))
        led = ledgers[key] = {
            "ids": ids,
            "entries": [],
            "summary": {
                "pos_total": 0.0, "neg_total": 0.0, "balance": 0.0, "engagement": 0.0,
                "by_char": {ids[0]: {"pos_caused": 0.0, "neg_caused": 0.0},
                            ids[1]: {"pos_caused": 0.0, "neg_caused": 0.0}},
                "counts": {}, "perceived": 0, "intended": 0, "missed": 0,
            },
        }
    return led


def default_discretion(source, volume="medium", channel="speech", intent=None):
    """How covert the act is, 0-1: traits, volume, medium; the model's own INTENT
    covert rating wins when given."""
    if intent and intent.get("discretion") is not None:
        return max(0.0, min(1.0, float(intent["discretion"])))
    d = _NEGATIVE_DEFAULT_DISCRETION
    traits = set(source.get("traits") or []) | set(source.get("personality_traits") or [])
    if traits & _SUBTLE:
        d += 0.2
    if traits & _IMPULSIVE:
        d -= 0.2
    d += {"low": 0.25, "medium": 0.0, "high": -0.2, "loud": -0.3, "intense": -0.3}.get(volume, 0.0)
    if channel in ("text", "email", "post"):
        d += 0.1
    return max(0.0, min(1.0, d))


# ── writing ───────────────────────────────────────────────────────────────────

def _push(led, entry):
    led["entries"].append(entry)
    del led["entries"][:-ENTRY_CAP]


def _entry_id(world, layer):
    n = world.get("_impact_seq", 0) + 1
    world["_impact_seq"] = n
    return f"imp_{layer[0]}{n}"


def log_intent(world, source_id, target_id, kind, magnitude, discretion, channel, ref=None,
               text=None, memory_refs=None):
    """The source's side. Stored on the (source, target) pair when there is a target,
    else on the pair with the first recipient that registers it (see handle_intent)."""
    spec = impact_kinds.kinds(world)[kind]
    entry = {
        "id": _entry_id(world, "intent"), "tick": world.get("tick", 0), "layer": "intent",
        "source": source_id, "target": target_id, "polarity": spec["polarity"], "kind": kind,
        "magnitude": round(magnitude, 2), "discretion": round(discretion, 2), "channel": channel,
        "ref": ref, "text": (text or "")[:160] or None, "memory_refs": memory_refs or [],
        "registered": 0,
    }
    if target_id:
        led = get_ledger(world, source_id, target_id)
        _push(led, entry)
        led["summary"]["intended"] += 1
    return entry


def _apply_deltas(world, recipient, source_id, kind, value):
    from brain.relationships import ensure_relationship
    spec = impact_kinds.kinds(world)[kind]
    rel = ensure_relationship(recipient, source_id)
    for field, per10 in spec.get("deltas", {}).items():
        cur = rel.get(field, 0) or 0
        new = cur + per10 * value / 10.0
        if field in ("resentment", "hostility", "fear"):
            new = max(0, min(100, new))
        else:
            new = max(-100, min(100, new))
        rel[field] = round(new, 3)


def register(world, intent, recipient, value, passed, log, scale=1.0, flags=None):
    """Write the perceived entry on the (source, recipient) pair and update the
    summary and the recipient's feelings."""
    source_id, rid = intent["source"], recipient["id"]
    led = get_ledger(world, source_id, rid)
    v = round(value * scale, 2)
    entry = {
        "id": _entry_id(world, "perceived"), "tick": world.get("tick", 0), "layer": "perceived",
        "source": source_id, "target": rid, "polarity": intent["polarity"], "kind": intent["kind"],
        "magnitude": v, "discretion": intent["discretion"], "channel": intent["channel"],
        "ref": intent.get("ref"), "origin": intent["id"], "text": intent.get("text"),
        "memory_refs": intent.get("memory_refs") or [],
        "checks_passed": passed, "checks_total": CHECKS_TOTAL, "checks": log,
    }
    if flags:
        entry.update(flags)
    _push(led, entry)
    s = led["summary"]
    s["perceived"] += 1
    s["engagement"] = round(s["engagement"] + v, 2)
    s["balance"] = round(s["balance"] + intent["polarity"] * v, 2)
    if intent["polarity"] > 0:
        s["pos_total"] = round(s["pos_total"] + v, 2)
        s["by_char"][source_id]["pos_caused"] = round(s["by_char"][source_id]["pos_caused"] + v, 2)
    else:
        s["neg_total"] = round(s["neg_total"] + v, 2)
        s["by_char"][source_id]["neg_caused"] = round(s["by_char"][source_id]["neg_caused"] + v, 2)
    s["counts"][intent["kind"]] = s["counts"].get(intent["kind"], 0) + 1
    intent["registered"] = intent.get("registered", 0) + 1
    _apply_deltas(world, recipient, source_id, intent["kind"], v)
    _mirror_pair_fields(world, led)
    try:
        from systems import grudges
        grudges.on_perceived(world, recipient, source_id, intent, entry, v)       # a heavy enough hurt becomes a grudge
    except Exception as exc:
        print(f"[grudges] could not update a grudge: {exc!r}")
    return entry


def _mirror_pair_fields(world, led):
    """Cheap derived fields on both characters' relationship dicts so other
    systems can read the pair's balance without knowing about the ledger."""
    from brain.relationships import ensure_relationship
    s = led["summary"]
    total = s["pos_total"] + s["neg_total"]
    ratio = round(100.0 * s["neg_total"] / total, 1) if total else 0.0
    a, b = led["ids"]
    chars = world.get("characters", {})
    for me, other in ((a, b), (b, a)):
        c = chars.get(me)
        if c:
            rel = ensure_relationship(c, other)
            rel["impact_balance"] = s["balance"]
            rel["impact_neg_ratio"] = ratio


def summarize(world, a, b):
    """The pair's scores with every percentage derived. None if no ledger yet."""
    led = get_ledger(world, a, b, create=False)
    if not led:
        return None
    s = led["summary"]
    total = s["pos_total"] + s["neg_total"]

    def pct(num, den):
        return round(100.0 * num / den, 1) if den else 0.0

    by_char = {}
    for cid in led["ids"]:
        bc = s["by_char"][cid]
        own = bc["pos_caused"] + bc["neg_caused"]
        by_char[cid] = {
            "pos_caused": bc["pos_caused"], "neg_caused": bc["neg_caused"],
            "net_caused": round(bc["pos_caused"] - bc["neg_caused"], 2),
            "neg_ratio": pct(bc["neg_caused"], own),
            "share_of_pos": pct(bc["pos_caused"], s["pos_total"]),
            "share_of_neg": pct(bc["neg_caused"], s["neg_total"]),
            "share_of_total": pct(own, total),
        }
    return {
        "ids": led["ids"], "pos_total": s["pos_total"], "neg_total": s["neg_total"],
        "balance": s["balance"], "engagement": s["engagement"],
        "neg_ratio": pct(s["neg_total"], total), "pos_ratio": pct(s["pos_total"], total),
        "by_char": by_char, "counts": dict(s["counts"]),
        "perceived": s["perceived"], "intended": s["intended"],
    }


# ── producing ─────────────────────────────────────────────────────────────────

def emit_impact(source, kind, *, target_id=None, magnitude=None, discretion=None, channel="speech",
                audience="hearing", volume="medium", text=None, ref=None, mentions=None,
                victim_id=None, intent=None, memory_refs=None):
    """Called from wherever something intentional happens. Safe from agent
    worker threads: it only posts an event; the handler does the writing.

    audience: "hearing" (whoever could hear it), "sight" (whoever could see it),
              "targets" (target only -- text, call, anything delivered directly)."""
    if not kind:
        return
    emit("impact_intent", {
        "source_id": source["id"], "target_id": target_id, "kind": kind, "magnitude": magnitude,
        "discretion": discretion if discretion is not None else default_discretion(source, volume, channel, intent),
        "channel": channel, "audience": audience, "volume": volume, "text": text, "ref": ref,
        "mentions": list(mentions or []), "victim_id": victim_id, "memory_refs": memory_refs or [],
    })


def _recipients(world, source, data):
    """[(recipient dict, ctx extras)] for the event, resolved against the world as
    it stands now."""
    from systems.expressions import audience as hearing_audience
    chars = world.get("characters", {})
    target_id, victim_id = data.get("target_id"), data.get("victim_id")
    mentions = set(data.get("mentions") or [])
    out = {}

    def add(cid, **extra):
        c = chars.get(cid)
        if c and cid != source["id"] and not (c.get("is_workplace_npc") or c.get("is_service_worker")):
            out.setdefault(cid, {}).update(extra)

    mode = data.get("audience", "hearing")
    if target_id:
        add(target_id, is_target=True, certain=(mode == "targets"))
    if mode == "hearing":
        heard = hearing_audience(world, source, data.get("volume", "medium"))
        heard_ids = {h["id"] for h in heard}
        for h in heard:
            add(h["id"], clarity=h["clarity"])
        if target_id and target_id not in heard_ids:
            out.get(target_id, {})["clarity"] = 0.0        # addressed, but out of earshot
        if len(heard) == 1 and not target_id:
            out.get(heard[0]["id"], {})["only_listener"] = True
    elif mode == "sight":
        for cid, c in chars.items():
            if cid == source["id"]:
                continue
            seen = (c.get("perception") or {}).get("visible_people") or []
            if any(p.get("id") == source["id"] for p in seen):
                add(cid, clarity=1.0)
        if victim_id and victim_id != target_id:
            add(victim_id, is_target=True, certain=True)
    for mid in mentions:
        add(mid, mentioned=True)
    return list(out.items())


def _closeness(world, observer, victim_id):
    if not victim_id:
        return 0.0
    rel = (observer.get("relationships") or {}).get(victim_id) or {}
    return max(0.0, min(1.0, max(rel.get("friendship", 0) or 0, rel.get("trust", 0) or 0,
                                 (rel.get("familiarity", 0) or 0) / 2) / 100.0))


def handle_intent(data, world):
    chars = world.get("characters", {})
    source = chars.get(data.get("source_id"))
    kind = data.get("kind")
    specs = impact_kinds.kinds(world)
    if not source or kind not in specs:
        return []
    spec = specs[kind]
    M = data.get("magnitude") if data.get("magnitude") is not None else spec["base"]
    d = data.get("discretion", _NEGATIVE_DEFAULT_DISCRETION)
    intent = log_intent(world, source["id"], data.get("target_id"), kind, M, d, data.get("channel", "speech"),
                        ref=data.get("ref"), text=data.get("text"), memory_refs=data.get("memory_refs"))
    T = threshold(d)
    written = []
    for rid, extra in _recipients(world, source, data):
        r = chars[rid]
        rel = (r.get("relationships") or {}).get(source["id"]) or {}
        victim_id = data.get("victim_id")
        closeness = 0.0
        scale = 1.0
        flags = None
        observer = not (extra.get("is_target") or extra.get("mentioned") or extra.get("only_listener"))
        if observer and victim_id and rid != victim_id:
            closeness = _closeness(world, r, victim_id)
        ctx = {
            "kind": kind, "polarity": spec["polarity"], "magnitude": M, "discretion": d,
            "channel": data.get("channel"), "clarity": extra.get("clarity"),
            "certain": extra.get("certain", False), "is_target": extra.get("is_target", False),
            "mentioned": extra.get("mentioned", False), "only_listener": extra.get("only_listener", False),
            "witness_closeness": closeness, "volume": data.get("volume"),
        }
        passed, log = evaluate(r, rel, ctx)
        if observer:
            if closeness >= 0.3:
                scale = WITNESS_SCALE * (0.5 + closeness / 2)
                flags = {"witnessed": True, "victim": victim_id}
            elif strain(rel) >= 20:
                scale = ASSUMED_SCALE
                flags = {"misattributed": True}
        if passed < T:
            continue
        value = final_value(M, passed, d)
        if value <= 0:
            continue
        written.append(register(world, intent, r, value, passed, log, scale=scale, flags=flags))
    if not written:
        led = get_ledger(world, source["id"], data.get("target_id") or source["id"], create=False)
        if led:
            led["summary"]["missed"] += 1
    return written


# ── event subscriptions ───────────────────────────────────────────────────────

def _on_impact_intent(data, world):
    handle_intent(data, world)


def _on_expression_made(data, world):
    """A one-way remark: it counts only when the speaker meant it (an INTENT) or its
    speech act is one with a fixed meaning; plain exclaims and muttering don't."""
    chars = world.get("characters", {})
    source = chars.get(data.get("speaker"))
    if not source:
        return
    intent = data.get("intent")
    kind = impact_kinds.kind_for_speech(data.get("speech_act"), intent)
    if not kind:
        return
    handle_intent({
        "source_id": source["id"], "target_id": data.get("target"), "kind": kind,
        "discretion": default_discretion(source, data.get("volume", "medium"), "expression", intent),
        "channel": "expression", "audience": "hearing", "volume": data.get("volume", "medium"),
        "text": data.get("text"), "ref": {"type": "expression", "id": data.get("id")},
        "mentions": data.get("mentions"),
    }, world)


def _on_conversation_ignored(data, world):
    chars = world.get("characters", {})
    ignorer = chars.get(data.get("ignorer_id"))
    if not ignorer:
        return
    handle_intent({
        "source_id": ignorer["id"], "target_id": data.get("speaker_id"),
        "kind": "ignored_heard" if data.get("heard") else "ignored",
        "discretion": 0.1, "channel": "speech", "audience": "targets",
        "ref": {"type": "conversation", "id": data.get("conv_id")}, "text": data.get("utterance"),
    }, world)


subscribe("impact_intent", _on_impact_intent)
subscribe("expression_made", _on_expression_made)
subscribe("conversation_ignored", _on_conversation_ignored)
