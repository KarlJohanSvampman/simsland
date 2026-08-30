"""
systems/reading_process.py

Powers the read_newspaper/browse_news activities (see
systems/action_router.py::_route_read_newspaper/_route_browse_news).
While active, every READING_PICK_INTERVAL_TICKS (5 sim-minutes -- 1 tick
== 1 simulated second, see core/tick_schedule.py) picks a new random
recent world["news"] item, shows it as a speech bubble (non-blocking --
doesn't interrupt reading, see incidental_speech.py), and -- if someone's
nearby -- reads it aloud and asks their opinion, which can escalate into
a real group debate (apply_speech_to_group(), brain/conversations.py's
new multi-party support). Mirrors systems/cooking_process.py's
active_process + update_* shape exactly.
"""

import random

READING_PICK_INTERVAL_TICKS = 5 * 60  # 5 sim-minutes
DEBATE_TRIGGER_PROB = 0.3
# Mirrors action_router.py's heard_speech wake-up cap ("so a shout in a
# crowded room doesn't stampede everyone... on a 2-slot Ollama budget") --
# same reasoning applies to spawning a group conversation.
MAX_DEBATE_PARTICIPANTS = 4


def start_reading_news(c, world, medium):
    """medium: "paper" | "phone". Caller is responsible for scaffolding
    c["activity"] itself (_route_read_newspaper/_route_browse_news) --
    this only sets up the active_process side, same division of
    responsibility cooking_process.py's start_cooking_process() has with
    whatever routed the cook_recipe action in the first place."""
    tick = world.get("tick", 0)
    item = _pick_news_item(world)

    process = {
        "type":             "reading_news",
        "medium":           medium,
        "started_tick":     tick,
        "last_pick_tick":   tick,
        "current_item_id":  item.get("id") if item else None,
    }
    c["active_process"] = process

    if item:
        _announce_item(c, world, item)

    return process


def _pick_news_item(world, avoid_id=None):
    pool = [n for n in world.get("news", [])[-10:] if n.get("id") != avoid_id]
    if not pool:
        # Nothing left once avoid_id is excluded (e.g. only 1 item total
        # exists) -- fall back to the unfiltered pool rather than reading
        # nothing.
        pool = world.get("news", [])[-10:]
    if not pool:
        return None
    return random.choice(pool)


def update_reading_process(c, world):
    """Called every CADENCE["reading"] ticks for every character (see
    sim_loop.py) -- no-ops immediately for anyone not currently reading,
    same guard shape as cooking_process.py::update_cooking_process."""
    process = c.get("active_process")
    if not process or process.get("type") != "reading_news":
        return False

    tick = world.get("tick", 0)
    elapsed = tick - process.get("last_pick_tick", tick)
    if elapsed < READING_PICK_INTERVAL_TICKS:
        return False

    item = _pick_news_item(world, avoid_id=process.get("current_item_id"))
    if not item:
        return False

    process["current_item_id"] = item["id"]
    process["last_pick_tick"] = tick

    _announce_item(c, world, item)
    return True


def _announce_item(c, world, item):
    """One news pick's worth of reaction: always a solo speech bubble of
    what's being read; if someone's nearby and off cooldown, also read it
    aloud and ask their opinion; that can further escalate into a real
    debate."""
    headline = item.get("headline") or "something in the news"

    from systems.incidental_speech import fire_incidental
    fire_incidental(c, "inform", f'"{headline}"', world)

    # Local import -- action_router.py doesn't import this module, so no
    # cycle, but matches this codebase's established convention of
    # function-scoped cross-system imports rather than module-level ones.
    from systems.action_router import _co_present_characters
    listeners = _co_present_characters(c, world)
    if not listeners:
        return

    from systems.incidental_speech import _on_cooldown, _mark_cooldown
    listener = next((l for l in listeners if not _on_cooldown(c, l["id"], world)), None)
    if not listener:
        return
    _mark_cooldown(c, listener["id"], world)

    fire_incidental(
        c, "inform", f'"{headline}" -- what do you think?', world,
        target_id=listener["id"],
    )

    if random.random() < DEBATE_TRIGGER_PROB:
        _spawn_debate(c, world, item, listeners)


def _spawn_debate(c, world, item, listeners):
    """Puts the reading item away and hands off to a real group
    conversation (brain/conversations.py's new multi-party support)
    seeded with the headline as topic. Every present listener becomes a
    genuine conversation participant, not just an independently-reacting
    bystander -- see the group-conversations round for why this is safe
    now (add_message/tone/dynamics/observations/reflections already
    generalize to N participants)."""
    participant_ids = [c["id"]] + [l["id"] for l in listeners[:MAX_DEBATE_PARTICIPANTS - 1]]

    put_away_reading_item(c, world)
    c["active_process"] = None
    c["activity"] = None

    headline = item.get("headline") or "something in the news"

    from systems.action_router import apply_speech_to_group
    apply_speech_to_group(c, world, {
        "utterance":         f'"{headline}" -- honestly, I have thoughts on this.',
        "speech_act":        "argue",
        "topic":             headline,
        "conversation_type": "argument",
    }, participant_ids)

    from brain.cognition_scheduler import wake_character
    wake_character(c, world, "debate_started")


def put_away_reading_item(c, world):
    """Bespoke and simple -- reuses the existing, working place_item()
    directly and a small memory field on the character, deliberately NOT
    the broken retrieve_item/return_item/search_room system
    (activities.py's dispatch to those hits a NameError, a real
    pre-existing bug independent of this feature -- see the plan). Called
    from both natural activity completion (activities.py::finish_activity)
    and the debate-interrupt path above. Phones are never dropped here --
    phone.py's own independent set-down/forget logic already covers
    phones on its own per-tick chance."""
    process = c.get("active_process") or {}
    if process.get("medium") != "paper":
        return

    from systems.personal_items import get_item_by_template, place_item
    item = get_item_by_template(c, "newspaper")
    if not item:
        return

    placed = place_item(c, item["id"], c.get("x", 0), c.get("y", 0), world)
    if placed:
        c["_last_reading_spot"] = {
            "item_id": placed["id"],
            "x":       placed["x"],
            "y":       placed["y"],
            "tick":    world.get("tick", 0),
        }
