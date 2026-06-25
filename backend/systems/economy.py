def apply_expenses(world):
    """
    Issue a weekly bill to each household covering all recurring costs.
    Reads per-home expense fields (rent, electricity, water, gasoline,
    internet) then adds market-index-scaled food costs on top.
    """
    cal = world.get("calendar", {})
    if not (cal.get("weekday") == "Monday" and cal.get("hour") == 0):
        return

    from systems.housing import get_household_home, weekly_home_expenses
    env = world.get("environment", {})

    for h in world.get("households", {}).values():
        home      = get_household_home(h, world)
        n_members = max(1, len(h.get("members", [])))

        # Fixed home costs (rent, utilities, gasoline, internet)
        if home:
            fixed = weekly_home_expenses(home) * env.get("cost_of_living_index", 1.0)
        else:
            fixed = 150.0 * env.get("cost_of_living_index", 1.0)

        # Variable: food scales with household size and market price
        food = 80.0 * n_members * env.get("cost_of_living_index", 1.0)

        total = round(fixed + food, 2)

        h.setdefault("bills_due", []).append({
            "type":         "weekly",
            "amount":       total,
            "remaining":    total,
            "contributors": {},
            "breakdown": {
                "fixed_home": round(fixed, 2),
                "food":       round(food, 2),
            },
        })

        # Cache so the schedule generator can read it without recalculating
        h["weekly_expenses"] = total


def household_economy(world, household_id):
    h = world["households"].get(household_id)
    if not h:
        return None
    members = [
        world["characters"][cid]
        for cid in h.get("members", [])
        if cid in world["characters"]
    ]
    return {
        **h,
        "members":    [m["name"] for m in members],
        "tax_rate":   world["environment"].get("tax_rate"),
        "market":     world.get("market"),
    }
