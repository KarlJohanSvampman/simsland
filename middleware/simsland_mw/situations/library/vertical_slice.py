"""
The first seven situations (spec section 12). Deliberately small: enough to
exercise every trigger type, dynamic data, speech, no-op options and capability
gaps end to end before the rest of the catalogue is written.

Option coverage rule: every option maps to a real Simsland action, is a
deliberate no-op, or names the missing capability in `gap=`.
"""

from __future__ import annotations

from typing import Optional

from ..definition import OptionSeed as O, SituationContext, SituationDefinition as S, Trigger as T
from ._helpers import act, first_adult, interact, prop_action, socialize_with, speak_to

HOUR = 3600


# ---- need.hunger.noticeable -------------------------------------------------
def _hunger_text(ctx: SituationContext) -> str:
    h = ctx.get("character.needs.body.hunger", 0)
    lead = "Your stomach is growling" if h >= 75 else "You realise you're getting hungry"
    return f"{lead}. It's {ctx.get('environment.current.time_of_day') or 'a while'} and you haven't eaten in a while."


HUNGER = S(
    id="need.hunger.noticeable", category="physical_need", priority=60, cooldown_ticks=HOUR,
    triggers=(T("threshold_crossed", field="character.needs.body.hunger", threshold=50),),
    required_data=("character.needs", "environment.current", "environment.nearby_props",
                   "environment.available_interactions"),
    describe=_hunger_text,
    options=(
        O("eat_something_at_home", "Look through the refrigerator and find something to eat.",
          action=lambda c: interact(c, "food")),
        O("cook_a_proper_meal", "Take the time to cook a proper meal.",
          action=lambda c: interact(c, "cook"), min_age=14),
        O("order_food_delivery", "Order food to be delivered.", gap="food_delivery"),
        O("buy_food_out", "Head out and buy something to eat.", gap="food_purchase"),
        O("keep_going_for_now", "Ignore it for now and carry on with what you were doing.", noop=True),
    ),
)


# ---- need.energy.tired ------------------------------------------------------
TIRED = S(
    id="need.energy.tired", category="physical_need", priority=60, cooldown_ticks=HOUR,
    triggers=(T("threshold_crossed", field="character.needs.body.fatigue", threshold=60),),
    required_data=("character.needs", "environment.current", "environment.nearby_props",
                   "environment.available_interactions"),
    describe=lambda c: f"You're worn out. It's {c.get('environment.current.time_of_day') or 'late'} "
                       "and your body wants to stop.",
    options=(
        O("lie_down_and_sleep", "Lie down and go to sleep.", action=lambda c: prop_action(c, "sleep", "sleep")),
        O("sit_and_rest_a_while", "Sit down and rest for a bit without going to bed.",
          action=lambda c: prop_action(c, "sit_down", "seat")),
        O("make_coffee", "Make a coffee to get through it.", action=lambda c: interact(c, "coffee"),
          min_age=13),
        O("push_through_tiredness", "Push through it and keep going.", noop=True),
    ),
)


# ---- social.character_approaches -------------------------------------------
def _approacher(ctx: SituationContext) -> Optional[str]:
    pid = ctx.wake_payload.get("subject_id")
    return pid if pid and ctx.person(pid) else None


def _approach_text(ctx: SituationContext) -> str:
    pid = _approacher(ctx)
    rel = ctx.dc.relationships.get(pid or "") or {}
    if not rel:
        how = "someone you don't really know"
    elif (rel.get("friendship") or 0) >= 50:
        how = "someone you know well"
    else:
        how = "someone you know"
    return f"{ctx.name(pid)}, {how}, has come over toward you."


APPROACH = S(
    id="social.character_approaches", category="social", priority=70, cooldown_ticks=600,
    triggers=(T("event", event="person_entered_view", when=lambda c: _approacher(c) is not None,
                key=lambda c: c.wake_payload.get("subject_id") or ""),),
    required_data=("environment.nearby_characters", "character.relationships",
                   "environment.available_interactions"),
    describe=_approach_text,
    options=(
        O("greet_them", "Greet them.", action=lambda c: speak_to(c, _approacher(c)),
          speaks=True, speech_act="greet", default_line=lambda c: f"Hi, {c.name(_approacher(c))}."),
        O("ask_how_they_are", "Ask how they are.", action=lambda c: speak_to(c, _approacher(c)),
          speaks=True, speech_act="ask",
          default_line=lambda c: f"Hey {c.name(_approacher(c))}, how are you doing?"),
        O("stop_and_chat", "Stop what you're doing and chat.",
          action=lambda c: socialize_with(c, _approacher(c))),
        O("give_a_small_nod", "Give them a small nod and carry on.", noop=True),
        O("avoid_them", "Find a reason to avoid them.", gap="avoid_character"),
    ),
)


# ---- conversation.question --------------------------------------------------
def _asker(ctx: SituationContext) -> Optional[str]:
    pid = ctx.wake_payload.get("speaker_id")
    return pid if pid and ctx.person(pid) else None


def _is_question(ctx: SituationContext) -> bool:
    return "?" in (ctx.wake_payload.get("utterance") or "") and _asker(ctx) is not None


QUESTION = S(
    id="conversation.question", category="conversation", priority=80, cooldown_ticks=60,
    triggers=(T("event", event="heard_speech", when=_is_question,
                key=lambda c: (c.wake_payload.get("speaker_id") or "")
                + (c.wake_payload.get("utterance") or "")[:40]),),
    required_data=("environment.nearby_characters", "character.relationships",
                   "environment.available_interactions"),
    describe=lambda c: f"{c.name(_asker(c))} just asked you: \"{c.wake_payload.get('utterance')}\"",
    options=(
        O("answer_honestly", "Answer honestly, in your own words.",
          action=lambda c: speak_to(c, _asker(c)), speaks=True, speech_act="answer",
          default_line=lambda c: "Honestly, I'm not sure how to put it."),
        O("ask_what_they_mean", "Ask what they mean by that.",
          action=lambda c: speak_to(c, _asker(c)), speaks=True, speech_act="ask",
          default_line=lambda c: "What do you mean by that?"),
        O("deflect_the_question", "Deflect and change the subject.",
          action=lambda c: speak_to(c, _asker(c)), speaks=True, speech_act="deflect",
          default_line=lambda c: "Let's talk about that later."),
        O("decline_to_answer", "Politely decline to answer.",
          action=lambda c: speak_to(c, _asker(c)), speaks=True, speech_act="decline",
          default_line=lambda c: "I'd rather not get into that right now."),
        O("pretend_not_to_hear", "Pretend you didn't hear.", noop=True),
    ),
)


# ---- environment.messy_room -------------------------------------------------
MESSY = S(
    id="environment.messy_room", category="environment", priority=30, cooldown_ticks=2 * HOUR,
    triggers=(T("condition", condition="environment.room.cleanliness < 40",
                key=lambda c: c.get("environment.room.room_id") or ""),),
    required_data=("environment.room", "environment.available_interactions"),
    describe=lambda c: ("This room is a real mess." if c.get("environment.room.cleanliness", 100) < 20
                        else "This room has got untidy."),
    options=(
        O("sweep_and_scrub_the_floor", "Sweep and scrub the floor.", action=lambda c: act(c, "clean_floors")),
        O("dust_and_wipe_surfaces", "Dust and wipe down the surfaces.",
          action=lambda c: act(c, "dust_and_wipe")),
        O("ask_someone_to_help_tidy", "Ask someone nearby to help tidy up.",
          action=lambda c: speak_to(c, first_adult(c)), speaks=True, speech_act="request",
          default_line=lambda c: f"{c.name(first_adult(c))}, this place is a mess -- "
                                 "could you give me a hand tidying?"),
        O("leave_it_for_now", "Leave it; you'll deal with it later.", noop=True),
        O("get_out_of_the_room", "Leave the mess behind and go somewhere else.", gap="room_navigation"),
    ),
)


# ---- expectation.put_off_task ----------------------------------------------
CHORE_ACTIONS = {"floor": "clean_floors", "vacuum": "clean_floors", "dust": "dust_and_wipe",
                 "dish": "wash_dishes", "plant": "water_plants"}


def _put_off(ctx: SituationContext) -> Optional[dict]:
    """An expectation that is running out of time (or has already slipped a
    little) but hasn't yet produced the frustration that sends people to
    confront each other."""
    for e in ctx.get("character.expectations", []) or []:
        if e.get("satisfied"):
            continue
        end = e.get("window_end_tick")
        closing = e["status"] == "pending" and end is not None and 0 <= end - ctx.tick <= HOUR
        slipped = e["status"] == "missed" and e["frustration"] < 0.3
        if closing or slipped:
            return e
    return None


def _put_off_action(ctx: SituationContext):
    e = _put_off(ctx)
    if not e:
        return None
    for frag, action in CHORE_ACTIONS.items():
        if frag in e["id"]:
            return act(ctx, action)
    return None


PUT_OFF = S(
    id="expectation.put_off_task", category="expectation", priority=40, cooldown_ticks=2 * HOUR,
    triggers=(T("custom", when=lambda c: _put_off(c) is not None,
                key=lambda c: (_put_off(c) or {}).get("id", "")),),
    required_data=("character.expectations", "environment.current", "environment.available_interactions"),
    describe=lambda c: f"You keep meaning to get to \"{(_put_off(c) or {}).get('id', 'a task').replace('_', ' ')}\", "
                       "and it's still not done.",
    options=(
        O("do_it_now", "Stop putting it off and do it now.", action=_put_off_action),
        O("do_a_bit_of_it", "Do just a small part of it.", gap="partial_task_progress"),
        O("ask_for_a_hand", "Ask someone nearby to help you with it.",
          action=lambda c: speak_to(c, first_adult(c)), speaks=True, speech_act="request",
          default_line=lambda c: f"{c.name(first_adult(c))}, could you help me get this done?"),
        O("put_it_off_a_little_longer", "Put it off a little longer.", noop=True),
    ),
    notes="do_it_now resolves only for chores with a matching Simsland action; other expectations "
          "(groceries, school run) need an expectation->action mapping in the backend.",
)


# ---- cognition.quiet_moment -------------------------------------------------
def _examine_something(ctx: SituationContext):
    """Look closely at the nearest prop -- always with a target."""
    if not ctx.dc.allowed("examine"):
        return None
    for p in ctx.dc.props:
        if not any(t in p.get("template", "") for t in ("wall", "ceiling", "socket")):
            return {"type": "examine", "target": p["id"]}
    return None


def _chat_with_someone(ctx: SituationContext):
    others = [p for p in ctx.dc.people if p["id"] in ctx.dc.relationships]
    return socialize_with(ctx, others[0]["id"]) if others else None


QUIET = S(
    id="cognition.quiet_moment", category="cognition", priority=10, cooldown_ticks=HOUR // 2,
    triggers=(T("idle"),),
    required_data=("character.intentions", "environment.available_interactions",
                   "environment.nearby_props", "environment.nearby_characters",
                   "character.relationships"),
    describe=lambda c: "Nothing needs doing right now. You have a moment to yourself.",
    options=(
        O("look_around_the_place", "Take a look around.", action=lambda c: act(c, "look_around")),
        O("think_back_on_the_day", "Think back over recent events.", action=lambda c: act(c, "recall")),
        O("take_a_closer_look_at_something", "Take a closer look at something nearby.",
          action=_examine_something),
        O("use_the_computer", "Spend a little time on the computer.", action=lambda c: interact(c, "computer")),
        O("chat_with_someone_nearby", "Chat with someone nearby.", action=_chat_with_someone),
        O("write_in_the_diary", "Write in your diary.", action=lambda c: act(c, "write_diary")),
        O("read_the_news", "Catch up on the news.", action=lambda c: act(c, "browse_news"), min_age=12),
        O("practice_juggling", "Practise some juggling.", action=lambda c: act(c, "practice_juggling")),
        O("do_some_sit_ups", "Do a few sit-ups.", action=lambda c: act(c, "sit_ups")),
        O("sit_quietly", "Just be still for a while.", noop=True),
        O("pick_a_leisure_activity", "Pick something fun to do.", gap="leisure_activity_selection"),
    ),
    min_options=1,
)

VERTICAL_SLICE = (HUNGER, TIRED, APPROACH, QUESTION, MESSY, PUT_OFF, QUIET)
