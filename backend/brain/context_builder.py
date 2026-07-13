from systems.clothing import worn_summary, outfit_style_score, ALL_SLOTS
from systems.personal_items import inventory_summary, phone_actions, wallet_cash
from brain.memory import (
    biased_recall
)

from social.relationship_score import (
    relationship_score
)

from brain.beliefs import (
    compute_alignment
)

from brain.cognitive_pressure import (
    build_cognitive_pressure
)

from systems.social import (
    build_message_context
)

from brain.conversations import (
    find_conversation
)

from brain.memory import (
    biased_recall
)
# =========================================================
# RELATIONSHIP SUMMARY
# =========================================================

def summarize_relationship(

    c,

    other
):

    score = relationship_score(

        c,

        other["id"]
    )

    if score > 80:

        return (
            f"You feel very close to "
            f"{other['name']}."
        )

    if score > 40:

        return (
            f"You generally like "
            f"{other['name']}."
        )

    if score < -50:

        return (
            f"You strongly dislike "
            f"{other['name']}."
        )

    if score < 0:

        return (
            f"You feel uneasy around "
            f"{other['name']}."
        )

    return (
        f"You have neutral feelings "
        f"toward {other['name']}."
    )


# =========================================================
# RELATIONSHIP CONTEXT
# Uses the full brain/relationships.py schema to produce a
# natural-language summary of each known relationship, sorted
# by significance (most emotionally charged first).
# =========================================================

def build_relationship_context(c, world, limit=10):
    import time
    now = time.time()
    chars = world.get("characters", {})
    results = []

    for other_id, rel in c.get("relationships", {}).items():
        # Skip if truly never met
        if rel.get("familiarity", 0) < 1 and rel.get("interaction_count", 0) == 0:
            continue

        other = chars.get(other_id)
        name = other["name"] if other else other_id

        state      = rel.get("state", "stranger")
        trust      = rel.get("trust", 0)
        friendship = rel.get("friendship", 0)
        hostility  = rel.get("hostility", 0)
        attraction = rel.get("attraction", 0)
        resentment = rel.get("resentment", 0)
        comfort    = rel.get("comfort", 0)
        familiarity= rel.get("familiarity", 0)

        # Core summary sentence
        if state == "close_friend":
            summary = f"{name} is one of your closest friends — you trust them deeply."
        elif state == "friend":
            summary = f"You consider {name} a friend."
        elif state == "romantic_interest":
            summary = f"You have romantic feelings toward {name}."
        elif state == "acquaintance":
            summary = f"You know {name} a little — more acquaintance than friend."
        elif state == "enemy":
            summary = f"You and {name} have real hostility between you."
        elif state == "distrusted":
            summary = f"You've met {name} but don't trust them."
        else:
            summary = f"You've met {name} but don't know them well yet."

        # Nuance additions
        extras = []
        if resentment > 40:
            extras.append("There's lingering resentment between you.")
        if attraction > 50 and state != "romantic_interest":
            extras.append(f"You find {name} attractive.")
        if comfort > 60:
            extras.append(f"You feel very comfortable around {name}.")
        if trust < -20:
            extras.append(f"You don't fully trust {name}.")
        if hostility > 30 and state != "enemy":
            extras.append(f"There's tension between you.")
        if extras:
            summary += " " + " ".join(extras)

        # Recency
        last = rel.get("last_interaction", 0)
        if last:
            elapsed = now - last
            if elapsed < 3600:
                recency = "very recently"
            elif elapsed < 86400:
                recency = "today"
            elif elapsed < 604800:
                recency = f"{int(elapsed/86400)}d ago"
            else:
                recency = f"{int(elapsed/604800)}w ago"
        else:
            recency = None

        significance = (
            abs(friendship) + abs(trust) + abs(hostility) +
            abs(attraction) + abs(resentment) + familiarity * 0.3
        )

        results.append({
            "name":             name,
            "id":               other_id,
            "state":            state,
            "summary":          summary,
            "trust":            round(trust),
            "friendship":       round(friendship),
            "hostility":        round(hostility),
            "attraction":       round(attraction),
            "last_interaction": recency,
            "_sig":             significance,
        })

    results.sort(key=lambda x: x.pop("_sig"), reverse=True)
    return results[:limit]


# =========================================================
# SOCIAL CONTEXT
# =========================================================

def build_social_context(

    c,

    world
):

    return {
        "relationships":   build_relationship_context(c, world),
        "recent_messages": build_message_context(c, world),
    }

# =========================================================
# ACTIVE INTENTIONS
# =========================================================
# Calendar-driven intentions (prepare_for_event/budget_for_event/get_outfit
# — see systems/calendar_events.py::_inject_intention) accumulate without a
# cap as events approach, so a character with several upcoming events queued
# could carry 20+ of these at once. Only the character's current top
# priorities are actually decision-relevant each tick, so this only surfaces
# the top few — c["active_intentions"] is already priority-sorted by the
# time build_context() runs (agent_loop.py calls sort_intentions(c) first).

MAX_INTENTIONS_IN_CONTEXT = 6


def build_intentions(c):

    intentions = []

    for i in c.get(
        "active_intentions",
        []
    )[:MAX_INTENTIONS_IN_CONTEXT]:

        intentions.append({

            "type":
                i.get("type"),

            "priority":
                i.get("priority"),

            "progress":
                i.get(
                    "progress",
                    0
                ),

            "reason":
                i.get("reason")
        })

    return intentions


# =========================================================
# ATTENTION
# Surfaces the character's current focus and top salient things
# (brain/attention.py's c["attention"] = {"focus", "salience"}) as
# human-readable labels for the LLM context.
# =========================================================

def build_attention_summary(c, world):

    attention = c.get("attention", {})
    focus = attention.get("focus")

    def _label(key):
        if key.startswith("person:"):
            pid = key.split(":", 1)[1]
            person = world.get("characters", {}).get(pid, {})
            return person.get("name", pid)
        if key.startswith("scene:"):
            return key.split(":", 1)[1]
        return key

    salience = attention.get("salience", {})
    top = sorted(salience.items(), key=lambda kv: kv[1], reverse=True)[:3]

    return {
        "focus": {
            "on":       _label(focus["key"]),
            "strength": round(focus["strength"], 2),
        } if focus else None,

        "salient": [
            {"on": _label(key), "strength": round(value, 2)}
            for key, value in top
        ],
    }


# =========================================================
# ACTIVE CONVERSATIONS
# Conversations this character is currently a participant in
# (brain/conversations.py's world["conversations"] registry).
# =========================================================

def build_active_conversations(c, world):

    conversations = world.get("conversations", {})
    result = []

    for conv in conversations.values():

        if not conv.get("active"):
            continue

        if c["id"] not in conv.get("participants", []):
            continue

        other_id = next(
            (pid for pid in conv["participants"] if pid != c["id"]),
            None
        )
        other = world.get("characters", {}).get(other_id, {})

        result.append({
            "conversation_id": conv["id"],
            "with":            other.get("name", other_id),
            "topic":           conv.get("topic"),
            "tone":            conv.get("tone"),
            "your_turn":       conv.get("turn_owner") == c["id"],
            "recent_messages": [
                {
                    "speaker": (
                        "you" if m.get("speaker") == c["id"]
                        else other.get("name", m.get("speaker"))
                    ),
                    "utterance": m.get("utterance"),
                }
                for m in conv.get("history", [])[-5:]
            ],
        })

    return result


# =========================================================
# AVAILABLE ACTIONS
# Enumerates concrete targets from current perception so the
# LLM can reference real prop/character IDs in its action.
# =========================================================

def build_available_actions(c, world):

    perception = c.get("perception", {})

    # -----------------------------------------------
    # INTERACTABLE PROPS  (from visible_props)
    # -----------------------------------------------
    interactable = []

    for prop in perception.get("visible_props", []):
        tags = prop.get("tags", [])
        interactions = prop.get("interactions", [])

        if not tags and not interactions:
            continue

        interactable.append({
            "id":           prop["id"],
            "template":     prop.get("template"),
            "distance":     prop.get("distance"),
            "tags":         tags,
            "interactions": interactions,
        })

    # -----------------------------------------------
    # NEARBY CHARACTERS  (for speak/socialize targets)
    # -----------------------------------------------
    nearby_people = []

    from systems.body import get_odor_label, get_breath_label
    for person in perception.get("visible_people", []):
        entry = {
            "id":       person["id"],
            "name":     person.get("name"),
            "distance": person.get("distance"),
        }
        # Surface odor/breath cues for characters within close range
        dist = person.get("distance", 999)
        other_body = person.get("body", {})
        if dist < 4:
            odor_label = get_odor_label(other_body.get("odor", 0))
            if odor_label:
                entry["smells"] = odor_label
            breath_label = get_breath_label(other_body.get("mouth_hygiene", 100))
            if breath_label and dist < 2:
                entry["breath"] = breath_label
        nearby_people.append(entry)

    # -----------------------------------------------
    # ACTION TYPES available this tick
    # -----------------------------------------------
    action_types = [
        "move",
        "speak",
        "interact",
        "wait",
        "eat",
        "sleep",
        "work",
        "socialize",
        "call",
        "text",
    ]

    # Clothing in inventory — can put on
    wearable_in_inventory = [
        {"item_id": i["id"], "template_id": i.get("template_id"), "name": i.get("name"), "slot": i.get("slot")}
        for i in c.get("inventory", [])
        if i.get("slot")  # slot presence means it's wearable clothing
    ]

    # Occupied clothing slots — can take off
    worn_slots = [
        {"slot": slot, "name": item.get("name"), "template_id": item.get("template_id")}
        for slot, item in c.get("worn", {}).items()
        if item
    ]

    if wearable_in_inventory or worn_slots:
        action_types.extend(["wear", "undress"])

    # Assembly boxes — prop boxes and tile boxes
    from systems.assembly import assembly_boxes_in_inventory, tile_boxes_in_inventory
    prop_boxes = [
        {"item_id": i["id"], "name": i.get("name"), "prop_template": i.get("prop_template")}
        for i in assembly_boxes_in_inventory(c)
        if i.get("tile_type") != "tile"
    ]
    t_boxes = [
        {
            "item_id":           i["id"],
            "name":              i.get("name"),
            "material_template": i.get("material_template"),
            "quantity":          i.get("quantity", 1),
        }
        for i in tile_boxes_in_inventory(c)
    ]
    if prop_boxes:
        action_types.append("assemble_prop")
    if t_boxes:
        action_types.append("assemble_tile")

    # Hired services — always available (character decides if they can afford it)
    action_types.append("hire_service")

    # Individual wait activity (see systems/activities.py
    # start_microwave/take_out_of_microwave, sim_loop.py's character_wait
    # cadence block). start_microwave listed unconditionally like
    # hire_service (the route handler validates the target); the resume
    # action only appears once the timer's actually elapsed — before that
    # the character is free to do anything else, same as if nothing were
    # waiting at all — and is skipped entirely while a wait is already
    # running but not yet ready, so the LLM doesn't try to start a second
    # one on top of it.
    wait = c.get("character_wait")
    if not wait:
        action_types.append("start_microwave")
    elif wait.get("ready") and wait.get("resume_interaction"):
        action_types.append(wait["resume_interaction"])

    # Chore proposals (see systems/proposals.py) — propose_chore listed
    # unconditionally, same as hire_service (the route handler itself
    # validates the character is actually home before creating anything).
    # propose_recurring only appears once a joint chore this household
    # just finished is waiting to be offered (task_process.py's
    # finish_process() sets this; consumed the moment it's proposed).
    action_types.append("propose_chore")
    action_types.append("do_laundry_fill")
    household_id = c.get("household_id")
    household = world.get("households", {}).get(household_id) if household_id else None
    if household and household.get("_last_completed_chore"):
        action_types.append("propose_recurring")

    # respond_chore/advance_chore_round only make sense (and only appear)
    # when this character actually has something pending — see
    # _build_proposal_context() below, the same "proposals" context key
    # this mirrors, so the two never disagree about what's live.
    cid = c["id"]
    for p in world.get("proposals", {}).values():
        if p.get("status") != "open":
            continue
        if p.get("responses", {}).get(cid) == "pending" and "respond_chore" not in action_types:
            action_types.append("respond_chore")
        elif (p.get("proposer_id") == cid
              and "advance_chore_round" not in action_types
              and any(state == "counter" for state in p.get("responses", {}).values())):
            action_types.append("advance_chore_round")

    # Wall actions — always contextually available
    action_types.extend(["build_wall", "remove_wall"])

    # Paint buckets in inventory → paint_wall action
    from systems.containers import containers_in_inventory
    paint_buckets = [
        {
            "item_id":     ct["id"],
            "name":        ct["name"],
            "material_id": ct.get("material"),
            "uses":        ct.get("uses", 0),
        }
        for ct in containers_in_inventory(c)
        if ct.get("sub_type") == "bucket" and ct.get("uses", 0) > 0
    ]
    if paint_buckets:
        action_types.append("paint_wall")

    # Held stack — what's currently piled in the character's stacking hand,
    # and any item taken out of the stack into the free hand. This is the
    # actual functional payoff of "search_stack": the AI can already see
    # stack contents here without needing a separate data-revealing effect.
    held_stack_names = [
        {"item_id": i["id"], "name": i.get("name"), "stack_position": i.get("stack_position")}
        for i in c.get("held_stack", [])
    ]
    held_item = next((i for i in c.get("inventory", []) if i.get("location") == "held"), None)

    action_types.append("add_to_stack")
    if held_stack_names:
        action_types.extend(["put_down_stack", "search_stack", "take_from_stack"])
    if held_item:
        action_types.append("pocket_item")

    # Nearby walls for context
    from systems.walls import walls_near
    nearby_walls = [
        {
            "wall_id":      w["id"],
            "x":            w["x"],
            "y":            w["y"],
            "orientation":  w["orientation"],
            "load_bearing": w["load_bearing"],
            "material":     w["material"],
        }
        for w in walls_near(world, int(c.get("x", 0)), int(c.get("y", 0)), radius=3)
    ]

    return {
        "action_types":          action_types,
        "interactable_props":    interactable,
        "nearby_characters":     nearby_people,
        "wearable_items":        wearable_in_inventory,
        "worn_slots":            worn_slots,
        "assembly_boxes":        prop_boxes,
        "tile_boxes":            t_boxes,
        "paint_buckets":         paint_buckets,
        "nearby_walls":          nearby_walls,
        "held_stack_names":      held_stack_names,
        "held_item":             (
            {"item_id": held_item["id"], "name": held_item.get("name")}
            if held_item else None
        ),
    }


# =========================================================
# SCENE DESCRIPTION
# =========================================================
# Natural-language description of the character's immediate surroundings —
# who's nearby (reusing perception's existing per-person semantic
# descriptions from systems/perception/descriptions.py) and any active
# conversation — instead of dumping the full structured perception/social
# data as JSON. This is the "what the AI sees and who's there" half of the
# minimal context; build_context() below is the other half (traits/state).

def build_scene_description(c, world):

    perception = c.get("perception", {})
    lines = []

    building = c.get("building_id")
    room = c.get("room_id")
    if building:
        where = f"indoors, in {room}" if room else "indoors"
    else:
        where = "outdoors"
    lines.append(f"You are {where}.")

    people = perception.get("visible_people", [])
    if people:
        for p in people[:5]:
            bits = [p.get("description") or p.get("name") or "someone"]
            if p.get("activity"):
                bits.append(f"currently {p['activity']}")
            if p.get("appears"):
                bits.append(f"appears {p['appears']}")
            if p.get("speaking"):
                bits.append("speaking")
            lines.append(" — ".join(bits))
    else:
        lines.append("No one else is nearby.")

    for conv in build_active_conversations(c, world):
        turn_note = " — it's your turn to respond." if conv.get("your_turn") else "."
        lines.append(
            f"You are in conversation with {conv['with']} about "
            f"{conv.get('topic', 'something')}{turn_note}"
        )
        for m in conv.get("recent_messages", [])[-2:]:
            lines.append(f'{m["speaker"]}: "{m["utterance"]}"')

    props = perception.get("visible_props", [])
    prop_names = [p.get("template") for p in props[:5] if p.get("template")]
    if prop_names:
        lines.append("Nearby objects: " + ", ".join(prop_names))

    return "\n".join(lines)


# =========================================================
# NARRATIVE — the DM-style prose block
# =========================================================
# Composes existing sentence-generating helpers (build_scene_description,
# build_body_context, build_relationship_context, ...) into paragraphs
# instead of parallel JSON keys — denser than the old flat dict (no
# repeated keys/braces/quotes) and restores a few of the ~55 dormant
# subsystem sections (relationships, memories, family) that build_context()
# used to leave out entirely for token-budget reasons (see the old comment
# this replaced: a full dump of all ~55 sections measured ~4200 tokens and
# was too slow on constrained hardware). Those functions were fully built
# but never called from build_context() — the same "defined but never
# wired in" gap already found and fixed twice this session for
# touch-proposal and household-process context.
#
# Deliberately curated, not a dump of every subsystem: only the sections
# most likely to shape an actual decision this round. The rest of the
# dormant sections (secrets, conditioning, factions, pregnancy,
# intoxication, ...) stay out for now — see the LLM pipeline plan for
# follow-up scope.

def build_narrative(c, world):

    paragraphs = [build_scene_description(c, world)]

    # ---- hearing — restores perceive_audio()'s audible_events, computed
    # every perception cadence tick but never surfaced anywhere before this
    # (not in the old flat context, not consumed by attention.py either) ----
    audible = c.get("perception", {}).get("audible_events", [])
    if audible:
        lines = []
        for event in audible[:4]:
            if event.get("type") == "speech":
                lines.append(
                    f"You hear {event.get('speaker') or 'someone'} "
                    "talking somewhere nearby."
                )
            elif event.get("type") == "ambient" and event.get("sound"):
                lines.append(
                    f"You hear a {event['sound'].replace('_', ' ')}."
                )
        if lines:
            paragraphs.append(" ".join(lines))

    # ---- attention/focus — restores build_attention_summary, previously
    # unused (dead code, same gap as relationships/memories above) ----
    focus = build_attention_summary(c, world).get("focus")
    if focus and focus.get("strength", 0) > 0.4 and focus.get("on"):
        paragraphs.append(f"Your attention keeps drifting to {focus['on']}.")

    # ---- identity + emotional state ----
    name = c.get("name", "You")
    bits = [f"You are {name}"]
    if c.get("age") is not None:
        bits[0] += f", {c['age']} years old"
    if c.get("occupation"):
        bits[0] += f", working as a {c['occupation']}"
    bits[0] += "."
    traits = c.get("traits", [])
    if traits:
        bits.append(f"Your personality: {', '.join(traits)}.")
    bits.append(f"Right now you feel {c.get('emotion', 'neutral')}.")
    if c.get("stress", 0) > 60:
        bits.append("You're under real stress.")
    paragraphs.append(" ".join(bits))

    # ---- body / needs — reuse the already-prose build_body_context ----
    body_issues = build_body_context(c)
    if body_issues:
        paragraphs.append(" ".join(body_issues))

    # ---- active intentions/goals ----
    intentions = build_intentions(c)
    if intentions:
        top = intentions[0]
        line = f"Right now you're mainly focused on {top.get('type')}"
        if top.get("reason"):
            line += f" ({top['reason']})"
        line += "."
        rest = [i.get("type") for i in intentions[1:4] if i.get("type")]
        if rest:
            line += f" You're also thinking about: {', '.join(rest)}."
        paragraphs.append(line)

    # ---- relationships — restores build_relationship_context, which was
    # already fully built but never called from build_context() ----
    relationships = build_relationship_context(c, world, limit=5)
    if relationships:
        paragraphs.append(" ".join(r["summary"] for r in relationships))

    # ---- memories — restores build_memory_context, previously unused ----
    memories = build_memory_context(c)
    if memories:
        top_memories = sorted(
            memories, key=lambda m: m.get("importance", 0), reverse=True
        )[:3]
        mem_text = "; ".join(m["text"] for m in top_memories if m.get("text"))
        if mem_text:
            paragraphs.append(f"You recall: {mem_text}.")

    # ---- family — restores _build_family_context, previously unused ----
    family = _build_family_context(c, world)
    if family and family.get("members"):
        fam_bits = [
            f"{m['name']} ({m['kinship']})"
            for m in family["members"] if m.get("kinship")
        ]
        if fam_bits:
            paragraphs.append(f"Your family: {', '.join(fam_bits)}.")

    # ---- household processes + proposals — already carry descriptive
    # fields; inlined as sentences instead of nested JSON ----
    for p in _build_household_process_context(c, world) or []:
        paragraphs.append(
            f"There's a {p.get('type')} in progress, currently at the "
            f"{p.get('stage')} stage, waiting on {p.get('waiting')}."
        )

    proposals = _build_proposal_context(c, world) or {}
    for entry in proposals.get("incoming", []):
        paragraphs.append(entry["note"])
    for entry in proposals.get("mediating", []):
        paragraphs.append(entry["note"])

    return "\n\n".join(p for p in paragraphs if p)


# =========================================================
# MAIN CONTEXT BUILDER
# =========================================================
# narrative: the DM-style prose block above — everything the character
# perceives/remembers/feels, in free text. available_actions: the only
# place literal prop/character ids appear, kept as strict JSON because the
# model must echo those back exactly (see llm_brain.py::build_prompt,
# which assembles the two into one prompt).

def build_context(

    c,

    world
):

    return {

        "narrative": build_narrative(c, world),

        "available_actions": build_available_actions(c, world),
    }


def _build_household_process_context(c, world):
    """Ambient visibility into any in-progress household chore/recipe
    process (systems/task_process.py) — e.g. a wash cycle sitting in its
    "empty_washer" stage, waiting for someone to act on it. There is no
    push/notify mechanism anywhere in this codebase (deliberately, see
    task_process.py's module docstring) — a character only ever learns
    about a pending process by seeing it here, the same way hired-service
    contracts were meant to surface (systems/services.py's
    active_contracts_for_household(), though that particular wiring turned
    out to be dead code — not repeating that mistake here)."""
    household_id = c.get("household_id")
    if not household_id:
        return []
    return [
        {
            "type":        p.get("type"),
            "stage":       p.get("stage_name"),
            "waiting":     p.get("waiting"),
            "prop_id":     p.get("prop_id"),
        }
        for p in world.get("household_processes", [])
        if p.get("household_id") == household_id and not p.get("completed")
    ]


def _build_proposal_context(c, world):
    """Ambient visibility into pending systems/proposals.py negotiations —
    chore invites and recurring-schedule offers. This is the wiring the
    pre-existing touch-proposal system (systems/intimacy.py) was missing:
    its own context-surfacing function was defined but never actually
    added to build_context()'s returned dict, so incoming proposals were
    genuinely invisible to a recipient's LLM and got resolved by a
    tick-based probability heuristic instead of real AI choice. This
    function IS wired in (see build_context() above) — don't repeat that
    mistake if this gets refactored later.

    Surfaces two kinds of entries for a character:
      - incoming: a proposal awaiting THIS character's response (accept/
        decline/counter).
      - mediating: a proposal THIS character made, where one or more
        recipients have countered and are waiting on a decision (see
        systems/proposals.py's "proposer-mediated reconciliation" rule —
        counters are proposals to the proposer, not to each other).
    """
    cid = c["id"]
    incoming, mediating = [], []

    for p in world.get("proposals", {}).values():
        if p.get("status") != "open":
            continue

        if p.get("responses", {}).get(cid) == "pending":
            incoming.append({
                "proposal_id": p["id"],
                "kind":        p.get("kind"),
                "chore_id":    p.get("chore_id"),
                "params":      p.get("params"),
                "proposed_by": p.get("proposer_id"),
                "round":       p.get("round"),
                "note":        f"Someone proposed {p.get('chore_id')} — you can accept, decline, "
                               f"or counter with different details." if p.get("kind") == "chore"
                               else f"Someone offered to make {p.get('chore_id')} a recurring thing.",
            })

        elif p.get("proposer_id") == cid:
            counters = {
                rid: p["counter_params"].get(rid)
                for rid, state in p.get("responses", {}).items()
                if state == "counter"
            }
            if counters:
                mediating.append({
                    "proposal_id": p["id"],
                    "kind":        p.get("kind"),
                    "chore_id":    p.get("chore_id"),
                    "your_params": p.get("params"),
                    "counters":    counters,
                    "round":       p.get("round"),
                    "note":        "One or more people countered your proposal with different "
                                   "details — decide new terms (advance_chore_round) or let it "
                                   "lapse.",
                })

    result = {}
    if incoming:
        result["incoming"] = incoming
    if mediating:
        result["mediating"] = mediating
    return result or None


# ─────────────────────────────────────────────────────────────────────────────
# Baby / child context
# ─────────────────────────────────────────────────────────────────────────────

def _build_baby_context(c, world):
    """Context for a baby/infant/toddler character."""
    try:
        from systems.baby import get_baby_context
        lines = get_baby_context(c, world)
        return lines if lines else None
    except Exception:
        return None


def _build_crushes_context(c, world):
    try:
        from systems.crushes import get_crush_context
        lines = get_crush_context(c, world)
        # Add shared-idol note if talking with someone
        conv_partner_id = _get_current_conversation_partner(c, world)
        if conv_partner_id:
            partner = world.get("characters", {}).get(conv_partner_id, {})
            shared = _shared_idols(c, partner)
            for name in shared[:2]:
                lines.append(f"Both are fans of {name} — natural conversation topic.")
        return lines if lines else None
    except Exception:
        return None


def _get_current_conversation_partner(c, world):
    """Return the ID of whoever c is currently conversing with, if any."""
    try:
        for conv in world.get("conversations", {}).values():
            parts = conv.get("participants", [])
            if c.get("id") in parts and len(parts) == 2:
                other = [p for p in parts if p != c.get("id")]
                return other[0] if other else None
    except Exception:
        pass
    return None


def _shared_idols(c, partner):
    """Return list of celebrity names both characters are fans of."""
    c_celebs = {x["celebrity_id"] for x in c.get("crushes", [])
                if x.get("is_celebrity") and x.get("celebrity_id")}
    p_celebs = {x["celebrity_id"] for x in partner.get("crushes", [])
                if x.get("is_celebrity") and x.get("celebrity_id")}
    shared_ids = c_celebs & p_celebs
    names = []
    for cid in shared_ids:
        name = next((x["name"] for x in c.get("crushes", [])
                     if x.get("celebrity_id") == cid), cid)
        names.append(name)
    return names


def _build_prenatal_prep_context(c, world):
    """Context for a pregnant character's preparation tasks."""
    try:
        from systems.baby import get_prenatal_context
        lines = get_prenatal_context(c, world)
        return lines if lines else None
    except Exception:
        return None


# =========================================================
# SOCIAL MODELS
# =========================================================

def build_social_model_context(

    c,

    limit=8
):

    models = c.get(
        "social_models",
        {}
    )

    results = []

    for target_id, model in models.items():

        results.append({

            "target_id":
                target_id,

            "summary":
                model["summary"],

            "trust":
                model["trust"],

            "respect":
                model["respect"],

            "fear":
                model["fear"],

            "perceived_traits":
                model[
                    "perceived_traits"
                ]
        })

    results.sort(

        key=lambda x: (

            abs(x["trust"])
            +
            abs(x["respect"])
        ),

        reverse=True
    )

    return results[:limit]

# =========================================================
# ACTIVE CONVERSATIONS
# =========================================================

def build_conversation_context(

    c,

    world
):

    results = []

    for conv in world.get(
        "conversations",
        {}
    ).values():

        if not conv.get("active"):
            continue

        if c["id"] not in conv[
            "participants"
        ]:
            continue

        results.append({

            "topic":
                conv["topic"],

            "tone":
                conv["tone"],

            "recent_history":
                conv["history"][-5:],

            "turn_owner":
                conv["turn_owner"]
        })

    return results

    # =========================================================
# CURRENT TURN
# =========================================================

def get_current_turn(

    c,

    world
):

    for conv in world.get(
        "conversations",
        {}
    ).values():

        if not conv.get("active"):
            continue

        if conv.get(
            "turn_owner"
        ) == c["id"]:

            return {

                "conversation_id":
                    conv["id"],

                "topic":
                    conv["topic"],

                "tone":
                    conv["tone"],

                "participants":
                    conv["participants"],

                "recent_history":
                    conv["history"][-5:]
            }

    return None

    # =========================================================
# BUILD BELIEF CONTEXT
# =========================================================

def build_belief_context(c):

    results = []

    for topic, belief in c.get(
        "beliefs",
        {}
    ).items():

        value = belief.get(
            "value",
            0
        )

        certainty = belief.get(
            "certainty",
            0
        )

        # =====================================
        # INTERPRETATION
        # =====================================

        if value > 0.6:

            interpretation = (
                f"You strongly support "
                f"{topic}."
            )

        elif value > 0.2:

            interpretation = (
                f"You somewhat support "
                f"{topic}."
            )

        elif value < -0.6:

            interpretation = (
                f"You strongly oppose "
                f"{topic}."
            )

        elif value < -0.2:

            interpretation = (
                f"You somewhat oppose "
                f"{topic}."
            )

        else:

            interpretation = (
                f"You feel conflicted or "
                f"uncertain about {topic}."
            )

        results.append({

            "topic":
                topic,

            "certainty":
                certainty,

            "interpretation":
                interpretation
        })

    return results

# =========================================================
# BUILD NARRATIVES
# =========================================================

def build_narratives(c):

    return c.get(
        "narratives",
        []
    )[-5:]


# =========================================================
# BUILD SELF MODEL
# =========================================================

def build_self_model(c):

    results = []

    for key, v in c.get(
        "self_model",
        {}
    ).items():

        results.append({

            "aspect": key,

            "identity":
                v.get("value"),

            "confidence":
                v.get(
                    "confidence",
                    0
                )
        })

    return results

    # =========================================================
# BUILD SCHEDULE CONTEXT
# =========================================================

def build_schedule_context(c):

    block = c.get(
        "active_schedule_block"
    )

    if not block:
        return None

    return {

        "type":
            block["type"],

        "start":
            block["start"],

        "end":
            block["end"]
    }

# =========================================================
# BODY CONTEXT
# =========================================================

def build_body_context(c):
    from systems.body import get_odor_label, get_breath_label
    b = c.get("body", {})
    issues = []

    if b.get("bladder", 0) > 70:
        issues.append("You urgently need to use a toilet.")
    elif b.get("bowels", 0) > 75:
        issues.append("You need to use the toilet.")

    if b.get("fatigue", 0) > 80:
        issues.append("You feel exhausted.")
    elif b.get("fatigue", 0) > 60:
        issues.append("You feel tired.")

    debt = b.get("sleep_debt", 0)
    if debt > 50:
        issues.append(f"You're running on poor sleep — feeling foggy and irritable (sleep debt: {int(debt)}%).")
    elif debt > 25:
        issues.append("You haven't been sleeping enough lately.")

    if b.get("hygiene", 100) < 25:
        issues.append("You feel dirty and socially uncomfortable.")
    elif b.get("hygiene", 100) < 50:
        issues.append("You could use a shower.")

    odor_label = get_odor_label(b.get("odor", 0))
    if odor_label:
        issues.append(f"You smell {odor_label} — others around you may notice.")

    breath_label = get_breath_label(b.get("mouth_hygiene", 100))
    if breath_label:
        issues.append(f"You have {breath_label}.")

    if b.get("hunger", 0) > 75:
        issues.append("You are very hungry.")
    elif b.get("hunger", 0) > 55:
        issues.append("You're feeling hungry.")

    if b.get("hydration", 100) < 30:
        issues.append("You're dehydrated — you need something to drink.")

    if b.get("stomach_discomfort", 0) > 50:
        issues.append("Your stomach is hurting.")

    return issues

# =========================================================
# HOUSEHOLD RESOURCE CONTEXT
# =========================================================

def build_household_resource_context(

    c,

    world
):

    household_id = c.get(
        "household_id"
    )

    if not household_id:
        return None

    household = get_household(
        world,
        household_id
    )

    if not household:
        return None

    resources = household.get(
        "resources",
        {}
    )

    return {

        "food":
            resources.get(
                "food",
                0
            ),

        "quick_food":
            resources.get(
                "quick_food",
                0
            ),

        "drinks":
            resources.get(
                "drinks",
                0
            )
    }



# =========================================================
# MEMORY CONTEXT
# =========================================================

def build_memory_context(

    c
):

    memories = biased_recall(

        c,

        limit=8
    )

    results = []

    for m in memories:

        results.append({

            "text":
                m["text"],

            "importance":
                m.get(
                    "importance",
                    0
                    ),

            "tags":
                m.get(
                    "tags",
                    []
                ),

            "people":
                m.get(
                    "people",
                    []
                )
        })

    return results


# =========================================================
# CONFLICT CONTEXT
# Surfaces the character's active conflict (if any) so the
# LLM knows what phase they're in and what's at stake.
# =========================================================

def build_conflict_context(c, world):
    chars = world.get("characters", {})
    for conflict in world.get("conflicts", {}).values():
        if conflict["outcome"] is not None:
            continue
        if c["id"] not in conflict["parties"]:
            continue

        other_id   = None
        for pid in conflict["parties"]:
            if pid != c["id"]:
                other_id = pid
                break
        other      = chars.get(other_id)
        other_name = other["name"] if other else other_id

        phase = conflict["phase"]
        result = {
            "conflict_id":  conflict["id"],
            "phase":        phase,
            "with":         other_name,
            "with_id":      other_id,
            "issues":       conflict.get("issues", []),
            "my_willingness": round(conflict["willingness"].get(c["id"], 0), 2),
            "their_willingness": round(conflict["willingness"].get(other_id, 0), 2),
            "exchanges":    conflict["exchanges"],
        }

        if phase == "fight":
            result["fight_stage"] = conflict.get("fight_stage")
            result["escalation_score"] = round(conflict.get("escalation_score", 0), 1)

        if phase == "negotiation":
            result["proposed_terms"]  = conflict.get("proposed_terms",  [])
            result["accepted_terms"]  = conflict.get("accepted_terms",  [])

        return result

    return None


# =========================================================
# GRIEVANCE CONTEXT
# Shows top grievances against others so the LLM knows
# what's bothering this character even before a confrontation.
# =========================================================

def build_grievance_context(c, world):
    from systems.grievances import get_grievance_score
    chars   = world.get("characters", {})
    scores  = {}
    for g in c.get("grievances", []):
        bid = g["caused_by"]
        scores[bid] = scores.get(bid, 0) + g["weight"]

    results = []
    for other_id, score in scores.items():
        if score < 3.0:
            continue
        other = chars.get(other_id)
        name  = other["name"] if other else other_id
        top_events = sorted(
            [g for g in c["grievances"] if g["caused_by"] == other_id],
            key=lambda g: g["weight"], reverse=True
        )[:2]
        results.append({
            "with":       name,
            "score":      round(score, 1),
            "top_issues": [g["event_type"] for g in top_events],
        })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:5]


# =========================================================
# INVESTMENT CONTEXT
# =========================================================

def build_investment_context(c, world):
    from systems.investments import portfolio_value, position_pnl

    portfolio = c.get("portfolio", {})
    if not portfolio:
        return None

    stocks = world.get("stocks", {})
    positions = []
    

# =========================================================
# LONG-TERM NEED CONTEXT
# =========================================================

def _build_lt_need_context(c):
    from systems.lt_needs import build_lt_need_context
    return build_lt_need_context(c)


# =========================================================
# INVENTORY / WORN CONTEXT
# =========================================================

def _build_inventory_context(c):
    from systems.personal_items import inventory_summary
    return inventory_summary(c)


def _build_worn_context(c):
    from systems.clothing import worn_summary
    return worn_summary(c)


# =========================================================
# SERVICES CONTEXT
# =========================================================

def _build_services_context(c, world):
    from systems.services import active_contracts_for_household
    household_id = c.get("household_id")
    if not household_id:
        return []
    return active_contracts_for_household(world, household_id)


# =========================================================
# FACTION CONTEXT
# =========================================================

def _build_faction_context(c, world):
    from systems.faction_ai import get_faction_context
    return get_faction_context(c, world) or None


# =========================================================
# PHONE CONTEXT
# =========================================================

def _build_phone_context(c):
    from systems.phone import phone_context
    return phone_context(c)


# =========================================================
# SOCIAL EVENTS CONTEXT
# =========================================================

def _build_events_context(c, world):
    from systems.social_events import build_events_context
    return build_events_context(c, world)


def _build_hobbies_context(c, world):
    from systems.hobbies import build_hobby_context
    return build_hobby_context(c, world) or None


def _build_calendar_context(c, world):
    from systems.calendar_events import get_upcoming_events
    upcoming = get_upcoming_events(c, world, horizon_days=60)
    if not upcoming:
        return None
    items = []
    for ev in upcoming[:8]:
        n = ev["days_until"]
        when = "today" if n == 0 else ("tomorrow" if n == 1 else "in {} days".format(n))
        line = "{} {} ({})".format(ev["emoji"], ev["name"], when)
        if ev.get("prep_requirements"):
            line += " — prep: " + ", ".join(ev["prep_requirements"])
        items.append(line)
    return items

# =========================================================
# REPUTATION CONTEXT
# =========================================================

def _build_reputation_context(c):
    from systems.reputation import get_reputation_summary
    return get_reputation_summary(c)


# =========================================================
# FAMILY CONTEXT
# =========================================================

def _build_family_context(c, world):
    fam_id = c.get("family_id")
    if not fam_id:
        return None
    fam = world.get("families", {}).get(fam_id)
    if not fam:
        return None
    chars = world.get("characters", {})
    members = []
    for mid in fam.get("members", []):
        if mid == c["id"]:
            continue
        other = chars.get(mid, {})
        kinship = fam["relations"].get(f"{c['id']}:{mid}")
        members.append({
            "id":      mid,
            "name":    other.get("name", mid),
            "kinship": kinship,
            "age":     other.get("age"),
            "alive":   not other.get("deceased", False),
            "offscreen": other.get("is_offscreen", False),
        })
    return {
        "family_id":   fam_id,
        "surname":     fam.get("surname"),
        "role":        c.get("family_role"),
        "members":     members,
    }


# =========================================================
# SECRETS CONTEXT — keeper perspective
# =========================================================

def _build_secrets_keeper_context(c):
    secrets = c.get("secrets", [])
    if not secrets:
        return []
    out = []
    for s in secrets:
        targets_summary = {}
        for tid, dt in s.get("deception_targets", {}).items():
            targets_summary[tid] = {
                "deceived_level":  dt.get("deceived_level", 1.0),
                "suspicion_level": dt.get("suspicion_level", 0.0),
                "false_belief":    dt.get("false_belief"),
            }
        out.append({
            "id":       s["id"],
            "content":  s["content"],
            "severity": s.get("severity", 0.5),
            "stakes":   s.get("stakes"),
            "category": s.get("category"),
            "known_by": s.get("known_by", []),
            "targets":  targets_summary,
        })
    return out


# =========================================================
# SECRETS CONTEXT — target/deceived perspective
# =========================================================

def _build_secrets_target_context(c, world):
    """
    For each secret kept from this character, return what they perceive —
    their suspicion level, who they blame, and what false belief they hold.
    """
    my_id  = c["id"]
    chars  = world.get("characters", {})
    result = []
    for other in chars.values():
        if other["id"] == my_id:
            continue
        for s in other.get("secrets", []):
            dt = s.get("deception_targets", {}).get(my_id)
            if not dt:
                continue
            result.append({
                "secret_id":       s["id"],
                "kept_by":         other.get("name", other["id"]),
                "kept_by_id":      other["id"],
                "suspicion_level": dt.get("suspicion_level", 0.0),
                "suspicion_of":    dt.get("suspicion_of"),      # id blamed instead
                "false_belief":    dt.get("false_belief"),
                "category":        s.get("category"),
                # Deliberately omit actual content — the target doesn't know the truth
            })
    return result


def _build_attraction_context(c, world):
    try:
        from systems.attraction import get_attraction_context
        return get_attraction_context(c, world).get("attraction", [])
    except Exception:
        return []


def _build_intimacy_context(c, world):
    try:
        from systems.intimacy import get_intimacy_context
        return get_intimacy_context(c, world).get("intimacy", [])
    except Exception:
        return []


def _build_touch_proposal_context(c, world):
    """
    If someone has proposed a hug/kiss/cuddle TO this character (and it's pending),
    surface that so the LLM knows it should respond.
    Also surface outgoing proposals so the LLM knows to wait.
    """
    result = {}
    chars = world.get("characters", {})
    for oid, rel in c.get("relationships", {}).items():
        tneg = rel.get("touch_negotiation", {})
        if tneg.get("state") != "proposed":
            continue
        other = chars.get(oid)
        other_name = other.get("name", oid) if other else oid
        template_id = tneg.get("template_id", "hug")
        proposer_id = tneg.get("proposed_by")
        if proposer_id == c["id"]:
            # We proposed — waiting for response
            result["outgoing"] = {
                "to": other_name,
                "action": template_id,
                "note": f"You proposed a {template_id} to {other_name} — waiting for their response.",
            }
        else:
            # We received — need to respond
            result["incoming"] = {
                "from": other_name,
                "action": template_id,
                "note": f"{other_name} wants to {template_id} with you. You can accept or decline.",
            }
    return result or None


def _build_authority_contracts_context(c, world):
    """Active authority contracts + compliance scores for LLM context."""
    try:
        from systems.social_contracts import get_contracts_for_character
        contracts = get_contracts_for_character(c["id"], world)
        result = []
        for ct in contracts:
            score = ct.get("compliance_score", 0.5)
            ctype = ct.get("contract_type", "agreement")
            auth_id = ct.get("authority_id")
            chars = world.get("characters", {})
            auth_name = chars.get(auth_id, {}).get("name", auth_id) if auth_id else None
            terms_summary = [t.get("commitment", "") for t in ct.get("terms", [])]
            neg = ct.get("negotiation", {})
            entry = {
                "type": ctype,
                "authority": auth_name,
                "terms": terms_summary,
                "compliance_score": round(score, 2),
            }
            if neg.get("state") == "proposed":
                entry["pending_negotiation"] = f"Proposed: {neg.get('proposed_terms')} — offering: {neg.get('exchange_offer')}"
            result.append(entry)
        return result or None
    except Exception:
        return None


def _build_conditioning_context(c):
    try:
        from systems.conditioning import get_conditioning_context
        return get_conditioning_context(c) or None
    except Exception:
        return None


def _build_active_lies_context(c, world):
    """Surface active undetected lies so LLM knows to maintain consistency."""
    lies = [l for l in c.get("active_lies", []) if not l.get("detected")]
    if not lies:
        return None
    chars = world.get("characters", {})
    return [
        {
            "told_to": [chars.get(tid, {}).get("name", tid) for tid in l.get("told_to", [])],
            "claim":   l["lie_text"],
            "truth":   l["actual_truth"],
            "topic":   l["question_type"],
        }
        for l in lies[-5:]
    ]



def _build_private_offgrid_context(c, world):
    """
    Surface recent private off-grid events — things that happened while the
    character was away that they would not want household members to learn about.
    Only included in the character's OWN context; never surfaced to observers.
    """
    history = c.get("private_off_grid_history", [])
    if not history:
        return None
    chars = world.get("characters", {})
    result = []
    for entry in history[-3:]:   # last 3 outings with private events
        evs = []
        for ev in entry.get("events", []):
            item = {
                "what":     ev.get("description", ""),
                "category": ev.get("fear_tag", ""),
            }
            if ev.get("target_id"):
                item["with"] = chars.get(ev["target_id"], {}).get("name", "someone")
            evs.append(item)
        if evs:
            result.append({
                "tick":   entry["tick"],
                "reason": entry["reason"],
                "hidden": evs,
            })
    return result or None

def _build_notes_context(c, world):
    """Notes left in character's current location that they haven't read."""
    cur_loc = c.get("current_location") or c.get("building_id")
    cid     = c["id"]
    notes   = [
        n for n in world.get("notes", [])
        if n.get("location_id") == cur_loc and cid not in n.get("read_by", [])
    ]
    if not notes:
        return None
    chars = world.get("characters", {})
    return [
        {
            "from":  chars.get(n.get("author_id"), {}).get("name", "someone"),
            "text":  n["text"],
        }
        for n in notes[-3:]
    ]


def _build_envy_context(c, world):
    try:
        from systems.envy import get_envy_context
        return get_envy_context(c, world).get("envy_conflicts", [])
    except Exception:
        return []


def _build_trauma_context(c, world):
    try:
        from systems.trauma import get_trauma_context
        return get_trauma_context(c, world).get("trauma", [])
    except Exception:
        return []


def _build_pleasure_context(c, world):
    try:
        from systems.pleasure import get_pleasure_context
        return get_pleasure_context(c, world).get("sexual_history", [])
    except Exception:
        return []


def _build_rival_context(c, world):
    try:
        from systems.rival_cascade import get_rival_context
        return get_rival_context(c, world).get("rivalries", [])
    except Exception:
        return []


def _build_impulse_context(c, world):
    try:
        from systems.impulse import get_impulse_context
        return get_impulse_context(c, world).get("impulse", [])
    except Exception:
        return []


def _build_domestic_context(c, world):
    try:
        from systems.domestic_control import get_domestic_control_context
        return get_domestic_control_context(c, world).get("domestic_situation", [])
    except Exception:
        return []


def _build_emotional_control_context(c, world):
    try:
        from systems.domestic_control import get_emotional_control_victim_context
        return get_emotional_control_victim_context(c, world)
    except Exception:
        return []


def _build_repression_context(c, world):
    try:
        from systems.religious_repression import get_repression_context
        return get_repression_context(c, world)
    except Exception:
        return []


def _build_pregnancy_context(c, world):
    try:
        from systems.pregnancy import get_pregnancy_context
        return get_pregnancy_context(c, world)
    except Exception:
        return []


def _build_intoxication_context(c, world):
    try:
        from systems.harassment import get_harassment_context
        return get_harassment_context(c, world)
    except Exception:
        return []


def _build_posture_context(c, world):
    """Surface the character's current physical posture to the LLM."""
    posture = c.get("posture", "standing")
    result  = {"current": posture}
    if posture == "leaning_wall":
        result["leaning_on"]   = c.get("leaning_wall_id")
        result["can_push_off"] = True
    elif posture == "standing":
        try:
            from systems.walls import find_leanable_wall
            wall = find_leanable_wall(c, world)
            result["can_lean"]    = wall is not None
            if wall:
                result["nearest_wall"] = wall["wall_id"]
        except Exception:
            result["can_lean"] = False
    return result
