"""
systems/unresolved.py -- is there anything left for this character to do about?

Characters are creatures of habit: they have schedules, expectations and intentions for a reason. While any of those is still open
nothing about what they do is left to chance -- no wandering the house because the dice said so, no outing nobody planned, no
noticing-and-investigating, no random pick among things to do. Chance is only for a character with nothing to meet and nothing to
want (which, with intentions refilling every few minutes, is hardly ever). has_unresolved() is the one test for that.
"""


def has_unresolved(c, world=None):
    """True while they have an intention open (not decayed away) or an expectation still pending. Whatever is open, nothing about what
    they do is left to chance: the pressing things come first (systems/todo.py), and what is for when there is time is done in its own
    order once nothing pressing is left -- never swapped for a random pick."""
    for i in c.get("active_intentions", []):
        if i.get("strength", 1) > 0:
            return True
    return any(e.get("status") == "pending" for e in (c.get("expectations") or {}).values() if isinstance(e, dict))
