"""
llm/household_summary_narration.py

The three narration tiers for systems/household_summary.py's hourly ->
daily -> weekly cascade. Each function follows the same proven shape as
llm/offgrid_narration.py / llm/story_condensation.py: a plain-text LLM
call via call_llm_safe(), a household-scoped session key so the model
sees its own recent narration history, and a deterministic fallback
that never returns empty (this codebase's "never leave it blank" rule).

generate_hourly_summary()  -- narrates one hour's raw household events
generate_daily_summary()   -- condenses a day's hourly summaries into one
generate_weekly_summary()  -- condenses a week's daily summaries into
                               one, narrated in the HOUSE's own first-
                               person voice (the one genuinely different
                               prompt framing in this file, per the
                               user's explicit ask)
"""

from llm.llm_client import call_llm_safe
from llm.llm_gate import run_llm_call, PRIORITY_BACKGROUND


def _household_label(household):
    return household.get("name") or "the household"


async def _call(system_prompt, user_prompt, session):
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    result = await call_llm_safe(messages, session=session, char_id=None)
    if isinstance(result, dict) and result.get("error"):
        return None
    text = result.get("text", "") if isinstance(result, dict) else result
    if not isinstance(text, str) or not text.strip():
        return None
    return text.strip().strip('"')


# =========================================================
# HOURLY -- narrates one hour's raw event batch
# =========================================================

def _format_event_line(e, characters):
    who = characters.get(e.get("character_id"), {}).get("name", "someone")
    room = e.get("room_label") or "the house"
    etype = e.get("type")
    if etype == "activity_started":
        return f"{who} started {e.get('activity_type')} in {room}."
    if etype == "activity_completed":
        mins = round(e.get("duration_ticks", 0) / 60)
        return f"{who} finished {e.get('activity_type')} in {room} (about {mins} min)."
    if etype == "activity_interrupted":
        return f"{who} was interrupted while doing {e.get('activity_type')} in {room}."
    if etype == "speech":
        return f"{who} said, in {room}: \"{e.get('utterance')}\""
    return f"{who}: {etype} in {room}."


async def _generate_hourly_text(household, events, world, characters):
    session = household.setdefault("_summary_llm_session", {"history": []})
    lines = "\n".join(_format_event_line(e, characters) for e in events)
    prompt = f"""
Here is a raw log of everything that happened at {_household_label(household)}'s
home over the last hour, in order:

{lines}

Write a short (2-4 sentence) third-person summary of the hour. Mention
who did what, where in the house, and -- for anything that finished --
what the result was. Keep routine moments brief; don't invent detail
that isn't implied by the log.

Respond with ONLY the summary, no quotes, no extra text.
"""
    return await _call(
        "You narrate a household's hour-by-hour activity for a life-simulation game.",
        prompt, session,
    )


def _fallback_hourly_text(events, characters):
    if not events:
        return "A quiet hour at home."
    lines = [_format_event_line(e, characters) for e in events[:6]]
    return " ".join(lines)


def generate_hourly_summary(household, events, world):
    characters = world.get("characters", {})
    text = run_llm_call(
        _generate_hourly_text(household, events, world, characters),
        priority=PRIORITY_BACKGROUND,
    )
    if not text:
        text = _fallback_hourly_text(events, characters)
    return text


# =========================================================
# DAILY -- condenses a day's hourly summaries
# =========================================================

async def _generate_daily_text(household, hourly_texts, world):
    session = household.setdefault("_summary_llm_session", {"history": []})
    joined = "\n".join(f"- {t}" for t in hourly_texts)
    prompt = f"""
Here are the hour-by-hour summaries of what happened at
{_household_label(household)}'s home today, in order:

{joined}

Condense this into one short (3-5 sentence) daily summary -- the
throughline of the day, not a list. Keep it grounded in what's actually
described above.

Respond with ONLY the summary, no quotes, no extra text.
"""
    return await _call(
        "You condense a household's hourly activity logs into one daily summary for a life-simulation game.",
        prompt, session,
    )


def _fallback_daily_text(hourly_texts):
    if not hourly_texts:
        return "Not much of note happened at home today."
    return " ".join(hourly_texts[:4])


def generate_daily_summary(household, hourly_texts, world):
    text = run_llm_call(
        _generate_daily_text(household, hourly_texts, world),
        priority=PRIORITY_BACKGROUND,
    )
    if not text:
        text = _fallback_daily_text(hourly_texts)
    return text


# =========================================================
# WEEKLY -- condenses a week's daily summaries, narrated by the
# house itself, in its own first-person voice
# =========================================================

async def _generate_weekly_text(household, daily_texts, world):
    session = household.setdefault("_summary_llm_session", {"history": []})
    joined = "\n".join(f"- {t}" for t in daily_texts)
    prompt = f"""
Here are the daily summaries of what happened inside {_household_label(household)}'s
home this past week, in order:

{joined}

Write this week's summary as if the HOUSE ITSELF is narrating its own
story -- first person ("I watched...", "my walls heard...", "under my
roof..."), warm and a little wry, the way an old house that's seen a
lot might talk about the people living in it. 4-6 sentences. Stay
grounded in what's actually described above -- don't invent new events.

Respond with ONLY the narration, no quotes, no extra text.
"""
    return await _call(
        "You are a house narrating the week just past, in your own first-person voice, for a life-simulation game.",
        prompt, session,
    )


def _fallback_weekly_text(daily_texts):
    if not daily_texts:
        return "I kept quiet watch over an uneventful week."
    return "This week, under my roof: " + " ".join(daily_texts[:4])


def generate_weekly_summary(household, daily_texts, world):
    text = run_llm_call(
        _generate_weekly_text(household, daily_texts, world),
        priority=PRIORITY_BACKGROUND,
    )
    if not text:
        text = _fallback_weekly_text(daily_texts)
    return text
