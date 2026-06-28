"""
Personal inventory system.

Each character carries a list of items in c["inventory"].
Items are dicts with at minimum: id, type, name.

Supported types:
  smartphone  — enables phone-based actions (stocks, news, delivery, messaging)
  house_key   — unlocks/locks doors in a specific home (matched by home_id)
  wallet      — physical cash on hand (separate from c["money"] / bank balance)
  id_card     — future: needed for certain interactions
"""

import uuid


# =========================================================
# ITEM FACTORY — create instances from templates
# =========================================================

def make_item(template_id, quantity=1, world=None, **overrides):
    """
    Create an item instance from a template.
    Prefers world["definitions"]["item_templates"] (JSON), falls back to Python dict.
    """
    from data.item_templates import ITEM_TEMPLATES as _PY_TEMPLATES
    templates = (
        (world or {}).get("definitions", {}).get("item_templates")
        or _PY_TEMPLATES
    )
    template = templates.get(template_id)
    if not template:
        raise ValueError(f"Unknown item template: {template_id!r}")
    item = {
        "id":          f"item_{template_id}_{uuid.uuid4().hex[:6]}",
        "template_id": template_id,
        "quantity":    quantity,
        **template,
        **overrides,
    }
    return item


def make_item_stack(template_id, quantity, **overrides):
    """Convenience: make_item with explicit quantity for stackable items."""
    return make_item(template_id, quantity=quantity, **overrides)

# =========================================================
# PHONE ACTIONS
# Things a smartphone enables that a plain phone doesn't
# =========================================================

SMARTPHONE_ACTIONS = [
    "check_stocks",
    "browse_news",
    "order_delivery",
    "send_message",
    "call_contact",
    "open_banking_app",
    "use_rideshare",
]

BASIC_PHONE_ACTIONS = [
    "send_message",
    "call_contact",
]


# =========================================================
# ITEM FACTORIES
# =========================================================

def make_smartphone(owner_id=None, model="budget_phone"):
    return {
        "id":       f"item_phone_{uuid.uuid4().hex[:6]}",
        "type":     "smartphone",
        "name":     "Smartphone",
        "model":    model,
        "owner_id": owner_id,
        "battery":  1.0,
        "apps":     list(SMARTPHONE_ACTIONS),
    }


def make_house_key(home_id, building_id=None, owner_id=None):
    """
    A key tied to a specific home. Unlocks any door whose home_id matches.
    building_id defaults to home_id if not supplied.
    """
    return {
        "id":          f"item_key_{home_id}_{uuid.uuid4().hex[:4]}",
        "type":        "house_key",
        "name":        "House Key",
        "home_id":     home_id,
        "building_id": building_id or home_id,
        "owner_id":    owner_id,
    }


def make_wallet(cash=100.0, owner_id=None):
    return {
        "id":       f"item_wallet_{uuid.uuid4().hex[:6]}",
        "type":     "wallet",
        "name":     "Wallet",
        "cash":     round(float(cash), 2),
        "owner_id": owner_id,
    }


def make_id_card(char_id, char_name, owner_id=None):
    return {
        "id":        f"item_idcard_{uuid.uuid4().hex[:6]}",
        "type":      "id_card",
        "name":      "ID Card",
        "char_id":   char_id,
        "char_name": char_name,
        "owner_id":  owner_id,
    }


# =========================================================
# INVENTORY HELPERS
# =========================================================

def get_inventory(c):
    return c.setdefault("inventory", [])


def has_item(c, item_type):
    return any(i.get("type") == item_type for i in get_inventory(c))


def get_item(c, item_type):
    """Return first item of given type, or None."""
    for i in get_inventory(c):
        if i.get("type") == item_type:
            return i
    return None


def get_item_by_id(c, item_id):
    for i in get_inventory(c):
        if i.get("id") == item_id:
            return i
    return None


def add_item(c, item):
    get_inventory(c).append(item)


def remove_item(c, item_id):
    inv = get_inventory(c)
    c["inventory"] = [i for i in inv if i.get("id") != item_id]


# =========================================================
# SMARTPHONE
# =========================================================

def has_smartphone(c):
    return has_item(c, "smartphone")


def phone_actions(c):
    phone = get_item(c, "smartphone")
    if phone:
        return phone.get("apps", SMARTPHONE_ACTIONS)
    if has_item(c, "basic_phone"):
        return list(BASIC_PHONE_ACTIONS)
    return []


def can_do_phone_action(c, action):
    return action in phone_actions(c)


# =========================================================
# WALLET / CASH
# =========================================================

def wallet_cash(c):
    w = get_item(c, "wallet")
    return w["cash"] if w else 0.0


def spend_cash(c, amount):
    """
    Deduct from wallet. Returns True on success, False if insufficient.
    """
    w = get_item(c, "wallet")
    if not w or w["cash"] < amount:
        return False
    w["cash"] = round(w["cash"] - amount, 2)
    return True


def add_cash(c, amount):
    """Add cash to wallet (wages paid in cash, etc.)."""
    w = get_item(c, "wallet")
    if not w:
        w = make_wallet(0.0, owner_id=c.get("id"))
        add_item(c, w)
    w["cash"] = round(w["cash"] + amount, 2)


# =========================================================
# HOUSE KEYS + DOOR LOCKING
# =========================================================

def has_key_for(c, home_id):
    """Does this character carry a key for the given home?"""
    for i in get_inventory(c):
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


def _get_door_home_id(door):
    """
    A door's home_id is either explicit or defaults to its building's id.
    Doors marked with home_id restrict key access.
    """
    return door.get("home_id")


def can_unlock_door(c, world, building_id, door_id):
    """
    True if the character has a key whose home_id matches this door's home_id,
    OR if the door has no home_id (any resident can pass).
    """
    door = _find_door_in_world(world, building_id, door_id)
    if not door:
        return False
    if not door.get("locked"):
        return True  # door isn't locked
    home_id = _get_door_home_id(door)
    if not home_id:
        return True  # no key requirement
    return has_key_for(c, home_id)


def use_key_to_lock(c, world, building_id, door_id):
    """Lock a door. Returns True on success."""
    door = _find_door_in_world(world, building_id, door_id)
    if not door:
        return False
    home_id = _get_door_home_id(door)
    if home_id and not has_key_for(c, home_id):
        return False
    door["locked"] = True
    return True


def use_key_to_unlock(c, world, building_id, door_id):
    """Unlock a door. Returns True on success."""
    door = _find_door_in_world(world, building_id, door_id)
    if not door:
        return False
    home_id = _get_door_home_id(door)
    if home_id and not has_key_for(c, home_id):
        return False
    door["locked"] = False
    return True


def lock_home(c, world):
    """Lock all keyed doors in the character's home."""
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
    """Unlock all keyed doors in the character's home."""
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
        t = item.get("type")
        if t == "smartphone":
            result.append({
                "type":    "smartphone",
                "battery": item.get("battery", 1.0),
                "apps":    item.get("apps", []),
            })
        elif t == "house_key":
            result.append({
                "type":    "house_key",
                "home_id": item.get("home_id"),
            })
        elif t == "wallet":
            result.append({
                "type": "wallet",
                "cash": item.get("cash", 0.0),
            })
        elif t == "id_card":
            result.append({
                "type": "id_card",
          