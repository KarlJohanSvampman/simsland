"""
cpl/adapters/line_effects.py -- what a line does once it reaches its listener: the per-line side effects that used to
sit at the end of systems/action_router.py::apply_speech, moved here unchanged (docs/cpl_implementation_plan.md C12)
and registered, in their original order, as subscribers to a delivered line (cpl/adapters/events.py).
"""

import random  # noqa: F401 -- reflections are scheduled at a random delay, from the shared random stream

from core.event_bus import emit  # noqa: F401
from cpl.adapters.events import on_delivered


@on_delivered
def subject_and_social_line(world, d):
    c = d["speaker"]
    conv = d["conv"]
    utterance = d["utterance"]
    speech_act = d["speech_act"]
    topic = d["topic"]
    tick = d["tick"]
    speech = d["speech"]
    target_id = d["target_id"]
    # What it's about (kept on the conversation so nobody loses the thread), and what the line does socially
    # (social/discourse.py: applied on the main thread).
    from brain.conversations import set_subject
    _social = speech.get("social") if isinstance(speech.get("social"), dict) else {}
    set_subject(conv, _social.get("issue") or speech.get("subject") or topic, by=c["id"])
    emit("social_line", {"conversation_id": conv.get("id"), "speaker_id": c["id"], "target_id": target_id,
                         "utterance": utterance, "speech_act": speech_act, "social": _social, "tick": tick,
                         "listeners": [p.get("id") for p in (c.get("perception") or {}).get("visible_people", [])]})


@on_delivered
def pattern_concern(world, d):
    c = d["speaker"]
    listener = d["listener"]
    # Someone who has been worried about this person is raising it now.
    from systems.pattern_concern import on_speech as _concern_on_speech
    _concern_on_speech(c, listener, world)


@on_delivered
def impact_ledger(world, d):
    c = d["speaker"]
    conv = d["conv"]
    utterance = d["utterance"]
    speech_act = d["speech_act"]
    medium = d["medium"]
    volume = d["volume"]
    speech = d["speech"]
    target_id = d["target_id"]
    # What the line MEANT (insult, apology, compliment, lie, ...) -> the
    # relationship-impact ledger. Emit-only from this worker thread; see
    # systems/relationship_ledger.py.
    from systems.impact_kinds import kind_for_speech
    _impact_kind = kind_for_speech(speech_act, speech.get("intent"))
    if _impact_kind:
        from systems.relationship_ledger import emit_impact
        emit_impact(
            c, _impact_kind, target_id=target_id, channel="speech" if medium == "in_person" else medium,
            audience="hearing" if medium == "in_person" else "targets", volume=volume,
            text=utterance, ref={"type": "conversation", "id": conv.get("id"),
                                 "line": len(conv.get("history", [])) - 1},
            intent=speech.get("intent"),
        )


@on_delivered
def memory_acknowledgement(world, d):
    c = d["speaker"]
    listener = d["listener"]
    conv = d["conv"]
    utterance = d["utterance"]
    medium = d["medium"]
    volume = d["volume"]
    speech = d["speech"]
    # A line that draws on something the speaker remembers about the listener ("I remember you"): the ids the model
    # listed are checked, and what holds up is a personal acknowledgement (systems/memory_acknowledgement.py).
    if speech.get("uses_memories"):
        try:
            from systems.memory_acknowledgement import acknowledge
            acknowledge(c, listener, speech["uses_memories"], utterance, world, intent=speech.get("intent"),
                        channel="speech" if medium == "in_person" else medium,
                        audience="hearing" if medium == "in_person" else "targets", volume=volume,
                        ref={"type": "conversation", "id": conv.get("id"), "line": len(conv.get("history", [])) - 1})
        except Exception as _exc:
            print(f"[memory_acknowledgement] could not record an acknowledgement: {_exc!r}")


@on_delivered
def dialogue_memory(world, d):
    c = d["speaker"]
    listener = d["listener"]
    utterance = d["utterance"]
    speech_act = d["speech_act"]
    conversation_type = d.get("conversation_type")
    # What the line said ABOUT someone who isn't part of this conversation (gossip, praise, a lie about them) is read
    # from the whole conversation once it ends (social/discourse.py -> social/rumours.py), not guessed per line.


    # Per the user's explicit ask: commit every spoken exchange to
    # real memory, both what was said and what was heard, keyword-
    # tagged so it's searchable later.
    from systems.dialogue_memory import remember_dialogue
    remember_dialogue(c, listener, utterance, world,
                       speech_act=speech_act, conversation_type=conversation_type)


@on_delivered
def reaction_and_interaction(world, d):
    c = d["speaker"]
    listener = d["listener"]
    speech_act = d["speech_act"]
    tick = d["tick"]
    from systems.reactions import push_conversation_reaction
    from brain.relationships import apply_interaction
    from systems.action_router import _maybe_trigger_jealousy
    push_conversation_reaction(listener, speech_act, tick)

    apply_interaction(c, listener, speech_act)
    if speech_act == "flirt":
        _maybe_trigger_jealousy(c, listener, world)


@on_delivered
def analysis_and_reflections(world, d):
    c = d["speaker"]
    listener = d["listener"]
    conv = d["conv"]
    utterance = d["utterance"]
    speech_act = d["speech_act"]
    topic = d["topic"]
    tick = d["tick"]
    target_id = d["target_id"]
    from systems.conversation_analysis import analyze_message, should_schedule_reflection
    from systems.conversation_goals import check_goal_trending
    result = analyze_message(world, conv, c, listener, utterance, speech_act)

    # Is this trending toward the LISTENER's own goal for talking to
    # c? A sustained "no" from a not_interested participant retires
    # the conversation for them without spending a real LLM turn on
    # it -- see conversation_goals.py::check_goal_trending.
    check_goal_trending(conv, listener, topic or conv.get("topic", "general"))

    if should_schedule_reflection(result):
        listener.setdefault("pending_reflections", []).append({
            "type":           "conversation",
            "target_id":      c["id"],
            "reason":         speech_act,
            "scheduled_tick": tick + random.randint(50, 300),
            "observations":   result.get("observations", []),
        })

    # A real (non-generic) topic surfaced and the listener has no
    # opinion on it yet -- schedule an automatic, spontaneous
    # opinion-forming reflection (systems/reflection.py's
    # "form_opinion" kind), independent of the relationship-
    # significance gate above. See brain/opinions.py.
    topic_str = topic or conv.get("topic", "general")
    if topic_str not in ("general", "incidental") and topic_str not in listener.get("opinions", {}):
        listener.setdefault("pending_reflections", []).append({
            "type":           "form_opinion",
            "topic":          topic_str,
            "reason":         f"{c.get('name', 'Someone')} brought this up in conversation.",
            "scheduled_tick": tick + random.randint(20, 120),
        })
