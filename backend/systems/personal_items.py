"""
Personal inventory system.

Each character carries c["inventory"] — a list of item instances.
world["placed_items"] holds items dropped/placed in the world (rendered as 3D).

Item instance schema:
  id            — "item_{template_id}_{hex6}"
  template_id   — key into definitions.json item_templates
  name          — display name
  object_type   — "phone" | "computer" | "clothing" | "key" | "food" | ...
  location      — "pocket" | "held" | "placed"
  quantity      — 1 for non-stackables
  states        — runtime dict initialised from template's initial_states
                  e.g. {"battery": 100, "powered_on": True, "dirty": False}
  x, y          — set when location == "placed"
  placed_by     — char id, set when placed
  placed_at_tick

Items with template["model"] AND location == "placed" are rendered in the world.
Items in pocket/held are invisible in world.
"""

import uuid


# =========================================================
# ITEM FACTORY
# =========================================================

def make_item(template_id, quantity=1, world=None, **overrides):
    """
    Create a fresh item instance from a template.
    Initialises states from template's initial_states dict.
    """
    from data.item_templates import ITEM_TEMPLATES as _PY_TEMPLATES
    templates = (
        (world or {}).get("definitions", {}).get("item_templates")
        or _PY_TEMPLATES
    )
    template = templates.get(template_id)
    if not template:
        raise ValueError(f"Unknown item template: {template_id!r}")

    # Deep-copy initial_states so instances don't share the same dict
    initial_states = dict(template.get("initial_states") or {})

    item = {
        "id":          f"item_{template_id}_{uuid.uuid4().hex[:6]}",
        "template_id": template_id,
        "quantity":    quantity,
        "location":    "pocket",   # default: carried in pocket
        "states":      initial_states,
    }
    # Merge flat template fields (name, category, size, object_type, model, …)
    for k, v in template.items():
        if k not in ("initial_states",):
            item.setdefault(k, v)
    # Caller overrides last
    item.update(overrides)
    return item


def make_item_stack(template_id, quantity, world=None, **overrides):
    """Convenience: make_item with explicit quantity for stackable items."""
    return make_item(template_id, quantity=quantity, world=world, **overrides)


def create_generated_item(template_id, world, c=None, **overrides):
    """make_item() plus real per-instance LLM content for shared-model
    media items (book/magazine/dvd/music_disc -- see item_templates'
    "content_category" field and llm/item_content.py). `world` is
    required (unlike make_item) since the generation session lives on
    it. Bridges the async LLM call the same way action_router.py's
    _route_make_argument() already does (run_llm_call, llm/llm_gate.py)
    rather than a second bridging mechanism -- safe to call from sync
    system code as long as the caller isn't itself holding world_lock()
    (see this project's established constraint on real LLM calls)."""
    item = make_item(template_id, world=world, **overrides)
    content_category = item.get("content_category")
    if not content_category:
        return item

    from llm.item_content import generate_item_content, fallback_content
    from llm.llm_gate import run_llm_call
    content = run_llm_call(generate_item_content(c, world, item))
    item["content"] = content if isinstance(content, dict) and content else fallback_content(content_category)
    return item


# =========================================================
# BACKWARD-COMPAT FACTORIES (used before template system)
# =========================================================

SMARTPHONE_ACTIONS = [
    "check_stocks", "browse_news", "order_delivery", "send_message",
    "call_contact", "open_banking_app", "use_rideshare",
]
BASIC_PHONE_ACTIONS = ["send_message", "call_contact"]


def make_smartphone(owner_id=None, model="smartphone_budget", world=None):
    """Create a smartphone instance from template."""
    try:
        item = make_item(model, world=world)
    except ValueError:
        item = make_item("smartphone_budget", world=world)
    item["owner_id"] = owner_id
    return item


def make_house_key(home_id, building_id=None, owner_id=None):
    return {
        "id":          f"item_key_{home_id}_{uuid.uuid4().hex[:4]}",
        "template_id": "house_key",
        "object_type": "key",
        "name":        "House Key",
        "location":    "pocket",
        "states":      {},
        "quantity":    1,
        "home_id":     home_id,
        "building_id": building_id or home_id,
        "owner_id":    owner_id,
    }


def make_key(kind, ref_id, owner_id=None):
    """Generic key factory for car/mailbox. House keys keep using
    make_house_key() above -- has_key_for()/lock_home()/unlock_home()/
    can_unlock_door() below are all built around its home_id-matching
    semantics specifically (a real door-lock mechanic), and there's no
    equivalent car/mailbox lock to integrate with yet, just possession."""
    labels = {"car": "Car Key", "mailbox": "Mailbox Key"}
    return {
        "id":          f"item_key_{kind}_{uuid.uuid4().hex[:6]}",
        "template_id": f"{kind}_key",
        "object_type": "key",
        "key_kind":    kind,
        "name":        labels.get(kind, "Key"),
        "location":    "pocket",
        "states":      {},
        "quantity":    1,
        "ref_id":      ref_id,
        "owner_id":    owner_id,
    }


def has_key_for_ref(c, kind, ref_id):
    """Car/mailbox key check -- see make_key(). Separate from
    has_key_for() (house-only, keyed on home_id)."""
    return any(
        i.get("object_type") == "key" and i.get("key_kind") == kind and i.get("ref_id") == ref_id
        for i in get_inventory(c)
    )


def make_wallet(cash=100.0, owner_id=None, contents=None):
    """Cash stays on the simpler, already-wired states.cash path (see
    wallet_cash/spend_cash/add_cash below) rather than becoming a discrete
    item -- there's no real-world benefit to a "$1 bill" item instance.
    ID/bank/credit cards, though, are genuinely held *inside* the wallet:
    pre-stamped with the same items/capacity/accepted_categories shape
    containers.py's add_to_container/remove_from_container expect (mirrors
    item_templates["wallet"]["container"]), so this works with the
    existing generic container machinery from the moment it's created,
    not just once something happens to call ensure_item_container() on it.
    """
    return {
        "id":       f"item_wallet_{uuid.uuid4().hex[:6]}",
        "template_id": "wallet",
        "object_type": "wallet",
        "name":     "Wallet",
        "location": "pocket",
        "states":   {"cash": round(float(cash), 2)},
        "quantity": 1,
        "owner_id": owner_id,
        # legacy flat key for backward compat
        "cash":     round(float(cash), 2),
        "items":    contents or [],
        "capacity": 6,
        "accepted_categories": ["document", "financial"],
    }


def make_id_card(char_id, char_name, owner_id=None):
    return {
        "id":        f"item_idcard_{uuid.uuid4().hex[:6]}",
        "template_id": "id_card",
        "object_type": "document",
        "category":  "document",
        "name":      "ID Card",
        "location":  "pocket",
        "states":    {},
        "quantity":  1,
        "size":      1,
        "char_id":   char_id,
        "char_name": char_name,
        "owner_id":  owner_id,
    }


# Starter financial institutions -- each acts as both a bank (accounts/
# secured loans, see banking.py once that round ships) and a credit card
# provider. Defined here (not just in definitions.json's company_templates,
# which don't exist yet for these) so make_bank_card() has something real
# to reference immediately; the banking round replaces "bank" from a bare
# name string with a resolved company_templates lookup + a real account
# record, without needing to change this factory's call sites.
STARTER_BANKS = ("JPMC", "Morgan Stanley", "Barclays", "TD Bank", "Bank of America")


def make_bank_card(bank=None, account_number=None, owner_id=None):
    import random
    bank = bank or random.choice(STARTER_BANKS)
    return {
        "id":        f"item_bankcard_{uuid.uuid4().hex[:6]}",
        "template_id": "bank_card",
        "object_type": "bank_card",
        "category":  "financial",
        "name":      f"{bank} Bank Card",
        "location":  "pocket",
        "states":    {},
        "quantity":  1,
        "size":      1,
        "bank":      bank,
        "account_number": account_number or f"{random.randint(10**9, 10**10 - 1)}",
        "owner_id":  owner_id,
    }


def make_credit_card(provider, max_credit, owner_id=None):
    """Apply-only per credit.py's approval flow -- never starting
    inventory (see character_gen.py, which only ever grants a bank_card).
    The credit LINE lives directly on this item (max_credit/current_debt)
    rather than referencing an external account, unlike make_bank_card()
    -- a credit card isn't a deposit account, it's a lender's ledger of
    what this one character owes."""
    return {
        "id":          f"item_creditcard_{uuid.uuid4().hex[:6]}",
        "template_id": "credit_card",
        "object_type": "credit_card",
        "category":    "financial",
        "name":        f"{provider} Credit Card",
        "location":    "pocket",
        "states":      {},
        "quantity":    1,
        "size":        1,
        "provider":    provider,
        "max_credit":  round(float(max_credit), 2),
        "current_debt": 0.0,
        # Baseline + accumulator for credit.py::tick_monthly_card_cycle()'s
        # "was the minimum paid this month" check -- _payments_this_month
        # is incremented by make_payment() and compared against
        # _month_start_debt/12, deliberately NOT inferred from the
        # current_debt delta (a new charge raises current_debt too, which
        # would make someone who paid in full but also spent that month
        # look delinquent).
        "_month_start_debt": 0.0,
        "_payments_this_month": 0.0,
        "owner_id":    owner_id,
    }


# =========================================================
# INVENTORY HELPERS
# =========================================================

def get_inventory(c):
    return c.setdefault("inventory", [])


def has_item(c, object_type):
    """True if character carries an item with matching object_type."""
    return any(i.get("object_type") == object_type for i in get_inventory(c))


def has_item_template(c, template_id):
    """True if character carries an item from a specific template."""
    return any(i.get("template_id") == template_id for i in get_inventory(c))


def get_item(c, object_type):
    """Return first item matching object_type, or None."""
    for i in get_inventory(c):
        if i.get("object_type") == object_type:
            return i
    return None


def get_item_by_template(c, template_id):
    """Return first item from a specific template, or None."""
    for i in get_inventory(c):
        if i.get("template_id") == template_id:
            return i
    return None


def get_item_by_id(c, item_id):
    for i in get_inventory(c):
        if i.get("id") == item_id:
            return i
    return None


def add_item(c, item):
    # setdefault, not a forced overwrite: an item created for one
    # character but ending up in another's hands (found, borrowed,
    # gifted, stolen) should keep tracking its real owner, not silently
    # get reassigned just because someone else is now carrying it --
    # action_router.py's "check someone else's device" snooping gate
    # already depends on owner_id meaning the true owner, not the
    # current holder. This is a backstop for the common case (a
    # character's own purchase/creation never got owner_id stamped at
    # all) covering every caller that funnels through here, rather than
    # patching each item factory/call site individually.
    item.setdefault("owner_id", c.get("id"))
    get_inventory(c).append(item)


def remove_item(c, item_id):
    inv = get_inventory(c)
    c["inventory"] = [i for i in inv if i.get("id") != item_id]


def recall_overdue_loans(world):
    """Periodic sweep (see sim_loop.py) -- returns any item past its
    loan due_tick (set by systems/proposals.py::_finalize_item_loan) to
    the real owner's inventory automatically. Always honored, no
    "borrower forgot to give it back" enforcement gap -- that kind of
    friction (declined return, relationship hit) is a plausible future
    addition, not implemented here."""
    chars = world.get("characters", {})
    tick = world.get("tick", 0)
    for borrower in list(chars.values()):
        for item in list(get_inventory(borrower)):
            loan = item.get("loan")
            if not loan or tick < loan.get("due_tick", 0):
                continue
            owner = chars.get(loan.get("owner_id"))
            if not owner:
                continue
            remove_item(borrower, item["id"])
            item.pop("loan", None)
            item["location"] = "pocket"
            record_item_history(item, world, "returned", by=borrower["id"], to_owner=owner["id"])
            add_item(owner, item)


def record_item_history(item, world, event, **fields):
    """item["history"] -- a provenance log, not a state machine: every
    purchase/gift/loan/sale appends one entry rather than overwriting
    anything, so "how did this end up here" stays answerable later.
    Callers that change ownership (give_item, a completed sale/trade)
    are responsible for updating item["owner_id"] themselves alongside
    calling this -- this function only logs, it never mutates owner_id."""
    item.setdefault("history", []).append({
        "tick": world.get("tick", 0),
        "event": event,
        **fields,
    })


# =========================================================
# PLACED ITEMS — world["placed_items"]
# Items dropped/put down in the world; rendered as 3D if template has model
# =========================================================

def drop_item(c, item_id, world):
    """
    Remove item from character inventory and place it at their position.
    Returns the placed instance or None if not found.
    """
    item = get_item_by_id(c, item_id)
    if not item:
        return None
    remove_item(c, item_id)
    item["location"]       = "placed"
    item["x"]             = c.get("x", 0)
    item["y"]             = c.get("y", 0)
    item["placed_by"]     = c.get("id")
    item["placed_at_tick"]= world.get("tick", 0)
    world.setdefault("placed_items", {})[item_id] = item
    from sim_loop import _mark_dirty
    _mark_dirty(world, placed_item_ids={item_id})
    return item


def place_item(c, item_id, x, y, world):
    """Place item at specific coordinates."""
    item = get_item_by_id(c, item_id)
    if not item:
        return None
    remove_item(c, item_id)
    item["location"]        = "placed"
    item["x"]              = x
    item["y"]              = y
    item["placed_by"]      = c.get("id")
    item["placed_at_tick"] = world.get("tick", 0)
    world.setdefault("placed_items", {})[item_id] = item
    from sim_loop import _mark_dirty
    _mark_dirty(world, placed_item_ids={item_id})
    return item


def pick_up_item(c, item_id, world):
    """
    Move item from world placed_items into character inventory.
    Returns item or None.
    """
    placed = world.get("placed_items", {})
    item = placed.pop(item_id, None)
    if not item:
        return None
    item["location"] = "pocket"
    item.pop("x", None)
    item.pop("y", None)
    item.pop("placed_by", None)
    item.pop("placed_at_tick", None)
    add_item(c, item)
    return item


def break_item(c, item_id, world):
    """Destroy an item — remove from inventory, emit debris if desired."""
    item = get_item_by_id(c, item_id)
    if item:
        remove_item(c, item_id)
        return item
    # Also check placed items
    placed = world.get("placed_items", {})
    return placed.pop(item_id, None)


def give_item(giver, receiver, item_id, world):
    """Transfer item from giver to receiver's inventory -- a real
    ownership change (unlike add_item()'s setdefault backstop), so
    owner_id is reassigned outright and logged."""
    item = get_item_by_id(giver, item_id)
    if not item:
        return False
    remove_item(giver, item_id)
    item["location"] = "pocket"
    prior_owner = item.get("owner_id")
    item["owner_id"] = receiver.get("id")
    record_item_history(item, world, "gifted",
                         by=giver.get("id"), from_owner=prior_owner, to_owner=receiver.get("id"))
    add_item(receiver, item)
    return True


# =========================================================
# PHONE
# =========================================================

def get_phone(c):
    """Return the character's phone instance (any smartphone template), or None."""
    for item in get_inventory(c):
        if item.get("object_type") == "phone":
            return item
    return None


def has_smartphone(c):
    return get_phone(c) is not None


def phone_battery(c):
    phone = get_phone(c)
    if not phone:
        return 0.0
    return phone.get("states", {}).get("battery", phone.get("battery", 1.0))


def phone_is_usable(c):
    """Phone exists and has enough battery to use."""
    return phone_battery(c) > 0.05


def phone_actions(c):
    phone = get_phone(c)
    if phone:
        return phone.get("apps", SMARTPHONE_ACTIONS)
    return []


def can_do_phone_action(c, action):
    return phone_is_usable(c) and action in phone_actions(c)


# =========================================================
# COMPUTER
# =========================================================

def get_computer(c, world):
    """A laptop the character is carrying, or one left at home by someone
    in their own household (world["placed_items"], the same drop_item/
    pick_up_item mechanism systems/phone.py uses for a set-down phone) --
    the "might use a computer instead if at home" alternative."""
    for item in get_inventory(c):
        if item.get("object_type") == "computer":
            return item
    household_id = c.get("household_id")
    if not household_id:
        return None
    characters = world.get("characters", {})
    for item in world.get("placed_items", {}).values():
        if item.get("object_type") != "computer":
            continue
        owner = characters.get(item.get("placed_by"))
        if owner and owner.get("household_id") == household_id:
            return item
    return None


def has_computer(c, world):
    return get_computer(c, world) is not None


# =========================================================
# WALLET / CASH
# =========================================================

def wallet_cash(c):
    w = get_item(c, "wallet")
    if w:
        return w.get("states", {}).get("cash", w.get("cash", 0.0))
    return 0.0


def spend_cash(c, amount):
    w = get_item(c, "wallet")
    if not w:
        return False
    cash = w.get("states", {}).get("cash", w.get("cash", 0.0))
    if cash < amount:
        return False
    new_cash = round(cash - amount, 2)
    w.setdefault("states", {})["cash"] = new_cash
    w["cash"] = new_cash  # legacy flat key
    return True


def add_cash(c, amount):
    w = get_item(c, "wallet")
    if not w:
        w = make_wallet(0.0, owner_id=c.get("id"))
        add_item(c, w)
    cash = w.get("states", {}).get("cash", w.get("cash", 0.0))
    new_cash = round(cash + amount, 2)
    w.setdefault("states", {})["cash"] = new_cash
    w["cash"] = new_cash


def pay_from_wallet(c, world, price):
    """Pay `price` the way a real person reaches for their wallet: cash
    first, then a bank card (debits the linked account via
    systems/banking.py), then a credit card (charges it via
    systems/credit.py). Shared by every checkout path in the game --
    originally written just for systems/convenience_store.py's register,
    factored out here so systems/procurement.py's general market
    purchases (which used to only ever deduct c["money"]) use the exact
    same fallback logic rather than a second, divergent copy. Returns
    True if any method covered the full price."""
    if wallet_cash(c) >= price and spend_cash(c, price):
        return True

    wallet = get_item(c, "wallet")
    if not wallet:
        return False

    from systems.banking import get_balance, withdraw, BANK_NAME_TO_KEY
    for item in wallet.get("items", []):
        if item.get("object_type") != "bank_card":
            continue
        bank_key = BANK_NAME_TO_KEY.get(item.get("bank"))
        if not bank_key:
            continue
        balance = get_balance(world, bank_key, item["account_number"])
        if balance is not None and balance >= price:
            if withdraw(world, bank_key, item["account_number"], price):
                return True

    from systems.credit import charge as charge_credit_card
    for item in wallet.get("items", []):
        if item.get("object_type") != "credit_card":
            continue
        if charge_credit_card(item, price):
            return True

    return False


# =========================================================
# HOUSE KEYS + DOOR LOCKING
# =========================================================

def has_key_for(c, home_id):
    for i in get_inventory(c):
        if i.get("object_type") == "key" and i.get("home_id") == home_id:
            return True
        # backward compat
        if i.get("type") == "house_key" and i.get("home_id") == home_id:
            return True
    return False


def _find_door_in_world(world, building_id, door_id):
    for building in world.get("buildings", []):
        if building["id"] != building_id:
            continue
        for door in building.get("doors", []):
            if door["id"] == door_id:
                return door
    return None


def can_unlock_door(c, world, building_id, door_id):
    door = _find_door_in_world(world, building_id, door_id)
    if not door:
        return False
    if not door.get("locked"):
        return True
    home_id = door.get("home_id")
    if not home_id:
        return True
    return has_key_for(c, home_id)


def use_key_to_lock(c, world, building_id, door_id):
    door = _find_door_in_world(world, building_id, door_id)
    if not door:
        return False
    home_id = door.get("home_id")
    if home_id and not has_key_for(c, home_id):
        return False
    door["locked"] = True
    return True


def use_key_to_unlock(c, world, building_id, door_id):
    door = _find_door_in_world(world, building_id, door_id)
    if not door:
        return False
    home_id = door.get("home_id")
    if home_id and not has_key_for(c, home_id):
        return False
    door["locked"] = False
    return True


def lock_home(c, world):
    home_id = c.get("household_id") or c.get("home_id")
    if not home_id or not has_key_for(c, home_id):
        return False
    for building in world.get("buildings", []):
        if building["id"] != home_id:
            continue
        for door in building.get("doors", []):
            if door.get("home_id") == home_id:
                door["locked"] = True
    return True


def unlock_home(c, world):
    home_id = c.get("household_id") or c.get("home_id")
    if not home_id or not has_key_for(c, home_id):
        return False
    for building in world.get("buildings", []):
        if building["id"] != home_id:
            continue
        for door in building.get("doors", []):
            if door.get("home_id") == home_id:
                door["locked"] = False
    return True


# =========================================================
# INVENTORY SUMMARY — for LLM context
# =========================================================

def inventory_summary(c):
    items = get_inventory(c)
    if not items:
        return []
    result = []
    for item in items:
        otype = item.get("object_type") or item.get("type", "unknown")
        states = item.get("states", {})
        entry = {
            "id":          item.get("id"),
            "template_id": item.get("template_id"),
            "name":        item.get("name", otype),
            "object_type": otype,
            "location":    item.get("location", "pocket"),
        }
        if states:
            entry["states"] = states
        if otype == "key":
            entry["home_id"] = item.get("home_id")
        result.append(entry)
    return result
