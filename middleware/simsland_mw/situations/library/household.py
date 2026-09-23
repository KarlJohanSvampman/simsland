"""
Household & domestic-life situations.

Evaluated against a ChatGPT-authored "Household & Domestic Situation
Library" spec (~100 situation types across cleaning, bills, groceries,
entertainment, hobbies, gardening, furniture, privacy, ...) against what's
actually here first -- and the pattern is now familiar from every other
spec this session: the DOMAIN logic is already real and mature (systems/
plants.py, systems/appliance_degradation.py, systems/mail.py's bill-
paying, systems/intimate_item_discovery.py, systems/chores.py, systems/
household_storage.py, systems/refurnishing.py, ...), it just never woke
anyone reactively -- confirmed by grep, zero wake_character() calls
anywhere in any of those modules before this round. Real wake_character()
calls added at the four clearest, highest-value points (see each backend
module's own diff): a household genuinely can't cover its bills (systems/
mail.py::attempt_pay_bills), someone stumbles onto someone else's private
item (systems/intimate_item_discovery.py), a plant crosses a real
"needs water soon" threshold (systems/plants.py), an appliance actually
breaks (systems/appliance_degradation.py). This file is the situation
built on top of each.

The other ~95 situation types in that spec are NOT built this pass --
most of them (trash/cleaning/laundry/TV/hobbies/shopping/...) either need
a real backend mechanic wired up first (e.g. trash: systems/waste.py's
own move_waste_to_bin() is confirmed dead code, never called anywhere --
household-level trash "fullness" never actually accumulates today,
disconnected from the real per-item "trash" action) or are lower-value
background/entertainment flavor than the four picked here. Flagged
honestly as a real, scoped-down v1, not silently pretended complete.
"""

from __future__ import annotations

from ..definition import OptionSeed as O, SituationContext, SituationDefinition as S, Trigger as T
from ._helpers import act, first_adult, speak_to

MINUTE = 60
HOUR = 60 * MINUTE


# ---- household.bill_trouble -------------------------------------------------
# systems/mail.py::attempt_pay_bills wakes the paying character with
# {"amount_owed", "household_wealth"} once household wealth runs out
# before the week's bills are fully covered -- real financial stress, not
# every ordinary (successfully auto-paid) bill.

def _bill_trouble_target(ctx: SituationContext):
    return first_adult(ctx)


BILL_TROUBLE = S(
    id="household.bill_trouble", category="household", priority=71, cooldown_ticks=6 * HOUR,
    triggers=(T("event", event="household_bill_trouble",
                key=lambda c: "household"),),
    required_data=("environment.nearby_characters", "environment.available_interactions"),
    describe=lambda c: (
        f"The household still owes {c.wake_payload.get('amount_owed', 0):.0f} after this week's bills -- "
        f"there wasn't enough money to cover it."
    ),
    dynamic_options=lambda c: (
        (O("discuss_with_household", "Talk it over with whoever's around.",
           action=lambda c: speak_to(c, _bill_trouble_target(c)), speaks=True, speech_act="declare",
           default_line=lambda c: "We need to talk about money -- we're behind on bills."),
         O("ask_for_help", "Ask them for help sorting it out.",
           gap="propose_financial_help"))
        if _bill_trouble_target(c) else ()
    ),
    options=(
        O("worry_about_it", "Sit with how bad this is for a moment.", noop=True),
        O("accept_for_now", "There's nothing to be done about it right this moment.", noop=True),
    ),
    notes="ask_for_help names a real gap: there's no dedicated 'ask someone for money to cover a "
          "shared bill' action distinct from the generic propose_request negotiation, which needs a "
          "specific item_id/amount this seed has no principled way to invent. discuss_with_household "
          "is real -- a genuine declare-type conversation opener, not a resolution.",
    min_options=1,
)


# ---- household.intimate_object_discovered -----------------------------------
# systems/intimate_item_discovery.py already applies the real relationship
# effect (apply_creeped_out) the moment this fires -- this situation is
# the deliberate social choice layered on top: what does the discoverer
# actually DO about it, not whether it affected them (that already
# happened, passively, for real).

def _discovery_owner(ctx: SituationContext):
    pid = ctx.wake_payload.get("owner_id")
    return pid if pid and ctx.person(pid) else None


INTIMATE_OBJECT_DISCOVERED = S(
    id="household.intimate_object_discovered", category="household", priority=46, cooldown_ticks=2 * HOUR,
    triggers=(T("event", event="intimate_object_discovered",
                key=lambda c: c.wake_payload.get("owner_id") or ""),),
    required_data=("environment.nearby_characters", "character.relationships"),
    describe=lambda c: "You come across something private of "
                       f"{c.wake_payload.get('owner_name', 'someone')}'s while you're around their things.",
    dynamic_options=lambda c: (
        (O("mention_it_to_them", "Mention it to them directly.",
           action=lambda c: speak_to(c, _discovery_owner(c)), speaks=True, speech_act="joke",
           default_line=lambda c: "So... I saw something of yours I wasn't expecting."),)
        if _discovery_owner(c) else ()
    ),
    options=(
        O("pretend_not_to_notice", "Pretend you didn't see it and move on.", noop=True),
        O("put_it_back_and_forget_it", "Put it back exactly where it was and don't mention it.", noop=True),
        O("tell_someone_else", "Bring it up with someone else in the household later.",
          gap="gossip_about_specific_third_party_fact"),
    ),
    notes="tell_someone_else names a real gap: systems/conversation_analysis.py's own gossip handling "
          "(see its module docstring) deliberately never lets a situation hand it a specific fact to "
          "relay -- it always picks from what the speaker genuinely already holds at gossip time, not "
          "an injected topic. mention_it_to_them and the two noops are real.",
    min_options=1,
)


# ---- household.plant_needs_water --------------------------------------------
# systems/plants.py wakes the household's own chosen-responsible member
# once a specific plant's moisture crosses a real low threshold.

PLANT_NEEDS_WATER = S(
    id="household.plant_needs_water", category="household", priority=40, cooldown_ticks=3 * HOUR,
    triggers=(T("event", event="plant_needs_water",
                key=lambda c: c.wake_payload.get("plant_id") or ""),),
    required_data=("environment.nearby_characters", "environment.available_interactions"),
    describe=lambda c: f"{c.wake_payload.get('plant_name', 'A plant')} looks like it needs water soon.",
    dynamic_options=lambda c: (
        (O("ask_someone_else_to_do_it", "Ask someone else to take care of it.",
           action=lambda c: speak_to(c, first_adult(c)), speaks=True, speech_act="ask",
           default_line=lambda c: "Can you water the plants? They're looking dry."),)
        if first_adult(c) else ()
    ),
    options=(
        O("water_it", "Water it.", action=lambda c: act(c, "water_plants")),
        O("water_all_the_plants_while_im_at_it", "Fill up the watering can and do all the plants while you're at it.",
          action=lambda c: act(c, "water_plants")),
        O("leave_it_for_now", "Leave it for now.", noop=True),
    ),
    notes="water_it/water_all_the_plants_while_im_at_it both resolve to the same real water_plants "
          "action (systems/action_router.py's own doc: 'fill a watering can and water plants that need "
          "it' -- already a household-wide sweep, not single-plant-targeted) -- kept as two distinct "
          "options for the LLM's own framing (a quick fix vs. a deliberate round), same 'the "
          "differentiation lives in intent, not the outcome' shape as social_media.rumor_about_self's "
          "deny_it_publicly/explain_what_happened.",
    min_options=1,
)


# ---- household.appliance_broken ---------------------------------------------
# systems/appliance_degradation.py already raises a real background desire
# (replace_appliance) for the household's chosen-responsible member the
# moment this fires -- this situation is the immediate, in-the-moment
# reaction on top of that longer-running want.

APPLIANCE_BROKEN = S(
    id="household.appliance_broken", category="household", priority=47, cooldown_ticks=2 * HOUR,
    triggers=(T("event", event="appliance_broken",
                key=lambda c: c.wake_payload.get("object_type") or ""),),
    required_data=("environment.nearby_characters",),
    describe=lambda c: f"The {(c.wake_payload.get('object_type') or 'appliance').replace('_', ' ')} just broke.",
    dynamic_options=lambda c: (
        (O("tell_household", "Let whoever's around know it broke.",
           action=lambda c: speak_to(c, first_adult(c)), speaks=True, speech_act="declare",
           default_line=lambda c: "Heads up, the "
                                  f"{(c.wake_payload.get('object_type') or 'appliance').replace('_', ' ')} just died."),)
        if first_adult(c) else ()
    ),
    options=(
        O("deal_with_it_later", "Leave it for now -- it's not urgent.", noop=True),
        O("get_annoyed", "Just be annoyed about it for a moment.", noop=True),
    ),
    notes="Replacing/repairing it is already a real, separate background want (systems/"
          "appliance_degradation.py's own add_desire('replace_appliance', ...)), not offered as a "
          "one-shot option here -- this situation is only the immediate reaction.",
    min_options=1,
)


HOUSEHOLD = (BILL_TROUBLE, INTIMATE_OBJECT_DISCOVERED, PLANT_NEEDS_WATER, APPLIANCE_BROKEN)
