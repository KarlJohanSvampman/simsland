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

def build_intentions(c):

    intentions = []

    for i in c.get(
        "active_intentions",
        []
    ):

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
    }


# =========================================================
# MAIN CONTEXT BUILDER
# =========================================================

def build_context(

    c,

    world
):

    context = {

        # =====================================
        # IDENTITY
        # =====================================

        "identity": {

            "name":
                c.get("name"),

            "age":
                c.get("age"),

            "traits":
                c.get(
                    "traits",
                    []
                ),

            "occupation":
                c.get(
                    "occupation"
                )
        },

        # =====================================
        # INTERNAL STATE
        # =====================================

        "internal_state": {

            "emotion":
                c.get("emotion", "neutral"),

            "mood":
                c.get("mood"),

            "stress":
                c.get("stress", 0),

            "social_need":
                c.get("needs", {}).get("social", 0.7),

            "fun_need":
                c.get("needs", {}).get("fun", 0.6),

            "sleep_debt":
                c.get("body", {}).get("sleep_debt", 0),
        },

        # =====================================
        # ACTIVE INTENTIONS
        # =====================================

        "active_intentions":
            build_intentions(c),

        # =====================================
        # PERCEPTION (SCENE)
        # =====================================
        "perception":
            c.get(
                "perception",
                {}
            ),
        # =====================================
        # ATTENTION
        # =====================================
        "attention_summary":
            build_attention_summary(
                c,
                world
            ),
        # =====================================
        # CURRENT LOCATION
        # =====================================

        "location": {

            "building":
                c.get(
                    "building_id"
                ),

            "room":
                c.get(
                    "room_id"
                )
        },

        # =====================================
        # PHONE
        # =====================================

        "phone_notifications":
            c.get(
                "phone_notifications",
                []
            ),

        # =====================================
        # NEWS
        # =====================================

        "news":
            world.get(
                "news_feed",
                []
            )[:5],

        # =====================================
        # ACTIONS
        # =====================================

        "available_actions":
            build_available_actions(
                c,
                world
            ),

        "conversations":
            build_conversation_context(
                c,
                world
            ),
        "persistent_desires":
        [
            d

            for d in c.get(
                "persistent_desires",
                []
            )

            if not d.get(
                "resolved"
            )
        ][:5],
        "current_turn":
            get_current_turn(
                c,
                world
            ),
        "beliefs": build_belief_context(c),
        "political_alignment": compute_alignment(c),
        "life_narratives": build_narratives(c),
        "self_model": build_self_model(c),
        "schedule": build_schedule_context(c),
        "body_state": build_body_context(c),
        "lt_needs": _build_lt_need_context(c),
        "household_resources":build_household_resource_context( c,world),
        "cognitive_pressure": build_cognitive_pressure(c),
        "social": build_social_context(c,world),
        "memories": build_memory_context(c),
        "active_conversations":build_active_conversations(c, world),
        "social_models":build_social_model_context(c),
        "active_conflict": build_conflict_context(c, world),
        "grievances": build_grievance_context(c, world),
        "investments":       build_investment_context(c, world),
        "inventory":         _build_inventory_context(c),
        "worn":              _build_worn_context(c),
        "services":          _build_services_context(c, world),
        "phone":             _build_phone_context(c),
        "social_events":     _build_events_context(c, world),
        "upcoming_calendar_events": _build_calendar_context(c, world),
        "hobbies":           _build_hobbies_context(c, world),
        "reputation":        _build_reputation_context(c),
        "factions":          _build_faction_context(c, world),
        "family":            _build_family_context(c, world),
        "secrets_held":      _build_secrets_keeper_context(c),
        "secrets_targeted":  _build_secrets_target_context(c, world),
        "attraction":        _build_attraction_context(c, world),
        "intimacy":          _build_intimacy_context(c, world),
        "rivalries":         _build_rival_context(c, world),
        "envy_conflicts":    _build_envy_context(c, world),
        "impulse":           _build_impulse_context(c, world),
        "domestic_situation": _build_domestic_context(c, world),
        "emotional_control_situation": _build_emotional_control_context(c, world),
        "religious_repression": _build_repression_context(c, world),
        "pregnancy":         _build_pregnancy_context(c, world),
        "trauma":            _build_trauma_context(c, world),
        "sexual_history":    _build_pleasure_context(c, world),
    }

    return context


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
