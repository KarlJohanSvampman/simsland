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
            "conversation_id":    conv["id"],
            "with":               other.get("name", other_id),
            "with_id":            other_id,
            "topic":              conv.get("topic"),
            "tone":               conv.get("tone"),
            "conversation_type":  conv.get("conversation_type"),
            "medium":             conv.get("medium", "in_person"),
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
    is_child = c.get("age_group") == "child"

    for prop in perception.get("visible_props", []):
        tags = prop.get("tags", [])
        interactions = prop.get("interactions", [])

        if not tags and not interactions:
            continue

        # Children can't cook for themselves (see systems/child_care.py) —
        # strip stove/oven/microwave-type props from what they're even
        # told is available, rather than relying on the LLM to decline.
        if is_child and "cooking" in tags:
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

    # describe (Round 8) / recall (Round 9) — cost no in-world time but do
    # cost one of a small per-decision-cycle turn budget (see
    # brain/cognition_scheduler.py::stage_and_wake/note_think), so they're
    # only offered while budget remains; otherwise a character could drill
    # describe -> describe -> describe (or recall -> recall -> ...) forever
    # without ever doing anything.
    if c.get("cognition", {}).get("turn_budget", 0) > 0:
        action_types.append("describe")
        action_types.append("recall")

    # Prop disposal/destruction (see activities.py's trash/destroy
    # completion handler) — offered generically whenever a prop is visible,
    # same "route handler validates the specific target" convention as
    # interact/the hostile-action types; "destroy" additionally reports a
    # real property_damage incident (systems/emergency.py).
    if interactable:
        action_types.extend(["trash", "destroy"])
        # examine/search/carry/clean (see action_router.py's _route_examine/
        # _route_search/_route_carry/_route_clean) — fully routed but never
        # offered before this round, same class of gap as trash/destroy
        # above; the route handler validates the specific target the same
        # way.
        action_types.extend(["examine", "search", "carry", "clean"])

    # sit_down/lie_down (see action_router.py's _route_sit_down/
    # _route_lie_down) — routed but never offered before this round. The
    # route handlers themselves don't validate the target is actually
    # seatable/sleepable, so this gate is the only check; SYSTEM_PROMPT
    # already documents "seatable"/"sleepable" tags to the LLM
    # (llm_brain.py) for the eat/sleep actions, reused here.
    if any("seatable" in entry.get("tags", []) for entry in interactable):
        action_types.append("sit_down")
    if any("sleepable" in entry.get("tags", []) for entry in interactable):
        action_types.append("lie_down")

    # lean_against_wall/push_off_wall (see action_router.py's
    # _route_lean_against_wall/_route_push_off_wall, systems/posture.py) —
    # reuses the exact detection _build_posture_context() already computes
    # (can_lean / current == "leaning_wall") so narrative and available
    # actions never disagree about what's live.
    if c.get("posture") == "standing":
        try:
            from systems.walls import find_leanable_wall
            if find_leanable_wall(c, world) is not None:
                action_types.append("lean_against_wall")
        except Exception:
            pass
    elif c.get("posture") == "leaning_wall":
        action_types.append("push_off_wall")

    # Exercise (see systems/exercise.py, action_router.py) — jog/sit_ups
    # need no target, offered unconditionally like hire_service/
    # propose_chore (the route handler needs no target validation).
    # chin_ups/lift_weights only when a prop with the matching anchor
    # interaction (do_pull_ups / lift_weights) is actually visible.
    action_types.extend(["jog", "sit_ups"])
    for entry in interactable:
        if "do_pull_ups" in entry.get("interactions", []) and "chin_ups" not in action_types:
            action_types.append("chin_ups")
        if "lift_weights" in entry.get("interactions", []) and "lift_weights" not in action_types:
            action_types.append("lift_weights")

    # Phone/computer "online actions" (see systems/phone.py,
    # action_router.py's _route_computer* family + _require_phone_or_
    # computer) — these routes and VALID_ACTIONS registration are both
    # new this round (the routes were fully built already but
    # unreachable). Offered together whenever either device is
    # available -- e.g. at home with the phone in pocket -- so the LLM
    # picks, rather than the game forcing a device choice.
    from systems.personal_items import get_phone, get_computer
    has_phone = get_phone(c) is not None
    has_computer_device = get_computer(c, world) is not None
    if has_phone:
        action_types.extend([
            "phone_call", "phone_answer", "phone_send_text",
            "phone_check", "phone_read_text",
        ])
    if has_phone or has_computer_device:
        action_types.extend([
            "computer_social_media", "computer_videos", "computer_game",
            "computer_wiki_research", "computer_window_shopping",
            "computer_dating", "computer_job_search", "computer_apply_for_job",
            "computer_send_email", "computer_respond_email", "computer_check_email",
        ])
        # Stock trading (see systems/stock_market.py, systems/investments.py)
        # and ordering (systems/procurement.py, systems/services.py) —
        # fully routed but never offered before this round, same class of
        # gap as the rest of the computer_* family above. No extra
        # world-state prerequisite: c["portfolio"] always exists (defaults
        # to {}) and the item/service catalogs are static data, not
        # per-character state.
        action_types.extend([
            "computer_list_stocks", "computer_buy_stock", "computer_sell_stock",
            "computer_check_stock_value", "computer_order_item", "computer_order_service",
        ])
        # Social events (systems/social_events.py) — browsing/planning need
        # no pre-existing state (same "route validates" pattern as
        # hire_service); rsvp/comment/attend need a real event_id, only
        # available once browsing has actually surfaced one.
        action_types.extend(["social_browse_events", "social_event_plan"])
        if c.get("last_discovered_events"):
            action_types.extend([
                "social_event_rsvp", "social_event_comment", "social_event_attend",
            ])
        # Hobby session organizing (systems/hobbies.py) — both routes need
        # a hobby_id; only meaningful for a character who actually has a
        # hobby to organize around.
        if c.get("hobbies"):
            action_types.extend(["organize_hobby_session", "plan_hobby_session"])

    # retrieve_phone — offered only once the phone is actually away
    # (systems/phone.py::maybe_set_phone_down/maybe_forget_phone).
    phone_state = c.get("phone_state")
    if not has_phone and phone_state and phone_state.get("last_known_location"):
        action_types.append("retrieve_phone")

    # Plants/gardening (see systems/plants.py) — water/pull_weed offered
    # when a visible prop is an actual planted instance (has a live
    # plant_state, checked against the real world prop rather than the
    # perception-scanned tags, since plant_template/plant_state aren't
    # part of the perceived-prop shape); harvest additionally requires
    # the plant's own fruit container (systems/containers.py) to be
    # non-empty, since fruit now only appears there once the plant turns
    # "mature" (systems/plants.py::tick_plants) rather than being granted
    # on demand. plant_seed offered when a visible prop is an empty pot
    # (category "pot", no plant_template yet) — soil-tile planting works
    # via the same route (an x/y target) but isn't offered here yet since
    # there's no nearby-tile scan in this function; garden/growhouse
    # floorplan content is deferred, same as the bedroom-assignment round.
    #
    # Collect (see systems/containers.py) — the general version of
    # harvest, offered whenever ANY reachable container (a visible prop
    # with storage/fruit, or an item-container the character is
    # carrying/wearing) actually has something in it. Reuses
    # containers_in_inventory() (already imported below for paint
    # buckets) for the carried/worn case.
    world_props_by_id = {p["id"]: p for p in world.get("props", [])}
    has_plant = False
    has_harvestable_plant = False
    has_empty_pot = False
    has_container_with_contents = False
    for entry in interactable:
        live_prop = world_props_by_id.get(entry["id"])
        if not live_prop:
            continue
        if live_prop.get("plant_state"):
            has_plant = True
            if live_prop.get("items"):
                has_harvestable_plant = True
                has_container_with_contents = True
        elif "pot" in entry.get("tags", []) and not live_prop.get("plant_template"):
            has_empty_pot = True
        elif live_prop.get("items"):
            has_container_with_contents = True

    from systems.containers import containers_in_inventory
    for ct in containers_in_inventory(c):
        if ct.get("items"):
            has_container_with_contents = True
            break
    if not has_container_with_contents:
        for item in list(c.get("worn", {}).values()) + c.get("inventory", []):
            if item and item.get("items"):
                has_container_with_contents = True
                break

    if has_plant:
        action_types.extend(["water", "pull_weed"])
    if has_harvestable_plant:
        action_types.append("harvest")
    if has_empty_pot:
        action_types.append("plant_seed")
    if has_container_with_contents:
        action_types.append("collect")

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

    # Child care (see systems/child_care.py) — feed_child/remind_child only
    # offered when a co-located child actually has a flagged need, mirroring
    # propose_recurring's "only appears once there's something to act on"
    # shape above.
    #
    # Baby care (see systems/baby.py) — breastfeed/bottle_feed/hold_baby
    # routed but never offered before this round; gated on a co-located
    # character actually being a baby (c["baby_needs"] is only ever set —
    # non-None — on infants, see systems/schema_defaults.py). The route
    # handlers use current_location for their own locality re-check (not
    # building_id, which nothing else in this file relies on either) —
    # this offering-side gate uses building_id like feed_child/
    # remind_child above; a mismatch just means the route's own check
    # declines a stale offer, same "offer is a pre-check" pattern as
    # snoopable_devices/open_proposals elsewhere in this function.
    # put_baby_in_carriage additionally needs a pushable prop nearby.
    has_pushable_prop = any(
        world_props_by_id.get(entry["id"], {}).get("move_capacity") is not None
        for entry in interactable
    )
    for other in world.get("characters", {}).values():
        if other.get("building_id") != c.get("building_id"):
            continue
        if other.get("_awaiting_caregiver") and "feed_child" not in action_types:
            action_types.append("feed_child")
        if other.get("_awaiting_reminder") and "remind_child" not in action_types:
            action_types.append("remind_child")
        if other.get("baby_needs") is not None:
            for a in ("breastfeed", "bottle_feed", "hold_baby"):
                if a not in action_types:
                    action_types.append(a)
            if has_pushable_prop and "put_baby_in_carriage" not in action_types:
                action_types.append("put_baby_in_carriage")

    # respond_chore/advance_chore_round only make sense (and only appear)
    # when this character actually has something pending — see
    # _build_proposal_context() below, the same "proposals" context key
    # this mirrors, so the two never disagree about what's live. Branches
    # on kind so "social_ask" proposals (systems/proposals.py) surface
    # respond_social/advance_social_round instead — respond()/
    # proposer_advance_round() are already kind-agnostic, only the action
    # name the LLM sees needs to match the kind.
    cid = c["id"]
    for p in world.get("proposals", {}).values():
        if p.get("status") != "open":
            continue
        kind = p.get("kind")
        if kind == "social_ask":
            respond_action, advance_action = "respond_social", "advance_social_round"
        elif kind == "request":
            respond_action, advance_action = "respond_request", "advance_request_round"
        else:
            respond_action, advance_action = "respond_chore", "advance_chore_round"
        if p.get("responses", {}).get(cid) == "pending" and respond_action not in action_types:
            action_types.append(respond_action)
        elif (p.get("proposer_id") == cid
              and advance_action not in action_types
              and any(state == "counter" for state in p.get("responses", {}).values())):
            action_types.append(advance_action)

    # Lie/excuse engine (see systems/excuses.py) — give_excuse listed
    # whenever someone's actually present to give it to (the route handler
    # further validates the target exists); leave_note always available —
    # same "route handler validates" pattern as hire_service/propose_chore.
    if nearby_people:
        action_types.append("give_excuse")
    action_types.append("leave_note")

    # announce_departure (see action_router.py's _route_announce_departure)
    # — routed but never offered before this round; unconditional, same
    # "route handler finds its own target/no-ops harmlessly" pattern as
    # leave_note above (it searches for a nearby authority itself when no
    # target is given).
    action_types.append("announce_departure")

    # Social negotiation (see systems/proposals.py's "social_ask" kind) —
    # propose_social listed whenever there's someone nearby to propose to,
    # same "route handler validates" pattern as give_excuse.
    if nearby_people:
        action_types.append("propose_social")

    # Social rules (see systems/social_rules.py) — always available;
    # self-authored, no target required for household scope, and the
    # route itself validates an individual-scope target. propose_request
    # gated on nearby_people, same convention as propose_social above.
    action_types.append("propose_rule")
    action_types.append("add_rule_exception")
    if nearby_people:
        action_types.append("propose_request")

    # Behavior-based suspicion (see systems/worries.py) — form_theory
    # only offered once there's actually something to have a theory
    # about; check_device only once a real snoopable phone is found
    # (radius/owner-elsewhere/suspicion-threshold gate, computed below
    # alongside known_contacts/open_proposals as its own self-contained
    # list so the LLM has a real item id to target).
    if any(w.get("suspicion_level", 0) > 0.15 for w in c.get("worries", {}).values()):
        action_types.append("form_theory")

    # Touch proposals (see systems/intimacy.py) — the six propose-touch
    # types listed whenever someone's nearby, same "route handler
    # validates the rest" pattern (propose_touch() already does its own
    # stage/relationship checks). respond_touch only appears when this
    # character actually has an incoming pending proposal.
    if nearby_people:
        action_types.extend([
            "hug", "kiss", "kiss_peck", "kiss_deep",
            "cuddle", "hold_hands", "handshake", "high_five",
        ])
    if any(
        rel.get("touch_negotiation", {}).get("state") == "proposed"
        and rel.get("touch_negotiation", {}).get("proposed_by") != cid
        for rel in c.get("relationships", {}).values()
    ):
        action_types.append("respond_touch")

    # Hostile intentions / emergency (see systems/conflict_pipeline.py,
    # systems/emergency.py) — confront listed whenever someone's nearby and
    # this character isn't already a party to an active conflict (avoids
    # offering an action that start_conflict()'s own double-conflict guard
    # would just silently no-op). call_911 only appears once there's a
    # real, unreported incident this character is aware of — see
    # _build_incident_context(), the same detection this mirrors in
    # build_narrative() so the two never disagree about what's live.
    if nearby_people and not build_conflict_context(c, world):
        action_types.append("confront")

    active_incidents = [
        inc for inc in _build_incident_context(c, world) if not inc["reported"]
    ]
    if active_incidents:
        action_types.append("call_911")

    # call_parent (see systems/hostile_actions.py's offender_is_minor/
    # victim_injured incident tagging, action_router.py's _route_call_parent)
    # -- offered instead of/alongside call_911 for a co-located adult when
    # the offender is a child and nobody was actually hurt. call_911 above
    # stays available regardless; this just adds the more fitting option.
    if c.get("age_group") in ("adult", "elderly") and any(
        inc["offender_is_minor"] and not inc["victim_injured"]
        for inc in active_incidents
    ):
        action_types.append("call_parent")

    # Hostile actions (see systems/hostile_actions.py) — the six offensive
    # types listed whenever someone's nearby, same "route handler
    # validates the rest" pattern as propose_touch/confront. dodge/block/
    # turn_and_run only appear once this character is an active target —
    # someone visible has a recent_hostile_acts entry aimed at them —
    # mirroring the exact detection this mirrors in build_narrative() so
    # the two never disagree about what's live.
    if nearby_people:
        action_types.extend([
            "grab_offensive", "hold", "punch", "kick", "shove", "threaten",
        ])
    if _has_recent_aggressor(c, world):
        action_types.extend(["dodge", "block", "turn_and_run"])

    # Weapon-gated strikes (see systems/hostile_actions.py) — stab/knock
    # only offered when the actor is actually holding a matching
    # weapon_category item (unarmed, effectiveness_modifiers already
    # apply a heavy penalty — but offering the action bare-handed would
    # be misleading, so it's gated out entirely instead). wield_item
    # offered whenever there's an eligible weapon-tagged item in
    # inventory not already held.
    from systems.templates import resolve_item

    held_weapon_category = None
    _held = next((i for i in c.get("inventory", []) if i.get("location") == "held"), None)
    if _held:
        held_weapon_category = resolve_item(world, _held).get("weapon_category")
    if nearby_people and held_weapon_category == "melee_weapon_sharp":
        action_types.append("stab")
    if nearby_people and held_weapon_category == "melee_weapon_blunt":
        action_types.append("knock")

    if any(
        i.get("location") != "held" and resolve_item(world, i).get("weapon_category")
        for i in c.get("inventory", [])
    ):
        action_types.append("wield_item")

    # Knockdown/critical-severity recovery — _route_stand_up
    # (action_router.py) already existed but, like the rest of the
    # posture-action family, was never reachable until it was registered.
    # "crawling" is now the one on-the-ground-but-conscious state, reached
    # either via a knockdown/fumble (hostile_actions.py) or automatically
    # via critical severity (health.py::apply_severity_consequences) — a
    # character can always try to stand back up from it.
    if c.get("posture") == "crawling":
        action_types.append("stand_up")

    # Multi-round grapple (see systems/grapple.py) — wrestle listed
    # whenever someone's nearby, same "route handler validates the rest"
    # pattern as the other hostile actions. While actively grappled
    # (either side), move/turn_and_run are physically impossible (see the
    # matching gate in action_router.py::_route_move/_route_turn_and_run)
    # so they're removed here too; release_hold is the holder's own free
    # exit, dodge stays available as the held character's struggle option
    # (already offered above via _has_recent_aggressor once someone's
    # come at them).
    if nearby_people and not c.get("grappled_by") and not c.get("grappling"):
        action_types.append("wrestle")
    if c.get("grappling"):
        action_types.append("release_hold")
    if c.get("grappled_by"):
        # dodge must stay available for the whole grapple, not just the
        # initial 15-tick _has_recent_aggressor window above — a held
        # character needs to be able to keep struggling every round.
        if "dodge" not in action_types:
            action_types.append("dodge")
    if c.get("held_by"):
        # dodge/struggle option for a pin-mode hold, same reasoning as the
        # wrestle-mode grappled_by case above.
        if "dodge" not in action_types:
            action_types.append("dodge")
    if c.get("holding"):
        action_types.append("release_hold")

    from systems.action_router import _movement_blocked
    if _movement_blocked(c):
        action_types = [a for a in action_types if a not in ("move", "turn_and_run")]

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

    # -----------------------------------------------
    # KNOWN CONTACTS (for phone_call/phone_send_text/computer_send_email
    # targets not currently nearby) — nearby_characters is the only
    # addressable-id list that existed before this; a character couldn't
    # be phoned/texted at all unless they also happened to be visible.
    # Same familiarity/interaction_count gate build_relationship_context()
    # already uses, so the two stay in agreement about who counts as
    # "known", sorted by most recent contact first, capped to keep this
    # list from growing unbounded over a long-lived character's life.
    # -----------------------------------------------
    known_contacts = []
    chars = world.get("characters", {})
    for other_id, rel in c.get("relationships", {}).items():
        if rel.get("familiarity", 0) < 1 and rel.get("interaction_count", 0) == 0:
            continue
        other = chars.get(other_id)
        if not other:
            continue
        known_contacts.append({
            "id":           other_id,
            "name":         other.get("name", other_id),
            "last_contact": rel.get("last_contact", 0),
        })
    known_contacts.sort(key=lambda k: -k["last_contact"])
    known_contacts = known_contacts[:15]

    # -----------------------------------------------
    # OPEN PROPOSALS (for respond_chore/respond_social/respond_request/
    # advance_*_round) — the proposal_id itself was never actually
    # surfaced to the LLM anywhere before this (the narrative note in
    # _build_proposal_context() carries the id, but build_context() only
    # pulls the note string out of it, discarding the id) — meaning
    # respond_chore/respond_social had no real id to supply. Self-
    # contained loop, same pattern as known_contacts above, not reused
    # from _build_proposal_context()'s narrative-note loop.
    # -----------------------------------------------
    open_proposals = []
    for p in world.get("proposals", {}).values():
        if p.get("status") != "open" or p.get("responses", {}).get(c["id"]) != "pending":
            continue
        proposer = chars.get(p.get("proposer_id"))
        open_proposals.append({
            "proposal_id": p["id"],
            "kind":        p.get("kind"),
            "topic":       p.get("chore_id"),
            "situation":   p.get("params", {}).get("situation"),
            "urgency":     p.get("params", {}).get("urgency"),
            "from_id":     p.get("proposer_id"),
            "from_name":   proposer.get("name", p.get("proposer_id")) if proposer else None,
        })

    # -----------------------------------------------
    # SNOOPABLE DEVICES (systems/worries.py's check_device) — a phone
    # someone else set down, within reach, its owner elsewhere, and
    # this character suspicious enough of the owner to actually check
    # it. Full gate re-validated again at the route level (owner could
    # walk back in before the action executes) -- this is only the
    # availability-side pre-check, same relationship as open_proposals
    # has to respond_chore's own re-validation.
    # -----------------------------------------------
    snoopable_devices = []
    own_building = c.get("building_id")
    for item in world.get("placed_items", {}).values():
        if item.get("object_type") != "phone":
            continue
        owner_id = item.get("owner_id")
        if not owner_id or owner_id == c["id"]:
            continue
        owner = chars.get(owner_id)
        if not owner:
            continue
        worry = c.get("worries", {}).get(owner_id)
        if not worry or worry.get("suspicion_level", 0) <= 0.3:
            continue
        loc = (owner.get("phone_state") or {}).get("last_known_location")
        if not loc or loc.get("prop_id") != item["id"]:
            continue
        if owner.get("building_id") == loc.get("building_id"):
            continue  # owner's right there, not actually unattended
        if own_building != loc.get("building_id"):
            continue
        d = abs(c.get("x", 0) - item.get("x", 0)) + abs(c.get("y", 0) - item.get("y", 0))
        if d > 3:
            continue
        snoopable_devices.append({
            "item_id":    item["id"],
            "owner_id":   owner_id,
            "owner_name": owner.get("name", owner_id),
        })
    if snoopable_devices:
        action_types.append("check_device")

    return {
        "action_types":          action_types,
        "interactable_props":    interactable,
        "nearby_characters":     nearby_people,
        "known_contacts":        known_contacts,
        "open_proposals":        open_proposals,
        "snoopable_devices":     snoopable_devices,
        "wearable_items":        wearable_in_inventory,
        "worn_slots":            worn_slots,
        "assembly_boxes":        prop_boxes,
        "tile_boxes":            t_boxes,
        "paint_buckets":         paint_buckets,
        "nearby_walls":          nearby_walls,
        "active_incidents":      active_incidents,
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

# Optional LLM-set conversation_type (see action_router.py::apply_speech())
# rendered as its own framing sentence instead of the flat default — falls
# back to the exact original phrasing when unset, so untyped conversations
# are unchanged.
_CONVERSATION_TYPE_PHRASING = {
    "argument":    "You're in the middle of an argument with {who} about {topic}",
    "negotiation": "You're negotiating with {who} about {topic}",
    "persuasion":  "You're trying to convince {who} about {topic}",
    "competition": "You and {who} are in a friendly competition about {topic}",
    "gossip":      "You're gossiping with {who} about {topic}",
}


# Non-in-person conversation media (phone/computer round, phase 2) —
# same "extend the dict, don't reinvent the function" pattern as
# _CONVERSATION_TYPE_PHRASING above.
_MEDIUM_VERB = {
    "call":  "on a call",
    "text":  "texting",
    "email": "emailing",
}


def _conversation_frame_line(conv):
    who = conv["with"]
    topic = conv.get("topic") or "something"
    medium = conv.get("medium", "in_person")
    template = _CONVERSATION_TYPE_PHRASING.get(conv.get("conversation_type"))
    base = template.format(who=who, topic=topic) if template else \
        f"You are in conversation with {who} about {topic}"
    medium_verb = _MEDIUM_VERB.get(medium)
    if not medium_verb:
        return base
    if template:
        # Richer conversation_type framing already carries its own verb
        # ("negotiating", "gossiping", ...) — just note it isn't
        # face-to-face rather than replacing the whole sentence.
        return f"{base} ({medium_verb})"
    return f"You're {medium_verb} with {who} about {topic}"


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
        lines.append(_conversation_frame_line(conv) + turn_note)
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

# =========================================================
# NARRATIVE SECTIONS
# =========================================================
# Each _sec_<name>(c, world) returns the paragraph(s) that section
# contributes — a str, a list[str] (for sections that emit several
# separate paragraphs, e.g. one per pending proposal), or None/[] to
# contribute nothing this call. NARRATIVE_SECTIONS below drives both
# build_narrative()'s assembly order and its brief/full tiering (see
# TIER_SETS) — "core" sections always run; "full" sections are skipped in
# brief mode (event-driven wakes that don't need the whole scene re-told,
# see brain/cognition_scheduler.py / BRIEF_REASONS below). This table is
# also what brain/describe_registry.py (Round 8) draws room-description
# content from.

def _sec_scene(c, world):
    return build_scene_description(c, world)


def _sec_hearing(c, world):
    # restores perceive_audio()'s audible_events, computed every perception
    # cadence tick but never surfaced anywhere before this (not in the old
    # flat context, not consumed by attention.py either). event["speaker"]/
    # ["topic"] already carry perceive_audio()'s mishearing (perception.py::
    # _perceived_topic) — a corrupted topic is reported with full
    # confidence here, same as a correct one, because that's what an
    # unintended misunderstanding actually is; only the very-low-clarity
    # case (speaker is None) gets an explicit hedge.
    audible = c.get("perception", {}).get("audible_events", [])
    if not audible:
        return None
    lines = []
    for event in audible[:4]:
        if event.get("type") == "speech":
            speaker = event.get("speaker")
            topic = event.get("topic")
            if not speaker:
                lines.append(
                    "You hear muffled talking nearby, but can't "
                    "make out who or what."
                )
            elif topic:
                lines.append(
                    f"You hear {speaker} mention something about {topic}."
                )
            else:
                lines.append(f"You hear {speaker} talking somewhere nearby.")
        elif event.get("type") == "ambient" and event.get("sound"):
            lines.append(
                f"You hear a {event['sound'].replace('_', ' ')}."
            )
    return " ".join(lines) if lines else None


def _sec_incidents(c, world):
    # active incidents (fire, assault, ...) — see _build_incident_context()
    # below. Only incidents this character is a participant in or
    # physically close enough to have witnessed.
    incidents = _build_incident_context(c, world)
    if not incidents:
        return None
    lines = []
    for inc in incidents:
        if inc["type"] == "fire":
            lines.append(
                f"There's a fire{' spreading' if inc['severity'] >= 40 else ''} here"
                f"{' — you could call 911.' if not inc['reported'] else ' — it has already been reported.'}"
            )
        else:
            label = inc["type"].replace("_", " ")
            lines.append(
                f"There's a {label} happening nearby"
                f"{' — you could call 911.' if not inc['reported'] else ' — it has already been reported.'}"
            )
        # Self-incrimination nudge — narrative only, the LLM stays free to
        # call anyway (per the fluid-reactions design constraint). Only
        # relevant while nobody's called it in yet.
        if inc.get("offender_id") == c["id"] and not inc["reported"]:
            lines.append("Calling attention to this could implicate you.")
        # Flee-on-arrival nudge — same "nudge, not a forced behavior" rule;
        # turn_and_run is a real action they can choose in response.
        if inc.get("offender_id") == c["id"] and inc.get("responder_status") == "arrived":
            lines.append("The police have arrived — you might want to get out of here.")
    return " ".join(lines)


def _sec_grapple(c, world):
    # active grapple — see systems/grapple.py. Explains why move/
    # turn_and_run disappeared and release_hold/dodge showed up.
    if c.get("grappled_by"):
        holder = world.get("characters", {}).get(c["grappled_by"])
        holder_name = holder.get("name", "someone") if holder else "someone"
        return f"{holder_name} is holding you in place — you're struggling to break free."
    if c.get("grappling"):
        held = world.get("characters", {}).get(c["grappling"])
        held_name = held.get("name", "them") if held else "them"
        return f"You're holding {held_name} in place — they're struggling to get free."
    return None


def _sec_body_fitness(c, world):
    # body composition + fitness — systems/body_composition.py and
    # systems/exercise.py, both fully built in earlier rounds but never
    # actually surfaced to the LLM until now. Self-conscious framing at the
    # extremes is the "impacts motivation" ask -- not a hard mechanical
    # block on any action, just narrative pressure, same as every other
    # nudge-not-force pattern in this file.
    from systems.body_composition import get_body_composition_context
    from systems.exercise import get_exercise_context
    body_lines = get_body_composition_context(c).get("body_composition", [])
    fitness_lines = get_exercise_context(c).get("fitness", [])
    return " ".join(body_lines + fitness_lines) if (body_lines or fitness_lines) else None


def _sec_aggressor(c, world):
    # active aggressor — see _has_recent_aggressor(). Explains why dodge/
    # block/turn_and_run suddenly appeared, same "gate the action + explain
    # it in prose" pattern as every other gated action this session (touch
    # proposals, chore proposals, ...).
    if _has_recent_aggressor(c, world):
        return "Someone nearby just came at you — you could dodge, block, or turn and run."
    return None


def _sec_witnessed(c, world):
    # witnessed offenses — see systems/excuses.py::
    # check_witnessed_hostility_for_observer(). Purely a "who did I just
    # see do something hostile" cue; confront/call_911 were already
    # reachable via nearby_people/proximity (§ above), this just gives the
    # LLM a name and a reason.
    return _build_witnessed_offense_line(c, world)


def _sec_attention(c, world):
    # attention/focus — restores build_attention_summary, previously
    # unused (dead code, same gap as relationships/memories above)
    focus = build_attention_summary(c, world).get("focus")
    if focus and focus.get("strength", 0) > 0.4 and focus.get("on"):
        return f"Your attention keeps drifting to {focus['on']}."
    return None


def _sec_identity(c, world):
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
    return " ".join(bits)


def _sec_body(c, world):
    # reuse the already-prose build_body_context
    body_issues = build_body_context(c)
    return " ".join(body_issues) if body_issues else None


def _sec_health(c, world):
    # injury/illness severity — see systems/health.py::compute_severity().
    # Previously the LLM had zero visibility into physical_health/
    # mental_health/health_state/injuries at all.
    return _build_health_context(c, world)


def _sec_bedroom(c, world):
    # bedroom ownership — see systems/bedroom_assignment.py
    bedroom_id = c.get("bedroom_id")
    if not bedroom_id:
        return None
    roommates = [
        other.get("name", "someone")
        for other in world.get("characters", {}).values()
        if other["id"] != c["id"] and other.get("bedroom_id") == bedroom_id
    ]
    if roommates:
        return f"You share your room with {', '.join(roommates)}."
    return "You have your own room."


def _sec_intentions(c, world):
    intentions = build_intentions(c)
    if not intentions:
        return None
    top = intentions[0]
    line = f"Right now you're mainly focused on {top.get('type')}"
    if top.get("reason"):
        line += f" ({top['reason']})"
    line += "."
    rest = [i.get("type") for i in intentions[1:4] if i.get("type")]
    if rest:
        line += f" You're also thinking about: {', '.join(rest)}."
    return line


def _sec_turn_budget(c, world):
    # describe/recall (Rounds 8-9) are withheld from the action menu once
    # cognition.turn_budget hits 0 (see build_available_actions()) — this
    # is the only thing that tells the character *why* those options just
    # vanished, so it doesn't read as an unexplained restriction mid-chain.
    if c.get("cognition", {}).get("turn_budget", 0) > 0:
        return None
    return "You've already taken time to look and think this round — better to act now."


def _sec_relationships(c, world):
    # restores build_relationship_context, which was already fully built
    # but never called from build_context()
    relationships = build_relationship_context(c, world, limit=5)
    return " ".join(r["summary"] for r in relationships) if relationships else None


def _sec_grievances(c, world):
    # restores build_grievance_context, previously unused (same "defined
    # but never wired in" gap as everything else in this function).
    # Surfaced so the LLM has visible motive before ever reaching for the
    # "confront" action.
    grievances = build_grievance_context(c, world)
    if not grievances:
        return None
    top = grievances[0]
    return f"You're still bothered by {top['with']} over {', '.join(top['top_issues'])}."


def _sec_conflict(c, world):
    # restores build_conflict_context, previously unused. Purely reflects
    # the trait/dice-driven conflict_pipeline.py state machine; the LLM
    # cannot alter this resolution, only decide whether to have entered it
    # (via "confront") and how to react.
    conflict = build_conflict_context(c, world)
    if not conflict:
        return None
    other = conflict["with"]
    phase = conflict["phase"]
    if phase == "deliberation":
        return (
            f"You're privately weighing whether to work things out with {other} "
            f"or let it turn into a fight."
        )
    if phase == "negotiation":
        issues = ", ".join(conflict.get("issues", [])) or "what's been bothering you"
        return f"You're negotiating with {other} about {issues}."
    if phase == "fight":
        stage = (conflict.get("fight_stage") or "verbal_dispute").replace("_", " ")
        return f"You're in a {stage} with {other}."
    return None


def _sec_memories(c, world):
    # restores build_memory_context, previously unused
    memories = build_memory_context(c)
    if not memories:
        return None
    top_memories = sorted(
        memories, key=lambda m: m.get("importance", 0), reverse=True
    )[:3]
    mem_text = "; ".join(m["text"] for m in top_memories if m.get("text"))
    return f"You recall: {mem_text}." if mem_text else None


def _sec_family(c, world):
    # restores _build_family_context, previously unused
    family = _build_family_context(c, world)
    if not family or not family.get("members"):
        return None
    fam_bits = [
        f"{m['name']} ({m['kinship']})"
        for m in family["members"] if m.get("kinship")
    ]
    return f"Your family: {', '.join(fam_bits)}." if fam_bits else None


def _sec_household_processes(c, world):
    # already carry descriptive fields; inlined as sentences instead of
    # nested JSON
    procs = _build_household_process_context(c, world) or []
    lines = [
        f"There's a {p.get('type')} in progress, currently at the "
        f"{p.get('stage')} stage, waiting on {p.get('waiting')}."
        for p in procs
    ]
    return lines or None


def _sec_proposals(c, world):
    proposals = _build_proposal_context(c, world) or {}
    out = []
    for key in ("incoming", "mediating", "resolved", "rule_fired"):
        for entry in proposals.get(key, []):
            out.append(entry["note"])
    return out or None


def _sec_social_rules(c, world):
    lines = _build_social_rules_context(c, world)
    return list(lines) if lines else None


def _sec_worries(c, world):
    lines = _build_worries_context(c, world)
    return list(lines) if lines else None


def _sec_influence(c, world):
    lines = _build_influence_context(c, world)
    return list(lines) if lines else None


def _sec_touch(c, world):
    # restores _build_touch_proposal_context/_build_intimacy_context,
    # previously unused (dead code, same gap as relationships/memories
    # above)
    touch = _build_touch_proposal_context(c, world) or {}
    out = []
    if touch.get("incoming"):
        out.append(touch["incoming"]["note"])
    if touch.get("outgoing"):
        out.append(touch["outgoing"]["note"])
    return out or None


def _sec_intimacy(c, world):
    intimacy_lines = _build_intimacy_context(c, world)
    return "; ".join(intimacy_lines) + "." if intimacy_lines else None


def _sec_phone(c, world):
    # phone location — systems/phone.py::get_phone_context(): "set down
    # nearby" / "not sure where it is" (forgotten). Battery state
    # (_build_phone_context()) only matters narratively once it's actually
    # low, same "only mention what's notable" rule the rest of this
    # function follows.
    from systems.phone import get_phone_context
    out = []
    phone_location_line = get_phone_context(c)
    if phone_location_line:
        out.append(phone_location_line)
    phone_battery = _build_phone_context(c)
    if phone_battery and phone_battery.get("usable") is False:
        out.append(f"Your phone's battery is dead ({phone_battery.get('battery', 0)}%).")
    elif phone_battery and phone_battery.get("battery", 100) < 20:
        out.append(f"Your phone's battery is low ({phone_battery.get('battery')}%).")
    return out or None


# (key, tier, fn) — order is the assembly order (matches the pre-refactor
# sequence exactly). tier "core" sections always run; "full" sections are
# skipped in brief mode — see TIER_SETS / BRIEF_REASONS.
NARRATIVE_SECTIONS = [
    ("scene",                "core", _sec_scene),
    ("hearing",               "full", _sec_hearing),
    ("incidents",             "full", _sec_incidents),
    ("grapple",               "full", _sec_grapple),
    ("body_fitness",          "full", _sec_body_fitness),
    ("aggressor",             "full", _sec_aggressor),
    ("witnessed",             "full", _sec_witnessed),
    ("attention",             "full", _sec_attention),
    ("identity",              "core", _sec_identity),
    ("body",                  "core", _sec_body),
    ("health",                "core", _sec_health),
    ("bedroom",               "full", _sec_bedroom),
    ("intentions",            "core", _sec_intentions),
    ("turn_budget",           "core", _sec_turn_budget),
    ("relationships",         "full", _sec_relationships),
    ("grievances",            "full", _sec_grievances),
    ("conflict",              "full", _sec_conflict),
    ("memories",              "full", _sec_memories),
    ("family",                "full", _sec_family),
    ("household_processes",   "full", _sec_household_processes),
    ("proposals",             "full", _sec_proposals),
    ("social_rules",          "full", _sec_social_rules),
    ("worries",               "full", _sec_worries),
    ("influence",             "full", _sec_influence),
    ("touch",                 "full", _sec_touch),
    ("intimacy",              "full", _sec_intimacy),
    ("phone",                 "full", _sec_phone),
]

TIER_SETS = {"brief": {"core"}, "full": {"core", "full"}}

# Wake reasons that only need the character re-oriented, not the whole
# scene re-told — see brain/cognition_scheduler.py. Deliberately NOT brief:
# idle, urgent_need, activity_finished, activity_aborted, schedule_block
# (real "what next" decisions needing full context), describe_result/
# recall_result (the whole point is more detail).
BRIEF_REASONS = {
    "person_entered_view", "heard_speech", "wait_ready", "activity_phase_changed",
}


def build_narrative(c, world, mode="full", wake_line=None, staged=()):
    paragraphs = [wake_line] if wake_line else []
    paragraphs.extend(staged)

    tiers = TIER_SETS.get(mode, TIER_SETS["full"])
    for _key, tier, fn in NARRATIVE_SECTIONS:
        if tier not in tiers:
            continue
        try:
            out = fn(c, world)
        except Exception:
            # One broken section must not kill the whole narrative.
            continue
        if not out:
            continue
        if isinstance(out, list):
            paragraphs.extend(p for p in out if p)
        else:
            paragraphs.append(out)

    return "\n\n".join(p for p in paragraphs if p)


# =========================================================
# MAIN CONTEXT BUILDER
# =========================================================
# narrative: the DM-style prose block above — everything the character
# perceives/remembers/feels, in free text. available_actions: the only
# place literal prop/character ids appear, kept as strict JSON because the
# model must echo those back exactly (see llm_brain.py::build_prompt,
# which assembles the two into one prompt).
#
# trigger_reason (default "idle" — matches the old always-full behavior
# for callers that don't pass one, e.g. api/debug.py) selects brief vs
# full narrative mode via BRIEF_REASONS above. wake_line/staged pass
# through to build_narrative() — see brain/cognition_scheduler.py::
# wake_line() and Round 8/9's staged_knowledge (describe/recall results).

def build_context(

    c,

    world,

    trigger_reason="idle",

    wake_line=None,

    staged=()
):

    mode = "brief" if trigger_reason in BRIEF_REASONS else "full"

    return {

        "narrative": build_narrative(c, world, mode=mode, wake_line=wake_line, staged=staged),

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

    Surfaces four kinds of entries for a character:
      - incoming: a proposal awaiting THIS character's response (accept/
        decline/counter).
      - mediating: a proposal THIS character made, where one or more
        recipients have countered and are waiting on a decision (see
        systems/proposals.py's "proposer-mediated reconciliation" rule —
        counters are proposals to the proposer, not to each other).
      - resolved: a proposal THIS character made that just accepted/
        declined — a pre-existing gap (nothing told the proposer the
        outcome, for social_ask especially, which has no hand-off side
        effect) fixed here with a one-time notification, gated by a
        "proposer_notified" flag stamped onto the proposal so it only
        narrates once.
      - rule_fired: a "request"-kind proposal that auto-resolved against
        THIS character's own systems/social_rules.py policy — auto-
        resolution (see action_router.py::_route_propose_request) calls
        respond() on the rule owner's behalf synchronously, so the normal
        "responses[cid]==pending" incoming branch above never fires for
        them; without this they'd have no way to learn their own rule
        just governed someone's request. Gated by "owner_notified",
        same one-time-narration pattern.
    """
    cid = c["id"]
    chars = world.get("characters", {})
    incoming, mediating, resolved, rule_fired = [], [], [], []

    for p in world.get("proposals", {}).values():
        kind = p.get("kind")

        if p.get("status") == "open":
            if p.get("responses", {}).get(cid) == "pending":
                if kind == "chore":
                    note = (f"Someone proposed {p.get('chore_id')} — you can accept, decline, "
                            f"or counter with different details.")
                elif kind == "social_ask":
                    note = (f"Someone is asking you: {p.get('chore_id')} — you can accept, "
                            f"decline, or counter.")
                elif kind == "request":
                    proposer = chars.get(p.get("proposer_id"))
                    params = p.get("params", {})
                    note = (f"{proposer.get('name', 'Someone') if proposer else 'Someone'} is "
                            f"asking you: {p.get('chore_id')} — {params.get('situation', '')} "
                            f"(urgency {params.get('urgency', 0)}/100) — you can accept, "
                            f"decline, or counter.")
                else:
                    note = f"Someone offered to make {p.get('chore_id')} a recurring thing."
                incoming.append({
                    "proposal_id": p["id"],
                    "kind":        kind,
                    "chore_id":    p.get("chore_id"),
                    "params":      p.get("params"),
                    "proposed_by": p.get("proposer_id"),
                    "round":       p.get("round"),
                    "note":        note,
                })

            elif p.get("proposer_id") == cid:
                counters = {
                    rid: p["counter_params"].get(rid)
                    for rid, state in p.get("responses", {}).items()
                    if state == "counter"
                }
                if counters:
                    if kind == "social_ask":
                        advance_action = "advance_social_round"
                    elif kind == "request":
                        advance_action = "advance_request_round"
                    else:
                        advance_action = "advance_chore_round"
                    mediating.append({
                        "proposal_id": p["id"],
                        "kind":        kind,
                        "chore_id":    p.get("chore_id"),
                        "your_params": p.get("params"),
                        "counters":    counters,
                        "round":       p.get("round"),
                        "note":        "One or more people countered your proposal with different "
                                       f"details — decide new terms ({advance_action}) or let it "
                                       "lapse.",
                    })

        elif p.get("status") == "resolved":
            if p.get("proposer_id") == cid and not p.get("proposer_notified"):
                # participants = accepted recipients + the proposer (always
                # included, see proposals.py::_maybe_resolve) -- so >1 means
                # at least one recipient actually accepted.
                accepted = len(p.get("participants", [])) > 1
                verb = "accepted" if accepted else "declined"
                resolved.append({
                    "proposal_id": p["id"],
                    "kind":        kind,
                    "chore_id":    p.get("chore_id"),
                    "note":        f"Your {p.get('chore_id')} request/proposal was {verb}.",
                })
                p["proposer_notified"] = True

            if (kind == "request" and p.get("auto_resolved")
                    and cid in p.get("recipients", []) and not p.get("owner_notified")):
                proposer = chars.get(p.get("proposer_id"))
                allowed = cid in p.get("participants", [])
                reason = p.get("auto_resolution_reason") or "your standing rule"
                rule_fired.append({
                    "proposal_id": p["id"],
                    "chore_id":    p.get("chore_id"),
                    "note":        (f"{proposer.get('name', 'Someone') if proposer else 'Someone'} "
                                     f"asked to {p.get('chore_id')}; your rule with them auto-"
                                     f"{'allowed' if allowed else 'declined'} it "
                                     f"({reason})."),
                })
                p["owner_notified"] = True

    result = {}
    if incoming:
        result["incoming"] = incoming
    if mediating:
        result["mediating"] = mediating
    if resolved:
        result["resolved"] = resolved
    if rule_fired:
        result["rule_fired"] = rule_fired
    return result or None


def _build_social_rules_context(c, world):
    """Surfaces this character's OWN standing social_rules.py policies
    and any active per-person exceptions in prose, so the owner's LLM
    remembers its own past decisions (e.g. "I already carved out an
    exception for Alex") without having to re-derive them. Only ever
    shows the owner's own rules -- someone learns another character's
    rule exists in-fiction, as a consequence of a request being
    resolved (see _build_proposal_context's rule_fired branch), not
    omnisciently ahead of time."""
    rules = c.get("social_rules", [])
    if not rules:
        return []

    chars = world.get("characters", {})
    households = world.get("households", {})
    now = world.get("tick", 0)
    lines = []

    for rule in rules:
        if rule["scope"] == "individual":
            who = chars.get(rule["scope_ids"][0], {}).get("name", "someone specific")
            scope_desc = who
        else:
            hh = households.get(rule["scope_ids"][0], {})
            scope_desc = f"household members of {hh.get('name', 'your household')}" \
                if len(rule["scope_ids"]) == 1 else "several households"
        verb = "may" if rule["default"] == "allow" else "may NOT"
        line = (f"Your rule on \"{rule['topic']}\": {scope_desc} {verb} "
                f"(priority {rule['priority']}).")

        exception_bits = []
        for subject_id, exc in rule.get("exceptions", {}).items():
            expires_tick = exc.get("expires_tick")
            if expires_tick is not None and now > expires_tick:
                continue   # expired, live-check consistent with resolve_request
            subject_name = chars.get(subject_id, {}).get("name", subject_id)
            exc_verb = "may" if exc["override"] == "allow" else "may NOT"
            expiry = f", expires in {expires_tick - now} ticks" if expires_tick is not None else ""
            reason = f" — {exc['reason']}" if exc.get("reason") else ""
            exception_bits.append(
                f"{subject_name} {exc_verb} (priority {exc['priority']}{expiry}){reason}"
            )
        if exception_bits:
            line += " Exception: " + "; ".join(exception_bits) + "."
        lines.append(line)

    return lines


def _build_worries_context(c, world):
    """Surfaces this character's OWN active worries (systems/worries.py)
    in prose -- their suspicion of someone else, why, and whatever
    theory they've formed about it. Only ever the observer's own
    worries; a subject never sees they're worried about, mirroring how
    secrets.py's target context deliberately withholds the keeper's
    actual content."""
    from systems.worries import get_active_worries
    active = get_active_worries(c)
    if not active:
        return []

    chars = world.get("characters", {})
    lines = []
    for subject_id, worry in active.items():
        level = worry.get("suspicion_level", 0)
        if level > 0.6:
            label = "seriously wrong"
        elif level > 0.3:
            label = "noticeably strange"
        else:
            label = "a little off"
        subject_name = chars.get(subject_id, {}).get("name", subject_id)
        line = f"Something feels {label} about {subject_name} lately."
        triggers = worry.get("triggers", [])
        if triggers:
            line += f" ({triggers[-1].get('note')})"
        if worry.get("false_belief"):
            line += f" You suspect: {worry['false_belief']}."
        if worry.get("suspicion_of"):
            blamed = chars.get(worry["suspicion_of"], {}).get("name", worry["suspicion_of"])
            line += f" You wonder if {blamed} is involved instead."
        lines.append(line)

    return lines


def _build_influence_context(c, world):
    """Surfaces recent trait absorptions from trusted, frequently-around
    people (systems/peer_influence.py). The negative (distrust/paranoia)
    branch needs no equivalent here -- it rides through the existing
    worries.py plumbing above automatically, since resolve_exposure_influence()
    reuses bump_suspicion()'s "prolonged_exposure" trigger note."""
    absorbed = c.get("absorbed_traits", [])
    if not absorbed:
        return []

    chars = world.get("characters", {})
    recent = absorbed[-2:]
    lines = []
    for entry in recent:
        source_name = chars.get(entry.get("source_person_id"), {}).get("name", "someone you're often around")
        trait = entry.get("trait", "")
        lines.append(
            f"You've noticed yourself becoming more {trait.replace('_', ' ')} lately, "
            f"since spending so much time around {source_name}."
        )
    return lines


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
            "alive":   other.get("alive", True),
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


_RECENT_AGGRESSOR_WINDOW_TICKS = 15


def _has_recent_aggressor(c, world):
    """True if a visible nearby character has a recent_hostile_acts entry
    (systems/hostile_actions.py) aimed at this character within the last
    few ticks — i.e. this character is an active target and dodge/block/
    turn_and_run are real, timely choices, not standing offers."""
    cid = c["id"]
    tick = world.get("tick", 0)
    chars = world.get("characters", {})
    for p in c.get("perception", {}).get("visible_people", []):
        other = chars.get(p["id"])
        if not other:
            continue
        for act in other.get("recent_hostile_acts", []):
            if (act.get("target_id") == cid
                    and tick - act.get("tick", -9999) <= _RECENT_AGGRESSOR_WINDOW_TICKS):
                return True
    return False


def _build_witnessed_offense_line(c, world):
    """Render a sentence for the most recent still-fresh entry in this
    character's witnessed_offenses (systems/excuses.py::
    check_witnessed_hostility_for_observer). Names the offender and, if
    known, their target."""
    tick = world.get("tick", 0)
    witnessed = c.get("witnessed_offenses", {})
    if not witnessed:
        return None
    chars = world.get("characters", {})

    offender_id, tagged_tick = max(witnessed.items(), key=lambda kv: kv[1])
    if tick - tagged_tick > _RECENT_AGGRESSOR_WINDOW_TICKS:
        return None
    offender = chars.get(offender_id)
    if not offender:
        return None
    offender_name = offender.get("name", "someone")

    victim_name = None
    for act in offender.get("recent_hostile_acts", []):
        if tick - act.get("tick", -9999) <= _RECENT_AGGRESSOR_WINDOW_TICKS:
            victim = chars.get(act.get("target_id"))
            if victim:
                victim_name = victim.get("name")
            break

    if victim_name:
        return (f"You just saw {offender_name} attack {victim_name} — "
                f"you could intervene or call 911.")
    return f"You just saw {offender_name} act violently — you could intervene or call 911."


def _build_health_context(c, world):
    """
    Self-awareness of injury/illness severity — see systems/health.py::
    compute_severity(), the first unified "how badly hurt is this
    character" aggregate in the codebase. Healthy/mild tiers get no
    paragraph (keeps token cost down, matches every other narrative
    section this session); moderate-or-worse names the tier and the
    worst active emergency/injury so the LLM understands why dodge/
    call_911/its own reduced options are showing up.
    """
    try:
        from systems.health import compute_severity
    except Exception:
        return None

    score, tier = compute_severity(c)
    hs = c.get("health_state", {})
    lines = []

    if tier not in ("healthy", "mild"):
        em = hs.get("active_emergencies", {})
        worst_label = None
        if em:
            worst_key = max(em, key=lambda k: em[k].get("severity", 0))
            worst_label = worst_key.replace("_", " ")
        else:
            injuries = hs.get("injuries", [])
            if injuries:
                last = injuries[-1]
                part = last.get("body_part", "body").replace("_", " ")
                worst_label = f"{last.get('type')} injury to your {part}"

        tier_phrase = {
            "moderate": "You're in noticeable pain and not at full strength.",
            "severe":   "You're badly hurt — every movement is a struggle.",
            "critical": "You're in critical condition, barely able to move.",
            "dead":     "You have died.",
        }.get(tier, "")
        if worst_label:
            tier_phrase += f" ({worst_label})"
        if tier_phrase:
            lines.append(tier_phrase)

    # Pain-specific line — independent of overall severity tier (pain is
    # only one of several signals compute_severity() weighs, so real pain
    # — bad domestic-abuse bruising, a nasty fever — doesn't always push
    # the aggregate tier past "moderate").
    if hs.get("pain", 0) >= 50:
        lines.append("You're in a lot of pain.")

    return " ".join(lines) or None


def _build_incident_context(c, world):
    """
    Active incidents (systems/emergency.py) this character is aware of —
    either a direct participant, or physically close enough to have
    witnessed it (same Manhattan-4 radius emergency.py::resolve() already
    uses for responder effect). Only unresolved incidents are surfaced;
    once extinguished/resolved they naturally drop out.
    """
    cid = c["id"]
    cx, cy = c.get("x", 0), c.get("y", 0)
    result = []
    for inc in world.get("incidents", []):
        if inc.get("extinguished"):
            continue
        if inc.get("type") == "fire" and inc.get("severity", 0) <= 0:
            continue
        loc = inc.get("location", {})
        is_participant = cid in inc.get("participants", [])
        is_nearby = (
            "x" in loc and "y" in loc
            and abs(cx - loc["x"]) + abs(cy - loc["y"]) < 4
        )
        if not (is_participant or is_nearby):
            continue
        result.append({
            "id":                 inc["id"],
            "type":               inc.get("type"),
            "severity":           inc.get("severity", 0),
            "reported":           inc.get("reported", False),
            "offender_id":        inc.get("offender_id"),
            "offender_is_minor":  inc.get("offender_is_minor", False),
            "victim_injured":     inc.get("victim_injured", False),
            "responder_status":   _responder_status_for_incident(inc, world),
        })
    return result


def _responder_status_for_incident(incident, world):
    """"en_route" / "arrived" for whichever responder was dispatched off a
    call linked to this incident (emergency.py::create_911_call's
    incident_id -> dispatch()'s responder.incident_id), or None if nobody's
    been dispatched yet. Computed from arrival_tick directly rather than
    trusting the responder's own "status" field, since resolve() only
    flips that on its own (÷30) cadence — this stays accurate to the tick
    even before that cadence catches up."""
    tick = world.get("tick", 0)
    call_ids = {
        call["id"] for call in world.get("calls", [])
        if call.get("incident_id") == incident["id"]
    }
    if not call_ids:
        return None
    for r in world.get("responders", []):
        if r.get("call_id") in call_ids:
            return "arrived" if tick >= r.get("arrival_tick", float("inf")) else "en_route"
    return None


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
