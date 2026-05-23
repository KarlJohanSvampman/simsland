from data.items import ITEMS


# =========================================================
# ENSURE
# =========================================================

def ensure_inventory(c):

    c.setdefault(
        "inventory",
        []
    )


# =========================================================
# ADD ITEM
# =========================================================

def add_item(

    c,

    item_id,

    quantity=1
):

    ensure_inventory(c)

    for item in c[
        "inventory"
    ]:

        if item["id"] == item_id:

            item["quantity"] += quantity
            return

    c["inventory"].append({

        "id": item_id,

        "quantity": quantity
    })


# =========================================================
# REMOVE ITEM
# =========================================================

def remove_item(

    c,

    item_id,

    quantity=1
):

    ensure_inventory(c)

    for item in c[
        "inventory"
    ]:

        if item["id"] != item_id:
            continue

        item["quantity"] -= quantity

        if item["quantity"] <= 0:

            c["inventory"].remove(
                item
            )

        return True

    return False


# =========================================================
# HAS ITEM
# =========================================================

def has_item(

    c,

    item_id,

    quantity=1
):

    ensure_inventory(c)

    for item in c[
        "inventory"
    ]:

        if (

            item["id"] == item_id

            and

            item["quantity"] >= quantity
        ):

            return True

    return False


# =========================================================
# COUNT CATEGORY
# =========================================================

def count_category(

    c,

    category
):

    ensure_inventory(c)

    total = 0

    for item in c[
        "inventory"
    ]:

        cfg = ITEMS.get(
            item["id"],
            {}
        )

        if cfg.get(
            "category"
        ) == category:

            total += item[
                "quantity"
            ]

    return total


# =========================================================
# FIND FOOD
# =========================================================

def find_food(c):

    ensure_inventory(c)

    foods = []

    for item in c[
        "inventory"
    ]:

        cfg = ITEMS.get(
            item["id"],
            {}
        )

        if cfg.get(
            "category"
        ) == "food":

            foods.append(item)

    return foods