"""
systems/telecom.py

Mobile data -- a consumable the character's phone carries, NOT a
recurring subscription (that's home internet, systems/subscriptions.py's
"internet" category, billed weekly on the household). Daily consumption
rate is trait-driven: "materialistic"/"impulsive" -> heavy, "frugal" ->
light, everyone else -> medium -- the closest real, plausible trait
hooks that exist in this codebase (confirmed via research: no
"extroverted"/"tech-savvy" trait exists to gate on instead, and these
weren't fabricated to fit). When a character's phone runs out, mobile-
data-dependent phone actions are gated until they buy more (see
has_mobile_data()).
"""

DAILY_GB_LIGHT = 1.0
DAILY_GB_MEDIUM = 1.5
DAILY_GB_HEAVY = 2.0

_HEAVY_DATA_TRAITS = {"materialistic", "impulsive"}
_LIGHT_DATA_TRAITS = {"frugal"}


def daily_data_usage_gb(c):
    tr = set(c.get("traits", [])) | set(c.get("personality_traits", []))
    if tr & _HEAVY_DATA_TRAITS:
        return DAILY_GB_HEAVY
    if tr & _LIGHT_DATA_TRAITS:
        return DAILY_GB_LIGHT
    return DAILY_GB_MEDIUM


def tick_daily_data_usage(c, world, home_fraction=0.0):
    """Called once per real calendar day (see sim_loop.py), with the day
    that just completed's home fraction already rolled over by systems/
    home_presence.py::roll_over_home_presence_day() -- that function
    owns the one daily reset now (a second consumer, systems/
    withdrawal_concern.py, needs the same underlying data, so this no
    longer does its own destructive consume-and-reset).

    Time spent at home doesn't cost mobile data IF the household
    actually has a home internet (ISP) subscription -- being home with
    no wifi to fall back on still burns the phone's own data, same as
    being out. This is the actual point of paying for home internet in
    the first place, per the user's own framing -- without an ISP
    subscription, home time buys no discount at all."""
    from systems.subscriptions import household_subscription

    household = world.get("households", {}).get(c.get("household_id"))
    has_isp = bool(household and household_subscription(household, "internet"))

    usage = daily_data_usage_gb(c)
    if has_isp:
        usage *= (1.0 - home_fraction)

    remaining = c.get("phone_data_gb_remaining", 0)
    c["phone_data_gb_remaining"] = max(0, round(remaining - usage, 2))


def has_mobile_data(c):
    return c.get("phone_data_gb_remaining", 0) > 0


def buy_mobile_data(world, c, service_id, gb_amount):
    """Buys gb_amount GB from a mobile_data service_template, paid from
    the character's own wallet cash (systems/personal_items.py -- the
    same real payment path any other personal purchase in this codebase
    already uses). Returns True on success."""
    if gb_amount <= 0:
        return False
    defs = world.get("definitions", {})
    st = defs.get("service_templates", {}).get(service_id)
    if not st or st.get("category") != "mobile_data":
        return False

    cost = round(st.get("cost_per_gb", 0) * gb_amount, 2)
    from systems.personal_items import spend_cash
    if not spend_cash(c, cost):
        return False

    c["phone_data_gb_remaining"] = round(c.get("phone_data_gb_remaining", 0) + gb_amount, 2)
    c["mobile_data_provider_id"] = service_id
    return True
