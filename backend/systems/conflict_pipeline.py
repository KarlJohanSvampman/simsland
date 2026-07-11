"""
systems/conflict_pipeline.py

Three-phase conflict state machine:

  DELIBERATION  Both parties privately evaluate willingness to engage
                constructively. Based on traits, emotion, relationship.
                → both willing          → NEGOTIATION
                → one or neither        → FIGHT
                → initiator backs down  → cold_shoulder

  NEGOTIATION   Structured exchange: name the problem, propose terms,
                find overlap (ZOPA). Each sim has a concession range
                shaped by their traits.
                → overlap found + accepted → social contract → resolved
                → no overlap / rejected    → FIGHT or cold_shoulder

  FIGHT         Escalating confrontation modelled as a stage machine:
                  verbal_dispute → heated_argument
                               → shouting_match → physical_altercation
                Each tick has a chance to escalate, de-escalate, or
                trigger a specific dramatic exit.
                → de_escalation     → drop a stage or end
                → storm_off         → dramatic exit, door slam
                → intervention      → third party breaks it up
                → physical_resolved → violence; may trigger law pipeline

Events emitted:
  conflict_started        on start_conflict()
  conflict_phase_changed  on phase transition
  conflict_resolved       on any terminal outcome
  social_contract_created on successful negotiation
  fight_physical          on physical_altercation (→ law pipeline)
  fight_storm_off         on storm-off exit
  fight_intervention      on third-party stop
"""

import uuid
import random

from core.event_bus import emit


# ── Constants ─────────────────────────────────────────────────────────────

PHASE_DELIBERATION = "deliberation"
PHASE_NEGOTIATION  = "negotiation"
PHASE_FIGHT        = "fight"

FIGHT_STAGES = [
    "verbal_dispute",
    "heated_argument",
    "shouting_match",
    "physical_altercation",
]

# How many ticks each phase runs before auto-advancing
DELIBERATION_DURATION = 10
NEGOTIATION_DURATION  = 30   # exchanges; each takes a few ticks
FIGHT_EXCHANGE_TICKS  = 5    # ticks between fight exchanges

# ── Trait helpers ─────────────────────────────────────────────────────────

def _has(c, *traits):
    return any(t in c.get("traits", []) for t in traits)


def _willingness_to_compromise(c, conflict, world):
    """
    0 = refuses to engage; 1 = very willing.
    Driven by traits, emotion, relationship state, and how bad the grievance is.
    """
    score = 0.5  # base

    # Personality
    if _has(c, "agreeable", "empathetic", "conflict_averse"):
        score += 0.20
    if _has(c, "stubborn", "hot_headed", "proud"):
        score -= 0.20
    if _has(c, "forgiving"):
        score += 0.10
    if _has(c, "vindictive", "aggressive"):
        score -= 0.15

    # Emotional state
    emotion = c.get("emotion", "neutral")
    if emotion in ("angry", "furious", "hostile"):
        score -= 0.25
    elif emotion in ("sad", "anxious", "guilty"):
        score += 0.10

    # Relationship — value it more → more willing to work it out
    other_id = _other_party(conflict, c["id"])
    rel = c.get("relationships", {}).get(other_id, {})
    friendship = rel.get("friendship", 0)
    hostility  = rel.get("hostility",  0)
    score += friendship * 0.003
    score -= hostility  * 0.004

    return max(0.0, min(1.0, score + random.gauss(0, 0.05)))


def _escalation_chance(c, other, stage_idx, world):
    """Probability this character's exchange escalates the fight."""
    base = 0.15 + stage_idx * 0.08  # higher stages escalate faster

    if _has(c, "hot_headed", "aggressive", "volatile"):
        base += 0.20
    if _has(c, "conflict_averse", "gentle", "calm"):
        base -= 0.15
    if _has(other, "provocative", "dismissive"):
        base += 0.10

    emotion = c.get("emotion", "neutral")
    if emotion in ("furious", "angry"):
        base += 0.15
    elif emotion in ("sad", "guilty"):
        base -= 0.10

    rel = c.get("relationships", {}).get(other["id"], {})
    base += rel.get("hostility", 0) * 0.002

    return max(0.0, min(0.95, base))


def _de_escalation_chance(c, other, world):
    """Probability this character backs down or softens."""
    base = 0.10
    if _has(c, "empathetic", "conflict_averse", "gentle"):
        base += 0.20
    if _has(c, "proud", "stubborn", "aggressive"):
        base -= 0.15
    emotion = c.get("emotion", "neutral")
    if emotion in ("sad", "guilty", "anxious"):
        base += 0.15
    rel = c.get("relationships", {}).get(other["id"], {})
    base += rel.get("friendship", 0) * 0.002
    return max(0.0, min(0.8, base))


def _concession_range(c):
    """
    How wide is this character's ZOPA? Returns a float 0-1.
    Stubborn sims barely concede; agreeable sims concede a lot.
    """
    base = 0.4
    if _has(c, "agreeable", "flexible", "empathetic"):
        base += 0.25
    if _has(c, "stubborn", "proud"):
        base -= 0.20
    if _has(c, "conflict_averse"):
        base += 0.15  # wants it to end, so gives ground
    return max(0.05, min(0.9, base))


# ── Helpers ───────────────────────────────────────────────────────────────

def _other_party(conflict, my_id):
    for pid in conflict["parties"]:
        if pid != my_id:
            return pid
    return None


def _get_chars(conflict, world):
    chars = world.get("characters", {})
    return [chars[pid] for pid in conflict["parties"] if pid in chars]


def _find_nearby_third_party(conflict, world):
    """Look for a character near the conflict who could intervene."""
    chars   = world.get("characters", {})
    parties = set(conflict["parties"])
    # crude proximity: same room as any party member
    party_rooms = {chars[pid].get("room_id") for pid in conflict["parties"] if pid in chars}
    for cid, c in chars.items():
        if cid in parties:
            continue
        if c.get("room_id") in party_rooms:
            if _has(c, "protective", "responsible", "brave") or random.random() < 0.15:
                return c
    return None


# ── Conflict creation ─────────────────────────────────────────────────────

def start_conflict(initiator_id, target_id, world):
    """
    Create a new conflict and move it into DELIBERATION.
    Skips if either party is already in an active conflict.
    """
    # Guard: no double-conflict
    for existing in world.get("conflicts", {}).values():
        if existing["outcome"] is not None:
            continue
        if initiator_id in existing["parties"] or target_id in existing["parties"]:
            return None

    from systems.grievances import get_top_grievances
    chars = world.get("characters", {})
    initiator = chars.get(initiator_id)
    if not initiator or not chars.get(target_id):
        return None

    # Collect grievances being brought to the table
    grievances = get_top_grievances(initiator, target_id)

    conflict = {
        "id":                f"conflict_{uuid.uuid4().hex[:8]}",
        "parties":           [initiator_id, target_id],
        "initiator":         initiator_id,
        "phase":             PHASE_DELIBERATION,
        "fight_stage_idx":   0,
        "fight_stage":       FIGHT_STAGES[0],
        "willingness":       {},
        "grievances_addressed": [g["id"] for g in grievances],
        "issues":            [g["event_type"] for g in grievances],
        "proposed_terms":    [],
        "accepted_terms":    [],
        "exchanges":         0,
        "escalation_score":  0.0,
        "tick_started":      world["tick"],
        "tick_phase_start":  world["tick"],
        "outcome":           None,
        "contract_id":       None,
        "log":               [],
    }

    world.setdefault("conflicts", {})[conflict["id"]] = conflict
    emit("conflict_started", {"conflict_id": conflict["id"], "parties": conflict["parties"]})
    return conflict


# ── Deliberation ──────────────────────────────────────────────────────────

def _process_deliberation(conflict, world):
    ticks_in_phase = world["tick"] - conflict["tick_phase_start"]

    # Compute willingness for any party that hasn't decided yet
    chars = world.get("characters", {})
    for pid in conflict["parties"]:
        if pid not in conflict["willingness"]:
            c = chars.get(pid)
            if c:
                conflict["willingness"][pid] = _willingness_to_compromise(c, conflict, world)

    if ticks_in_phase < DELIBERATION_DURATION:
        return  # still thinking

    both_willing   = all(w >= 0.45 for w in conflict["willingness"].values())
    either_willing = any(w >= 0.45 for w in conflict["willingness"].values())
    initiator_w    = conflict["willingness"].get(conflict["initiator"], 0)

    if initiator_w < 0.25:
        # Initiator backed down — suppress
        _resolve(conflict, "suppressed", world)
    elif both_willing:
        _change_phase(conflict, PHASE_NEGOTIATION, world)
    else:
        _change_phase(conflict, PHASE_FIGHT, world)


# ── Negotiation ───────────────────────────────────────────────────────────

def _process_negotiation(conflict, world):
    ticks_in_phase = world["tick"] - conflict["tick_phase_start"]
    chars = world.get("characters", {})

    # Every few ticks, run one negotiation exchange
    if ticks_in_phase % 8 != 0:
        return

    conflict["exchanges"] += 1
    parties = [chars[pid] for pid in conflict["parties"] if pid in chars]
    if len(parties) < 2:
        _resolve(conflict, "cold_shoulder", world)
        return

    a, b = parties[0], parties[1]

    # Check if a ZOPA exists
    range_a = _concession_range(a)
    range_b = _concession_range(b)
    overlap  = (range_a + range_b) - 1.0  # positive = overlap exists

    if overlap > 0 and conflict["exchanges"] >= 2:
        # Agreement reachable — build terms from issues
        terms = _build_terms(conflict, a, b, world)
        conflict["accepted_terms"] = terms
        _finalise_agreement(conflict, terms, world)
        return

    # No overlap yet — each exchange might shift willingness a little
    # (good faith effort) or harden positions (stubbornness)
    for c in parties:
        if _has(c, "stubborn", "proud"):
            conflict["willingness"][c["id"]] = max(0, conflict["willingness"][c["id"]] - 0.05)
        elif _has(c, "empathetic", "agreeable"):
            conflict["willingness"][c["id"]] = min(1, conflict["willingness"][c["id"]] + 0.03)

    if conflict["exchanges"] >= NEGOTIATION_DURATION // 8:
        # Time's up — check if anyone is still willing
        if all(w < 0.3 for w in conflict["willingness"].values()):
            _change_phase(conflict, PHASE_FIGHT, world)
        else:
            _resolve(conflict, "cold_shoulder", world)


def _build_terms(conflict, a, b, world):
    """Construct contract terms from the issues being negotiated."""
    terms = []
    for issue in conflict.get("issues", []):
        # Map common grievance types to behavioural commitments
        if issue == "loud_at_night":
            terms.append({
                "party":       b["id"],
                "commitment":  "no_loud_activity_after_22",
                "check_type":  "schedule",
                "params":      {"forbidden_activity": "loud", "quiet_start": 22, "quiet_end": 8},
            })
        elif issue == "ate_my_food":
            terms.append({
                "party":       b["id"],
                "commitment":  "do_not_eat_labelled_food",
                "check_type":  "manual",
                "params":      {},
            })
        elif issue == "left_mess":
            terms.append({
                "party":       b["id"],
                "commitment":  "clean_up_after_self",
                "check_type":  "manual",
                "params":      {},
            })
        else:
            # Generic behavioural commitment
            terms.append({
                "party":       b["id"],
                "commitment":  f"stop_{issue}",
                "check_type":  "manual",
                "params":      {"original_issue": issue},
            })
    return terms


def _finalise_agreement(conflict, terms, world):
    """Create a social contract and resolve the conflict."""
    from systems.social_contracts import create_contract
    contract = create_contract(
        conflict["parties"], terms, world,
        created_by_conflict=conflict["id"]
    )
    conflict["contract_id"] = contract["id"]
    emit("social_contract_created", {
        "contract_id": contract["id"],
        "parties":     conflict["parties"],
        "terms":       terms,
    })
    _resolve(conflict, "agreement", world)


# ── Fight ─────────────────────────────────────────────────────────────────

def _process_fight(conflict, world):
    ticks_in_phase = world["tick"] - conflict["tick_phase_start"]
    if ticks_in_phase % FIGHT_EXCHANGE_TICKS != 0:
        return

    chars  = world.get("characters", {})
    parties = [chars[pid] for pid in conflict["parties"] if pid in chars]
    if len(parties) < 2:
        _resolve(conflict, "cold_shoulder", world)
        return

    a, b   = parties[0], parties[1]
    stage  = conflict["fight_stage_idx"]
    conflict["exchanges"] += 1

    # ── Third-party intervention check (stages 0-2) ───────────────────────
    if stage < 3 and conflict["exchanges"] % 3 == 0:
        intervener = _find_nearby_third_party(conflict, world)
        if intervener and random.random() < 0.25:
            conflict["log"].append({
                "tick": world["tick"],
                "event": "intervention",
                "by": intervener["id"],
            })
            emit("fight_intervention", {
                "conflict_id":  conflict["id"],
                "intervener_id": intervener["id"],
                "parties":      conflict["parties"],
            })
            _resolve(conflict, "intervention", world)
            return

    # ── Escalation / de-escalation rolls ─────────────────────────────────
    esc_a = _escalation_chance(a, b, stage, world)
    esc_b = _escalation_chance(b, a, stage, world)
    de_a  = _de_escalation_chance(a, b, world)
    de_b  = _de_escalation_chance(b, a, world)

    conflict["escalation_score"] += (esc_a + esc_b) / 2

    # Storm off — either party can exit at any stage
    for c, other in [(a, b), (b, a)]:
        if _has(c, "conflict_averse") and stage >= 1 and random.random() < 0.20:
            conflict["log"].append({"tick": world["tick"], "event": "storm_off", "by": c["id"]})
            emit("fight_storm_off", {
                "conflict_id": conflict["id"],
                "leaver_id":   c["id"],
                "stage":       conflict["fight_stage"],
            })
            _resolve(conflict, "storm_off", world)
            return

    # De-escalation — both back down
    if random.random() < de_a * de_b * 3:
        if stage == 0:
            _resolve(conflict, "de_escalated", world)
        else:
            _drop_stage(conflict, world)
        return

    # Escalation
    if random.random() < (esc_a + esc_b) / 2:
        _raise_stage(conflict, world)

    # If we've reached physical altercation
    if conflict["fight_stage_idx"] >= 3:
        _handle_physical(conflict, a, b, world)


def _raise_stage(conflict, world):
    if conflict["fight_stage_idx"] < len(FIGHT_STAGES) - 1:
        conflict["fight_stage_idx"] += 1
        conflict["fight_stage"] = FIGHT_STAGES[conflict["fight_stage_idx"]]
        conflict["log"].append({
            "tick": world["tick"],
            "event": "escalated",
            "to_stage": conflict["fight_stage"],
        })
        emit("conflict_escalated", {
            "conflict_id": conflict["id"],
            "stage":       conflict["fight_stage"],
            "parties":     conflict["parties"],
        })


def _drop_stage(conflict, world):
    if conflict["fight_stage_idx"] > 0:
        conflict["fight_stage_idx"] -= 1
        conflict["fight_stage"] = FIGHT_STAGES[conflict["fight_stage_idx"]]
        conflict["log"].append({"tick": world["tick"], "event": "de_escalated_stage"})


def _handle_physical(conflict, a, b, world):
    """Resolve a physical altercation — may trigger law pipeline."""
    conflict["log"].append({"tick": world["tick"], "event": "physical"})
    emit("fight_physical", {
        "conflict_id": conflict["id"],
        "parties":     conflict["parties"],
    })
    # Relationship damage
    for c, other in [(a, b), (b, a)]:
        rel = c.setdefault("relationships", {}).setdefault(other["id"], {})
        rel["hostility"]  = min(100, rel.get("hostility",  0) + 20)
        rel["trust"]      = max(-100, rel.get("trust",     0) - 25)
        rel["friendship"] = max(-100, rel.get("friendship",0) - 15)
    _resolve(conflict, "physical_resolved", world)


# ── Phase management ──────────────────────────────────────────────────────

def _change_phase(conflict, new_phase, world):
    conflict["phase"]           = new_phase
    conflict["tick_phase_start"] = world["tick"]
    conflict["exchanges"]        = 0
    emit("conflict_phase_changed", {
        "conflict_id": conflict["id"],
        "phase":       new_phase,
        "parties":     conflict["parties"],
    })


def _resolve(conflict, outcome, world):
    conflict["outcome"]     = outcome
    conflict["tick_ended"]  = world["tick"]

    # Relationship update based on outcome
    chars = world.get("characters", {})
    parties = [chars[pid] for pid in conflict["parties"] if pid in chars]
    if len(parties) == 2:
        a, b = parties
        _apply_outcome_relationship(a, b, outcome)
        _apply_outcome_relationship(b, a, outcome)

    # Clear confrontation-emitted flag so fresh grievances can re-trigger
    for pid in conflict["parties"]:
        c = chars.get(pid)
        if c:
            other = _other_party(conflict, pid)
            emitted = c.get("_confrontation_emitted", [])
            if other in emitted:
                emitted.remove(other)
            # Cold shoulder after unresolved conflict
            if outcome in ("cold_shoulder", "storm_off", "suppressed"):
                cold_shoulder = c.setdefault("cold_shoulder_towards", [])
                if other not in cold_shoulder:
                    cold_shoulder.append(other)

    emit("conflict_resolved", {
        "conflict_id": conflict["id"],
        "outcome":     outcome,
        "parties":     conflict["parties"],
        "contract_id": conflict.get("contract_id"),
    })


def _apply_outcome_relationship(c, other, outcome):
    rel = c.setdefault("relationships", {}).setdefault(other["id"], {})
    if outcome == "agreement":
        rel["trust"]      = min(100, rel.get("trust", 0) + 8)
        rel["comfort"]    = min(100, rel.get("comfort", 0) + 5)
        rel["resentment"] = max(-100, rel.get("resentment", 0) - 10)
    elif outcome == "de_escalated":
        rel["trust"]      = min(100, rel.get("trust", 0) + 3)
        rel["resentment"] = max(-100, rel.get("resentment", 0) - 5)
    elif outcome in ("storm_off", "cold_shoulder"):
        rel["resentment"] = min(100, rel.get("resentment", 0) + 8)
        rel["comfort"]    = max(-100, rel.get("comfort", 0) - 5)
    elif outcome == "physical_resolved":
        rel["hostility"]  = min(100, rel.get("hostility", 0) + 25)
        rel["trust"]      = max(-100, rel.get("trust", 0) - 30)
        rel["fear"]       = min(100, rel.get("fear", 0) + 15)


# ── Main update loop ──────────────────────────────────────────────────────

def process_conflicts(world):
    """Advance every active conflict. Called from sim_loop on a fast cadence."""
    for conflict in list(world.get("conflicts", {}).values()):
        if conflict["outcome"] is not None:
            continue
        phase = conflict["phase"]
        if phase == PHASE_DELIBERATION:
            _process_deliberation(conflict, world)
        elif phase == PHASE_NEGOTIATION:
            _process_negotiation(conflict, world)
        elif phase == PHASE_FIGHT:
            _process_fight(conflict, world)
