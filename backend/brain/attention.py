import math


# =========================================================
# DECAY
# =========================================================

def decay_attention(c):

    attention = c.get(
        "attention",
        {}
    )

    salience = attention.get(
        "salience",
        {}
    )

    updated = {}

    for k, v in salience.items():

        nv = v * 0.96

        if nv > 0.05:

            updated[k] = nv

    attention["salience"] = updated


# =========================================================
# BOOST SALIENCE
# =========================================================

def boost_attention(

    c,

    key,

    amount
):

    attention = c.setdefault(
        "attention",
        {}
    )

    salience = attention.setdefault(
        "salience",
        {}
    )

    salience[key] = min(

        1.0,

        salience.get(
            key,
            0
        ) + amount
    )


# =========================================================
# SOCIAL SALIENCE
# =========================================================

def update_social_attention(

    c,

    perception
):

    # =====================================
    # PEOPLE
    # =====================================

    for p in perception.get(
        "visible_people",
        []
    ):

        strength = 0.05

        if p.get(
            "appears"
        ) in [

            "tense",

            "agitated",

            "anxious",

            "positive",

             "confident"
        ]:

            strength += 0.2

        if p.get(
            "speaking"
        ):

            strength += 0.1

        focus = c.get(
        "attention",
            {}
        ).get(
            "focus"
        )

        if focus:

            current_strength = focus.get(
                "strength",
                0
            )

            if current_strength > 0.8:

                strength *= 0.5
        
        boost_attention(

            c,

            f"person:{p['id']}",

            strength
        )

    # =====================================
    # SCENES
    # =====================================

    for s in perception.get(
        "social_scenes",
        []
    ):

        strength = 0.1

        if s.get(
            "tone"
        ) in [

            "heated",

            "aggressive",

            "awkward"
        ]:

            strength += 0.25

        boost_attention(

            c,

            f"scene:{s['topic']}",

            strength
        )

        social = c.get(
            "social",
            {}
        )

        rel = social.get(
            p["id"],
            {}
        )

        strength += (
            rel.get(
                "tension",
                0
            ) * 0.25
        )

        strength += (
            rel.get(
                "attraction",
                0
            ) * 0.15
        )
# =========================================================
# SELECT FOCUS
# =========================================================

def select_attention_focus(c):

    attention = c.get(
        "attention",
        {}
    )

    salience = attention.get(
        "salience",
        {}
    )

    if not salience:

        attention["focus"] = None

        return None

    top = max(

        salience.items(),

        key=lambda x: x[1]
    )

    key, value = top

    if value < 0.15:

        attention["focus"] = None

        return None

    focus = {

        "key":
            key,

        "strength":
            value
    }

    attention["focus"] = focus

    return focus


# =========================================================
# MAIN UPDATE
# =========================================================

def update_attention(

    c,

    world
):

    perception = c.get(
        "perception",
        {}
    )

    decay_attention(c)

    update_social_attention(

        c,

        perception
    )
    focus = c.get(
        "attention",
        {}
    ).get(
        "focus"
    )

    if focus:

        key = focus.get(
            "key",
            ""
        )

        if key.startswith(
            "person:"
        ):

            pid = key.split(":")[1]

            rel = c.get(
                "social",
                {}
            ).get(
                pid,
                {}
            )

            if rel.get(
                "tension",
                0
            ) > 0.7:

                c["stress"] = min(
                    1,
                    c.get(
                        "stress",
                        0
                    ) + 0.01
                )
    select_attention_focus(c)