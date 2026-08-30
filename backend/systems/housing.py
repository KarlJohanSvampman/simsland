# =========================================================
# HOME DEFAULTS
# Sets expense fields used by economy.apply_expenses and
# the schedule generator. Call when creating or loading a home.
# =========================================================

def ensure_home_defaults(home):
    home.setdefault("quality",     0.5)
    home.setdefault("crime_risk",  0.3)
    home.setdefault("vacant",      True)
    home.setdefault("household_id", None)
    # Weekly recurring costs (currency units per week)
    home.setdefault("rent",        800)   # rent or mortgage payment
    home.setdefault("electricity", 60)    # power bill
    home.setdefault("water",       30)    # water/sewage
    home.setdefault("gasoline",    40)    # estimated weekly fuel (per household)
    home.setdefault("internet",    20)    # broadband
    return home


# =========================================================
# WEEKLY EXPENSE TOTAL FOR A HOME
# =========================================================

def weekly_home_expenses(home):
    """Sum all weekly recurring costs for a home."""
    return (
        home.get("rent",        0) +
        home.get("electricity", 0) +
        home.get("water",       0) +
        home.get("gasoline",    0) +
        home.get("internet",    0)
    )


# =========================================================
# GET HOME
# =========================================================

def get_home(

    world,

    home_id
):

    return world.get(
        "homes",
        {}
    ).get(
        home_id
    )


# =========================================================
# GET HOUSEHOLD HOME
# =========================================================

def get_household_home(household, world):
    hid = household.get("home_id")
    if not hid:
        return None
    return get_home(world, hid)


# =========================================================
# VACANCY
# =========================================================

def is_home_vacant(home):
    return home.get("vacant", False)


def get_vacant_homes(world):
    return [
        h for h in world.get("homes", {}).values()
        if h.get("vacant", True)
    ]


# =========================================================
# ASSIGN / VACATE
# =========================================================

def assign_household_to_home(household, home, world=None):
    home["household_id"]     = household["id"]
    home["vacant"]           = False
    household["home_id"]     = home["id"]
    # Restarts the convenience-tracking "settling in" clock (see
    # systems/convenience.py) -- whether this move was chosen or forced,
    # stability toward "established housing" begins counting from here.
    household["home_since_tick"] = world.get("tick", 0) if world else None


def vacate_home(home, household=None):
    home["household_id"] = None
    home["vacant"]       = True
    if household:
        household["home_id"] = None
