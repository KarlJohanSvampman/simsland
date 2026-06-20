def apply_expenses(world):

    cal = world.get("calendar", {})

    # run weekly (Monday 00:00)
    if not (cal.get("weekday") == "Monday" and cal.get("hour") == 0):
        return

    env = world["environment"]

    for h in world["households"].values():

        utility = 60 * env.get("power_cost_index", 1)
        food = 120 * env.get("cost_of_living_index", 1)

        total = round(utility + food, 2)

        h.setdefault("bills_due", []).append({
            "type": "weekly",
            "amount": total,
            "remaining": total,
            "contributors": {}
        })

def household_economy(world, household_id):
    h=world["households"].get(household_id)
    if not h: return None
    members=[world["characters"][cid] for cid in h.get("members",[]) if cid in world["characters"]]
    return {**h,"members":[m["name"] for m in members],"tax_rate":world["environment"].get("tax_rate"),"market":world.get("market")}
