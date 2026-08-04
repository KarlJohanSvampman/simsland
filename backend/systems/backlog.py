# =========================================================
# BACKLOG
# A single "how much has this character got planned right now"
# read, feeding waiting-driven stress (see systems/waiting.py) --
# pulls from the three places a character's near-term commitments
# already live: activity_queue.py's pending task list, open
# proposals.py entries the character is a party to, and today's
# remaining schedule.py blocks.
# =========================================================


def count_planned(c, world):
    count = 0

    for task in c.get("activity_queue", []):
        if task.get("status") == "pending":
            count += 1

    cid = c.get("id")
    for proposal in world.get("proposals", {}).values():
        if proposal.get("status") != "open":
            continue
        if proposal.get("proposer_id") == cid or cid in proposal.get("recipients", []):
            count += 1

    cal      = world.get("calendar", {})
    day      = cal.get("weekday", "").lower()
    time_str = f"{cal.get('hour', 0):02d}:{cal.get('minute', 0):02d}"
    for block in c.get("schedule", {}).get("week", {}).get(day, []):
        s, e = block.get("start", ""), block.get("end", "")
        # Overnight blocks (s > e) already passed the point where they'd
        # count as "still to come" today by the time this runs during the
        # day -- only count same-day blocks that start after now.
        if s > e:
            continue
        if s >= time_str:
            count += 1

    return count


# Per-tick stress from being blocked while things pile up -- small and
# capped so a character with a huge backlog doesn't spike to max stress
# in a handful of ticks. Only meant to be called while a character is
# actively in a "waiting for X" state (see systems/waiting.py); a busy
# character who isn't waiting on anything shouldn't accrue this.
WAITING_STRESS_PER_TICK   = 0.01
WAITING_STRESS_MAX_PLANNED = 8


def apply_waiting_stress(c, world):
    planned = min(count_planned(c, world), WAITING_STRESS_MAX_PLANNED)
    if planned <= 0:
        return
    c["stress"] = min(100, c.get("stress", 0) + WAITING_STRESS_PER_TICK * planned)
