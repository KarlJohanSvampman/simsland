"""
systems/subscriptions.py

Generic recurring "subscription" mechanism a HOUSEHOLD holds against a
service_templates entry (home insurance, life insurance, home internet,
home security monitoring, entertainment) -- systems/market.py's catalog
already carries these ("type": "service"). Mobile data is deliberately
NOT handled here -- it's a one-off pay-per-GB top-up, not a recurring
subscription (see systems/telecom.py). Vehicle insurance is also NOT
handled here -- it extends the vehicle's own existing insurance_pays/
insurance_premium_cost fields (systems/vehicles.py, added last round but
never wired to anything) rather than introducing a competing household-
level record for the same concept -- see insure_vehicle()/
payout_vehicle_insurance() below.

household["subscriptions"] = {
    sub_id: {
        "id", "service_id", "provider_company_id", "category",
        "weekly_cost", "started_tick",
        "payout_max" (insurance_home/insurance_life only),
        "throughput_mbps" (internet only),
    }
}
Only one subscription per category at a time -- picking a new provider
in the same category (e.g. switching home insurers) replaces the old
one rather than stacking two policies.
"""

import random
import uuid

HOUSEHOLD_CATEGORIES = ("insurance_home", "insurance_life", "internet", "security", "entertainment")


def subscribe_household(world, household, service_id):
    """Returns the new subscription dict, or None if service_id doesn't
    resolve to a real service_template."""
    defs = world.get("definitions", {})
    st = defs.get("service_templates", {}).get(service_id)
    if not st:
        return None

    subs = household.setdefault("subscriptions", {})
    category = st.get("category")
    for sub_id in [sid for sid, s in subs.items() if s.get("category") == category]:
        subs.pop(sub_id)

    sub = {
        "id":                  f"sub_{uuid.uuid4().hex[:8]}",
        "service_id":          service_id,
        "provider_company_id": st.get("provider_company_id"),
        "category":            category,
        "weekly_cost":         st.get("weekly_cost", 0),
        "payout_max":          st.get("payout_max"),
        "throughput_mbps":     st.get("throughput_mbps"),
        "started_tick":        world.get("tick", 0),
    }
    subs[sub["id"]] = sub
    return sub


def cancel_household_subscription(household, sub_id):
    return household.get("subscriptions", {}).pop(sub_id, None) is not None


def household_subscription(household, category):
    """The household's current subscription in `category` (at most one,
    per subscribe_household()'s replace-on-switch rule), or None."""
    for sub in household.get("subscriptions", {}).values():
        if sub.get("category") == category:
            return sub
    return None


def weekly_subscriptions_total(household):
    return round(sum(s.get("weekly_cost", 0) for s in household.get("subscriptions", {}).values()), 2)


def has_home_insurance(household):
    return household_subscription(household, "insurance_home") is not None


def default_home_insurance_service_id(defs):
    """The service_template a household gets auto-enrolled in if one
    isn't chosen at creation -- home insurance is mandatory (per the
    user's own spec: no household is ever uninsured), so there must
    always be a fallback rather than leaving a household unprotected."""
    for sid, st in (defs.get("service_templates") or {}).items():
        if st.get("category") == "insurance_home":
            return sid
    return None


# =========================================================
# HOUSEHOLD INSURANCE PAYOUTS -- hooked to real existing incident types,
# not a new disaster-simulation system.
# =========================================================

def payout_home_insurance(world, household):
    """Pays payout_max straight to household wealth if the household has
    a home policy; doesn't cancel the subscription (a real insurer
    doesn't drop you after one claim). Returns the amount paid (0 if
    uninsured)."""
    sub = household_subscription(household, "insurance_home")
    if not sub:
        return 0
    amount = sub.get("payout_max", 0)
    household["wealth"] = household.get("wealth", 0) + amount
    return amount


def payout_life_insurance(world, household):
    sub = household_subscription(household, "insurance_life")
    if not sub:
        return 0
    amount = sub.get("payout_max", 0)
    household["wealth"] = household.get("wealth", 0) + amount
    return amount


# =========================================================
# VEHICLE INSURANCE -- extends systems/vehicles.py's own per-instance
# insurance_pays/insurance_premium_cost fields (added last round,
# defaulted to 0, never actually wired to a real payer until now).
# =========================================================

def insure_vehicle(world, vehicle, service_id):
    """Sets the vehicle's own insurance_pays/insurance_premium_cost
    directly from a service_template (category "insurance_vehicle").
    Returns True on success."""
    defs = world.get("definitions", {})
    st = defs.get("service_templates", {}).get(service_id)
    if not st or st.get("category") != "insurance_vehicle":
        return False
    vehicle["insurance_pays"] = st.get("payout_max", 0)
    vehicle["insurance_premium_cost"] = st.get("weekly_cost", 0)
    vehicle["insurance_service_id"] = service_id
    return True


def payout_vehicle_insurance(world, vehicle):
    """Pays the vehicle's own insurance_pays to its owning household's
    wealth. Capped at the vehicle's current value -- insurance covers the
    car, not a windfall beyond what it was worth."""
    payout = min(vehicle.get("insurance_pays", 0), vehicle.get("value", 0))
    if payout <= 0:
        return 0
    household = world.get("households", {}).get(vehicle.get("household_id"))
    if not household:
        return 0
    household["wealth"] = household.get("wealth", 0) + payout
    return payout


def household_vehicle_insurance_weekly(world, household_id):
    """Sum of insurance_premium_cost across every vehicle this household
    owns -- folded into economy.py's weekly bill alongside the
    subscriptions total (vehicle insurance isn't itself a household
    "subscription" record, see this module's own docstring, but it's
    still a real recurring cost)."""
    from systems.vehicles import household_vehicles
    return round(sum(v.get("insurance_premium_cost", 0) for v in household_vehicles(world, household_id)), 2)


# =========================================================
# ONLINE COMMUNITY PROFILE + PEER-DRIVEN ENTERTAINMENT DESIRE
# Mirrors systems/peer_influence.py's exposure-accumulates-then-crosses-
# a-threshold SHAPE, without literally calling into it -- that module is
# hard-wired to trait/belief adoption specifically, not consumption
# desire, and bolting a third unrelated use onto its one function would
# make it harder to reason about, not easier.
# =========================================================

ONLINE_INTERESTS = ("gaming", "music", "streaming")
PEER_DESIRE_GAIN = 0.08          # per real contact sharing the same favorite, per check
PEER_DESIRE_THRESHOLD = 1.0      # crossing this fires a real subscribe intention


def generate_online_profile(defs):
    """Called once at character generation. A randomized interest plus a
    "favorite" service -- the specific publisher/producer's product they
    like, per the user's own framing -- drawn from whichever
    service_templates actually match that interest (category
    "entertainment", "interest" field), so the profile always points at
    a real, purchasable product rather than an invented company name
    with nothing behind it."""
    interest = random.choice(ONLINE_INTERESTS)
    candidates = [
        sid for sid, st in (defs.get("service_templates") or {}).items()
        if st.get("category") == "entertainment" and st.get("interest") == interest
    ]
    return {
        "interest":            interest,
        "favorite_service_id": random.choice(candidates) if candidates else None,
        "subscribe_desire":    0.0,
    }


def maybe_grow_subscription_desire(c, world):
    """Called on a slow cadence for a character whose household doesn't
    already subscribe to their own favorite. The more of their real
    contacts (c["relationships"]) share that exact same favorite, the
    faster desire grows -- once it crosses PEER_DESIRE_THRESHOLD, a real
    "subscribe_service" intention fires (surfaced into context/available
    actions the normal way, not an auto-purchase -- the character still
    has to actually go through with it)."""
    profile = c.get("online_profile")
    if not profile or not profile.get("favorite_service_id"):
        return

    household = world.get("households", {}).get(c.get("household_id"))
    if household:
        existing = household_subscription(household, "entertainment")
        if existing and existing.get("service_id") == profile["favorite_service_id"]:
            return  # household already has exactly this one

    chars = world.get("characters", {})
    exposure = sum(
        1 for other_id in c.get("relationships", {})
        if (chars.get(other_id) or {}).get("online_profile", {}).get("favorite_service_id")
           == profile["favorite_service_id"]
    )
    if exposure <= 0:
        return

    profile["subscribe_desire"] = profile.get("subscribe_desire", 0.0) + PEER_DESIRE_GAIN * exposure
    if profile["subscribe_desire"] < PEER_DESIRE_THRESHOLD:
        return

    from brain.intentions import add_intention
    add_intention(c, {
        "type":       "subscribe_service",
        "category":   "leisure",
        "priority":   25,
        "service_id": profile["favorite_service_id"],
        "reason":     "so many friends are into it -- you want to subscribe too",
    })
    profile["subscribe_desire"] = 0.0
