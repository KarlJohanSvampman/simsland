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


REACTIONS = (DOOR_SIGNAL, COMMOTION, POST_ABOUT_SELF)
