import json
from llm.llm_client import call_llm,call_llm_safe

# =========================
# ⚡ HEURISTIC GATE
# =========================
def should_use_llm(c):

    needs = c.get("needs", {})

    # basic survival = no LLM
    if needs.get("hunger", 0) > 0.8:
        return False

    if needs.get("energy", 1) < 0.2:
        return False

    # already executing plan
    if c.get("plan"):
        return False

    # strong emotions → LLM
    if c.get("emotion") in ["angry", "jealous", "fear"]:
        return True

    # default: skip most of the time
    return False


# =========================
# 🔁 DECISION CACHE
# =========================
def get_recent_decision(c):
    return c.get("_last_decision")


def set_recent_decision(c, decision):
    c["_last_decision"] = decision


# =========================
# 🧠 FALLBACK LOGIC
# =========================
def fallback_decision(c):

    needs = c.get("needs", {})

    if needs.get("hunger", 0) > 0.7:
        return {"action": "eat"}

    if needs.get("energy", 1) < 0.3:
        return {"action": "sleep"}

    if needs.get("bladder", 0) > 0.7:
        return {"action": "toilet"}

    return {"action": "idle"}


# =========================
# 🧠 LLM DECISION
# =========================
async def llm_decision(c, world, perception, memories):

    prompt = f"""
You are {c.get("name")}.

State:
Needs: {c.get("needs")}
Emotion: {c.get("emotion")}
Plan: {c.get("plan")}

Perceived surroundings:
{summarize_perception(perception)}

Memories:
{memories}

Respond ONLY in JSON:
{{"action": "<action_name>", "target": "<optional>"}}
"""

    try:
        result = await call_llm([{"role": "user", "content": prompt}])

        # depending on your ollama response shape
        if isinstance(result, dict) and "message" in result:
            text = result["message"].get("content", "")
        else:
            text = str(result)

        parsed = json.loads(text)
        return parsed

    except Exception:
        return fallback_decision(c)


# =========================
# 🎯 MAIN ENTRY
# =========================
async def decide_action(c, world, perception, memories):

    # 🔁 reuse recent decision when safe
    recent = get_recent_decision(c)
    if recent and not should_use_llm(c):
        return recent

    # 🧠 decide whether to use LLM
    if should_use_llm(c):
        decision = await llm_decision(c, world, perception, memories)
    else:
        decision = fallback_decision(c)

    # cache it
    set_recent_decision(c, decision)

    return decision



def summarize_perception(
    perception
):

    lines = []

    # =====================================
    # PEOPLE
    # =====================================

    for p in perception.get(
        "visible_people",
        []
    ):

        line = (

            f"You see "

            f"{p['name']} "

            f"nearby looking "

            f"{p['appears']}."
        )

        if p.get("activity"):

            line += (

                f" They appear to be "

                f"{p['activity']}."
            )

        lines.append(line)

    # =====================================
    # SOCIAL SCENES
    # =====================================

    for s in perception.get(
        "social_scenes",
        []
    ):

        lines.append(

            f"There is a "

            f"{s['tone']} "

            f"conversation about "

            f"{s['topic']} "

            f"between "

            f"{', '.join(s['participants'])}."
        )

    # =====================================
    # AUDIO
    # =====================================

    for a in perception.get(
        "audible_events",
        []
    ):

        lines.append(

            f"You hear "

            f"{a['speaker']} "

            f"speaking nearby."
        )

    return "\n".join(lines)