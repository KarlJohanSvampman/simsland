# =========================================================
# PRODUCT CATALOG
# =========================================================

PRODUCTS = {

    # =====================================================
    # GROCERIES
    # =====================================================

    "cheap_frozen_dinner": {

        "category": "groceries",

        "resource_type":
            "PROCESSED_MEAL",

        "price": 8,

        "quality": 0.35,

        "nutrition": 0.45,

        "brand": "Budget Choice",

        "delivery_supported": True
    },

    "premium_frozen_dinner": {

        "category": "groceries",

        "resource_type":
            "PROCESSED_MEAL",

        "price": 18,

        "quality": 0.72,

        "nutrition": 0.75,

        "brand": "Chef Select",

        "delivery_supported": True
    },

    "bag_of_rice": {

        "category": "groceries",

        "resource_type":
            "FOOD_CARB",

        "quantity": 5,

        "price": 12,

        "quality": 0.55,

        "delivery_supported": True
    },

    "potatoes": {

        "category": "groceries",

        "resource_type":
            "FOOD_CARB",

        "quantity": 4,

        "price": 6,

        "quality": 0.6,

        "delivery_supported": True
    },

    "chicken_pack": {

        "category": "groceries",

        "resource_type":
            "FOOD_PROTEIN",

        "quantity": 4,

        "price": 15,

        "quality": 0.7,

        "delivery_supported": True
    },

    "ground_beef": {

        "category": "groceries",

        "resource_type":
            "FOOD_PROTEIN",

        "quantity": 3,

        "price": 14,

        "quality": 0.65,

        "delivery_supported": True
    },

    "vegetable_mix": {

        "category": "groceries",

        "resource_type":
            "FOOD_VEGETABLE",

        "quantity": 4,

        "price": 10,

        "quality": 0.7,

        "delivery_supported": True
    },

    "fruit_basket": {

        "category": "groceries",

        "resource_type":
            "FOOD_FRUIT",

        "quantity": 6,

        "price": 9,

        "quality": 0.8,

        "delivery_supported": True
    },

    "chips": {

        "category": "groceries",

        "resource_type":
            "FOOD_SNACK",

        "quantity": 3,

        "price": 5,

        "quality": 0.45,

        "delivery_supported": True
    },

    "coffee_pack": {

        "category": "groceries",

        "resource_type":
            "DRINK_COFFEE",

        "quantity": 10,

        "price": 14,

        "quality": 0.75,

        "delivery_supported": True
    },

    "tea_box": {

        "category": "groceries",

        "resource_type":
            "DRINK_TEA",

        "quantity": 12,

        "price": 8,

        "quality": 0.7,

        "delivery_supported": True
    },

    "milk_carton": {

        "category": "groceries",

        "resource_type":
            "DRINK_MILK",

        "quantity": 4,

        "price": 6,

        "quality": 0.7,

        "delivery_supported": True
    },

    "soft_drink_pack": {

        "category": "groceries",

        "resource_type":
            "DRINK_SOFT",

        "quantity": 6,

        "price": 9,

        "quality": 0.5,

        "delivery_supported": True
    },

    "beer_case": {

        "category": "groceries",

        "resource_type":
            "DRINK_ALCOHOL",

        "quantity": 12,

        "price": 22,

        "quality": 0.55,

        "delivery_supported": True
    },

    # =====================================================
    # HYGIENE
    # =====================================================

    "soap_pack": {

        "category": "hygiene",

        "resource_type":
            "HYGIENE",

        "quantity": 6,

        "price": 8,

        "quality": 0.55,

        "delivery_supported": True
    },

    "premium_soap_pack": {

        "category": "hygiene",

        "resource_type":
            "HYGIENE",

        "quantity": 6,

        "price": 18,

        "quality": 0.9,

        "delivery_supported": True
    },

    "toilet_paper_pack": {

        "category": "hygiene",

        "resource_type":
            "TOILET_PAPER",

        "quantity": 16,

        "price": 14,

        "quality": 0.7,

        "delivery_supported": True
    },

    "cleaning_bundle": {

        "category": "cleaning",

        "resource_type":
            "CLEANING",

        "quantity": 10,

        "price": 15,

        "quality": 0.65,

        "delivery_supported": True
    },

    # =====================================================
    # APPLIANCES
    # =====================================================

    "cheap_microwave": {

        "category": "appliances",

        "object_type":
            "microwave",

        "price": 80,

        "quality": 0.35,

        "durability": 0.4,

        "delivery_required": True,

        "delivery_supported": True
    },

    "premium_microwave": {

        "category": "appliances",

        "object_type":
            "microwave",

        "price": 240,

        "quality": 0.9,

        "durability": 0.95,

        "delivery_required": True,

        "delivery_supported": True
    },

    "cheap_fridge": {

        "category": "appliances",

        "object_type":
            "fridge",

        "price": 500,

        "quality": 0.45,

        "durability": 0.55,

        "delivery_required": True,

        "delivery_supported": True
    },

    # =====================================================
    # FURNITURE
    # =====================================================

    "cheap_sofa": {

        "category": "furniture",

        "object_type":
            "sofa",

        "price": 350,

        "quality": 0.35,

        "comfort": 0.45,

        "delivery_required": True,

        "delivery_supported": True
    },

    "comfortable_sofa": {

        "category": "furniture",

        "object_type":
            "sofa",

        "price": 1200,

        "quality": 0.92,

        "comfort": 0.95,

        "delivery_required": True,

        "delivery_supported": True
    },

    "cheap_bed": {

        "category": "furniture",

        "object_type":
            "bed",

        "price": 450,

        "quality": 0.4,

        "comfort": 0.5,

        "delivery_required": True,

        "delivery_supported": True
    },

    # =====================================================
    # CLOTHING
    # =====================================================

    "basic_tshirt": {

        "category": "clothing",

        "price": 15,

        "quality": 0.45,

        "style": 0.35,

        "delivery_supported": True
    },

    "designer_jacket": {

        "category": "clothing",

        "price": 240,

        "quality": 0.95,

        "style": 0.98,

        "delivery_supported": True
    },

    # =====================================================
    # ELECTRONICS
    # =====================================================

    "budget_phone": {

        "category": "electronics",

        "object_type":
            "phone",

        "price": 250,

        "quality": 0.45,

        "delivery_supported": True
    },

    "gaming_laptop": {

        "category": "electronics",

        "object_type":
            "computer",

        "price": 1800,

        "quality": 0.92,

        "delivery_required": True,

        "delivery_supported": True
    }
}


# =========================================================
# HELPERS
# =========================================================

def get_product(product_id):

    return PRODUCTS.get(
        product_id
    )


def products_by_category(category):

    return {

        pid: p

        for pid, p in PRODUCTS.items()

        if p.get("category") == category
    }


def products_by_resource(resource_type):

    return {

        pid: p

        for pid, p in PRODUCTS.items()

        if p.get(
            "resource_type"
        ) == resource_type
    }


def affordable_products(

    category,

    budget
):

    results = []

    for pid, p in PRODUCTS.items():

        if p.get(
            "category"
        ) != category:

            continue

        if p.get(
            "price",
            0
        ) <= budget:

            results.append((

                pid,

                p
            ))

    return results