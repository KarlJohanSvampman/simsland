"""
social_odor.py — smell-based social pressure system.

When a character is near someone who smells strongly, they may generate
an intention to suggest that person shower, or move away from them.

Called from generate_social_intentions in a new pass.
"""

from systems.body import get_odor_label
from brain.intentions import add_intention

# Distance within which smell is perceived (grid units)
SMELL_RADIUS = 4

# Below this odor no social reaction
ODOR_NOTICE_THRESHOLD = 40   # "noticeably unpleasant"
ODOR_STRONG_THRESHOLD = 65   # "strongly unpleasant"


def generate_odor_social_intentions(c, world):
    """
    Scan nearby characters. If anyone smells strongly enough, generate
    a low-priority intention to address it (comment, suggest shower, move away).
    """
    perception = c.get("perception", {})
    visible    = perception.get("visible_people", [])

    for person_snapshot in visible:
        dist  = person_snapshot.get("distance", 999)
        if dist > SMELL_RADIUS:
            continue

        body_snap = person_snapshot.get("body", {})
        odor      = body_snap.get("odor", 0)

        if odor < ODOR_NOTICE_THRESHOLD:
            continue

        other_id   = person_snapshot.get("id")
        odor_label = get_odor_label(odor)

        if odor >= ODOR_STRONG_THRESHOLD:
            # Strong smell: suggest shower or move away
            add_intention(c, {
                "type":       "suggest_hygiene",
                "category":   "social",
                "target_id":  other_id,
                "priority":   35,
                "reason":     f"nearby_character_smells_{odor_label.replace(' ', '_')}",
                "context":    {
                    "odor_label": odor_label,
                    "other_id":   other_id,
                    "other_name": person_snapshot.get("name"),
                },
            })
        else:
            # Mild smell: just note it internally (LLM context surfaces it)
            # No hard intention, let the LLM decide how to react
            pass


def apply_odor_social_pressure(smelly_c, world):
    """
    Called when a character has high odor. Push surrounding characters to
    generate a suggest_hygiene intention if they haven't recently.
    Runs from sim_loop on a slow cadence.
    """
    odor = smelly_c.get("body", {}).get("odor", 0)
    if odor < ODOR_NOTICE_THRESHOLD:
        return

    cid = smelly_c["id"]
    for other_c in world.get("characters", {}).values():
        if other_c["id"] == cid:
            continue
        # Rough distance check
        dx = abs(other_c.get("x", 0) - smelly_c.get("x", 0))
        dy = abs(other_c.get("y", 0) - smelly_c.get("y", 0))
        if dx + dy > SMELL_RADIUS:
            continue
        add_intention(other_c, {
            "type":      "suggest_hygiene",
            "category":  "social",
            "target_id": cid,
            "priority":  30,
            "reason":    "nearby_character_smells",
            "context": {
                "odor_label": get_odor_label(odor),
                "other_id":   cid,
                "other_name": smelly_c.get("name"),
            },
        })
