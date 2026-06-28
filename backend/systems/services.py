"""
Hired services system.

Flow:
  1. request_service(c, world, ...) → creates a contract in world["service_contracts"]
     Illicit services deduct cash immediately; legitimate ones bill at completion.
  2. update_services(world) runs on SLOW cadence:
     spawned      → spawn NPC worker outside household door
     en_route     → travel delay (10 sim-min), then notify household
     at_door      → auto-admit after 5 sim-min, move worker inside
     working      → execute one unit of work per tick; progress through detail list
     done         → bill household (if legitimate), remove NPC, mark departed
  3. Service worker NPCs in world["characters"] have is_service_worker=True;
     sim_loop skips them in the normal LLM agent cycle.

Contract schema:
{
    "id":             "contract_reconstruction_abc123",
    "service_type":   "reconstruction",
    "subtype":        "floor_tiling",
    "household_id":   "household_1",
    "requested_by":   "c1",
    "status":         "spawned",          # phase name
    "worker_id":      None,               # set when spawned
    "phase_tick":     12345,              # tick when current phase started
    "duration_ticks": 9000,
    "details": {
        # floor_tiling:  {"tiles": [{"x":1,"y":2,"material":"wood_floor_01"}, ...]}
        # paint_wall:    {"walls": [{"wall_id":"w1","material":"wallpaper_blue_01"},...]}
        # build_wall:    {"positions": [{"x":1,"y":2}, ...]}
        # remove_wall:   {"wall_ids": ["tile_key_1", ...]}
        # insert_door/window: {"positions": [{"x":1,"y":2,"rotation":0}, ...]}
        # appliance_repair:   {"prop_ids": ["prop_fridge_1", ...]}
        # childcare:     {"child_ids": ["c3"]}
        # cannabis/etc:  {}   (quantity field used)
        # companionship: {}
    },
    "quantity":       5,                  # units of work
    "cost":           220.0,
    "illicit":        False,
    "payment_method": "bill",             # "bill" | "cash"
    "work_progress":  0,                  # units completed so far
}
"""

import uuid
import random

from data.services import (
    SERVICE_CATALOG,
    WORKER_NAMES,
    TICKS_PER_HOUR,
)

# Phase constants
PHASE_SPAWNED   = "spawned"
PHASE_EN_ROUTE  = "en_route"
PHASE_AT_DOOR   = "at_door"
PHASE_WORKING   = "working"
PHASE_DONE      = "done"
PHASE_DEPARTED  = "departed"


# =========================================================
# REQUEST SERVICE
# =========================================================

def request_service(c, world, service_type, subtype, details, quantity=1):
    """
    A character hires a service.

    details — dict specific to the subtype:
      floor_tiling:    {"tiles": [{"x","y","material"}, ...]}
      paint_wall:      {"walls": [{"wall_id","material"}, ...]}
      build_wall:      {"positions": [{"x","y"}, ...]}
      remove_wall:     {"wall_ids": ["x,y", ...]}
      insert_door/window: {"positions": [{"x","y","rotation"}, ...]}
      appliance_repair: {"prop_ids": ["prop_id", ...]}
      childcare:       {"child_ids": ["c3"]}
      drug/escort:     {}  — quantity drives the cost

    Returns the contract dict, or None if cannot afford illicit service.
    """
    catalog = SERVICE_CATALOG.get(service_type)
    if not catalog:
        return None
    sub = catalog["subtypes"].get(subtype)
    if not sub:
        return None

    illicit = catalog.get("illicit", False)
    cost    = _estimate_cost(service_type, subtype, details, quantity, world)

    # Illicit: immediate cash payment
    if illicit:
        from systems.personal_items import wallet_cash, spend_cash
        if wallet_cash(c) < cost:
            return None
        spend_cash(c, cost)

    hid      = _find_household_id(c, world)
    duration = _estimate_duration(service_type, subtype, quantity, details)

    contract = {
        "id":             f"contract_{service_type}_{uuid.uuid4().hex[:6]}",
        "service_type":   service_type,
        "subtype":        subtype,
        "household_id":   hid,
        "requested_by":   c["id"],
        "status":         PHASE_SPAWNED,
        "worker_id":      None,
        "phase_tick":     world["tick"],
        "duration_ticks": duration,
        "details":        details,
        "quantity":       quantity,
        "cost":           cost,
        "illicit":        illicit,
        "payment_method": "cash" if illicit else "bill",
        "work_progress":  0,
    }

    world.setdefault("service_contracts", []).append(contract)
    return contract


# =========================================================
# UPDATE SERVICES  — called each SLOW tick from sim_loop
# =========================================================

def update_services(world):
    contracts = world.get("service_contracts", [])

    for contract in list(contracts):
        status = contract["status"]

        if status == PHASE_SPAWNED:
            _spawn_worker(contract, world)

        elif status == PHASE_EN_ROUTE:
            _advance_en_route(contract, world)

        elif status == PHASE_AT_DOOR:
            _advance_at_door(contract, world)

        elif status == PHASE_WORKING:
            _advance_working(contract, world)

        elif status == PHASE_DONE:
            _advance_done(contract, world)

    # Prune fully departed contracts
    world["service_contracts"] = [
        c for c in contracts if c["status"] != PHASE_DEPARTED
    ]


# =========================================================
# PHASES
# =========================================================

def _spawn_worker(contract, world):
    """Create a temporary NPC character just outside the household door."""
    stype  = contract["service_type"]
    sub    = SERVICE_CATALOG[stype]["subtypes"][contract["subtype"]]
    trait  = sub.get("worker_trait", "contractor")
    name   = random.choice(WORKER_NAMES.get(trait, ["Worker"]))

    # Position: just outside the front door of the household's home
    hid    = contract["household_id"]
    h      = world.get("households", {}).get(hid, {})
    home   = _get_home(h, world)
    dx, dy = random.uniform(-2, 2), -4
    wx     = home.get("x", 0) + dx
    wy     = home.get("y", 0) + dy

    wid = f"worker_{stype}_{uuid.uuid4().hex[:6]}"
    world.setdefault("characters", {})[wid] = {
        "id":               wid,
        "name":             name,
        "x":                wx,
        "y":                wy,
        "rotation":         0,
        "facing":           "north",
        "template":         "adult_base",
        "is_service_worker": True,
        "service_contract": contract["id"],
        "service_role":     trait,
        "animation_state":  "walk",
        "body": {
            "hunger": 20, "hydration": 80, "bladder": 5, "bowels": 5,
            "fatigue": 10, "sleep_debt": 0, "hygiene": 95, "odor": 0,
            "mouth_hygiene": 95, "recent_intake": 20,
            "stomach_discomfort": 0, "pain": 0, "sickness": 0,
        },
        "traits":          [trait],
        "inventory":       [],
        "worn":            {},
        "money":           0.0,
        "portfolio":       {},
        "watched_stocks":  [],
        "last_stock_check": 0,
        "active_intentions": [],
    }

    contract["worker_id"] = wid
    contract["status"]    = PHASE_EN_ROUTE
    contract["phase_tick"] = world["tick"]


def _advance_en_route(contract, world):
    """After a short travel delay, announce arrival."""
    travel_ticks = TICKS_PER_HOUR // 6   # 10 sim-minutes
    if world["tick"] - contract["phase_tick"] >= travel_ticks:
        contract["status"]     = PHASE_AT_DOOR
        contract["phase_tick"] = world["tick"]
        worker_name = _worker_name(contract, world)
        _notify(contract, world, "service_worker_arrived",
                f"{worker_name} has arrived at your door.")


def _advance_at_door(contract, world):
    """Auto-admit after a short wait; move worker inside."""
    wait_ticks = TICKS_PER_HOUR // 12   # 5 sim-minutes
    if world["tick"] - contract["phase_tick"] >= wait_ticks:
        _move_worker_inside(contract, world)
        contract["status"]     = PHASE_WORKING
        contract["phase_tick"] = world["tick"]


def _advance_working(contract, world):
    """Execute one unit of work. Transition to done when complete."""
    qty  = contract["quantity"]
    prog = contract["work_progress"]

    if prog >= qty:
        contract["status"]     = PHASE_DONE
        contract["phase_tick"] = world["tick"]
        return

    subtype = contract["subtype"]

    if subtype == "floor_tiling":
        _do_floor_tiling(contract, world)

    elif subtype == "paint_wall":
        _do_paint_wall(contract, world)

    elif subtype == "build_wall":
        _do_build_wall(contract, world)

    elif subtype == "remove_wall":
        _do_remove_wall(contract, world)

    elif subtype in ("insert_door", "insert_window"):
        _do_insert_opening(contract, world)

    elif subtype == "appliance_repair":
        _do_repair(contract, world)

    elif subtype in ("cannabis", "stimulants", "downers"):
        _do_drug_deal(contract, world)

    elif subtype == "companionship":
        _do_companionship(contract, world)

    else:
        # Time-based passive service (gardening, childcare) — just tick forward
        contract["work_progress"] += 1


def _advance_done(contract, world):
    """Bill if legitimate, remove worker NPC, mark departed."""
    if not contract["illicit"]:
        _bill_household(contract, world)

    # Notify completion
    sname = SERVICE_CATALOG[contract["service_type"]]["name"]
    subname = SERVICE_CATALOG[contract["service_type"]]["subtypes"][contract["subtype"]]["name"]
    _notify(contract, world, "service_complete",
            f"{sname} ({subname}) has been completed.")

    # Remove worker from world
    wid = contract.get("worker_id")
    if wid:
        world.get("characters", {}).pop(wid, None)

    contract["status"] = PHASE_DEPARTED


# =========================================================
# WORK EXECUTORS
# =========================================================

def _do_floor_tiling(contract, world):
    tiles = contract["details"].get("tiles", [])
    prog  = contract["work_progress"]
    if prog >= len(tiles):
        contract["work_progress"] = contract["quantity"]
        return
    t   = tiles[prog]
    x   = int(t.get("x", 0))
    y   = int(t.get("y", 0))
    mid = t.get("material", "wood_floor_01")
    mt  = world.get("definitions", {}).get("material_templates", {}).get(mid, {})
    world.setdefault("tiles", {})[f"{x},{y}"] = {
        "x":           x,
        "y":           y,
        "type":        "floor",
        "interior":    mt.get("interior", True),
        "floor":       mt.get("floor", True),
        "material":    mid,
        "placed_by":   contract["worker_id"],
        "building_id": _home_id(contract, world),
        "walkable":    True,
    }
    contract["work_progress"] += 1


def _do_paint_wall(contract, world):
    from systems.walls import paint_wall as _paint_wall
    walls = contract["details"].get("walls", [])
    prog  = contract["work_progress"]
    if prog >= len(walls):
        contract["work_progress"] = contract["quantity"]
        return
    w   = walls[prog]
    wid = w.get("wall_id")
    mat = w.get("material")
    if wid and mat:
        _paint_wall(world, wid, mat)
    contract["work_progress"] += 1


def _do_build_wall(contract, world):
    from systems.walls import create_wall
    positions = contract["details"].get("positions", [])
    prog      = contract["work_progress"]
    if prog >= len(positions):
        contract["work_progress"] = contract["quantity"]
        return
    pos         = positions[prog]
    x           = int(pos.get("x", 0))
    y           = int(pos.get("y", 0))
    orientation = pos.get("orientation", "v")
    material    = pos.get("material", "paint_white_matt")
    create_wall(
        world, x, y, orientation,
        building_id=_home_id(contract, world),
        load_bearing=False,
        material=material,
        interior=True,
    )
    contract["work_progress"] += 1


def _do_remove_wall(contract, world):
    from systems.walls import remove_wall
    wall_ids = contract["details"].get("wall_ids", [])
    prog     = contract["work_progress"]
    if prog >= len(wall_ids):
        contract["work_progress"] = contract["quantity"]
        return
    remove_wall(world, wall_ids[prog])   # silently skips load_bearing walls
    contract["work_progress"] += 1


def _do_insert_opening(contract, world):
    positions = contract["details"].get("positions", [])
    prog      = contract["work_progress"]
    if prog >= len(positions):
        contract["work_progress"] = contract["quantity"]
        return
    pos      = positions[prog]
    subtype  = contract["subtype"]
    template = "door_standard" if subtype == "insert_door" else "window_standard"
    world.setdefault("props", []).append({
        "id":          f"prop_{template}_{uuid.uuid4().hex[:6]}",
        "template":    template,
        "building_id": _home_id(contract, world),
        "x":           int(pos.get("x", 0)),
        "y":           int(pos.get("y", 0)),
        "rotation":    pos.get("rotation", 0),
        "state":       {"reserved_by": [], "placed_by": contract["worker_id"]},
    })
    contract["work_progress"] += 1


def _do_repair(contract, world):
    prop_ids = contract["details"].get("prop_ids", [])
    prog     = contract["work_progress"]
    if prog >= len(prop_ids):
        contract["work_progress"] = contract["quantity"]
        return
    pid = prop_ids[prog]
    for prop in world.get("props", []):
        if prop.get("id") == pid:
            s = prop.setdefault("state", {})
            s["durability"] = 1.0
            s["broken"]     = False
            break
    contract["work_progress"] += 1


def _do_drug_deal(contract, world):
    """Hand drug items to the requesting character immediately."""
    from systems.personal_items import add_item
    subtype = contract["subtype"]
    sub     = SERVICE_CATALOG["drug_dealer"]["subtypes"].get(subtype, {})
    effects = sub.get("item_effects", {})
    qty     = contract.get("quantity", 1)

    buyer = world.get("characters", {}).get(contract["requested_by"])
    if buyer:
        add_item(buyer, {
            "id":          f"item_{subtype}_{uuid.uuid4().hex[:6]}",
            "template_id": subtype,
            "type":        "consumable",
            "name":        subtype.replace("_", " ").title(),
            "category":    "drug",
            "stackable":   True,
            "max_stack":   10,
            "quantity":    qty,
            "consumable":  True,
            "uses":        qty,
            "effects":     effects,
            "illicit":     True,
        })

    contract["work_progress"] = contract["quantity"]


def _do_companionship(contract, world):
    """Satisfy socialize/play lt_needs for the buyer each work tick."""
    from systems.lt_needs import satisfy_lt_need
    buyer = world.get("characters", {}).get(contract["requested_by"])
    if buyer:
        satisfy_lt_need(buyer, "socialize", world)
        satisfy_lt_need(buyer, "play", world)
    contract["work_progress"] += 1


# =========================================================
# BILLING
# =========================================================

def _bill_household(contract, world):
    hid = contract["household_id"]
    h   = world.get("households", {}).get(hid)
    if not h:
        return
    svc    = SERVICE_CATALOG[contract["service_type"]]
    sub    = svc["subtypes"][contract["subtype"]]
    bill = {
        "type":        "bill",
        "subtype":     "service",
        "from":        svc["name"],
        "subject":     f"{svc['name']} — {sub['name']}",
        "amount":      contract["cost"],
        "due_tick":    world["tick"] + 7 * 24 * TICKS_PER_HOUR,
        "contract_id": contract["id"],
    }
    h.setdefault("bills_due", []).append(bill)
    h.setdefault("mailbox", {}).setdefault("items", []).append(bill)


# =========================================================
# COST / DURATION
# =========================================================

def _estimate_cost(service_type, subtype, details, quantity, world):
    sub  = SERVICE_CATALOG[service_type]["subtypes"][subtype]
    mode = sub.get("price_mode")

    if mode == "per_tile":
        tiles  = details.get("tiles", [])
        n      = max(quantity, len(tiles), 1)
        mat_cost = 0.0
        for t in tiles:
            mid   = t.get("material", "wood_floor_01")
            entry = world.get("market", {}).get("catalog", {}).get(mid)
            mat_cost += entry["current_price"] if entry else sub.get("labor_rate", 8.0)
        return round(sub["labor_rate"] * n + mat_cost, 2)

    elif mode == "per_wall":
        walls = details.get("walls", details.get("positions", details.get("wall_ids", [])))
        n = max(quantity, len(walls), 1)
        return round((sub.get("labor_rate", 50.0) + sub.get("material_rate", 0.0)) * n, 2)

    elif mode == "per_unit":
        n = max(quantity, 1)
        return round(
            (sub.get("labor_rate", 50.0) + sub.get("material_rate", 0.0) + sub.get("unit_price", 0.0)) * n,
            2,
        )

    elif mode == "hourly":
        hours = sub.get("duration_hours", details.get("duration_hours", 1))
        return round(sub.get("hourly_rate", 20.0) * hours, 2)

    return 0.0


def _estimate_duration(service_type, subtype, quantity, details):
    sub  = SERVICE_CATALOG[service_type]["subtypes"][subtype]
    mode = sub.get("price_mode")
    if mode in ("per_tile", "per_wall", "per_unit"):
        n = max(quantity, 1)
        return sub.get("duration_per_unit", 3600) * n
    elif mode == "hourly":
        hours = sub.get("duration_hours", details.get("duration_hours", 1))
        return int(hours * TICKS_PER_HOUR)
    return TICKS_PER_HOUR


# =========================================================
# HELPERS
# =========================================================

def _find_household_id(c, world):
    for hid, h in world.get("households", {}).items():
        if c["id"] in h.get("members", []):
            return hid
    return None


def _home_id(contract, world):
    hid = contract["household_id"]
    return world.get("households", {}).get(hid, {}).get("home_id")


def _get_home(household, world):
    hid = household.get("home_id")
    return world.get("homes", {}).get(hid, {}) if hid else {}


def _worker_name(contract, world):
    wid = contract.get("worker_id")
    if wid:
        w = world.get("characters", {}).get(wid)
        if w:
            return w.get("name", "Worker")
    return "Worker"


def _move_worker_inside(contract, world):
    wid  = contract.get("worker_id")
    hid  = contract["household_id"]
    h    = world.get("households", {}).get(hid, {})
    home = _get_home(h, world)
    if wid and wid in world.get("characters", {}):
        world["characters"][wid]["x"] = home.get("x", 0) + 1
        world["characters"][wid]["y"] = home.get("y", 0) + 1
        world["characters"][wid]["animation_state"] = "idle"


def _notify(contract, world, event_type, message):
    hid = contract["household_id"]
    h   = world.get("households", {}).get(hid)
    if h:
        h.setdefault("notifications", []).append({
            "type":    event_type,
            "message": message,
            "tick":    world["tick"],
        })


# =========================================================
# CONTEXT HELPERS
# =========================================================

def available_services():
    """Flat list of all service/subtype combos for LLM context."""
    result = []
    for stype, catalog in SERVICE_CATALOG.items():
        for subtype, sub in catalog["subtypes"].items():
            result.append({
                "service_type": stype,
                "subtype":      subtype,
                "name":         f"{catalog['name']} — {sub['name']}",
                "illicit":      catalog.get("illicit", False),
            })
    return result


def active_contracts_for_household(world, household_id):
    """Active contracts for a given household (not yet departed)."""
    return [
        c for c in world.get("service_contracts", [])
        if c["household_id"] == household_id
        and c["status"] != PHASE_DEPARTED
    ]
                                              