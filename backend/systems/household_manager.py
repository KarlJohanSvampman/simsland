"""
systems/household_manager.py

Household administration: family name, owned floorplans (building_ids),
and member characters — driven by the mailbox prop's admin modal
(frontend), routed through backend/api/household.py.

housing.py's home_id/homes system (a single abstract rent/bills unit per
household) used to be genuinely disconnected from the real building a
household actually lives in -- home_id was never set anywhere in this
file, confirmed live (a household built through the real create_
household -> assign_building_to_household -> add_member_to_household
flow always had home_id=None), so get_household_home() always returned
None and economy.py::apply_expenses() silently fell back to its flat
$150/week placeholder for every household in the game regardless of
their actual home. _ensure_household_housing_setup() below reconciles
this -- home_id now tracks the first building a household is assigned
(a household that later acquires a SECOND building keeps its original
home_id, matching the spirit of "independent, not forced 1:1" this
docstring used to describe) -- and, once the household actually has both
a home and a member to be the borrower, originates its starter mortgage
and enrolls mandatory home insurance (systems/loans.py::
originate_mortgage, systems/subscriptions.py) -- per explicit user
direction, every household starts with both. Idempotent, called from
both assign_building_to_household() and add_member_to_household() since
generate_world.py's real call order assigns the building BEFORE the
member exists to borrow against.
"""

from uuid import uuid4
from systems.schema_defaults import ensure_household_defaults


def create_household(world, name):
    h = {"id": str(uuid4()), "name": name}
    ensure_household_defaults(h)
    world["households"][h["id"]] = h
    return h


def _ensure_household_housing_setup(world, household):
    home_id = household.get("home_id")
    if not home_id:
        return
    from systems.housing import ensure_home_defaults
    home = world.setdefault("homes", {}).setdefault(home_id, {"id": home_id})
    ensure_home_defaults(home)
    home["household_id"] = household["id"]
    home["vacant"] = False

    from systems.loans import originate_mortgage
    originate_mortgage(world, household, home)

    from systems.subscriptions import has_home_insurance, subscribe_household, default_home_insurance_service_id
    if not has_home_insurance(household):
        default_id = default_home_insurance_service_id(world.get("definitions", {}))
        if default_id:
            subscribe_household(world, household, default_id)


def assign_building_to_household(world, building, household):
    old_hid = building.get("owner_household_id")
    if old_hid and old_hid != household["id"]:
        old = world["households"].get(old_hid)
        if old and building["id"] in old.get("building_ids", []):
            old["building_ids"].remove(building["id"])
    building["owner_household_id"] = household["id"]
    if building["id"] not in household["building_ids"]:
        household["building_ids"].append(building["id"])
    # NOT setdefault -- ensure_household_defaults() already puts a real
    # "home_id": None key on every household at creation, so setdefault
    # would be a no-op (the key already exists, just with a None value).
    if household.get("home_id") is None:
        household["home_id"] = building["id"]
    _ensure_household_housing_setup(world, household)


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
    _grant_household_keys(world, character, household)
    _ensure_household_housing_setup(world, household)


def _grant_household_keys(world, character, household):
    """House/car/mailbox keys, granted for whichever the household
    actually has -- called on every join (not just generation-time) since
    a household's building/car/mailbox can be assigned after a character
    already lives there. has_key_for()/has_key_for_ref() guard against
    duplicate grants on repeat calls (e.g. re-adding an existing member)."""
    from systems.personal_items import (
        make_house_key, has_key_for, make_key, has_key_for_ref,
    )
    from systems.vehicles import household_car
    from systems.props import get_props_by_template

    home_id = household["id"]
    if household.get("building_ids") and not has_key_for(character, home_id):
        character.setdefault("inventory", []).append(
            make_house_key(home_id=home_id, building_id=household["building_ids"][0],
                            owner_id=character["id"]))

    car = household_car(world, home_id)
    if car and not has_key_for_ref(character, "car", car["id"]):
        character.setdefault("inventory", []).append(
            make_key("car", car["id"], owner_id=character["id"]))

    for mailbox in get_props_by_template(world, "mailbox"):
        if mailbox.get("household_id") == home_id and not has_key_for_ref(character, "mailbox", mailbox["id"]):
            character.setdefault("inventory", []).append(
                make_key("mailbox", mailbox["id"], owner_id=character["id"]))


def remove_member_from_household(character, household):
    character["household_id"] = None
    if character["id"] in household.get("members", []):
        household["members"].remove(character["id"])
