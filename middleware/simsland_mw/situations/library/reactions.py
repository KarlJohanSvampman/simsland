"""
Reaction-based situations: real wake events Simsland already fires
(door_signal, noticed_commotion, post_about_self) that had no matching
SituationDefinition before this -- a character who received one of these
wakes just fell through to the generic rule-based menu, with no framing
of what actually just happened.

Evaluated against a ChatGPT-authored WorldEvent/Perception specification
proposing a full new dataclass-and-provider layer for this; adopted the
*behavior* (a real, scored situation the moment something happens, rather
than only ever reacting via the generic menu) using this codebase's own
existing SituationDefinition/Trigger/OptionSeed shape instead of building
a second, parallel architecture next to the one already here -- the
information-boundary concern that spec's Perception/WorldEvent split is
really protecting (a character should never receive information they
have no legitimate way to know) is already handled by
narrative/perception.py's sanitize_person()/FORBIDDEN_OTHER_KEYS
whitelist, which these situations also respect: nothing here ever reads
another character's private state, only what Simsland already put on
the wake_payload for the character who was actually woken.
"""

from __future__ import annotations

from typing import Optional

from ..definition import OptionSeed as O, SituationContext, SituationDefinition as S, Trigger as T
from ._helpers import act, first_adult, speak_to

HOUR = 3600


# ---- communication.door_signal ----------------------------------------------
# systems/doorbell.py::resolve_door_signal wakes every occupant who heard the
# bell/knock with {"visitor_name": ...} -- nothing else has happened yet, the
# visitor is just waiting outside.

DOOR_SIGNAL = S(
    id="communication.door_signal", category="communication", priority=65, cooldown_ticks=120,
    triggers=(T("event", event="door_signal",
                key=lambda c: c.wake_payload.get("visitor_name") or ""),),
    required_data=("environment.available_interactions",),
    describe=lambda c: f"There's someone at the door -- {c.wake_payload.get('visitor_name', 'someone')} is waiting outside.",
    options=(
        O("go_answer_the_door", "Go answer the door.", gap="answer_door"),
        O("unlock_the_door_first", "Unlock the door so they can let themselves in.",
          action=lambda c: act(c, "unlock_door")),
        O("call_out_that_youre_coming", "Call out that you're coming.", gap="call_out_generic"),
        O("ignore_it", "Ignore it and carry on with what you were doing.", noop=True),
    ),
    notes="go_answer_the_door/call_out_that_youre_coming need a generic no-target-required "
          "backend capability (open the door for a waiting visitor; shout something with no "
          "specific listener) that doesn't exist yet -- see capability_report(). "
          "unlock_the_door_first is real today but only actually helps if the door was locked.",
    min_options=1,   # same reasoning as cognition.quiet_moment: "ignore it" alone is a
                     # legitimate, presentable choice, and how many of the other options
                     # resolve depends entirely on door-lock state.
)


# ---- reaction.commotion -------------------------------------------------------
# systems/curiosity.py already autonomously starts walking the character
# toward whatever they noticed *before* waking them with {"summary": ...} --
# by the time this situation fires, "go investigate" is already in progress.
# The real remaining choice is whether to keep at it, call out, or let it go.

COMMOTION = S(
    id="reaction.commotion", category="reaction", priority=60, cooldown_ticks=10 * 60,
    triggers=(T("event", event="noticed_commotion",
                key=lambda c: c.wake_payload.get("summary") or ""),),
    required_data=("environment.nearby_characters", "character.relationships",
                   "environment.available_interactions"),
    describe=lambda c: c.wake_payload.get("summary") or "Something just caught your attention.",
    dynamic_options=lambda c: (
        (O("call_out_to_check", "Call out to see if everyone's alright.",
           action=lambda c: speak_to(c, first_adult(c)), speaks=True, speech_act="ask",
           default_line=lambda c: "Hey, is everything okay over there?"),)
        if first_adult(c) else ()
    ),
    options=(
        O("keep_investigating", "Keep heading over to see what happened.", noop=True),
        O("let_it_go", "Decide it's probably nothing and get back to what you were doing.",
          gap="abandon_investigation"),
    ),
    notes="let_it_go names a real gap: systems/curiosity.py has no way to cancel an in-progress "
          "investigation from the middleware side yet -- picking any other real action still "
          "redirects the character away from it in practice, this option just has no dedicated "
          "backend hook of its own to point at.",
    min_options=1,   # "keep_investigating" alone must still be enough to fire -- with no one
                     # else around to call out to, this would otherwise silently never surface
                     # and the character would fall through to the generic menu instead, with no
                     # framing at all for what they're already walking toward.
)


# ---- social_media.post_about_self --------------------------------------------
# systems/social_media.py::create_post wakes every character named in a post's
# text (or tagged as a photo subject) with {"author_name", "author_id",
# "post_id"} -- per that module's own docstring, seeing the post is not the
# same as knowing whether it's true; this situation only ever offers finding
# out more or reacting to the fact that it exists, never states its content
# as settled fact.

POST_ABOUT_SELF = S(
    id="social_media.post_about_self", category="social_media", priority=55, cooldown_ticks=45 * 60,
    triggers=(T("event", event="post_about_self",
                key=lambda c: c.wake_payload.get("post_id") or c.wake_payload.get("author_id") or ""),),
    required_data=("character.relationships", "environment.available_interactions"),
    describe=lambda c: (f"You come across a social media post from "
                        f"{c.wake_payload.get('author_name', 'someone')} that mentions you."),
    options=(
        O("read_it_properly", "Stop and read the post properly.",
          action=lambda c: act(c, "computer_social_media")),
        O("message_them_about_it", "Message them about it.", gap="remote_text_reply_with_llm_content"),
        O("comment_publicly", "Reply to it publicly.", gap="comment_on_social_post_by_content"),
        O("ignore_it", "Ignore it and move on.", noop=True),
    ),
    notes="Two real gaps, not one: (1) decisions/executor.py's build_decision() only ever "
          "substitutes the model's own words into an outcome of type=='speak' -- a text message "
          "to someone who isn't physically nearby (speak_to() requires dc.people, i.e. co-presence) "
          "has nowhere for real LLM-composed content to land yet. (2) comment_publicly needs the "
          "post's own text, which this seed deliberately doesn't have access to (wake_payload only "
          "ever carries author_name/author_id/post_id, per this module's own knowledge-boundary "
          "docstring) -- a real fix threads post_id through to a dedicated comment-composing step.",
    min_options=1,   # "ignore_it" alone is a legitimate, presentable choice -- see
                     # communication.door_signal's identical reasoning above.
)


# ---- social_media.rumor_about_self ---------------------------------------
# Same wake site as POST_ABOUT_SELF (systems/social_media.py::
# _notify_mentioned_characters) but only when the post carries "rumor" in
# its tags -- a genuinely different situation from an ordinary mention:
# higher priority (this is actively about your reputation, not just
# "someone brought you up"), and the real options are about managing an
# unverified claim rather than just reading/replying to an ordinary post.
# Per the belief/opinion spec's own point about this seed (a manipulative/
# ambitious character might want to use a rumor rather than fight it):
# that's left to the LLM's own judgment via what it actually writes, not
# forced by a dedicated "use_rumor" option with no mechanical backend
# effect of its own -- ignore_it already covers "don't fight it."

RUMOR_ABOUT_SELF = S(
    id="social_media.rumor_about_self", category="social_media", priority=75, cooldown_ticks=45 * 60,
    triggers=(T("event", event="rumor_about_self",
                key=lambda c: c.wake_payload.get("post_id") or c.wake_payload.get("author_id") or ""),),
    required_data=("character.relationships", "environment.available_interactions"),
    describe=lambda c: (f"People online are spreading something about you, posted by "
                        f"{c.wake_payload.get('author_name', 'someone')}. You don't know "
                        f"how far it's already gone."),
    dynamic_options=lambda c: (
        (O("confront_them_directly", "Confront them about it directly.",
           action=lambda c: speak_to(c, c.wake_payload.get("author_id")),
           speaks=True, speech_act="accuse",
           default_line=lambda c: "Did you seriously post that about me?"),)
        if c.person(c.wake_payload.get("author_id")) else ()
    ),
    options=(
        O("deny_it_publicly", "Post a public denial.", action=lambda c: act(c, "post_social_media")),
        O("explain_what_happened", "Post your own account of what actually happened.",
          action=lambda c: act(c, "post_social_media")),
        O("message_them_privately", "Message them about it privately.",
          gap="remote_text_reply_with_llm_content"),
        O("ignore_it", "Ignore it and hope it blows over.", noop=True),
    ),
    notes="deny_it_publicly/explain_what_happened both resolve to the same real post_social_media "
          "action -- the difference is purely in what the LLM actually writes, which the middleware "
          "has no way to distinguish after the fact (same shape as POST_ABOUT_SELF's comment_publicly "
          "gap note: there's no dedicated 'reply to THIS post' capability yet, just 'make a new "
          "post'). confront_them_directly only appears when the poster happens to already be "
          "co-present.",
    min_options=1,
)


# ---- social_media.rumor_seen -----------------------------------------------
# Fired for an OBSERVER (not the rumor's subject, not its author) -- see
# systems/social_media.py::view_post's _apply_rumor_exposure, called when a
# character views a post tagged "rumor". That same call already nudges the
# observer's own person:<subject_id> opinion (brain/opinions.py) -- the real
# belief effect happens there, passively, regardless of whether this
# situation gets selected at all. This situation is the deliberate choice
# layered on top: does the character actually DO anything about what they
# just passively absorbed.

RUMOR_SEEN = S(
    id="social_media.rumor_seen", category="social_media", priority=45, cooldown_ticks=30 * 60,
    triggers=(T("event", event="rumor_seen",
                key=lambda c: c.wake_payload.get("post_id") or ""),),
    required_data=("character.relationships", "environment.available_interactions"),
    describe=lambda c: (f"You see people online discussing something about "
                        f"{c.wake_payload.get('subject_name', 'someone')}."),
    dynamic_options=lambda c: (
        (O("ask_them_directly", "Ask them directly about it.",
           action=lambda c: speak_to(c, c.wake_payload.get("subject_id")),
           speaks=True, speech_act="ask",
           default_line=lambda c: "Hey, is it true what people are saying about you online?"),)
        if c.person(c.wake_payload.get("subject_id")) else ()
    ),
    options=(
        O("share_it", "Pass the information along.", action=lambda c: act(c, "post_social_media")),
        O("defend_them", "Speak up for them publicly.", action=lambda c: act(c, "post_social_media")),
        O("investigate", "Try to find out whether it's actually true.", gap="investigate_claim"),
        O("ignore_it", "Don't get involved.", noop=True),
    ),
    notes="investigate has no dedicated backend capability yet (a real fact-finding action distinct "
          "from just asking the subject, which ask_them_directly already covers when they're "
          "co-present) -- gapped rather than faked.",
    min_options=1,
)


REACTIONS = (DOOR_SIGNAL, COMMOTION, POST_ABOUT_SELF, RUMOR_ABOUT_SELF, RUMOR_SEEN)
