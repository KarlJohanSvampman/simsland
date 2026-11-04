"""
llm/conversation_tags.py

Reading a finished conversation: what it was about, what kind of opening it had, what it relates to, whether it
was part of an argument, and what was said about people who weren't there (gossip, rumours, praise).

A pure model call -- plain data in, plain data out, no world state -- so it runs on a systems/bg_llm worker
(systems/conversation_archive.py submits it and applies the answer on a later tick). No programmatic fallback: a
conversation the model couldn't read stays untagged and is tried again.
"""

import json

from llm.llm_client import call_llm_safe
from llm.llm_gate import run_llm_call, PRIORITY_BACKGROUND

OPENINGS = ("suggestion", "request", "criticism", "complaint", "accusation", "insult", "question", "invitation",
            "news", "compliment", "apology", "small_talk")
ARGUMENT_TYPES = ("provocation", "unmet_expectation", "lying_accusation", "clash_of_wants", "wrong_done")

_SYSTEM = ("You read transcripts of conversations between people in a life simulation and describe them for an "
           "archive. Return STRICT JSON only.")


async def _tag(transcript, people, earlier):
    earlier_txt = "\n".join(f"- {e['id']}: {e.get('subject') or '(untagged)'} ({e.get('when', '')})" for e in earlier) \
        or "(none)"
    prompt = f"""
The conversation, between {', '.join(people)} (the first speaker started it):
{transcript}

Earlier conversations between the same people (id: subject):
{earlier_txt}

Describe it. STRICT JSON with exactly these keys:
{{"subject": <3-8 words: what it was about>,
  "opening": <what the first speaker opened with, one of: {", ".join(OPENINGS)}>,
  "tags": <2-5 short lowercase tags>,
  "relates_to": <the id of the earlier conversation it continues or refers back to, or null>,
  "argument": <null, or {{"type": one of {", ".join(ARGUMENT_TYPES)}, "subject": <3-8 words>,
                "started_by": <name of who started the disagreement>}} if they disagreed, criticised,
                accused or insulted each other>,
  "about_others": <list of what was said about people NOT in the conversation, each
                   {{"name": <their name>, "said_by": <speaker's name>, "claim": <a few words>,
                     "tone": <-2 (damning) .. 2 (glowing)>, "rumour": <true if it's hearsay or speculation>}},
                   [] if nobody else was talked about>}}
"""
    messages = [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": prompt}]
    result = await call_llm_safe(messages, session={"history": []}, char_id=None)
    if isinstance(result, dict) and result.get("error"):
        return None
    text = result.get("text", "") if isinstance(result, dict) else result
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        start, end = text.index("{"), text.rindex("}") + 1
        data = json.loads(text[start:end])
    except Exception:
        return None
    return _clean(data, {e["id"] for e in earlier})


def _clean(data, earlier_ids):
    if not isinstance(data, dict):
        return None
    subject = str(data.get("subject") or "").strip()[:80]
    if not subject:
        return None
    opening = str(data.get("opening") or "").strip().lower().replace(" ", "_")
    tags = [str(t).strip().lower()[:30] for t in (data.get("tags") or []) if str(t).strip()][:5]
    rel = data.get("relates_to")
    arg = data.get("argument")
    if isinstance(arg, dict) and str(arg.get("type") or "").lower() in ARGUMENT_TYPES:
        arg = {"type": str(arg["type"]).lower(), "subject": str(arg.get("subject") or subject).strip()[:80],
               "started_by": str(arg.get("started_by") or "").strip()[:60]}
    else:
        arg = None
    about = []
    for a in data.get("about_others") or []:
        if not isinstance(a, dict) or not a.get("name"):
            continue
        try:
            tone = max(-2, min(2, int(round(float(a.get("tone", 0))))))
        except (TypeError, ValueError):
            tone = 0
        about.append({"name": str(a["name"]).strip()[:60], "said_by": str(a.get("said_by") or "").strip()[:60],
                      "claim": str(a.get("claim") or "").strip()[:120], "tone": tone, "rumour": bool(a.get("rumour"))})
    return {"subject": subject, "opening": opening if opening in OPENINGS else "small_talk", "tags": tags,
            "relates_to": rel if rel in earlier_ids else None, "argument": arg, "about_others": about[:6]}


def tag(transcript, people, earlier):
    """Blocking; call from a bg_llm worker. The tags, or None."""
    result = run_llm_call(_tag(transcript, people, earlier), priority=PRIORITY_BACKGROUND)
    return result if isinstance(result, dict) and result.get("subject") else None
