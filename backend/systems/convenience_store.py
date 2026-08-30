"""
systems/convenience_store.py

On-grid physical retail: a real building (floorplan_templates
["convenience_store_a"]) with a staffed register (prop_templates
["register"]) the customer and cashier both physically walk to, via the
real pathfinding stack (navigation.py::plan_character_route, movement.py
::update_character_movement, interactions.py::begin_interaction) --
unlike every other business in this game, which is an abstracted
off-grid trip (systems/offgrid.py). An ATM (prop_templates["atm"]) sits
just outside for cash/card conversion, per the original spec.

No general "NPC assigned to work at a specific prop" system exists
anywhere else in this codebase (systems/jobs.py is 100% abstract, no
building/prop link) -- update_convenience_store_staffing() below is a
narrow, purpose-built version of that just for the register.
"""

import random

REGISTER_TEMPLATE = "register"
ATM_TEMPLATE = "atm"


def _register_props(world):
    return [p for p in world.get("props", []) if p.get("template") == REGISTER_TEMPLATE]


def _store_business(world):
    return (world.get("definitions", {}).get("company_templates") or {}).get("convenience_store")


def _anchor_world_pos(prop, interaction):
    anchor = next((a for a in prop.get("anchors", []) if a.get("interaction") == interaction), None)
    if not anchor:
        return None
    from systems.anchors import get_world_anchor_position
    return get_world_anchor_position(prop, anchor)


# =========================================================
# CASHIER STAFFING
# =========================================================

def update_convenience_store_staffing(world):
    """Called on a slow cadence (see sim_loop.py) -- walks each
    register's assigned cashier (register["cashier_id"], set once at
    hiring/setup time) to the staff_register anchor once the store opens,
    and leaves them be once they're there. No forced walk-away when
    closed in this pass -- an acceptable simplification, not a
    correctness gap (nothing else depends on the cashier leaving)."""
    from systems.business_hours import is_open
    business = _store_business(world)
    if not business:
        return
    open_now = is_open(business, world, "storefront")
    if not open_now:
        return

    for register in _register_props(world):
        cashier_id = register.get("cashier_id")
        if not cashier_id:
            continue
        cashier = world.get("characters", {}).get(cashier_id)
        if not cashier or cashier.get("alive") is False:
            continue
        if cashier.get("is_moving") or cashier.get("route"):
            continue  # already walking somewhere (to the register or otherwise)

        pos = _anchor_world_pos(register, "staff_register")
        if not pos:
            continue
        ax, ay = pos
        already_there = (
            cashier.get("building_id") == register.get("building_id")
            and abs(cashier.get("x", 0) - ax) < 1
            and abs(cashier.get("y", 0) - ay) < 1
        )
        if already_there:
            continue

        from systems.navigation import plan_character_route
        if plan_character_route(world, cashier, ax, ay):
            cashier["is_moving"] = True
            cashier["animation_state"] = "walk"


# =========================================================
# CHECKOUT
# =========================================================

def resolve_checkout(c, world, act):
    """Called from activities.py::complete_activity() for
    activity_type=="convenience_store_checkout". The catalog entry was
    already picked at start_activity() time (act["state"]["catalog_entry"]
    -- see activities.py) since this generic interaction system has no
    channel for external item selection. Pays via cash first, then a
    bank card, then a credit card -- the same fallback order a real
    person reaches for their wallet in."""
    entry = (act.get("state") or {}).get("catalog_entry")
    if not entry:
        return
    price = entry.get("price", 0)
    if price <= 0:
        return

    if not _pay(c, world, price):
        return  # couldn't afford it by any method -- walked in, walked out empty-handed

    from systems.personal_items import make_item, add_item, record_item_history
    try:
        item = make_item(entry["item_template"], world=world, owner_id=c["id"])
    except ValueError:
        return
    record_item_history(item, world, "purchased", by=c["id"], from_source="convenience_store",
                         price=price)
    add_item(c, item)


def _pay(c, world, price):
    # See systems/personal_items.py::pay_from_wallet() -- the cash / bank
    # card / credit card fallback originally written here now lives there
    # so systems/procurement.py's general market purchases share the exact
    # same logic instead of a second, divergent copy.
    from systems.personal_items import pay_from_wallet
    return pay_from_wallet(c, world, price)


# =========================================================
# ATM
# =========================================================

WITHDRAW_TARGET_CASH = 100.0
LOW_CASH_THRESHOLD = 20.0


def resolve_atm_use(c, world, act):
    """No structured withdraw/deposit-amount input reaches this generic
    interaction (see convenience_store_checkout's docstring for the same
    limitation) -- so the ATM resolves the plausible default: if
    carrying little cash and holding a bank card with funds, withdraw up
    to WITHDRAW_TARGET_CASH; otherwise, if carrying a lot of cash and a
    bank card, deposit the excess back onto the card. At most one of the
    two happens per visit, same as a real ATM trip."""
    from systems.personal_items import wallet_cash, add_cash, spend_cash, get_item
    wallet = get_item(c, "wallet")
    if not wallet:
        return

    from systems.banking import get_balance, withdraw, deposit, BANK_NAME_TO_KEY
    bank_card = next((i for i in wallet.get("items", []) if i.get("object_type") == "bank_card"), None)
    if not bank_card:
        return
    bank_key = BANK_NAME_TO_KEY.get(bank_card.get("bank"))
    if not bank_key:
        return

    cash = wallet_cash(c)
    if cash < LOW_CASH_THRESHOLD:
        balance = get_balance(world, bank_key, bank_card["account_number"]) or 0
        amount = min(WITHDRAW_TARGET_CASH - cash, balance)
        if amount > 0 and withdraw(world, bank_key, bank_card["account_number"], amount):
            add_cash(c, amount)
    elif cash > WITHDRAW_TARGET_CASH * 2:
        excess = cash - WITHDRAW_TARGET_CASH
        if spend_cash(c, excess):
            deposit(world, bank_key, bank_card["account_number"], excess)
