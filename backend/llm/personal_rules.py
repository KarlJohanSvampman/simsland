"""
llm/personal_rules.py -- the model turns a director's notes on a character's lines (systems/dialogue_feedback.py)
into a few short personal rules, in the character's own voice (systems/personal_rules.py proposes them; the
director approves). A pure model call: plain prompt in, plain list out -- runs on a bg_llm worker.
"""

import re

from llm.llm_client import call_llm_safe
from llm.llm_gate import run_llm_call, PRIORITY_BACKGROUND

SYSTEM = (
    "You help keep a simulated person in character. A director has left notes on things this person said: lines they "
    "liked or disliked, why, and sometimes a line that would have fit better. Turn what the notes have in common into "
    "short personal rules this person keeps from now on, written in the first person as the person themselves "
    "(\"I ...\"), each under 20 words, concrete about how they talk or behave -- not about the director or the notes. "
    "Don't repeat a rule they already have, and never propose one that was turned down. At most 3 rules; fewer is "
    "better. Reply with one line per rule:\n"
    "RULE: <the rule> | FROM: <the numbers of the notes it comes from>\n"
    "or just NONE if the notes don't add up to a rule."
)


def build_prompt(name, age, traits, quirks, approved, rejected, notes):
    lines = [f"Person: {name}" + (f", {age}" if age else "") + (f". Traits: {', '.join(traits)}." if traits else ".")]
    if quirks:
        lines.append(f"How they talk: {', '.join(quirks)}.")
    if approved:
        lines.append("Rules they already keep:\n" + "\n".join(f"- {r}" for r in approved))
    if rejected:
        lines.append("Rules that were turned down (don't propose these again):\n" + "\n".join(f"- {r}" for r in rejected))
    lines.append("The director's notes:")
    for i, n in enumerate(notes, 1):
        bits = [f'{i}. They said: "{n["utterance"]}"']
        if n.get("verdict"):
            bits.append(f"-- {n['verdict']}d")
        if n.get("comment"):
            bits.append(f"-- why: {n['comment']}")
        if n.get("suggestion"):
            bits.append(f'-- would fit better: "{n["suggestion"]}"')
        lines.append(" ".join(bits))
    return "\n".join(lines)


_RULE = re.compile(r"(?im)^\s*[-*]?\s*RULE\s*:\s*(.+?)\s*(?:\|\s*FROM\s*:\s*([\d,\s]+))?\s*$")


def parse(text, n_notes):
    """'RULE: I keep it casual with family | FROM: 1, 3' -> [{"text", "from": [0, 2]}] (note indexes)."""
    out = []
    for m in _RULE.finditer(text or ""):
        rule = m.group(1).strip().strip('"').strip()
        if not rule or rule.upper() == "NONE":
            continue
        frm = [int(x) - 1 for x in re.findall(r"\d+", m.group(2) or "") if 0 < int(x) <= n_notes]
        out.append({"text": rule[:200], "from": frm})
    return out[:3]


async def _propose(prompt, char_id):
    res = await call_llm_safe([{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}], char_id=char_id)
    if isinstance(res, dict):
        return None if res.get("error") else res.get("text")
    return res


def propose(prompt, n_notes, char_id):
    """Blocking; call from a bg_llm worker. [{"text", "from"}] -- [] when the notes add up to nothing, None when the
    model didn't answer (try again later)."""
    text = run_llm_call(_propose(prompt, char_id), priority=PRIORITY_BACKGROUND)
    if not isinstance(text, str):
        return None
    return parse(text, n_notes)
