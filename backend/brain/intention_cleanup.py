# =========================================================
# CLEAN INTENTIONS
# =========================================================

def clean_intentions(c):

    intentions = c.get(
        "active_intentions",
        []
    )

    seen = set()

    cleaned = []

    for i in reversed(intentions):

        key = i.get("type")

        if key in seen:
            continue

        seen.add(key)

        cleaned.append(i)

    cleaned.reverse()

    c["active_intentions"] = (
        cleaned[-10:]
    )


# =========================================================
# SORT INTENTIONS
# =========================================================

def sort_intentions(c):

    intentions = c.get(
        "active_intentions",
        []
    )

    intentions.sort(

        key=lambda x:
            x.get(
                "priority",
                0
            ),

        reverse=True
    )