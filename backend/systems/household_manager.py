"""
systems/household_manager.py

Household administration: family name, owned floorplans (building_ids),
and member characters — driven by the mailbox prop's admin modal
(frontend), routed through backend/api/household.py.

Deliberately independent of housing.py's home_id/homes system, which
tracks a single abstract rent/bills unit per household. A household may
have both a home_id (economy) and separately zero-or-more building_ids
(placed floorplans this module manages) — the two are not reconciled.
"""

from uuid import uuid4
from systems.schema_defaults import ensure_household_defaults


def create_household(world, name):
    h = {"id": str(uuid4()), "name": name}
    ensure_household_defaults(h)
    world["households"][h["id"]] = h
    return h


def assign_building_to_household(world, building, household):
    old_hid = building.get("owner_household_id")
    if old_hid and old_hid != household["id"]:
        old = world["households"].get(old_hid)
        if old and building["id"] in old.get("building_ids", []):
            old["building_ids"].remove(building["id"])
    building["owner_household_id"] = household["id"]
    if building["id"] not in household["building_ids"]:
        household["building_ids"].append(building["id"])


def unassign_building(building, household=None):
    building["owner_household_id"] = None
    if household and building["id"] in household.get("building_ids", []):
        household["building_ids"].remove(building["id"])


def add_member_to_household(world, character, household):
    old_hid = character.get("household_id")
    if old_hid and old_hid != household["id"]:
        old = world["households"].get(old_hid)
        if old and character["id"] in old.get("members", []):
            old["members"].remove(character["id"])
    character["household_id"] = household["id"]
    if character["id"] not in household["members"]:
        household["members"].append(character["id"])


def remove_member_from_household(character, household):
    character["household_id"] = None
    if character["id"] in household.get("members", []):
        household["members"].remove(character["id"])
