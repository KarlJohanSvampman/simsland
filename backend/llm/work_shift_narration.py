"""
llm/work_shift_narration.py

Generates real, hourly-granular work-shift narration in ONE LLM call
per shift (not N calls) -- modeled on llm/behavior_theory.py's shape
(own session, strict JSON, deterministic fallback). Each element of the
returned list is one hour's "beat":

    {"hour": int, "text": str, "detail": str, "notable": bool,
     "mentions_names": [str, ...], "sentiment": "positive"|"negative"|"neutral",
     "busy_minutes": int | None,
     "stuck_in_mind": {"thought": str, "reason": str} | None}

"sentiment" drives a real, deterministic workplace_reputation/
workplace_dependency nudge on anyone in mentions_names (see systems/
offgrid.py::_resolve_work_shift()) -- criticism/jealousy is "negative",
praise/attraction/fondness is "positive", a neutral work-only mention is
"neutral" (no nudge).

"text" is the short, phone-call-appropriate version; "detail" is the
fuller version for an in-person retelling later (same underlying event,
two lengths -- see systems/offgrid.py::_resolve_work_shift(), which
stores both on the same memory rather than regenerating either later).
mentions_names references the real roster by NAME (the LLM doesn't know
character ids) -- resolved back to ids by the caller.
"""

import json

from llm.llm_client import call_llm_safe
from llm.llm_gate import run_llm_call, PRIORITY_BACKGROUND


def _fallback_beats(hours, job_title, hour_rolls):
    """Never leave a shift with zero narration -- one generic line per
    hour, matching this codebase's universal LLM-failure convention."""
    beats = []
    for i in range(hours):
        notable = hour_rolls[i] != "normal" if i < len(hour_rolls) else False
        beats.append({
            "hour": i + 1,
            "text": f"Continued working as a {job_title}." if not notable
                    else f"Something out of the ordinary came up as a {job_title}.",
            "detail": f"Nothing much stood out this hour -- just the usual work as a {job_title}."
                    if not notable else
                    f"Something genuinely out of the ordinary happened this hour while working as a {job_title}, "
                    "though the details are a little hazy in memory.",
            "notable": notable,
            "mentions_names": [],
            "sentiment": "neutral",
            "busy_minutes": None,
            "stuck_in_mind": None,
        })
    return beats


async def _generate(c, world, hours, job_title, roster, hour_rolls):
    session = c.setdefault("_work_shift_llm_session", {"history": []})

    roster_lines = "\n".join(
        f"- {r['name']} ({r['role']}, you {'like' if r['reputation'] > 10 else 'dislike' if r['reputation'] < -10 else 'feel neutral about'} them, "
        f"reputation={r['reputation']:.0f}, you depend on their cooperation at {r['dependency']:.0f}/100)"
        for r in roster
    ) or "(no particular coworkers come to mind right now)"

    rolls_line = ", ".join(f"hour {i+1}: {r}" for i, r in enumerate(hour_rolls))

    prompt = f"""
{c.get('name', 'Someone')} is working a {hours}-hour shift as a {job_title}.

Known coworkers:
{roster_lines}

Per-hour notability rolls (pre-decided, do not change): {rolls_line}
- "normal" hours: nothing objectively notable happened. Either write a
  short, mundane line about the work itself, OR (about half the time)
  a personal thought -- criticism, praise, romantic/sexual attraction
  or fantasy, jealousy, or an opinion about the work/workplace itself
  -- about ONE of the real coworkers above, consistent with how much
  {c.get('name','they')} likes/depends on that person. Occasionally
  (rarely) instead generate a totally UNRELATED, tangential thought
  that got stuck in their mind for no strong reason -- something small
  seen or heard that reminds them of something from childhood, an old
  memory, a strange association -- the more far-fetched the
  justification the better. When you do this, fill "stuck_in_mind"
  with {{"thought": <the odd fixation>, "reason": <a stretched,
  not-fully-convincing reason it came to mind>}}; otherwise leave it
  null.
- "notable" or "rare" hours: something real happened -- a real
  situation, possibly involving a real coworker by name, possibly
  escalating into real conflict or drama. If the situation plausibly
  means being pulled into a real meeting (a real, timed commitment),
  set "busy_minutes" to a realistic value between 30 and 180; otherwise
  leave it null.

For EVERY hour, provide a SHORT "text" (1 sentence, what you'd mention
in a quick phone call) and a fuller "detail" (2-4 sentences, what
you'd actually explain in person later, describing the same event in
more depth -- for a "normal" hour with no personal thought or
stuck_in_mind entry, "detail" can just restate "text" a little more
fully).

For any hour mentioning a real coworker, also set "sentiment" to
"positive" (praise/attraction/fondness), "negative" (criticism/
jealousy/conflict), or "neutral" (a plain work-only mention). Use
"neutral" whenever mentions_names is empty.

Respond with STRICT JSON only, no prose outside the JSON:
{{"beats": [{{"hour": 1, "text": "...", "detail": "...", "notable": false,
"mentions_names": ["Real Coworker Name"], "sentiment": "neutral",
"busy_minutes": null, "stuck_in_mind": null}}, ...]}} -- exactly {hours}
entries, hour 1 through {hours}.
"""
    messages = [
        {"role": "system", "content": "You narrate one character's work shift in a life-simulation game, hour by hour. Return STRICT JSON only."},
        {"role": "user", "content": prompt},
    ]
    result = await call_llm_safe(messages, session=session, char_id=c.get("id"))
    if isinstance(result, dict) and result.get("error"):
        return None
    text = result.get("text", "") if isinstance(result, dict) else result
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        parsed = json.loads(text)
    except Exception:
        return None
    beats = parsed.get("beats")
    if not isinstance(beats, list) or len(beats) != hours:
        return None
    return beats


def generate_hourly_work_beats(c, world, hours, job_title, roster, hour_rolls):
    """Sync entry point. roster: [{"id","name","role","reputation",
    "dependency"}, ...]. Returns a list of exactly `hours` beat dicts,
    real LLM content or the deterministic fallback -- never empty."""
    beats = run_llm_call(
        _generate(c, world, hours, job_title, roster, hour_rolls),
        priority=PRIORITY_BACKGROUND,
    )
    if not beats:
        return _fallback_beats(hours, job_title, hour_rolls)
    return beats
