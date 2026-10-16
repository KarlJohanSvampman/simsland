"""
systems/child_worldview.py

How a small child fills the gaps in a world they only partly understand.

* IMAGINATION. A child who's been wondering about something for a while, with
  nobody having told them, doesn't leave it blank: they invent an explanation
  from their own small world and hold it as true. It becomes an account from the
  pseudo-source "imagination" (systems/child_cognition.py), so when a grown-up
  finally answers, the two are compared like any other pair -- and a child who
  keeps being wrong learns to trust their own made-up ideas a little less.
  The child can also proudly tell it to other children as fact.

* REFERENCE BREADTH. A child's default picture of normal is their own household:
  rich children assume every family is rich, poor children that every family
  counts coins. Breadth is how many other households they actually know -- it's
  derived live from relationships, nothing stored. It only widens by exposure.

* COMPARISON AND DESPAIR. With no reference there is nothing to compare, so a
  child with breadth 0 doesn't envy anyone. Once they know another family they
  notice differences -- and what they do with it depends on...

* PERSPECTIVE-TAKING. How well they can picture something from another
  person's side. It grows with age, with empathy, with having heard grown-ups
  disagree, and with having seen more kinds of family. A child who can't yet
  take another's perspective only feels what a difference means for *them*; one
  who can feels bad *for* a family with less, and can see why someone with more
  doesn't see it the same way.

Everything here is derived from existing data; the only stored state is the
imagined explanation on the question it answers.
"""

from systems import bg_llm

IMAGINE_AFTER_TICKS = 1800        # wondering this long with no answer before they invent one
IMAGINE_MIN_AGE     = 3

IMAGINATION_ID      = "imagination"
IMAGINATION_BASE    = 0.25        # credibility of their own idea ...
IMAGINATION_SCALE   = 0.35        # ... plus this x naivety (a naive child believes themselves)
IMAGINATION_CAP     = 0.60
_IMAGINATION        = {"id": IMAGINATION_ID, "name": "your own idea", "age_group": "self"}

COMPARE_THRESHOLD   = 0.15        # difference in family standing a child notices
LOW_PERSPECTIVE     = 0.35        # below this, how things are for ME is all that registers
HIGH_PERSPECTIVE    = 0.65        # above this, they can usually see the other person's side
_EMPATHY_TRAITS     = {"empathetic": .20, "compassionate": .20, "thoughtful": .08, "perceptive": .05,
                       "selfish": -.12, "inconsiderate": -.10, "cruel": -.20, "egotistical": -.08}


# ---------------------------------------------------------------------------
# Derived measures
# ---------------------------------------------------------------------------

def reference_breadth(child, world):
    """How many OTHER households this child actually knows someone from."""
    chars = world.get("characters", {})
    own = child.get("household_id")
    seen = set()
    for oid, rel in (child.get("relationships") or {}).items():
        other = chars.get(oid)
        if not other or other.get("is_workplace_npc") or other.get("alive") is False:
            continue
        if (rel.get("familiarity") or 0) < 5 and (rel.get("hours_this_week") or 0) <= 0:
            continue
        hid = other.get("household_id")
        if hid and hid != own:
            seen.add(hid)
    return len(seen)


def perspective_taking(child, world):
    """0..1: how well they can picture things from someone else's side."""
    cog = child.get("child_cognition") or {}
    age = child.get("age") if child.get("age") is not None else 8
    traits = set(child.get("traits", []) or []) | set(child.get("personality_traits", []) or [])
    score = 0.15 + 0.04 * (age - 3)
    score += sum(d for t, d in _EMPATHY_TRAITS.items() if t in traits)
    score += min(0.20, 0.03 * (cog.get("conflicts_heard") or 0))      # having heard people disagree
    score += min(0.15, 0.05 * reference_breadth(child, world))        # having seen other ways to live
    return max(0.0, min(1.0, score))


def imagination_credibility(child, world=None):
    from systems.child_cognition import naivety
    learned = ((child.get("child_cognition") or {}).get("source_adjust") or {}).get(IMAGINATION_ID, 0.0)
    return max(0.0, min(IMAGINATION_CAP, IMAGINATION_BASE + IMAGINATION_SCALE * naivety(child, world) + learned))


# ---------------------------------------------------------------------------
# Imagination
# ---------------------------------------------------------------------------

def _fallback(q):
    from llm.child_imagination import FALLBACKS
    options = FALLBACKS.get(q.get("tone")) or FALLBACKS["tense"]
    return options[sum(map(ord, q["id"])) % len(options)]


def service_imagination(c, world):
    """Per-tick, children only. A question nobody has answered for long enough gets an
    invented explanation. The model call runs off-thread (systems/bg_llm) and is
    applied on a later tick; nothing is stored until it's applied, so a restart
    just asks again."""
    from systems.child_cognition import _state, _open_questions
    cog = _state(c)
    if (c.get("age") or 0) < IMAGINE_MIN_AGE:
        return
    tick = world.get("tick", 0)
    for q in _open_questions(cog):
        if q.get("imagined") or q["accounts"] or q.get("followup"):
            continue
        if tick - q["created_tick"] < IMAGINE_AFTER_TICKS:
            continue
        key = f"imagine:{c['id']}:{q['id']}"
        from llm.child_imagination import imagine_explanation
        bg_llm.submit(key, imagine_explanation, c.get("name", "A child"), c.get("age"), q["text"], q.get("tone"))
        ready, text = bg_llm.take(key)
        if not ready:
            continue
        text = text or _fallback(q)
        q["imagined"] = text
        q["accounts"].append({"source_id": IMAGINATION_ID, "tick": tick, "text": text, "imagined": True})


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

def _family_band(score):
    return "rich" if score >= 0.65 else ("poor" if score <= 0.30 else "ordinary")


def get_worldview_context(c, world):
    """Sentences about the child's frame of reference (or [])."""
    from systems.standing import _family_score
    chars = world.get("characters", {})
    parts = []
    breadth = reference_breadth(c, world)
    own_family = _family_score(c, world)

    if breadth == 0:
        band = _family_band(own_family)
        parts.append({
            "rich":     "Your family has a lot, and you assume every family does -- that's just what normal looks like to you.",
            "poor":     "Your family counts every coin, and you assume that's how every family lives.",
            "ordinary": "You assume every family lives the way yours does.",
        }[band])
    elif breadth == 1:
        parts.append("You've only really seen one other family, so you're not sure whose way is the normal one.")
    else:
        parts.append("You've seen enough different families to know people live in very different ways.")

    # Only once there's something to compare against.
    if breadth >= 1:
        pt = perspective_taking(c, world)
        best = None
        for oid, rel in (c.get("relationships") or {}).items():
            other = chars.get(oid)
            if (not other or other.get("is_workplace_npc") or not other.get("household_id")
                    or other.get("household_id") == c.get("household_id")
                    or ((rel.get("familiarity") or 0) < 5 and (rel.get("hours_this_week") or 0) <= 0)):
                continue
            diff = _family_score(other, world) - own_family
            if abs(diff) >= COMPARE_THRESHOLD and (best is None or abs(diff) > abs(best[1])):
                best = (other, diff)
        if best:
            other, diff = best
            name = other.get("name", "someone")
            if diff > 0:
                parts.append(f"You noticed {name}'s family has so much more than yours."
                             + (" That doesn't feel fair." if pt < LOW_PERSPECTIVE
                                else " You wonder how it feels to have that, and whether they even notice."))
            else:
                parts.append(f"You noticed {name}'s family doesn't have much."
                             + (" You feel bad for them." if pt >= LOW_PERSPECTIVE
                                else " You're glad it isn't you."))

    pt = perspective_taking(c, world)
    if pt < LOW_PERSPECTIVE:
        parts.append("You mostly think about how things are for you; it's hard to imagine how someone else feels about them.")
    elif pt < HIGH_PERSPECTIVE:
        parts.append("You're starting to be able to imagine how others feel -- when someone is sad or left out, you feel it a bit too.")
    else:
        parts.append("You can usually picture how things look from the other person's side, even when you don't agree with them.")
    return parts
