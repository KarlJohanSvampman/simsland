import random

from data.recipes import (
    RECIPES
)


# =========================================================
# CHOOSE RECIPE
# =========================================================

def choose_recipe(

    c,

    household
):

    skill = c.get(
        "cooking_skill",
        0.3
    )

    traits = c.get(
        "traits",
        []
    )

    possible = []

    for rid, recipe in RECIPES.items():

        difficulty = recipe.get(
            "difficulty",
            0.5
        )

        if difficulty > (

            skill + 0.3
        ):
            continue

        score = 1.0

        if "lazy" in traits:

            score -= (
                difficulty * 2
            )

        if "foodie" in traits:

            score += (
                difficulty * 2
            )

        possible.append((

            rid,

            score
        ))

    if not possible:
        return None

    possible.sort(

        key=lambda x: x[1],

        reverse=True
    )

    top = possible[:3]

    return random.choice(top)[0]