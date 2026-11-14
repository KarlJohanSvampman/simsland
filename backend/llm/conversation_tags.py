"""
llm/conversation_tags.py

Reading a finished conversation (design sections 5, 9, 10, 14, 19): what it was about and how it went socially --
the issues it raised or carried on and each person's position, whether a confrontation happened in it and how it
ended, agreements made, renegotiated or broken, how the opener's approach was received, what each now makes of the
other, and what was said about people who weren't there.

A pure model call -- plain data in, plain data out, no world state -- so it runs on a systems/bg_llm worker
(systems/conversation_archive.py submits it; social/discourse.py applies the answer). Everything is validated here;
no programmatic fallback: a conversation the model couldn't read stays untagged and is tried again.
"""

import json

from llm.llm_client import call_llm_safe
from llm.llm_gate import run_llm_call, PRIORITY_BACKGROUND

OPENINGS = ("suggestion", "request", "criticism", "complaint", "accusation", "insult", "question", "invitation",
            "news", "compliment", "apology", "small_talk")
ISSUE_CATEGORIES = ("unmet_expectation", "broken_promise", "unfair_treatment", "disrespect", "personal_habit",
                    "household_responsibility", "relationship_problem", "financial_dispute", "social_norm_violation",
                    "ideological_disagreement", "interpersonal_boundary", "abuse_of_authority", "competition",
                    "misunderstanding", "betrayal", "public_reputation", "dishonesty", "other")
CONFRONTATION_TYPES = ("provocation", "bullying", "ridicule", "criticism", "behavioural_request",
                       "expectations_dispute", "power_play", "negotiation", "contract_proposal", "defence")
CONFRONTATION_OUTCOMES = ("mutual_understanding", "apology_accepted", "apology_rejected", "behaviour_change_accepted",
                          "contract_established", "contract_renegotiated", "unresolved", "withdrew",
                          "refused_discussion", "public_humiliation", "relationship_deterioration", "physical_fight",
                          "third_party_intervention")
INITIATIVE_RESPONSES = ("accepted_positively", "accepted_reluctantly", "ignored", "rejected", "interrupted", "hostile",
                        "counter_proposal", "reconciliation")
INTERACTION_TAGS = ("casual", "friendly", "introductory", "affectionate", "supportive", "flirtatious",
                    "information_exchange", "inquiry", "explanation", "advice", "gossip", "rumour", "news_discussion",
                    "complaint", "venting", "reassurance", "apology", "disappointment", "accusation",
                    "disagreement", "criticism", "provocation", "confrontation", "negotiation", "reconciliation")
TONES = ("warm", "friendly", "neutral", "awkward", "tense", "hostile", "playful", "sad", "formal")
STANDING_KINDS = ("kept_promise", "broke_promise", "competence", "incompetence", "consideration", "selfish", "support",
                  "public_humiliation", "unmet_expectation", "apology_with_change", "apology", "defended_me",
                  "hypocrisy", "insult", "ridicule", "provocation", "bullying", "threat", "lied", "agreement",
                  "reconciliation", "dismissed_me", "listened", "helped")
STANCES = ("favourable", "opposed", "neutral", "uncertain")
SIDES = ("initiator", "target", "neutral", "mediator")

_SYSTEM = ("You read transcripts of conversations between people in a life simulation and describe, for the "
           "simulation's records, what happened between them socially. People can see things differently, be wrong, "
           "or leave things unresolved -- record that, don't tidy it up. Return STRICT JSON only.")


def _ctx_block(ctx):
    ctx = ctx or {}
    lines = []
    for i in ctx.get("issues") or []:
        lines.append(f"- issue {i['id']}: {i['subject']} ({i['category']})")
    if ctx.get("confrontation"):
        x = ctx["confrontation"]
        lines.append(f"- a confrontation was under way in this conversation ({x['id']}): {x['initiator']} took up "
                     f"\"{x['problem']}\" with {x['target']} ({x['type']})")
    for k in ctx.get("contracts") or []:
        lines.append(f"- agreement {k['id']}: {k.get('title')} -- terms: {'; '.join(t for t in k['terms'] if t)}")
    for r in ctx.get("rumours") or []:
        lines.append(f"- rumour {r['id']} going round about {r['about']}: {r['claim']}")
    if ctx.get("structured"):
        lines.append("- recorded as it happened (take this as given, don't guess it from the lines):")
        lines += [f"    {l}" for l in ctx["structured"]]
    return "\n".join(lines) or "(nothing on record)"


async def _tag(transcript, people, earlier, ctx=None):
    earlier_txt = "\n".join(f"- {e['id']}: {e.get('subject') or '(untagged)'} ({e.get('when', '')})" for e in earlier) \
        or "(none)"
    prompt = f"""
The conversation, between {', '.join(people)} (the first speaker started it):
{transcript}

Earlier conversations between the same people (id: subject):
{earlier_txt}

Already on record between them:
{_ctx_block(ctx)}

Describe it. STRICT JSON with exactly these keys:
{{"subject": <3-8 words: what it was about>,
  "opening": <what the first speaker opened with, one of: {", ".join(OPENINGS)}>,
  "tags": <2-5 short lowercase topic tags>,
  "interaction_tags": <1-4 of: {", ".join(INTERACTION_TAGS)}>,
  "tone": <one of: {", ".join(TONES)}>,
  "relates_to": <the id of the earlier conversation it continues or refers back to, or null>,
  "issues": <problems between them that came up (raised, argued, or settled); [] if none. Each:
     {{"same_as": <the id of an issue on record if it's that one, else null>,
       "subject": <3-8 words>, "category": <one of: {", ".join(ISSUE_CATEGORIES)}>,
       "raised_by": <name>, "between": [<names of those it's between>],
       "positions": {{<name>: {{"position": <how THEY see it, one sentence, in their terms>,
                                "stance": <one of: {", ".join(STANCES)}>, "confidence": <0..1>}}}},
       "status": <"open" | "progress" | "resolved">}}>,
  "confrontation": <null, or -- if someone took a problem up with someone (a complaint, criticism, request to change,
     accusation, provocation, power play, negotiation...) --
     {{"type": <one of: {", ".join(CONFRONTATION_TYPES)}>, "initiator": <name>, "target": <name>,
       "issue": <the subject of the issue it was about>, "problem_statement": <what the problem is, as put>,
       "desired_outcome": <what the initiator wanted>,
       "outcome": <one of: {", ".join(CONFRONTATION_OUTCOMES)}>, "ended_by": <name or null>,
       "summary": <one sentence: how it ended>,
       "sides": {{<name of anyone else who joined in>: <one of: {", ".join(SIDES)}>}}}}>,
  "agreement": <null, or if they agreed how things will be from now on:
     {{"title": <a few words>, "renegotiates": <id of an agreement on record it replaces, or null>,
       "terms": [{{"responsible": <name>, "obligation": <what they'll do or not do>, "frequency": <how often, or null>}}]}}>,
  "violations": <agreements on record that someone was said not to have kept: [{{"contract_id": <id>,
     "responsible": <name>, "what": <a few words>, "disputed": <true if they deny it or dispute it>}}], or []>,
  "initiative_response": <how the other person received the first speaker's approach, one of:
     {", ".join(INITIATIVE_RESPONSES)}>,
  "standing_events": <things that change how one regards the other: [{{"observer": <name>, "subject": <name>,
     "kind": <one of: {", ".join(STANDING_KINDS)}>, "why": <a few words>}}], or []>,
  "about_others": <what was said about people NOT in the conversation, each
     {{"name": <their name>, "said_by": <speaker's name>, "claim": <a few words>,
       "tone": <-2 (damning) .. 2 (glowing)>, "rumour": <true if hearsay or speculation>,
       "same_as": <the id of a rumour on record if it's that one, else null>}}, [] if nobody else was talked about>,
  "told_about_themselves": <a rumour on record told to the very person it's about: [{{"rumour_id": <id>,
     "told_by": <name>}}], or []>}}
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
    return _clean(data, {e["id"] for e in earlier}, ctx or {})


def _s(v, n):
    return str(v).strip()[:n] if isinstance(v, (str, int, float)) and str(v).strip() and \
        str(v).strip().lower() not in ("null", "none") else None


def _f(v, lo=0.0, hi=1.0):
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return None


def _clean(data, earlier_ids, ctx):
    if not isinstance(data, dict):
        return None
    subject = _s(data.get("subject"), 80)
    if not subject:
        return None
    issue_ids = {i["id"] for i in ctx.get("issues") or []}
    contract_ids = {k["id"] for k in ctx.get("contracts") or []}
    rumour_ids = {r["id"] for r in ctx.get("rumours") or []}
    opening = str(data.get("opening") or "").strip().lower().replace(" ", "_")
    tags = [str(t).strip().lower()[:30] for t in (data.get("tags") or []) if str(t).strip()][:5]
    itags = [t for t in (str(x).strip().lower() for x in data.get("interaction_tags") or []) if t in INTERACTION_TAGS][:4]
    tone = str(data.get("tone") or "").strip().lower()

    issues = []
    for it in data.get("issues") or []:
        if not isinstance(it, dict) or not _s(it.get("subject"), 90):
            continue
        cat = str(it.get("category") or "").lower()
        positions = {}
        for nm, p in (it.get("positions") or {}).items():
            if isinstance(p, dict) and _s(p.get("position"), 240):
                st = str(p.get("stance") or "").lower()
                positions[str(nm)[:60]] = {"position": _s(p["position"], 240),
                                           "stance": st if st in STANCES else "uncertain",
                                           "confidence": _f(p.get("confidence"))}
        issues.append({"same_as": it.get("same_as") if it.get("same_as") in issue_ids else None,
                       "subject": _s(it["subject"], 90), "category": cat if cat in ISSUE_CATEGORIES else "other",
                       "raised_by": _s(it.get("raised_by"), 60),
                       "between": [str(x)[:60] for x in it.get("between") or [] if x][:4],
                       "positions": positions,
                       "status": it.get("status") if it.get("status") in ("open", "progress", "resolved") else "open"})

    conf = data.get("confrontation")
    if isinstance(conf, dict) and _s(conf.get("initiator"), 60) and _s(conf.get("target"), 60):
        t = str(conf.get("type") or "").lower()
        o = str(conf.get("outcome") or "").lower()
        conf = {"type": t if t in CONFRONTATION_TYPES else "criticism", "initiator": _s(conf["initiator"], 60),
                "target": _s(conf["target"], 60), "issue": _s(conf.get("issue"), 90),
                "problem_statement": _s(conf.get("problem_statement"), 240),
                "desired_outcome": _s(conf.get("desired_outcome"), 200),
                "outcome": o if o in CONFRONTATION_OUTCOMES else "unresolved",
                "ended_by": _s(conf.get("ended_by"), 60), "summary": _s(conf.get("summary"), 240),
                "sides": {str(k)[:60]: str(v).lower() for k, v in (conf.get("sides") or {}).items()
                          if str(v).lower() in SIDES}}
    else:
        conf = None

    ag = data.get("agreement")
    if isinstance(ag, dict) and ag.get("terms"):
        terms = [{"responsible": _s(t.get("responsible"), 60), "obligation": _s(t.get("obligation"), 160),
                  "frequency": _s(t.get("frequency"), 40)}
                 for t in ag["terms"] if isinstance(t, dict) and _s(t.get("obligation"), 160)][:5]
        ag = {"title": _s(ag.get("title"), 80), "terms": terms,
              "renegotiates": ag.get("renegotiates") if ag.get("renegotiates") in contract_ids else None} if terms else None
    else:
        ag = None

    violations = [{"contract_id": v["contract_id"], "responsible": _s(v.get("responsible"), 60),
                   "what": _s(v.get("what"), 120), "disputed": bool(v.get("disputed"))}
                  for v in data.get("violations") or [] if isinstance(v, dict) and v.get("contract_id") in contract_ids]

    resp = str(data.get("initiative_response") or "").lower()
    standing_events = [{"observer": _s(e.get("observer"), 60), "subject": _s(e.get("subject"), 60),
                        "kind": str(e.get("kind")).lower(), "why": _s(e.get("why"), 100)}
                       for e in data.get("standing_events") or []
                       if isinstance(e, dict) and str(e.get("kind")).lower() in STANDING_KINDS][:6]
    about = []
    for a in data.get("about_others") or []:
        if not isinstance(a, dict) or not a.get("name"):
            continue
        try:
            tone_v = max(-2, min(2, int(round(float(a.get("tone", 0))))))
        except (TypeError, ValueError):
            tone_v = 0
        about.append({"name": str(a["name"]).strip()[:60], "said_by": str(a.get("said_by") or "").strip()[:60],
                      "claim": str(a.get("claim") or "").strip()[:120], "tone": tone_v, "rumour": bool(a.get("rumour")),
                      "same_as": a.get("same_as") if a.get("same_as") in rumour_ids else None})
    told = [{"rumour_id": t["rumour_id"], "told_by": _s(t.get("told_by"), 60)}
            for t in data.get("told_about_themselves") or [] if isinstance(t, dict) and t.get("rumour_id") in rumour_ids]

    return {"subject": subject, "opening": opening if opening in OPENINGS else "small_talk", "tags": tags,
            "interaction_tags": itags, "tone": tone if tone in TONES else "neutral",
            "relates_to": data.get("relates_to") if data.get("relates_to") in earlier_ids else None,
            "issues": issues[:4], "confrontation": conf, "agreement": ag, "violations": violations[:4],
            "initiative_response": resp if resp in INITIATIVE_RESPONSES else None,
            "standing_events": standing_events, "about_others": about[:6], "told_about_themselves": told[:3]}


def tag(transcript, people, earlier, ctx=None):
    """Blocking; call from a bg_llm worker. The reading, or None."""
    result = run_llm_call(_tag(transcript, people, earlier, ctx), priority=PRIORITY_BACKGROUND)
    return result if isinstance(result, dict) and result.get("subject") else None
