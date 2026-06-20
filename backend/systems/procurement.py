import random

from data.products import (
    PRODUCTS,
    affordable_products
)

from systems.household_storage import (
    add_household_resource
)

from systems.resource_runtime import (
    create_resource
)


# =========================================================
# PROCUREMENT METHODS
# =========================================================

PROCUREMENT_METHODS = [

    "in_person",

    "online"
]


# =========================================================
# CREATE PROCUREMENT REQUEST
# =========================================================

def create_procurement_request(

    c,

    category,

    priority=0.5,

    budget=None,

    quantity=1
):

    return {

        "category": category,

        "priority": priority,

        "budget": budget,

        "quantity": quantity,

        "created_by": c["id"]
    }


# =========================================================
# CHOOSE PROCUREMENT METHOD
# =========================================================

def choose_procurement_method(

    c,

    request
):

    traits = c.get(
        "traits",
        []
    )

    laziness = c.get(
        "laziness",
        0
    )

    energy = c.get(
        "needs",
        {}
    ).get(
        "energy",
        1
    )

    category = request.get(
        "category"
    )

    # =====================================================
    # LARGE ITEMS
    # =====================================================

    if category in [

        "furniture",

        "appliances"
    ]:

        return "online"

    # =====================================================
    # LOW ENERGY
    # =====================================================

    if energy < 0.25:

        return "online"

    # =====================================================
    # LAZY
    # =====================================================

    if (

        "lazy" in traits

        or

        laziness > 0.6
    ):

        if random.random() < 0.7:

            return "online"

    # =====================================================
    # DEFAULT
    # =====================================================

    return random.choice([

        "in_person",

        "online"
    ])


# =========================================================
# CHOOSE PRODUCT
# =========================================================

def choose_product(

    c,

    category,

    budget=None
):

    money = c.get(
        "money",
        0
    )

    if budget is None:
        budget = money

    products = affordable_products(

        category,

        budget
    )

    if not products:
        return None

    traits = c.get(
        "traits",
        []
    )

    scored = []

    for pid, product in products:

        score = 1.0

        quality = product.get(
            "quality",
            0.5
        )

        price = product.get(
            "price",
            0
        )

        # =================================================
        # TRAITS
        # =================================================

        if "frugal" in traits:

            score += (
                1.0 / max(1, price)
            ) * 100

        if "foodie" in traits:

            score += (
                quality * 3
            )

        if "materialistic" in traits:

            score += (
                quality * 2
            )

        if "lazy" in traits:

            if product.get(
                "delivery_supported"
            ):

                score += 1.5

        score += random.uniform(
            -0.5,
            0.5
        )

        scored.append((

            pid,

            product,

            score
        ))

    scored.sort(

        key=lambda x: x[2],

        reverse=True
    )

    return scored[0][1]


# =========================================================
# PURCHASE PRODUCT
# =========================================================

def purchase_product(

    c,

    household,

    product,

    world,

    method="in_person"
):

    if not product:
        return False

    price = product.get(
        "price",
        0
    )

    if c.get(
        "money",
        0
    ) < price:

        return False

    c["money"] -= price

    # =====================================================
    # ONLINE
    # =====================================================

    if method == "online":

        schedule_delivery(

            household,

            product,

            world
        )

        return True

    # =====================================================
    # IMMEDIATE ACQUISITION
    # =====================================================

    acquire_product(

        household,

        product
    )

    return True


# =========================================================
# ACQUIRE PRODUCT
# =========================================================

def acquire_product(

    household,

    product
):

    # =====================================================
    # RESOURCE PRODUCTS
    # =====================================================

    if "resource_type" in product:

        resource = create_resource(

            product[
                "resource_type"
            ],

            quantity=product.get(
                "quantity",
                1
            ),

            quality=product.get(
                "quality",
                0.5
            ),

            container=
                determine_container(
                    product
                )
        )

        add_household_resource(

            household,

            resource
        )

        return

    # =====================================================
    # OBJECT PRODUCTS
    # =====================================================

    household.setdefault(
        "owned_objects",
        []
    )

    household[
        "owned_objects"
    ].append({

        "object_type":
            product.get(
                "object_type"
            ),

        "quality":
            product.get(
                "quality",
                0.5
            ),

        "product":
            product
    })


# =========================================================
# DELIVERY
# =========================================================

def schedule_delivery(

    household,

    product,

    world
):

    world.setdefault(
        "deliveries",
        []
    )

    delay_hours = random.randint(
        12,
        48
    )

    arrival_tick = (

        world["tick"]

        +

        delay_hours * 3600
    )

    world[
        "deliveries"
    ].append({

        "household_id":
            household["id"],

        "product":
            product,

        "arrival_tick":
            arrival_tick,

        "status":
            "in_transit"
    })


# =========================================================
# CONTAINER
# =========================================================

def determine_container(

    product
):

    rt = product.get(
        "resource_type"
    )

    if rt in [

        "FOOD_PROTEIN",

        "FOOD_VEGETABLE",

        "MEAL",

        "STORED_MEAL",

        "PROCESSED_MEAL",

        "DRINK_MILK"
    ]:

        return "fridge"

    if rt in [

        "FOOD_CARB",

        "FOOD_SNACK",

        "FOOD_SPICE",

        "DRINK_COFFEE",

        "DRINK_TEA"
    ]:

        return "pantry"

    if rt in [

        "HYGIENE",

        "TOILET_PAPER"
    ]:

        return "bathroom"

    return "storage"