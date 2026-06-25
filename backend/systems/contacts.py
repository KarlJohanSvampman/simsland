import time


def ensure_contact(c, other):

    oid = other["id"]

    c.setdefault("contacts", {})

    if oid not in c["contacts"]:
        c["contacts"][oid] = {
            "has_number": False,
            "interaction_count": 0,
            "created_at": time.time(),
            "last_contact": 0
        }

    return c["contacts"][oid]


def update_contact(c, other):

    contact = ensure_contact(c, other)

    contact["interaction_count"] += 1
    contact["last_contact"] = time.time()

    return contact


def maybe_learn_phone(c, other):

    contact = ensure_contact(c, other)

    rel = c.get("relationships", {}).get(other["id"], {})

    # learn number based on familiarity
    if rel.get("chemistry", 0) > 5 or contact["interaction_count"] > 5:
        contact["has_number"] = True