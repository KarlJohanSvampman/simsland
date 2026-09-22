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

What did NOT hold up under inspection: the spec's own worked examples
(conversation.accusation, conversation.threat) assume an "accuse" speech act
and a conversational "threat" exist as real, LLM-selectable moves. Checked
brain/llm_brain.py's actual SYSTEM_PROMPT -- the real, complete speech_act
vocabulary the LLM is ever told about is compliment/flirt/insult/challenge/
vulnerable/confession/apology/supportive/dismissive/gossip/brag/lie/
awkward_silence/joke/guilt_trip/comfort/question/smalltalk/urgent_report/
greet/ask/declare/argue/whisper. "accuse" and "threat" (as a SPEECH act,
distinct from hostile_actions.py's physical/verbal "threaten" ACTION) exist
only inside one dead tone-blending set in conversations.py, never reachable
by the model. Scoped this file to conversation.insult -- the one worked
example that's actually fully real end to end -- rather than building
situations around moves nothing can currently trigger; accusation/threat are
real, valuable follow-ups but need their own backend speech-act work first
(see this module's own notes on that).
"""

from __future__ import annotations

from ..definition import OptionSeed as O, SituationContext, SituationDefinition as S, Trigger as T
from ._helpers import speak_to

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
        O("walk_away", "End it there and walk away.", gap="leave_conversation_deliberately"),
    ),
    notes="walk_away names a real gap: there's no backend action yet for deliberately disengaging "
          "from an active conversation independent of a normal move-elsewhere destination -- picking "
          "any of the real speak options above at least keeps the character in control of how this "
          "goes, which is why it isn't the only option here despite the gap.",
)


CONVERSATION = (INSULT,)
