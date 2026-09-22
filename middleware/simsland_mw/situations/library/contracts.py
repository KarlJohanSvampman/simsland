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

from ..definition import OptionSeed as O, SituationContext, SituationDefinition as S, Trigger as T
from ._helpers import speak_to

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


CONTRACTS = (CONTRACT_VIOLATED,)
