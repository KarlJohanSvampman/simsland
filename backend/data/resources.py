RESOURCE_TYPES = {

    # =====================================================
    # FOOD INGREDIENTS
    # =====================================================

    "FOOD_PROTEIN": {

        "category": "ingredient",

        "cookable": True
    },

    "FOOD_CARB": {

        "category": "ingredient",

        "cookable": True
    },

    "FOOD_VEGETABLE": {

        "category": "ingredient",

        "cookable": True
    },

    "FOOD_SPICE": {

        "category": "ingredient",

        "cookable": False
    },

    # =====================================================
    # QUICK FOODS
    # =====================================================

    "FOOD_FRUIT": {

        "category": "quick_food",

        "ready_to_eat": True
    },

    "FOOD_SNACK": {

        "category": "quick_food",

        "ready_to_eat": True
    },

    # =====================================================
    # PREPARED
    # =====================================================

    "PROCESSED_MEAL": {

        "category": "prepared_food",

        "requires_heating": True
    },

    "MEAL": {

        "category": "meal",

        "ready_to_eat": True
    },

    "STORED_MEAL": {

        "category": "meal",

        "requires_heating": True,

        "fast_decay": True
    },

    # =====================================================
    # DRINKS
    # =====================================================

    "DRINK_SOFT": {

        "category": "drink"
    },

    "DRINK_ALCOHOL": {

        "category": "drink"
    },

    "DRINK_MILK": {

        "category": "drink"
    },

    "DRINK_COFFEE": {

        "category": "drink"
    },

    "DRINK_TEA": {

        "category": "drink"
    },

    # =====================================================
    # WASTE
    # =====================================================

    "TRASH_FOOD_PACKAGING": {

        "category": "waste"
    },

    "TRASH_CARDBOARD": {

        "category": "waste"
    },

    "TRASH_PLASTIC": {

        "category": "waste"
    },

    "TRASH_ORGANIC": {

        "category": "waste"
    },

    # =====================================================
    # HYGIENE
    # =====================================================

    "HYGIENE": {

        "category": "consumable"
    },

    "TOILET_PAPER": {

        "category": "consumable"
    },

    "CLEANING": {

        "category": "consumable"
    },

    # =====================================================
    # HOBBY SUPPLIES
    # max_uses: how many sessions one unit lasts.
    # consumable: True means the item is eventually depleted.
    # =====================================================

    "PAINT_SET": {
        "category":   "hobby_supply",
        "max_uses":   12,
        "hobby":      "painting",
        "consumable": True,
    },
    "CANVAS": {
        "category":   "hobby_supply",
        "max_uses":   1,
        "hobby":      "painting",
        "consumable": True,
    },
    "ART_BRUSH": {
        "category":   "hobby_supply",
        "max_uses":   20,
        "hobby":      "painting",
        "consumable": False,
    },
    "GUITAR": {
        "category":   "hobby_supply",
        "max_uses":   500,
        "hobby":      "music",
        "consumable": False,
    },
    "GUITAR_PICK": {
        "category":   "hobby_supply",
        "max_uses":   10,
        "hobby":      "music",
        "consumable": True,
    },
    "YARN": {
        "category":   "hobby_supply",
        "max_uses":   8,
        "hobby":      "craft",
        "consumable": True,
    },
    "KNITTING_NEEDLES": {
        "category":   "hobby_supply",
        "max_uses":   200,
        "hobby":      "craft",
        "consumable": False,
    },
    "BOOK": {
        "category":   "hobby_supply",
        "max_uses":   1,
        "hobby":      "reading",
        "consumable": False,
    },
    "GAME_CONTROLLER": {
        "category":   "hobby_supply",
        "max_uses":   1000,
        "hobby":      "gaming",
        "consumable": False,
    },
}
