"""
Social contract situations.

Evaluated against a ChatGPT-authored Social Contracts/Projects/Consequences/
Reputation specification (~30 new dataclasses: SocialContract, ContractTerm,
SocialProject, ProjectTask, ReputationMark, ...) against what's actually
here first -- and this is a very different starting point from the last two
specs: almost the entire concept already exists, real and active, just
spread across several modules rather than one unified system:

  spec concept          ->  this codebase
  ---------------------------------------------------------------
  SocialContract         ->  systems/social_contracts.py (632 lines --
                              terms, check_type-based violation detection,
                              compliance scoring, negotiation state machine,
                              authority/curfew contracts, all WIRED IN:
                              sim_loop.py runs check_contract_violations()
                              every tick)
  ContractProposal /
  Negotiation             ->  systems/proposals.py (514 lines, including
                              offer_recurring()/_finalize_recurring_offer()
                              for the spec's own "Recurring Family Game
                              Night" example)
  Social Project           ->  systems/social_events.py (942 lines -- event
                              drafts, co-organizer approval, RSVP, invites,
                              comments, attendance-tradeoff evaluation)
  Expectation (distinct
  from Contract, per the
  spec's own section 44/79) ->  systems/expectations.py (577 lines) --
                              already a SEPARATE system from contracts here
                              too, matching the spec's own distinction
  ReputationMark (character-
  specific, tagged, evidenced,
  decaying)                 ->  systems/grievances.py (228 lines) -- per-
                              holder, per-source ("caused_by") tagged
                              entries (insulted/betrayed/broke_promise/
                              disrespected/...) with real decay
                              (DECAY_RATE=0.997/tick) and compounding on
                              repeat -- almost a 1:1 match to the spec's
                              own tag examples
  Global/public reputation  ->  systems/reputation.py -- a genuinely
                              DIFFERENT, complementary concept (community-
                              wide single score, not per-relationship) the
                              spec doesn't separately call out

What was actually missing, confirmed by grep: zero wake_character() calls
anywhere in social_contracts.py or proposals.py -- a violated contract (the
spec's own flagship example, the curfew) only ever reached the affected
party's next regularly-scheduled think(), same class of gap already fixed
this session for target_reactions.py's "provoked" and social_media.py's
"post_about_self". Fixed there (systems/social_contracts.py::
report_violation now calls wake_character), and this file is the situation
built on top of that real wake.
"""

from __future__ import annotations

from typing import Optional

from ..definition import OptionSeed as O, SituationContext, SituationDefinition as S, Trigger as T
from ._helpers import act, speak_to

MINUTE = 60


def _violator(ctx: SituationContext):
    pid = ctx.wake_payload.get("violator_id")
    return pid if pid and ctx.person(pid) else None


CONTRACT_VIOLATED = S(
    id="contract.violated", category="contract", priority=72, cooldown_ticks=5 * MINUTE,
    triggers=(T("event", event="contract_violated",
                key=lambda c: c.wake_payload.get("contract_id") or ""),),
    required_data=("environment.nearby_characters", "character.relationships",
                   "environment.available_interactions"),
    describe=lambda c: (
        f"{c.wake_payload.get('violator_name', 'Someone')} just missed "
        f"\"{c.wake_payload.get('commitment', 'something they agreed to')}\"."
    ),
    dynamic_options=lambda c: (
        (
            O("confront_them", "Confront them about it.",
              action=lambda c: speak_to(c, _violator(c)), speaks=True, speech_act="challenge",
              default_line=lambda c: "You were supposed to handle this."),
            O("remind_them", "Remind them what they agreed to.",
              action=lambda c: speak_to(c, _violator(c)), speaks=True, speech_act="declare",
              default_line=lambda c: "You know you agreed to this, right?"),
            O("forgive_them", "Let them know it's alright, just this once.",
              action=lambda c: speak_to(c, _violator(c)), speaks=True, speech_act="supportive",
              default_line=lambda c: "It's okay -- just try to keep to it next time."),
        )
        if _violator(c) else ()
    ),
    options=(
        O("let_it_go", "Let it go for now.", noop=True),
        O("propose_renegotiation", "Suggest changing the terms of the agreement.",
          gap="negotiate_contract_not_offered"),
    ),
    notes="propose_renegotiation names a real gap: action_router.py's negotiate_contract route "
          "(systems/social_contracts.py::propose_contract_modification) exists and works, but "
          "context_builder.py never actually offers the negotiate_contract action_type to the LLM "
          "at all -- confirmed via grep, same class of gap as several other already-fixed this "
          "session. Needs a real eligibility check (character is the SUBJECT, not just A party, of "
          "an active authority contract) that this seed can't determine on its own from a bare "
          "contract_id, so it's flagged rather than guessed at.",
    min_options=1,   # let_it_go alone is a legitimate, presentable choice when the violator
                     # isn't even perceivable right now (a text-based commitment, say).
)


# ---- contract.proposal_received -----------------------------------------------
# systems/proposals.py's propose()/proposer_advance_round() now wake the
# recipient with reason "proposal_received" for a brand new proposal OR a
# revised one after a counter-round -- previously only passively visible via
# context_builder.py's own open_proposals list (real, but nothing ever
# prompted a character to actually look at it).

# respond()/proposer_advance_round() are kind-agnostic (dispatch purely by
# proposal_id, per action_router.py's own comments on respond_social/
# respond_request reusing _route_respond_chore) -- but each KIND still needs
# an action_type Simsland actually recognizes as *offered* right now
# (dc.allowed()), and only some kinds support "counter" at all (systems/
# proposals.py::respond() rejects counter outright for anything not in
# chore/social_ask/request/item_loan/item_sale).
_RESPOND_ACTION_BY_KIND = {
    "chore":           "respond_chore",
    "social_ask":       "respond_social",
    "request":          "respond_request",
    "item_loan":        "respond_item_loan",
    "item_sale":        "respond_item_sale",
    # recurring_offer supports no counter and has no action_type of its own
    # -- reuses respond_chore, which routes to the same kind-agnostic
    # respond() regardless of what the ORIGINAL proposal's kind was.
    "recurring_offer":  "respond_chore",
}
_KINDS_SUPPORTING_COUNTER = {"chore", "social_ask", "request", "item_loan", "item_sale"}


def _respond_action_type(ctx: SituationContext) -> Optional[str]:
    return _RESPOND_ACTION_BY_KIND.get(ctx.wake_payload.get("kind"))


def _proposal_id(ctx: SituationContext) -> Optional[str]:
    return ctx.wake_payload.get("proposal_id")


def _kind_supports_counter(ctx: SituationContext) -> bool:
    return ctx.wake_payload.get("kind") in _KINDS_SUPPORTING_COUNTER


PROPOSAL_RECEIVED = S(
    id="contract.proposal_received", category="contract", priority=58, cooldown_ticks=2 * MINUTE,
    triggers=(
        T("event", event="proposal_received",
          key=lambda c: c.wake_payload.get("proposal_id") or ""),
        T("event", event="proposal_countered",
          key=lambda c: c.wake_payload.get("proposal_id") or ""),
    ),
    required_data=("environment.available_interactions",),
    describe=lambda c: (
        f"{c.wake_payload.get('from_name', 'Someone')} has proposed something: "
        f"\"{c.wake_payload.get('topic', 'a plan')}\"."
    ),
    dynamic_options=lambda c: (
        (O("counter_offer", "Suggest different terms instead.",
           action=lambda c: act(c, _respond_action_type(c),
                                proposal_id=_proposal_id(c), response="counter")),)
        if _kind_supports_counter(c) else ()
    ),
    options=(
        O("accept_it", "Accept it.",
          action=lambda c: act(c, _respond_action_type(c),
                               proposal_id=_proposal_id(c), response="accept")),
        O("decline_it", "Turn it down.",
          action=lambda c: act(c, _respond_action_type(c),
                               proposal_id=_proposal_id(c), response="decline")),
        O("think_about_it", "Leave it pending and think about it a bit longer.", noop=True),
    ),
    notes="Every real option here needs its OWN action_type actually offered right now "
          "(dc.allowed()) -- if the recipient's available_actions never surfaced respond_social/"
          "respond_chore/etc. at all for some reason, accept_it/decline_it/counter_offer simply "
          "don't resolve and only think_about_it survives, which is why min_options=1.",
    min_options=1,
)


# ---- contract.proposal_resolved -------------------------------------------------
# systems/proposals.py::_maybe_resolve wakes the PROPOSER once every
# recipient has answered. other_id/other_name are only ever set when the
# proposal had exactly one recipient (the common case -- a multi-recipient
# "chore" proposal has no single "the other person" to address) -- real
# follow-up options are offered only then; a resolved multi-party proposal
# still fires this situation, just with fewer resolvable options (see
# min_options/dynamic_options below), same pattern as this file's other
# situations.

def _resolved_other(ctx: SituationContext) -> Optional[str]:
    pid = ctx.wake_payload.get("other_id")
    return pid if pid and ctx.person(pid) else None


PROPOSAL_RESOLVED = S(
    id="contract.proposal_resolved", category="contract", priority=40, cooldown_ticks=2 * MINUTE,
    triggers=(T("event", event="proposal_resolved",
                key=lambda c: c.wake_payload.get("proposal_id") or ""),),
    required_data=("environment.nearby_characters",),
    describe=lambda c: (
        f"Your proposal about \"{c.wake_payload.get('topic', 'the plan')}\" has an answer: "
        f"{c.wake_payload.get('outcome_summary', 'it has been decided')}."
    ),
    dynamic_options=lambda c: (
        (
            O("thank_them", "Thank them for their answer.",
              action=lambda c: speak_to(c, _resolved_other(c)), speaks=True, speech_act="supportive",
              default_line=lambda c: f"Thanks for letting me know, {c.name(_resolved_other(c))}."),
            O("ask_why", "Ask why they answered the way they did.",
              action=lambda c: speak_to(c, _resolved_other(c)), speaks=True, speech_act="ask",
              default_line=lambda c: "Can I ask why?"),
            O("bring_it_up_again_later", "Let it go for now, but plan to bring it up again another time.",
              gap="schedule_future_followup"),
        )
        if _resolved_other(c) else ()
    ),
    options=(
        O("move_on", "Take note and move on.", noop=True),
    ),
    notes="thank_them/ask_why only resolve when the other party is a single, currently-perceivable "
          "character (systems/proposals.py only names other_id/other_name for a single-recipient "
          "proposal in the first place) -- a resolved multi-recipient chore proposal still fires "
          "this situation with only move_on available, which is why min_options=1.",
    min_options=1,
)


CONTRACTS = (CONTRACT_VIOLATED, PROPOSAL_RECEIVED, PROPOSAL_RESOLVED)
