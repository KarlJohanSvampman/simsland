"""
Crime & Legal System situations -- v1 (child safeguarding pass).

Evaluated against a ChatGPT-authored "Simsland Crime & Legal System"
spec (123 sections: authoritative crime/evidence/investigation/arrest/
charge/proceeding/conviction/sentencing state machine, kept strictly
separate from character belief/reputation/psychology, PLUS a dedicated
child safeguarding/CPS custody pathway triggered by a caregiver's
arrest -- with the explicit invariant that arrest must never mean
automatic guilt or automatic permanent child removal) against what's
actually here first.

Unlike every earlier spec pass this session, most of THIS spec's own
headline ask -- the CPS/child-safeguarding pathway -- was not a gap at
all. It already existed, real and fully wired, landed earlier this
same project: systems/child_welfare.py::tick_child_welfare() (ticked
from sim_loop.py) already resolves caregivers via systems/child_care.py
::_find_parents_for_child(), checks real unavailability (jailed/
held_pending_trial/incapacitated/dead -- systems/law.py's own
legal.status field, not suspicion or accusation), checks for any other
present covering adult first, then searches systems/family.py's real
kinship graph for a relative before ever involving CPS, and only
dispatches a CPS worker + sends the child off-grid ("cps_care") as the
last resort. This already matches the spec's own core invariants
(arrest != guilt, safe-care-first, relative-before-foster) almost
exactly. systems/law.py itself is likewise a real, wired arrest ->
trial -> jail/sentencing pipeline with genuinely distinct
acquittal/conviction outcomes (a single crime_solve_rate-driven roll,
simpler than the spec's elaborate Evidence/WitnessStatement dataclass
model, but the SEPARATION of suspected/arrested/charged/convicted as
real, distinct states the spec insists on is already honored).

Two real, narrower gaps were found and fixed in child_welfare.py
itself this pass (not duplicated here): a relative placement was
permanent with no way back once the triggering caregiver became
available again, and a CPS placement's own docstring already flagged
that an early release didn't dynamically re-sync the child's return --
both closed by a new _review_existing_placements() sweep, driven by a
real placement-origin marker. See child_welfare.py's own docstring for
the full account.

The remaining real gap -- and this file's actual scope -- is the same
shape as every prior spec this session: child_welfare.py had ZERO
wake_character() calls before this pass, so neither the child being
placed, the relative taking them in, nor the child being reunited ever
got an actual reactive decision, only a passive memory/story entry.
Three situations here close that:
  legal.child_placement          -- the child, at the moment of placement
  legal.took_in_relative_child   -- the relative who just received them
  legal.reunified_with_caregiver -- the child, the moment they go home

Deliberately NOT built this pass, named honestly (matching this
session's household.py/romance.py/violence.py precedent of scoping a
huge spec down to a real, reviewable slice):
  - Protective orders / no-contact restrictions (spec sections 40-41) --
    confirmed completely missing anywhere in this codebase (grepped
    protective_order/restraining_order/no_contact -- zero hits). A
    genuinely new mechanic (an enforced contact restriction, checked by
    the action validator), not a reactive situation on top of something
    real. Left for a future pass.
  - Juvenile offender handling (spec sections 115-117) -- confirmed
    completely missing: law.py's arrest/charge/sentencing pipeline has
    no age branch at all. A child character who somehow entered it
    today would run the identical adult bail/trial/jail logic. Also
    left for a future pass -- a real juvenile-diversion pathway is
    substantial new work, not a situation-layer fix.
  - Elaborate Evidence/WitnessStatement/Suspect dataclasses (spec
    sections 12-19) -- law.py's simpler crime_solve_rate roll already
    honors the spec's real invariant (arrest != guilt, a suspect CAN be
    "cleared" by simply never being rolled as guilty), just without the
    spec's own evidence-strength modeling. Not rebuilt -- doing so
    would mean replacing a real, working, tested system with a parallel
    one for schema purity alone, exactly what this session's own
    standing directive says not to do.
  - Crime witnessed/reported/discovered situations for adult crime in
    general (spec sections 78-84) -- middleware/situations/library/
    violence.py (this session's own prior pass) already covers the
    witnessing/reporting moment for the specific case that pipeline
    into law.py's arrest flow (hostile actions -> incidents ->
    maybe_arrest_from_incidents). Not duplicated here.
"""

from __future__ import annotations

from ..definition import OptionSeed as O, SituationContext, SituationDefinition as S, Trigger as T
from ._helpers import speak_to

MINUTE = 60


# ---- legal.child_placement ----------------------------------------------------
# systems/child_welfare.py::tick_child_welfare() wakes the child, at the
# moment of placement, with reason "child_placement".

def _placed_with(ctx: SituationContext):
    pid = ctx.wake_payload.get("placed_with_id")
    return pid if pid and ctx.person(pid) else None


def _is_relative_placement(ctx: SituationContext) -> bool:
    return ctx.wake_payload.get("placement_type") == "relative"


CHILD_PLACEMENT = S(
    id="legal.child_placement", category="legal", priority=80, cooldown_ticks=30 * MINUTE,
    triggers=(T("event", event="child_placement",
                key=lambda c: c.wake_payload.get("caregiver_id") or ""),),
    required_data=("environment.nearby_characters", "character.relationships"),
    describe=lambda c: (
        f"{c.wake_payload.get('caregiver_name', 'Your parent')} couldn't be there for you, so "
        f"you've gone to stay with {c.wake_payload.get('placed_with_name', 'someone')} for now."
        if _is_relative_placement(c) else
        f"{c.wake_payload.get('caregiver_name', 'Your parent')} couldn't be there for you, so "
        f"Child Protective Services has come to look after you for now."
    ),
    dynamic_options=lambda c: (
        (O("ask_where_parent_is", "Ask where your parent is and when they're coming back.",
           action=lambda c: speak_to(c, _placed_with(c)), speaks=True, speech_act="question",
           default_line=lambda c: f"When is {c.wake_payload.get('caregiver_name', 'my parent')} coming back?"),)
        if _placed_with(c) else ()
    ),
    options=(
        O("stay_with_caretaker", "Stay close to whoever's looking after you right now.", noop=True),
        O("ask_for_parent", "Ask for your parent, even though they're not here.", noop=True),
        O("stay_quiet", "Don't say anything -- just take it in.", noop=True),
    ),
    notes="ask_where_parent_is is real, only offered when the child is actually placed with a "
          "perceivable person (the relative case -- CPS care has no single perceivable "
          "placed_with_id). The three static options are always available and are each a "
          "legitimate reaction on their own -- a child doesn't have to ask anything.",
    min_options=1,
)


# ---- legal.took_in_relative_child ----------------------------------------------
# systems/child_welfare.py wakes the relative who just received the
# child, reason "took_in_relative_child".

def _placed_child(ctx: SituationContext):
    pid = ctx.wake_payload.get("child_id")
    return pid if pid and ctx.person(pid) else None


TOOK_IN_RELATIVE_CHILD = S(
    id="legal.took_in_relative_child", category="legal", priority=68, cooldown_ticks=30 * MINUTE,
    triggers=(T("event", event="took_in_relative_child",
                key=lambda c: c.wake_payload.get("child_id") or ""),),
    required_data=("environment.nearby_characters", "environment.available_interactions"),
    describe=lambda c: (
        f"{c.wake_payload.get('child_name', 'A child')} has just come to stay with you -- "
        f"{c.wake_payload.get('caregiver_name', 'their caregiver')} couldn't be there for them right now."
    ),
    dynamic_options=lambda c: (
        (O("welcome_them", "Sit down with them and let them know they're safe here.",
           action=lambda c: speak_to(c, _placed_child(c)), speaks=True, speech_act="comfort",
           default_line=lambda c: "You're safe here -- we'll figure this out together."),)
        if _placed_child(c) else ()
    ),
    options=(
        O("figure_out_logistics", "Start figuring out what they'll need while they're here.", noop=True),
        O("feel_overwhelmed", "Take a moment -- this is a lot, suddenly.", noop=True),
    ),
    notes="welcome_them is real. figure_out_logistics/feel_overwhelmed are both legitimate "
          "reactions on their own -- a relative doesn't have to say anything to the child right "
          "away.",
    min_options=1,
)


# ---- legal.reunified_with_caregiver --------------------------------------------
# systems/child_welfare.py::_review_existing_placements() wakes the
# child the moment a relative placement reverses for real (the CPS
# path's own return already narrates itself via process_cps_care_return
# -- no wake there, see child_welfare.py's own comment on why).

def _returning_caregiver(ctx: SituationContext):
    pid = ctx.wake_payload.get("caregiver_id")
    return pid if pid and ctx.person(pid) else None


REUNIFIED_WITH_CAREGIVER = S(
    id="legal.reunified_with_caregiver", category="legal", priority=60, cooldown_ticks=30 * MINUTE,
    triggers=(T("event", event="reunified_with_caregiver",
                key=lambda c: c.wake_payload.get("caregiver_id") or ""),),
    required_data=("environment.nearby_characters",),
    describe=lambda c: (
        f"You're going home -- {c.wake_payload.get('caregiver_name', 'your parent')} is able to "
        f"take care of you again."
    ),
    dynamic_options=lambda c: (
        (O("express_relief", "Tell them how glad you are to be back.",
           action=lambda c: speak_to(c, _returning_caregiver(c)), speaks=True, speech_act="vulnerable",
           default_line=lambda c: "I'm really glad to be home."),)
        if _returning_caregiver(c) else ()
    ),
    options=(
        O("settle_back_in", "Just settle back into being home.", noop=True),
    ),
    notes="express_relief is real, only offered when the returning caregiver is actually "
          "perceivable right now. settle_back_in alone is a legitimate, presentable choice.",
    min_options=1,
)


LEGAL = (CHILD_PLACEMENT, TOOK_IN_RELATIVE_CHILD, REUNIFIED_WITH_CAREGIVER)
