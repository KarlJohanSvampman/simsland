from fastapi import APIRouter

from db import load_world, save_world, world_lock
from systems.props import get_prop_by_id
from systems.building_entrances import get_building_by_id
from systems.household_manager import (
    create_household,
    assign_building_to_household,
    unassign_building,
    add_member_to_household,
    remove_member_from_household,
)

router = APIRouter()


# =========================================================
# CREATE HOUSEHOLD (and link the mailbox that created it)
# =========================================================

@router.post("/household/create")
def create(sim_id: str, payload: dict):
    with world_lock():
        world = load_world(sim_id)

        # mailbox_prop_id is optional -- a household is a valid data
        # record without a physical mailbox (e.g. created ahead of time
        # from the Character Creator, before any map location exists);
        # only link one if the caller supplied a real prop id.
        mailbox_id = payload.get("mailbox_prop_id")
        mailbox = get_prop_by_id(world, mailbox_id) if mailbox_id else None
        if mailbox_id and not mailbox:
            return {"ok": False, "error": "mailbox prop not found"}

        household = create_household(world, payload.get("name"))
        if mailbox:
            mailbox["household_id"] = household["id"]

        save_world(sim_id, world)
        return {"ok": True, "household": household}


# =========================================================
# SET FAMILY NAME
# =========================================================

@router.post("/household/set_name")
def set_name(sim_id: str, payload: dict):
    with world_lock():
        world = load_world(sim_id)

        household = world.get("households", {}).get(payload["household_id"])
        if not household:
            return {"ok": False, "error": "household not found"}

        household["name"] = payload.get("name")
        save_world(sim_id, world)
        return {"ok": True, "household": household}


@router.post("/household/set_newspaper_subscription")
def set_newspaper_subscription(sim_id: str, payload: dict):
    with world_lock():
        world = load_world(sim_id)

        household = world.get("households", {}).get(payload["household_id"])
        if not household:
            return {"ok": False, "error": "household not found"}

        household["newspaper_subscription"] = bool(payload.get("subscribed"))
        save_world(sim_id, world)
        return {"ok": True, "household": household}


# =========================================================
# ASSIGN / UNASSIGN BUILDING (floorplan)
# =========================================================

@router.post("/household/set_building_address")
def set_building_address(sim_id: str, payload: dict):
    with world_lock():
        world = load_world(sim_id)

        building = get_building_by_id(world, payload["building_id"])
        if not building:
            return {"ok": False, "error": "building not found"}

        building["address"] = payload.get("address")
        save_world(sim_id, world)
        return {"ok": True, "building": building}


@router.post("/household/assign_building")
def assign_building(sim_id: str, payload: dict):
    with world_lock():
        world = load_world(sim_id)

        household = world.get("households", {}).get(payload["household_id"])
        if not household:
            return {"ok": False, "error": "household not found"}

        building = get_building_by_id(world, payload["building_id"])
        if not building:
            return {"ok": False, "error": "building not found"}

        assign_building_to_household(world, building, household)
        save_world(sim_id, world)
        return {"ok": True, "household": household, "building": building}


@router.post("/household/unassign_building")
def unassign_building_route(sim_id: str, payload: dict):
    with world_lock():
        world = load_world(sim_id)

        building = get_building_by_id(world, payload["building_id"])
        if not building:
            return {"ok": False, "error": "building not found"}

        household = world.get("households", {}).get(building.get("owner_household_id"))
        unassign_building(building, household)
        save_world(sim_id, world)
        return {"ok": True, "building": building}


# =========================================================
# ASSIGN / UNASSIGN CHARACTER
# =========================================================

@router.post("/household/add_member")
def add_member(sim_id: str, payload: dict):
    with world_lock():
        world = load_world(sim_id)

        household = world.get("households", {}).get(payload["household_id"])
        if not household:
            return {"ok": False, "error": "household not found"}

        character = world.get("characters", {}).get(payload["character_id"])
        if not character:
            return {"ok": False, "error": "character not found"}

        add_member_to_household(world, character, household)
        save_world(sim_id, world)
        return {"ok": True, "household": household}


@router.post("/household/remove_member")
def remove_member(sim_id: str, payload: dict):
    with world_lock():
        world = load_world(sim_id)

        character = world.get("characters", {}).get(payload["character_id"])
        if not character:
            return {"ok": False, "error": "character not found"}

        household = world.get("households", {}).get(character.get("household_id"))
        if not household:
            return {"ok": False, "error": "character has no household"}

        remove_member_from_household(character, household)
        save_world(sim_id, world)
        return {"ok": True, "household": household}


# =========================================================
# LISTINGS — available floorplans / all characters
# =========================================================

@router.get("/household/list")
def list_households(sim_id: str):
    world = load_world(sim_id)

    households = [
        {"id": hid, "name": h.get("name"), "member_count": len(h.get("members", []))}
        for hid, h in world.get("households", {}).items()
    ]
    return {"ok": True, "households": households}


@router.get("/household/available_buildings")
def available_buildings(sim_id: str):
    world = load_world(sim_id)

    buildings = [
        {"id": b["id"], "template": b.get("template"), "x": b.get("x"), "y": b.get("y"),
         "address": b.get("address")}
        for b in world.get("buildings", [])
        if b.get("owner_household_id") is None
    ]
    return {"ok": True, "buildings": buildings}


@router.get("/household/characters")
def all_characters(sim_id: str):
    world = load_world(sim_id)

    characters = [
        {
            "id": c["id"],
            "name": c.get("name"),
            "household_id": c.get("household_id"),
            "x": c.get("x"),
            "y": c.get("y"),
            "alive": c.get("alive") is not False,
            "posture": c.get("posture"),
            "off_grid": c.get("off_grid", False),
            "off_grid_reason": c.get("off_grid_reason"),
            "return_tick": c.get("return_tick"),
            "travel_state": c.get("travel_state"),
        }
        for c in world.get("characters", {}).values()
    ]
    return {"ok": True, "tick": world.get("tick", 0), "characters": characters}


# =========================================================
# ADMIN DETAIL — resolved household for the modal
# =========================================================
# Named /admin (not the bare /household/{id}) to avoid colliding with the
# pre-existing GET /api/household/{household_id} in main.py, which returns
# household_economy()'s financial-summary shape — a different endpoint
# for a different purpose, left untouched.

@router.get("/household/{household_id}/admin")
def admin_detail(household_id: str, sim_id: str):
    world = load_world(sim_id)

    household = world.get("households", {}).get(household_id)
    if not household:
        return {"ok": False, "error": "household not found"}

    characters = world.get("characters", {})

    def _wallet_of(char):
        return next((i for i in char.get("inventory", []) if i.get("object_type") == "wallet"), None)

    def _credit_cards_of(char):
        wallet = _wallet_of(char)
        contents = wallet.get("items", []) if wallet else []
        return [
            {"provider": card.get("provider"), "current_debt": card.get("current_debt"),
             "max_credit": card.get("max_credit")}
            for card in contents if card.get("object_type") == "credit_card"
        ]

    members = [
        {
            "id": cid, "name": characters[cid].get("name"),
            # Finances -- read-only summary for Character Creator's Household
            # tab (banking/credit/loan round). Cash lives on the wallet item
            # instance (personal_items.py::make_wallet), not a bare c["money"]
            # field -- see wallet_cash()/spend_cash()/add_cash().
            "wallet_cash": (_wallet_of(characters[cid]) or {}).get("states", {}).get("cash"),
            "credit_score": characters[cid].get("credit_score"),
            "government_debt": characters[cid].get("government_debt"),
            "credit_cards": _credit_cards_of(characters[cid]),
        }
        for cid in household.get("members", [])
        if cid in characters
    ]

    buildings_by_id = {b["id"]: b for b in world.get("buildings", [])}
    buildings = [
        {"id": bid, "template": buildings_by_id[bid].get("template"),
         "x": buildings_by_id[bid].get("x"), "y": buildings_by_id[bid].get("y"),
         "address": buildings_by_id[bid].get("address")}
        for bid in household.get("building_ids", [])
        if bid in buildings_by_id
    ]

    # Loans live on the household (systems/loans.py -- joint co-borrowers),
    # not per-character. Resolve borrower names for display.
    loans = [
        {**loan, "borrower_names": [characters.get(bid, {}).get("name", bid)
                                     for bid in loan.get("borrower_ids", [])]}
        for loan in (household.get("loans") or {}).values()
    ]

    # Physical mailbox contents (systems/mail.py) -- bills/formal-request
    # letters, distinct from c["inbox"] (per-character SMS/call/email/
    # voicemail, systems/inbox.py). Never trimmed, so this list doubles
    # as full history; "opened" tracks whether it's been picked up (see
    # activities.py's "check_mail" activity, which sets it True via
    # sort_household_mail()).
    mailbox = household.get("mailbox") or {}
    mail_items = list(mailbox.get("items", []))

    return {
        "ok": True,
        "household": {
            "id": household["id"],
            "name": household.get("name"),
            "members": members,
            "buildings": buildings,
            "loans": loans,
            # Household-level aggregate finances -- distinct from each
            # member's personal wallet/credit above. shared_funds/wealth
            # are the pooled household pot (systems/economy.py); bills_due
            # is the pending-bills queue attempt_pay_bills() works through.
            "shared_funds": household.get("shared_funds", 0),
            "wealth": household.get("wealth", 0),
            "bills_due": household.get("bills_due", []),
            "newspaper_subscription": household.get("newspaper_subscription", False),
            "mail": {
                "unopened_count": mailbox.get("unopened_count", 0),
                "items": mail_items,
            },
        },
    }
