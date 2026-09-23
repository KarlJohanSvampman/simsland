"""
Violence, crime & physical conflict situations -- v1.

Evaluated against a ChatGPT-authored "Violence, Crime & Physical
Conflict Situation Library" spec (114 sections: threats, physical
confrontation, self-defense, defense of others, witnessing, property
crime, harassment/stalking, criminal discovery, reporting, retaliation,
aftermath, and a strict architectural boundary -- the LLM only ever
picks a semantic option like "leave"/"defend_self"/"call_for_help"; a
separate world engine, never the LLM, resolves success/failure, injury
and legal guilt) against what's actually here first. Unlike every
earlier spec pass this session, this is NOT a greenfield domain -- the
backend already has a large, real, wired pipeline for almost all of it:

  spec concept                    -> this codebase
  ------------------------------------------------------------------
  physical confrontation/fights    -> systems/conflict_pipeline.py
                                       (verbal_dispute -> heated_argument
                                       -> shouting_match -> physical_
                                       altercation state machine, ticked
                                       from sim_loop.py)
  direct combat (punch/kick/shove/
  threaten/grab/hold/wrestle/stab/
  knock) with real injury          -> systems/hostile_actions.py::
                                       resolve_hostile_action(), rolling
                                       real health.py::apply_injury()
                                       outcomes via an opposed check
                                       (systems/contested_checks.py) --
                                       already exactly the "LLM picks a
                                       semantic option, the engine
                                       resolves hit/evade/fumble/injury"
                                       boundary this spec asks for
  restraint/grapple/pin            -> systems/grapple.py
  self-defense verbs               -> dodge/block/turn_and_run/wrestle
                                       (real action_types already;
                                       there is no single unified
                                       "defend_self" verb, the spec's
                                       naming, but the semantic space is
                                       covered)
  robbery/mugging                  -> systems/crime.py::
                                       resolve_steal_from() -- real
                                       item/cash transfer without
                                       consent
  burglary/gangs/criminal career   -> systems/crime.py
  vandalism/property damage        -> systems/emergency.py::
                                       report_property_damage_incident
  police/911/dispatch              -> systems/emergency.py (real
                                       call_911 action_type, already
                                       offered whenever an unresolved
                                       incident is nearby -- brain/
                                       context_builder.py::
                                       _build_incident_context)
  arrest/trial/jail/sentencing     -> systems/law.py, all ticked from
                                       sim_loop.py
  crime/violence investigation     -> systems/detective_work.py (real,
                                       general-purpose story engine --
                                       notice_threats_violence/
                                       notice_property_damage already
                                       hooked from hostile_actions.py)
  reputation/grievance consequences -> systems/reputation.py,
                                       systems/grievances.py (already
                                       wired from core/event_handlers.py
                                       on fight_physical/character_
                                       arrested/character_jailed)

The confirmed real gap, across all 114 sections, was almost entirely in
ONE place: nobody involved in a hostile action other than its direct
TARGET ever got a reactive prompt about it. systems/target_reactions.py
::flag_provocation() already wakes the target for real (wake_reason
"provoked"), but:
  (a) the payload silently dropped the outcome ("hit"/"evaded"/
      "fumble") and the real incident_id systems/emergency.py::
      report_assault_incident() had just filed -- both were already
      threaded as parameters into flag_provocation(), just never
      reached the wake payload. Fixed in target_reactions.py/
      hostile_actions.py.
  (b) systems/hostile_actions.py's own "hostile_action_resolved" event
      was emitted with confirmed ZERO subscribers -- a bystander who
      watched a punch land got nothing at all. Fixed with a new
      core/event_handlers.py::_on_hostile_action_resolved subscriber
      that wakes co-present witnesses (wake_reason "witnessed_
      violence"), same "broadcast to bystanders" idiom already used
      for jealousy (systems/action_router.py::_maybe_trigger_jealousy).
  (c) middleware/situations/library/conversation.py already handles
      "insult"/"accuse" provocation types but stops there -- a
      character who gets punched, threatened, grabbed, or held falls
      through to the generic action menu with zero situational framing
      even though target_reactions.py's REACTION_WEIGHTS already
      covers all of them. This file closes that gap for real.

Situations built this pass:
  violence.threatened          -- provoked wake, provocation_type ==
                                   "threaten"
  violence.attacked            -- provoked wake, provocation_type in
                                   {punch, kick, shove, grab_offensive,
                                   hold, wrestle}; describe() branches
                                   on the real outcome now reaching the
                                   payload (a landed hit reads
                                   differently from a dodged attempt)
  violence.witnessed_violence  -- the new wake from (b) above

Deliberately NOT built this pass, named honestly:
  - Property crime victim agency: systems/crime.py::resolve_steal_from()
    resolves a robbery/mugging in one deterministic function call with
    no in-the-moment decision point for the victim -- spec section 23's
    "robbery_threat" (comply/resist/flee BEFORE the outcome is decided)
    would need resolve_steal_from restructured into a real two-phase
    threat -> victim choice -> resolution flow, a materially bigger
    change than a reactive situation and left untouched.
  - General harassment/stalking/coercion as a pattern-detection system
    distinct from what already exists: systems/harassment.py is real
    and wired, but models a specific sexual-harassment-drive escalation
    (lewd_stare -> crude_remark -> unwanted_touch -> explicit_
    proposition), not the spec's broader "someone keeps following/
    contacting me against my will" pattern. A genuinely different
    system, not built this pass.
  - A conversational "threat" speech_act distinct from the real
    "threaten" hostile action -- already evaluated and explicitly
    deferred by conversation.py's own docstring; not revisited here.
  - Arrest-moment agency (comply/ask_reason/remain_silent, spec section
    55) -- systems/law.py::schedule_trial() resolves custody/bail
    immediately with no LLM decision point in the moment, same class of
    gap as robbery above.
  - fight_physical (conflict_pipeline.py's own escalation-to-violence
    event, distinct from hostile_actions.py's per-action resolution)
    triggering its own witness wake -- a reasonable follow-up to (b)
    above, left out to keep this pass to one witness wake source with
    one consistent payload shape.
  - Pattern detection (repeated_conflict/repeated_threats/pattern_of_
    violence, spec section 95) -- no ConflictHistory-style aggregate
    exists yet; every event here is still independent.

Pre-existing observation, not fixed by this pass: none of hostile_
actions.py/contested_checks.py/crime.py gate on age. This predates this
change and is outside a reactive-situation-library's scope to fix
(unlike systems/romance.py's own explicit adult-only gate on becoming
partners, which this session added at the one real choke point for
that domain) -- flagged here for visibility, not addressed.
"""

from __future__ import annotations

from ..definition import OptionSeed as O, SituationContext, SituationDefinition as S, Trigger as T
from ._helpers import act, speak_to

MINUTE = 60

_ATTACK_TYPES = {"punch", "kick", "shove", "grab_offensive", "hold", "wrestle"}


def _actor(ctx: SituationContext):
    pid = ctx.wake_payload.get("actor_id")
    return pid if pid and ctx.person(pid) else None


def _incident_id(ctx: SituationContext):
    return ctx.wake_payload.get("incident_id")


# ---- violence.threatened -----------------------------------------------------
# systems/target_reactions.py::flag_provocation wakes the target with
# reason "provoked" -- this narrows to provocation_type == "threaten"
# (systems/hostile_actions.py's real "threaten" hostile action, an
# opposed check via systems/contested_checks.py, distinct from the
# still-deferred conversational threat speech_act -- see module
# docstring).

THREATENED = S(
    id="violence.threatened", category="violence", priority=70, cooldown_ticks=5 * MINUTE,
    triggers=(T("event", event="provoked",
                key=lambda c: c.wake_payload.get("actor_id") or "",
                when=lambda c: c.wake_payload.get("provocation_type") == "threaten"),),
    required_data=("environment.nearby_characters", "environment.available_interactions"),
    describe=lambda c: f"{c.wake_payload.get('actor_name', 'Someone')} just threatened you.",
    dynamic_options=lambda c: (
        (O("stand_up_to_them", "Stand your ground and tell them to back off.",
           action=lambda c: speak_to(c, _actor(c)), speaks=True, speech_act="challenge",
           default_line=lambda c: "Don't threaten me."),)
        if _actor(c) else ()
    ) + (
        (O("call_for_help", "Call 911.",
           action=lambda c: act(c, "call_911", target_id=_incident_id(c))),)
        if _incident_id(c) else ()
    ),
    options=(
        O("back_away", "Back away and put distance between you.",
          action=lambda c: act(c, "turn_and_run")),
        O("back_down", "Say nothing and let it go, for now.", noop=True),
    ),
    notes="stand_up_to_them/back_away/back_down are real. call_for_help only appears when "
          "hostile_actions.py's own resolve_hostile_action() actually filed a real incident "
          "(report_assault_incident) for this threat, same precondition call_911 always has "
          "elsewhere in this codebase.",
    min_options=1,
)


# ---- violence.attacked --------------------------------------------------------
# Same "provoked" wake, narrowed to the physical-contact provocation
# types. describe() now reads the real outcome (fixed this pass -- see
# module docstring) instead of assuming every provocation landed.

def _outcome(ctx: SituationContext) -> str:
    return ctx.wake_payload.get("outcome") or "hit"


ATTACKED = S(
    id="violence.attacked", category="violence", priority=76, cooldown_ticks=5 * MINUTE,
    triggers=(T("event", event="provoked",
                key=lambda c: c.wake_payload.get("actor_id") or "",
                when=lambda c: c.wake_payload.get("provocation_type") in _ATTACK_TYPES),),
    required_data=("environment.nearby_characters", "environment.available_interactions"),
    describe=lambda c: (
        f"{c.wake_payload.get('actor_name', 'Someone')} just {c.wake_payload.get('verb_phrase', 'attacked')} you."
        if _outcome(c) == "hit" else
        f"{c.wake_payload.get('actor_name', 'Someone')} just tried to "
        f"{c.wake_payload.get('verb_phrase', 'attack')} you -- you weren't hit."
    ),
    dynamic_options=lambda c: (
        (O("confront_them", "Confront them, right now.",
           action=lambda c: speak_to(c, _actor(c)), speaks=True, speech_act="challenge",
           default_line=lambda c: "Don't you ever do that again."),)
        if _actor(c) else ()
    ) + (
        (O("call_for_help", "Call 911.",
           action=lambda c: act(c, "call_911", target_id=_incident_id(c))),)
        if _incident_id(c) else ()
    ),
    options=(
        O("push_them_away", "Push them off you and create space.",
          action=lambda c: act(c, "shove")),
        O("run_away", "Get away from them.", action=lambda c: act(c, "turn_and_run")),
        O("freeze", "Freeze -- you don't move.", noop=True),
    ),
    notes="push_them_away/run_away/freeze/confront_them are real. call_for_help only appears "
          "once a real incident exists for this exact exchange (hit or fumble, per hostile_"
          "actions.py -- an evaded attempt files no incident).",
    min_options=1,
)


# ---- violence.witnessed_violence -----------------------------------------------
# core/event_handlers.py::_on_hostile_action_resolved (new this pass) --
# a co-present bystander who watched a hostile action actually land.

def _witness_target(ctx: SituationContext):
    pid = ctx.wake_payload.get("target_id")
    return pid if pid and ctx.person(pid) else None


WITNESSED_VIOLENCE = S(
    id="violence.witnessed_violence", category="violence", priority=62, cooldown_ticks=10 * MINUTE,
    triggers=(T("event", event="witnessed_violence",
                key=lambda c: c.wake_payload.get("actor_id") or ""),),
    required_data=("environment.nearby_characters", "environment.available_interactions"),
    describe=lambda c: (
        f"{c.wake_payload.get('actor_name', 'Someone')} just "
        f"{c.wake_payload.get('action', 'attacked')} "
        f"{c.wake_payload.get('target_name', 'someone')}, right in front of you."
    ),
    dynamic_options=lambda c: (
        (O("step_in", "Step in and tell them to stop.",
           action=lambda c: speak_to(c, _actor(c)), speaks=True, speech_act="challenge",
           default_line=lambda c: "Hey! Knock it off!"),)
        if _actor(c) else ()
    ) + (
        (O("check_on_them", "Ask the person who was hit if they're okay.",
           action=lambda c: speak_to(c, _witness_target(c)), speaks=True, speech_act="question",
           default_line=lambda c: "Are you okay?"),)
        if _witness_target(c) else ()
    ) + (
        (O("call_for_help", "Call 911.",
           action=lambda c: act(c, "call_911", target_id=_incident_id(c))),)
        if _incident_id(c) else ()
    ),
    options=(
        O("stay_back", "Keep your distance and stay out of it.", noop=True),
    ),
    notes="step_in/check_on_them/call_for_help are all real, each gated on its own target/"
          "incident actually being resolvable right now. stay_back alone is a legitimate choice "
          "-- characters don't automatically behave heroically (spec's own invariant).",
    min_options=1,
)


VIOLENCE = (THREATENED, ATTACKED, WITNESSED_VIOLENCE)
