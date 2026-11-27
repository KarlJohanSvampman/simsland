"""
The decision prompt as editable templates (brain/prompt_templates.py, api/prompt_templates.py,
frontend/prompt_editor.html).

A. The defaults reproduce the prompt the code built before templates: system and user message, with and without the
   look-around / action-menu extras.
B. Variables: {name} filled in, a block ({preamble}) rendered in place, an unknown name left as written and reported;
   blank lines from empty variables collapse.
C. Saving keeps only edits; an edit applies to the next prompt (the file is read again when it changes); saving the
   default text again is a reset.
D. Each narrative section is a variable of its own; a user template can place them one by one.
E. A template that fails to render falls back to the built-in prompt.
F. The page's warnings: no ACTION: line in the reply format, the situation left out, unknown variables.

Run inside the backend container:   python tests/test_prompt_templates.py
"""
import os, sys, tempfile, time, types
os.environ["COGNITION_MODE"] = "local"
sys.path.insert(0, "/app"); sys.path.insert(0, ".")
TMP = tempfile.mkdtemp()
os.environ["PROMPT_TEMPLATES_FILE"] = os.path.join(TMP, "prompt_templates.json")
failures = []
def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)

from brain import prompt_templates as PT
from brain import llm_brain as B

def old_system(av, cpl=None):
    menu = B._format_action_menu(av or {})
    extra = ""
    if cpl:
        from cpl.turns import FORMAT_LINES
        extra = FORMAT_LINES + "\n"
    return f"{B._PREAMBLE}\n\nActions: {menu}\n{B._ENVELOPE_FORMAT}{extra}"

av = {"action_types": ["move", "speak", "interact", "wait", "phone_send_text"],
      "interactable_props": [{"id": "p1", "name": "sofa", "tags": ["seatable"], "interactions": ["sit"]}],
      "nearby_characters": [{"id": "c2", "name": "Rebecca Carter"}]}
parts = {"wake_line": "Rebecca just said to you: \"Hi\"", "staged": [], "mode": "brief", "character_name": "Anthony Carter",
         "wake_reason": "heard_speech",
         "sections": [["scene", "You're in the kitchen."], ["identity", "You are Anthony, 36."], ["body", "You're hungry."]]}
narr = "\n\n".join([parts["wake_line"]] + [t for _k, t in parts["sections"]])
ctx = {"narrative": narr, "narrative_parts": parts, "available_actions": av, "environment_scan": None, "action_menu_cache": None}

# A
check("A: system message as before", B.build_system_prompt(av).strip() == old_system(av).strip())
check("A: user message as before", B.build_prompt(ctx) == B._builtin_prompt(ctx), (B.build_prompt(ctx), B._builtin_prompt(ctx)))
ctx2 = dict(ctx, environment_scan={"text": "A sofa, a lamp.", "focused": "The lamp is on."},
            action_menu_cache={"text": "- phone_send_text"})
check("A: ... with look-around and the fuller menu", B.build_prompt(ctx2) == B._builtin_prompt(ctx2))

# B
vals = {"a": "AAA", "empty": ""}
check("B: a variable filled in, a block rendered in place, an unknown one left",
      PT.render_text("x {a} {blk} {nope}", vals, {"blk": "[{a}]"}) == "x AAA [AAA] {nope}")
check("B: blank lines from empty variables collapse", PT.tidy("one\n\n\n\n\ntwo\n\n") == "one\n\ntwo")
check("B: unknown variables reported", PT.unknown_variables("{narrative} {bogus}", {}) == ["bogus"])

# C
PT.save({"preamble": "You are a person. Be brief.", "user": PT._code_defaults()["user"]})
import json
saved = json.load(open(os.environ["PROMPT_TEMPLATES_FILE"]))["templates"]
check("C: only the edit is kept", set(saved) == {"preamble"}, saved)
check("C: it applies to the next prompt", B.build_system_prompt(av).startswith("You are a person. Be brief."))
time.sleep(0.05)
PT.save({"preamble": PT._code_defaults()["preamble"]})
os.utime(os.environ["PROMPT_TEMPLATES_FILE"], (time.time() + 2, time.time() + 2))
check("C: saving the default again is a reset", PT.overrides() == {} and B.build_system_prompt(av).strip() == old_system(av).strip())

# D
PT.save({"user": "Now: {wake_line}\n\nYou: {section_identity}\n\n{section_body}\n\n{scene}"})
os.utime(os.environ["PROMPT_TEMPLATES_FILE"], (time.time() + 4, time.time() + 4))
u = B.build_prompt(ctx)
check("D: sections placed one by one, others left out", u.startswith("Now: Rebecca just said") and "You: You are Anthony, 36." in u
      and "You're hungry." in u and "You're in the kitchen." not in u, u)
check("D: every narrative section is a variable", all(f"section_{k}" in PT.all_variables() for k in PT.section_keys())
      and len(PT.section_keys()) > 20)
check("D: unsaved edits for the preview don't touch the file",
      B.build_prompt(ctx, unsaved={"user": "only {character_name}"}) == "only Anthony Carter"
      and "Now:" in B.build_prompt(ctx))

# E
real = PT.render
PT.render = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
check("E: a template that fails falls back to the built-in prompt",
      B.build_prompt(ctx) == B._builtin_prompt(ctx) and B.build_system_prompt(av).strip() == old_system(av).strip())
PT.render = real

# F
if "db" not in sys.modules:
    sys.modules["db"] = types.SimpleNamespace(load_world=lambda sim_id="default": {}, world_lock=None)
import api.prompt_templates as A
w = A._checks(dict(PT._code_defaults(), reply_format="Just answer.", user="Hello {nobody}"))
check("F: warnings -- no ACTION line, situation left out, unknown variable",
      any("ACTION" in x for x in w) and any("situation" in x for x in w) and any("{nobody}" in x for x in w), w)
check("F: the defaults raise none", A._checks(PT._code_defaults()) == [], A._checks(PT._code_defaults()))

print()
print("ALL PASSED" if not failures else f"{len(failures)} FAILED: {failures}")
sys.exit(1 if failures else 0)
