"""
systems/envy.py

Envy and conflict-of-interest as drama generators.

This module provides a daily tick that scans for envy-generating situations
across the simulation and routes them into the grievance and conflict systems.

Envy types:
  1. Romantic envy       — attracted to someone who is with another
  2. Partner jealousy    — partner showing interest elsewhere
  3. Status envy         — significant wealth/prestige/reputation gap
  4. Career envy         — co-worker promoted, got a better job, earns more
  5. Social envy         — someone is more popular / has more friends
  6. Opportunity envy    — someone got a lucky break you deserved

Conflict-of-interest types:
  1. Power-dynamic attraction  — supervisor ↔ subordinate attraction
  2. Romantic rivalry          — two chars competing for the same person
  3. Loyalty conflict          — attracted to a close friend's partner
  4. Professional conflict     — business partners with unequal attraction stakes

All envy events call add_grievance() so they integrate seamlessly with the
existing conflict pipeline and can escalate to confrontations, cold-shoulders,
or full conflicts.
"""

import random

from systems.grievances import add_grievance, SEVERITY as BASE_SEVERITY
from systems.attraction import (
    check_envy_events,
    check_conflict_of_interest,
    ENVY_ATTRACTION_THRESHOLD,
)

# ── Severity table extensions ─────────────────────────────────────────────

ENVY_SEVERITY = {
    "romantic_envy":      10.0,
    "partner_jealousy":    9.0,
    "status_envy":         5.0,
    "career_envy":         6.0,
    "social_envy":         4.0,
    "opportunity_envy":    5.5,
    "rejected_advance":    4.0,   # also used by intimacy.py
}

# Traits that amplify or suppress envy
AMPLIFY_TRAITS  = {"jealous", "possessive", "materialistic", "ambitious",
                   "greedy", "competitive", "spiteful", "vindictive"}
SUPPRESS_TRAITS = {"forgiving", "humble", "selfless", "compassionate", "wise",
                   "patient", "content"}


def _envy_multiplier(c):
    """Return a 0.3 – 2.0 severity multiplier based on traits."""
    traits = set(c.get("traits", []) + c.get("personality_traits", []))
    amp = sum(0.20 for t in traits if t in AMPLIFY_TRAITS)
    sup = sum(0.15 for t in traits if t in SUPPRESS_TRAITS)
    return max(0.3, min(2.0, 1.0 + amp - sup))


# ── Career envy ───────────────────────────────────────────────────────────

def _check_career_envy(world, chars):
    """
    Career envy: co-worker got a better job, higher salary, or was promoted
    recently while c is stagnating.
    """
    for cid, c in chars.items():
        traits = set(c.get("traits", []) + c.get("personality_traits", []))
        if not (traits & {"jealous", "ambitious", "competitive", "materialistic"}):
            continue  # only these types feel career envy

        c_job       = c.get("job") or {}
        c_prestige  = c_job.get("prestige_level", 1)
        c_salary    = c_job.get("salary", 0) or 0
        c_company   = c_job.get("company_id")

        for oid, o in chars.items():
            if oid == cid:
                continue
            o_job       = o.get("job") or {}
            o_company   = o_job.get("company_id")

            # Only care about co-workers (same company) or same industry
            same_workplace = c_company and c_company == o_company
            if not same_workplace:
                continue

            o_prestige  = o_job.get("prestige_level", 1)
            o_salary    = o_job.get("salary", 0) or 0
            prestige_gap = o_prestige - c_prestige
            salary_gap   = (o_salary - c_salary) / max(c_salary, 1.0)

            if prestige_gap >= 2 or salary_gap > 0.40:
                severity = ENVY_SEVERITY["career_envy"]
                if prestige_gap >= 3:
                    severity *= 1.4
                severity *= _envy_multiplier(c)
                add_grievance(
                    c, oid,
                    "career_envy",
                    world,
                    severity=round(min(severity, 15.0), 2),
                    details={"prestige_gap": prestige_gap,
                             "salary_gap": round(salary_gap, 2)}
                )


# ── Social envy ───────────────────────────────────────────────────────────

def _check_social_envy(world, chars):
    """
    Social envy: someone is significantly more popular / well-liked.
    """
    # Only paranoid, jealous, or insecure characters feel social envy
    for cid, c in chars.items():
        traits = set(c.get("traits", []) + c.get("personality_traits", []))
        if not (traits & {"jealous", "envious", "vain", "egotistical",
                          "competitive", "paranoid"}):
            continue

        c_friend_count = sum(
            1 for rel in c.get("relationships", {}).values()
            if rel.get("state") in ("friend", "close_friend")
        )
        c_rep = c.get("reputation", {}).get("global", 0.5)

        # Compare to household/workplace peers
        peer_ids = set()
        hid = c.get("household_id")
        if hid:
            for oc in chars.values():
                if oc.get("household_id") == hid and oc["id"] != cid:
                    peer_ids.add(oc["id"])
        wid = (c.get("job") or {}).get("company_id")
        if wid:
            for oc in chars.values():
                if (oc.get("job") or {}).get("company_id") == wid and oc["id"] != cid:
                    peer_ids.add(oc["id"])

        for oid in peer_ids:
            o = chars[oid]
            o_friend_count = sum(
                1 for rel in o.get("relationships", {}).values()
                if rel.get("state") in ("friend", "close_friend")
            )
            o_rep = o.get("reputation", {}).get("global", 0.5)
            friend_gap = o_friend_count - c_friend_count
            rep_gap    = o_rep - c_rep

            if friend_gap >= 3 or rep_gap >= 0.2:
                severity = ENVY_SEVERITY["social_envy"]
                severity *= _envy_multiplier(c)
                if friend_gap >= 5:
                    severity *= 1.3
                add_grievance(
                    c, oid,
                    "social_envy",
                    world,
                    severity=round(min(severity, 10.0), 2),
                    details={"friend_gap": friend_gap,
                             "rep_gap": round(rep_gap, 2)}
                )


# ── Opportunity envy ──────────────────────────────────────────────────────

def _check_opportunity_envy(world, chars):
    """
    Opportunity envy: someone got a lucky break (inheritance, windfall,
    chance encounter) that the envious char thinks should have been theirs.
    This is triggered by world events stored in world["recent_events"].
    """
    recent = world.get("recent_events", [])
    if not recent:
        return

    WINDFALL_EVENTS = {"inheritance_received", "lottery_won", "job_promoted",
                       "business_success", "wealthy_encounter"}

    for event in recent:
        etype = event.get("type", "")
        if etype not in WINDFALL_EVENTS:
            continue
        beneficiary_id = event.get("character_id")
        if not beneficiary_id or beneficiary_id not in chars:
            continue

        beneficiary = chars[beneficiary_id]
        b_household = beneficiary.get("household_id")
        b_company   = (beneficiary.get("job") or {}).get("company_id")

        for cid, c in chars.items():
            if cid == beneficiary_id:
                continue
            traits = set(c.get("traits", []) + c.get("personality_traits", []))
            if not (traits & {"jealous", "greedy", "spiteful", "competitive"}):
                continue
            # Only trigger if they're in the same social circle
            same_circle = (
                (b_household and c.get("household_id") == b_household) or
                (b_company   and (c.get("job") or {}).get("company_id") == b_company)
            )
            if not same_circle:
                continue

            severity = ENVY_SEVERITY["opportunity_envy"] * _envy_multiplier(c)
            add_grievance(
                c, beneficiary_id,
                "opportunity_envy",
                world,
                severity=round(min(severity, 12.0), 2),
                details={"event_type": etype}
            )


# ── Master daily tick ─────────────────────────────────────────────────────

def tick_envy(world):
    """
    Daily tick — runs all envy and conflict-of-interest checks.
    Called from sim_loop at DAILY cadence.
    """
    chars = {c["id"]: c for c in world.get("characters", [])
             if not c.get("is_offscreen")}

    # Romantic envy + partner jealousy + status envy (from attraction.py)
    check_envy_events(world)

    # Conflict-of-interest flags (from attraction.py)
    check_conflict_of_interest(world)

    # Career envy
    _check_career_envy(world, chars)

    # Social envy (every 3 days to save perf)
    if world.get("tick", 0) % (3 * 24 * 60) == 0:
        _check_social_envy(world, chars)

    # Opportunity envy (triggered by events, run daily)
    _check_opportunity_envy(world, chars)


# ── LLM context helper ────────────────────────────────────────────────────

def get_envy_context(c, world):
    """
    Summarise active envy grievances for LLM context.
    Returns dict with "envy" key listing who c envies and why.
    """
    chars  = {x["id"]: x for x in world.get("characters", [])}
    lines  = []
    ENVY_TYPES = {"romantic_envy", "partner_jealousy", "status_envy",
                  "career_envy", "social_envy", "opportunity_envy"}

    for griev in c.get("grievances", []):
        if griev.get("event_type") not in ENVY_TYPES:
            continue
        if griev.get("weight", 0) < 1.0:
            continue
        target = chars.get(griev["caused_by"], {})
        name   = target.get("name", griev["caused_by"])
        etype  = griev["event_type"].replace("_", " ")
        detail = griev.get("details", {})
        line   = f"{etype} toward {name}"
        if "attraction_target" in detail:
            tgt = chars.get(detail["attraction_target"], {}).get("name", "someone")
            line += f" (over {tgt})"
        elif "prestige_gap" in detail:
            line += f" (prestige gap +{detail['prestige_gap']})"
        lines.append(line)

    # Conflict-of-interest flags
    for oid, rel in c.get("relationships", {}).items():
        flags = rel.get("conflict_flags", [])
        if flags:
            name = chars.get(oid, {}).get("name", oid)
            lines.append(f"conflict_of_interest with {name}: {', '.join(flags)}")

    return {"envy_conflicts": lines} if lines else {}
