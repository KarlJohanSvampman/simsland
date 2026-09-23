"""
Romance, dating & intimate-relationship situations.

Evaluated against a ChatGPT-authored "Romance, Dating & Intimate
Relationship Situation Library" spec (69 sections: attraction, crushes,
flirting, dating, relationship formation, exclusivity, affection,
confession of love, jealousy, insecurity, reassurance, adult
sexual-interest situations kept non-graphic/consent-centered, betrayal,
romantic conflict, breakup, reconciliation, moving in together,
long-term partnership, romantic triangles) against what's actually here
first -- and the finding this round was bigger than any previous spec
pass this session:

THE single most load-bearing gap: rel["labels"] -- the field ~15
existing, already-built modules (systems/absence_suspicion.py,
detective_work.py, secret_keeping.py, bedroom_assignment.py,
domestic_control.py, excuses.py, incidental_speech.py,
nudity_perception.py, sexual_release.py, crushes.py, attraction.py,
temporary_separation.py, action_router.py, offgrid.py, events.py, plus
context_builder.py's own LLM narration) all gate real "partner"/
"spouse" behavior on -- was, before this pass, populated NOWHERE in
live gameplay (confirmed by grep: the only writer anywhere in backend/
was api/social_sandbox.py, a test/debug scenario-staging endpoint).
Not even generation-time married NPCs had it (family.py wrote a
separate, disconnected rel["kinship"] field instead). Fixing that sync
(family.py::sync_kinship_to_relationships) and building the one live
mechanic that was completely missing -- how two characters actually
BECOME partners, or stop being partners, during gameplay
(systems/romance.py::become_partners()/break_up(), wired into
systems/proposals.py's existing generic negotiation engine as a new
kind="romantic") -- unlocks that entire pre-existing engine (jealousy,
suspicion, affairs, bedroom sharing, domestic authority, secret-keeping,
...) for real, for the first time, without a single new situation.

The situations below are the reactive layer built ON TOP of that now-
real foundation, same shape as every other spec this session:

  romance.romantic_proposal_received  -- someone asks you out / confesses
                                          feelings (systems/proposals.py's
                                          new kind="romantic", chore_id
                                          "ask_out"/"confess_love")
  romance.romantic_proposal_answered  -- you learn whether they said yes
  romance.partner_flirted_with_someone_else -- a real, live-witnessed
                                          jealousy trigger (a co-present
                                          partner sees a flirt happen --
                                          systems/action_router.py::
                                          _maybe_trigger_jealousy)
  romance.partner_broke_up_with_me    -- the other, unilateral, half of
                                          systems/romance.py::break_up()

SAFETY (spec section 3's own explicit requirement -- "never generate
sexual situations involving minors", adult-only): confirmed by the
survey that NOTHING in attraction.py/crushes.py/intimacy.py gated age
anywhere before this pass. The real backstop is placed at the one
choke point everything here funnels through -- systems/proposals.py::
propose_romantic() and systems/romance.py::become_partners() both
refuse outright unless both parties are 18+ -- rather than only at this
situation layer, which a future caller could bypass. min_age=18 is
still set on every option below too, defense in depth.

Deliberately NOT built this pass, named honestly rather than silently
skipped:
  - The INITIATING half (an LLM actually choosing to ask someone out).
    propose_romantic/_route_propose_romantic are real and callable, but
    context_builder.py doesn't offer propose_romantic to the LLM yet --
    agenda.py's existing "seek_romance" mapping still resolves to a
    plain socialize_with, not a real proposal. A reasonable next step,
    left out to keep this pass to the REACTIVE situations the rest of
    this session's spec revisits have covered.
  - Sexual-intimacy content: confirmed the deepest-of-all-gaps this
    round -- definitions.json's sexual_acts/positions_registry/
    kinks_registry are all genuinely EMPTY in the live data (not just
    unwired code), so systems/intimacy.py's stage-4-6 negotiation engine
    and systems/intercourse_session.py's whole phased scene engine are
    both real, correctly wired, and completely unreachable end-to-end
    today regardless of anything built this pass. Populating that
    content registry is a distinct, much larger undertaking than a
    reactive situation library and is left untouched, same as this
    session's "systems/waste.py's dead code, not fixed this pass"
    precedent for the household spec.
  - Marriage/engagement/divorce as a live mechanic -- break_up() only
    ever touches the "partner" label; a "spouse" pair (family.py
    generation-time, or a future propose-marriage upgrade of the same
    romantic proposal engine) has no live way to separate yet.
  - The "someone is flirting with YOUR partner" (as opposed to "your
    partner is flirting with someone") framing -- _maybe_trigger_jealousy
    only checks the flirter's own co-present partner; the symmetric case
    would need its own situation, not built this pass.
"""

from __future__ import annotations

from ..definition import OptionSeed as O, SituationContext, SituationDefinition as S, Trigger as T
from ._helpers import act, speak_to

MINUTE = 60
HOUR = 60 * MINUTE


def _other_age_ok(ctx: SituationContext, pid) -> bool:
    """A defense-in-depth check on the OTHER party's age -- the real
    backstop already lives in systems/proposals.py::propose_romantic()/
    systems/romance.py::become_partners(), which both refuse outright
    for anyone under 18, so a proposal or wake naming an underage other
    party shouldn't exist in the first place. Checked again here anyway
    rather than trusted blindly."""
    age = ctx.dc.relationships.get(pid, {}).get("age") if pid else None
    return age is not None and age >= 18


# ---- romance.romantic_proposal_received -------------------------------------
# systems/proposals.py's propose_romantic() wakes the recipient with the
# same generic "proposal_received" reason contract.proposal_received
# already handles (kind-agnostic) -- this situation just gives kind==
# "romantic" its own, emotionally distinct framing and outranks the
# generic one by priority whenever both are eligible.

def _proposer(ctx: SituationContext):
    pid = ctx.wake_payload.get("from_id")
    return pid if pid and ctx.person(pid) and _other_age_ok(ctx, pid) else None


def _is_confession(ctx: SituationContext) -> bool:
    return ctx.wake_payload.get("topic") == "confess_love"


def _proposal_id(ctx: SituationContext):
    return ctx.wake_payload.get("proposal_id")


ROMANTIC_PROPOSAL_RECEIVED = S(
    id="romance.romantic_proposal_received", category="romance", priority=68, cooldown_ticks=10 * MINUTE,
    triggers=(T("event", event="proposal_received",
                key=lambda c: c.wake_payload.get("proposal_id") or "",
                when=lambda c: c.wake_payload.get("kind") == "romantic"),),
    required_data=("environment.nearby_characters", "character.relationships"),
    describe=lambda c: (
        f"{c.wake_payload.get('from_name', 'Someone')} just told you they have feelings for you."
        if _is_confession(c) else
        f"{c.wake_payload.get('from_name', 'Someone')} just asked you out."
    ),
    dynamic_options=lambda c: (
        (
            O("accept_it", "Say yes.", min_age=18,
              action=lambda c: act(c, "respond_romantic", proposal_id=_proposal_id(c), response="accept")),
            O("decline_it", "Turn them down, gently.", min_age=18,
              action=lambda c: act(c, "respond_romantic", proposal_id=_proposal_id(c), response="decline")),
        )
        if _proposer(c) else ()
    ),
    options=(
        O("think_about_it", "Leave it pending and think about it a bit longer.", min_age=18, noop=True),
    ),
    notes="accept_it/decline_it need respond_romantic actually offered right now (dc.allowed()) -- see "
          "brain/context_builder.py's proposals loop, which only lists it while this exact proposal is "
          "still pending for this character, same precondition as contract.proposal_received's own "
          "accept_it/decline_it.",
    min_options=1,
)


# ---- romance.romantic_proposal_answered --------------------------------------
# systems/proposals.py::_maybe_resolve wakes the PROPOSER once the answer
# is in -- same generic "proposal_resolved" reason contract.
# proposal_resolved already handles, given its own kind=="romantic" framing.

def _resolved_other(ctx: SituationContext):
    pid = ctx.wake_payload.get("other_id")
    return pid if pid and ctx.person(pid) and _other_age_ok(ctx, pid) else None


def _was_accepted(ctx: SituationContext) -> bool:
    return ctx.wake_payload.get("outcome_summary") == "accepted"


ROMANTIC_PROPOSAL_ANSWERED = S(
    id="romance.romantic_proposal_answered", category="romance", priority=64, cooldown_ticks=10 * MINUTE,
    triggers=(T("event", event="proposal_resolved",
                key=lambda c: c.wake_payload.get("proposal_id") or "",
                when=lambda c: c.wake_payload.get("kind") == "romantic"),),
    required_data=("environment.nearby_characters",),
    describe=lambda c: (
        f"{c.wake_payload.get('other_name', 'They')} said yes."
        if _was_accepted(c) else
        f"{c.wake_payload.get('other_name', 'They')} said no."
    ),
    dynamic_options=lambda c: (
        (O("tell_them_youre_glad", "Tell them how glad you are.",
           action=lambda c: speak_to(c, _resolved_other(c)), speaks=True, speech_act="compliment",
           default_line=lambda c: "I'm really glad you said yes.", min_age=18),)
        if _was_accepted(c) and _resolved_other(c) else
        (O("accept_the_answer", "Tell them it's alright, you appreciate the honesty.",
           action=lambda c: speak_to(c, _resolved_other(c)), speaks=True, speech_act="supportive",
           default_line=lambda c: "Okay -- thanks for being honest with me.", min_age=18),)
        if not _was_accepted(c) and _resolved_other(c) else ()
    ),
    options=(
        O("sit_with_it", "Take a moment to sit with it.", min_age=18, noop=True),
        O("confide_in_a_friend", "Talk it over with a friend.", min_age=18,
          gap="confide_specific_topic_on_demand"),
    ),
    notes="confide_in_a_friend names a real gap: systems/confiding.py's own passive confiding logic "
          "(see its module docstring) never lets a situation hand it a specific moment to relay on "
          "demand, same class of gap already flagged for household.intimate_object_discovered's "
          "tell_someone_else. tell_them_youre_glad/accept_the_answer/sit_with_it are real.",
    min_options=1,
)


# ---- romance.partner_flirted_with_someone_else -------------------------------
# systems/action_router.py::_maybe_trigger_jealousy wakes a co-present
# partner/spouse the moment they witness a real flirt speech act.

def _flirting_partner(ctx: SituationContext):
    pid = ctx.wake_payload.get("partner_id")
    return pid if pid and ctx.person(pid) else None


PARTNER_FLIRTED_WITH_SOMEONE_ELSE = S(
    id="romance.partner_flirted_with_someone_else", category="romance", priority=66, cooldown_ticks=15 * MINUTE,
    triggers=(T("event", event="partner_flirted_with_someone_else",
                key=lambda c: c.wake_payload.get("partner_id") or ""),),
    required_data=("environment.nearby_characters", "character.relationships"),
    describe=lambda c: (
        f"{c.wake_payload.get('partner_name', 'Your partner')} was just flirting with "
        f"{c.wake_payload.get('flirted_with_name', 'someone')}, right in front of you."
    ),
    dynamic_options=lambda c: (
        (O("confront_partner", "Ask them about it, right now.",
           action=lambda c: speak_to(c, _flirting_partner(c)), speaks=True, speech_act="challenge",
           default_line=lambda c: f"What was that with {c.wake_payload.get('flirted_with_name', 'them')}?",
           min_age=18),)
        if _flirting_partner(c) else ()
    ),
    options=(
        O("let_it_slide", "Let it go, for now.", min_age=18, noop=True),
        O("bring_it_up_later", "Say nothing now, but plan to bring it up later.", min_age=18,
          gap="schedule_future_followup"),
    ),
    notes="bring_it_up_later names the same real gap already flagged in contract.proposal_resolved's "
          "bring_it_up_again_later -- no scheduled-followup-reminder mechanism exists anywhere yet. "
          "confront_partner is real.",
    min_options=1,
)


# ---- romance.partner_broke_up_with_me ----------------------------------------
# systems/romance.py::break_up() wakes the other party -- unilateral, no
# consent needed to end a relationship.

def _ex(ctx: SituationContext):
    pid = ctx.wake_payload.get("initiator_id")
    return pid if pid and ctx.person(pid) else None


PARTNER_BROKE_UP_WITH_ME = S(
    id="romance.partner_broke_up_with_me", category="romance", priority=70, cooldown_ticks=30 * MINUTE,
    triggers=(T("event", event="partner_broke_up_with_me",
                key=lambda c: c.wake_payload.get("initiator_id") or ""),),
    required_data=("environment.nearby_characters", "character.relationships"),
    describe=lambda c: f"{c.wake_payload.get('initiator_name', 'They')} just ended things with you.",
    dynamic_options=lambda c: (
        (O("ask_why", "Ask them why.",
           action=lambda c: speak_to(c, _ex(c)), speaks=True, speech_act="question",
           default_line=lambda c: "Can I ask why?", min_age=18),)
        if _ex(c) else ()
    ),
    options=(
        O("take_time_alone", "Take some time to yourself.", min_age=18, noop=True),
        O("reach_out_to_a_friend", "Reach out to a friend about it.", min_age=18,
          gap="confide_specific_topic_on_demand"),
    ),
    notes="reach_out_to_a_friend names the same real confiding gap as romance.romantic_proposal_"
          "answered's confide_in_a_friend. ask_why/take_time_alone are real.",
    min_options=1,
)


ROMANCE = (
    ROMANTIC_PROPOSAL_RECEIVED,
    ROMANTIC_PROPOSAL_ANSWERED,
    PARTNER_FLIRTED_WITH_SOMEONE_ELSE,
    PARTNER_BROKE_UP_WITH_ME,
)
