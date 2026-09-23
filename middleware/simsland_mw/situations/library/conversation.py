"""
Conversation conflict situations.

Evaluated against a ChatGPT-authored Conversation/Discussion/Argument/
Escalation specification (~25 new dataclasses: Conversation, ConversationTurn,
EscalationLevel, ArgumentState, ConversationAnalyzer, ...) against what's
actually here first. Much of its *substance* already exists, just shaped
differently: backend/brain/conversations.py's real Conversation dict already
tracks tension/comfort/awkwardness/emotional_charge and blends tone
(update_conversation_tone) incrementally per speech_act exactly like the
spec's own "escalation should be incremental" principle (its section 25) --
and systems/target_reactions.py's flag_provocation() already simulates a
trait-weighted emotional reaction and wakes the target reactively for
insult/guilt_trip/threaten/punch/... existed before this file, just with no
situation built on top of that wake yet.

What did NOT hold up under inspection, first pass: the spec's own worked
examples (conversation.accusation, conversation.threat) assumed an "accuse"
speech act and a conversational "threat" existed as real, LLM-selectable
moves. Checked brain/llm_brain.py's actual SYSTEM_PROMPT -- the real,
complete speech_act vocabulary the LLM was ever told about didn't include
either; both existed only inside one dead tone-blending set in
conversations.py, never reachable by the model. "accuse" has since been
made real (backend/brain/llm_brain.py's prompt, systems/target_reactions.py's
REACTION_WEIGHTS, brain/conversations.py's apply_conversation_dynamics) --
conversation.accusation below is the situation built on top of that.
"threat" (as a SPEECH act, distinct from hostile_actions.py's physical/
verbal "threaten" ACTION) is still real follow-up work, not done here.
"""

from __future__ import annotations

from ..definition import OptionSeed as O, SituationContext, SituationDefinition as S, Trigger as T
from ._helpers import act, speak_to

MINUTE = 60


# ---- conversation.insult ------------------------------------------------------
# systems/target_reactions.py::flag_provocation wakes the target with reason
# "provoked" for punch/kick/shove/threaten/grab_offensive/hold/wrestle/insult/
# guilt_trip/compliment/flirt/joke/brag alike -- this situation only fires for
# the "insult" case; the others (a punch, a compliment, a joke) read as a
# completely different kind of moment and deserve their own situations rather
# than one that tries to cover all of them with compromise options.

def _insulter(ctx: SituationContext):
    pid = ctx.wake_payload.get("actor_id")
    return pid if pid and ctx.person(pid) else None


INSULT = S(
    id="conversation.insult", category="conversation", priority=75, cooldown_ticks=5 * MINUTE,
    triggers=(T("event", event="provoked",
                when=lambda c: c.wake_payload.get("provocation_type") == "insult" and _insulter(c) is not None,
                key=lambda c: c.wake_payload.get("actor_id") or ""),),
    required_data=("environment.nearby_characters", "character.relationships",
                   "environment.available_interactions"),
    describe=lambda c: (f"{c.name(_insulter(c))} just insulted you. "
                        f"{c.wake_payload.get('reaction_hint', '')}").strip(),
    options=(
        O("ignore_the_insult", "Ignore it and let it go.", noop=True),
        O("challenge_them", "Challenge what they just said.",
          action=lambda c: speak_to(c, _insulter(c)), speaks=True, speech_act="challenge",
          default_line=lambda c: "Excuse me?"),
        O("insult_them_back", "Insult them right back.",
          action=lambda c: speak_to(c, _insulter(c)), speaks=True, speech_act="insult",
          default_line=lambda c: "Real mature."),
        O("ask_why_theyre_being_like_this", "Ask why they're being like this.",
          action=lambda c: speak_to(c, _insulter(c)), speaks=True, speech_act="ask",
          default_line=lambda c: "What's that supposed to mean?"),
        O("try_to_calm_things_down", "Try to calm things down instead of escalating.",
          action=lambda c: speak_to(c, _insulter(c)), speaks=True, speech_act="comfort",
          default_line=lambda c: "Let's not do this right now."),
        O("walk_away", "End it there and walk away.", action=lambda c: act(c, "leave_conversation")),
    ),
    notes="walk_away resolves to a real leave_conversation action (systems/action_router.py's "
          "_route_leave_conversation) -- ends the active conversation for real; doesn't also generate "
          "a walk-to-some-tile movement, since no existing pathfinding utility picks an arbitrary "
          "destination and the real substance of 'walking away' from an argument is ending it.",
)


# ---- conversation.accusation --------------------------------------------------
# Same flag_provocation("provoked") wake as INSULT above, filtered to
# provocation_type=="accuse". Every option below needs its own DISTINCT
# speech_act (not just a distinct description) -- speak_to() always returns
# the same {"type": "speak", "target": pid} outcome regardless of what's
# actually being said, so speech_act is the only thing telling two options
# aimed at the same person apart (see situations/registry.py's compile(),
# fixed alongside this file to fold speech_act into its dedup signature).

def _accuser(ctx: SituationContext):
    pid = ctx.wake_payload.get("actor_id")
    return pid if pid and ctx.person(pid) else None


ACCUSATION = S(
    id="conversation.accusation", category="conversation", priority=78, cooldown_ticks=5 * MINUTE,
    triggers=(T("event", event="provoked",
                when=lambda c: c.wake_payload.get("provocation_type") == "accuse" and _accuser(c) is not None,
                key=lambda c: c.wake_payload.get("actor_id") or ""),),
    required_data=("environment.nearby_characters", "character.relationships",
                   "environment.available_interactions"),
    describe=lambda c: (f"{c.name(_accuser(c))} just accused you of something. "
                        f"{c.wake_payload.get('reaction_hint', '')}").strip(),
    options=(
        O("deny_it", "Deny it.",
          action=lambda c: speak_to(c, _accuser(c)), speaks=True, speech_act="dismissive",
          default_line=lambda c: "That's not true."),
        O("explain_what_happened", "Explain your side of what actually happened.",
          action=lambda c: speak_to(c, _accuser(c)), speaks=True, speech_act="declare",
          default_line=lambda c: "Let me explain what actually happened."),
        O("ask_why_they_think_that", "Ask what makes them think that.",
          action=lambda c: speak_to(c, _accuser(c)), speaks=True, speech_act="ask",
          default_line=lambda c: "What makes you think that?"),
        O("admit_it", "Admit it.",
          action=lambda c: speak_to(c, _accuser(c)), speaks=True, speech_act="confession",
          default_line=lambda c: "...Okay, you're right. I did."),
        O("get_defensive", "Get defensive and push back hard.",
          action=lambda c: speak_to(c, _accuser(c)), speaks=True, speech_act="challenge",
          default_line=lambda c: "How dare you accuse me of that."),
        O("walk_away", "End it there and walk away.", action=lambda c: act(c, "leave_conversation")),
    ),
    notes="admit_it is offered unconditionally -- whether it's actually TRUE that the character did "
          "whatever they're accused of isn't something this seed has (or should have) access to; "
          "that's the character's own private knowledge, and the LLM is the one who knows whether "
          "the admission is honest or a false confession. walk_away is the same real leave_conversation "
          "action as conversation.insult's.",
)


CONVERSATION = (INSULT, ACCUSATION)
