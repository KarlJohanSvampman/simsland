"""
systems/bg_work.py -- who has background-LLM work waiting (step 5a).

Four services hand work to the background LLM (systems/bg_llm.py) and collect the answers: loop-guard self-assessments
and personal rules (per character), behaviour theories (per character), household narrations (per household). Each
used to scan every character/household every 5 seconds looking for a "pending" marker. Now whoever sets a marker notes
the entity here; the services look only at the noted ones, and the "background_services" DUTY runs while any is noted.

    note(world, kind, entity_id)    work is waiting ("loop", "theory", "rules" for characters, "hhsum" for households)
    targets(world, kind)            the noted entity ids of that kind (a world never seen before is scanned once)
    done(world, kind, entity_id)    nothing more is waiting for that entity
    active(world)                   DUTY check
"""

KINDS = ("loop", "theory", "rules", "hhsum")


def _reg(world):
    reg = world.get("_bg_work")
    if reg is None:
        reg = world["_bg_work"] = {k: [] for k in KINDS}
        _rebuild(world, reg)
    return reg


def _rebuild(world, reg):
    for cid, c in dict.items(world.get("characters") or {}):
        if c.get("_loop_assessment"):
            reg["loop"].append(cid)
        if c.get("_rules_due") or c.get("_rules_ask"):
            reg["rules"].append(cid)
        if any(p.get("theory_pending") for ps in (c.get("behavior_patterns") or {}).values() for p in ps):
            reg["theory"].append(cid)
    for hid, h in dict.items(world.get("households") or {}):
        if any(e.get("pending") for t in ("hourly_summaries", "daily_summaries", "weekly_summaries") for e in h.get(t) or []):
            reg["hhsum"].append(hid)


def note(world, kind, entity_id):
    if world is None:
        return
    ids = _reg(world).setdefault(kind, [])
    if entity_id not in ids:
        ids.append(entity_id)
    from core.flow import wake_duty
    wake_duty(world, "background_services")


def targets(world, kind):
    return list(_reg(world).get(kind) or ())


def done(world, kind, entity_id):
    ids = _reg(world).get(kind) or []
    if entity_id in ids:
        ids.remove(entity_id)


def active(world):
    return any(_reg(world).get(k) for k in KINDS)
