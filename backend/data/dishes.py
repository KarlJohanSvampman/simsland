"""
Dish recipes -- a recipe is a RATIO (docs/food_system.md).

`per_person` is how many units of each group one portion takes; the cook multiplies by the number of people they cook for.
Groups: protein, carb, vitamin (a vegetable or a fruit), dairy (counts towards the protein share), spice (taste only).
`method` is the cookware (pot | pan | oven) and `minutes` the cooking time for one portion; every extra person adds `per_extra`.
"""

DISH_RECIPES = {
    "pasta_bolognese": {"name": "Pasta Bolognese", "method": "pot", "minutes": 25, "per_extra": 1,
                        "per_person": {"protein": 1, "carb": 1, "vitamin": 1, "spice": 0.5}},
    "chicken_stirfry": {"name": "Chicken Stir-fry", "method": "pan", "minutes": 15, "per_extra": 2,
                        "per_person": {"protein": 1, "carb": 1, "vitamin": 1, "spice": 0.5}},
    "roast_dinner":    {"name": "Roast Dinner", "method": "oven", "minutes": 75, "per_extra": 3,
                        "per_person": {"protein": 1, "carb": 1, "vitamin": 1, "spice": 0.5}},
    "veggie_curry":    {"name": "Veggie Curry", "method": "pot", "minutes": 35, "per_extra": 2,
                        "per_person": {"protein": 0.5, "carb": 1, "vitamin": 2, "spice": 1}},
    "mac_and_cheese":  {"name": "Mac and Cheese", "method": "pot", "minutes": 20, "per_extra": 1,
                        "per_person": {"carb": 2, "dairy": 1, "spice": 0.5}},
    "omelette":        {"name": "Omelette", "method": "pan", "minutes": 10, "per_extra": 2,
                        "per_person": {"protein": 2, "dairy": 0.5, "vitamin": 0.5, "spice": 0.5}},
    "baked_fish":      {"name": "Baked Fish and Vegetables", "method": "oven", "minutes": 45, "per_extra": 2,
                        "per_person": {"protein": 1, "carb": 0.5, "vitamin": 2, "spice": 0.5}},
}
