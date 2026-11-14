"""
Every command says which entities it changes (core/commands.py, docs/distributed_architecture_plan.md step 5a):
@command(name, entities=fn) for the ones that change named entities -- with per-entity locks (core/entity_locks.py) they
run alongside the tick when those differ -- or entities="world" for the ones that take the whole world on purpose
(resets, the editor, anything that reaches props, which are not locked one by one).

  * statically: every @command in the backend has an `entities=`;
  * live, with ENTITY_LOCKS=on, on the determinism fixture: each declared command reaches no entity it did not
    declare (an undeclared access is still locked -- correct, but it waits for the step that holds it, and the
    declaration should name it).

Run inside the backend container:   python tests/test_command_entities.py
"""

import ast
import os
import sys

os.environ.setdefault("COGNITION_MODE", "local")
os.environ["ENTITY_LOCKS"] = "on"
sys.path.insert(0, "/app")
sys.path.insert(0, ".")

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


# ── every command declares ───────────────────────────────────────────────────────────────────────────────────────────
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
missing, total = [], 0
for root, dirs, files in os.walk(here):
    dirs[:] = [d for d in dirs if d not in ("tests", "node_modules", "__pycache__", ".git")]
    for f in files:
        if not f.endswith(".py"):
            continue
        path = os.path.join(root, f)
        try:
            tree = ast.parse(open(path).read())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for d in node.decorator_list:
                if isinstance(d, ast.Call) and getattr(d.func, "id", None) == "command":
                    total += 1
                    if not any(k.arg == "entities" for k in d.keywords):
                        missing.append(f"{os.path.relpath(path, here)}:{node.name}")
check(f"every command declares its entities or the whole world ({total} commands)", total > 40 and not missing, missing)

# ── live: a declared command reaches only what it declared ────────────────────────────────────────────────────────────
import tests.determinism as D
D._install()
import db
import main  # noqa: F401 -- registers its commands
from core import commands, entity_locks as EL
from api import admin, household, director, persona, editor, middleware_bridge  # noqa: F401

SIM = "default"
with db.world_lock():
    w = db.load_world(SIM)
chars = [cid for cid, c in w["characters"].items() if not c.get("is_workplace_npc")]
a, b = chars[0], chars[1]
hid = w["characters"][a].get("household_id") or next(iter(w["households"]))
bld = next((x["id"] for x in w.get("buildings", []) if x.get("owner_household_id")), None)

declared = {n for n, e in commands.DECLARED.items() if e is not None and e != "world"}
world_wide = sorted(n for n, e in commands.DECLARED.items() if e == "world")
print(f"   {len(declared)} commands declare entities, {len(world_wide)} take the whole world: {', '.join(world_wide)}")

CALLS = {
    "household.set_name": lambda: household.set_name(SIM, {"household_id": hid, "name": "Test"}),
    "household.set_newspaper_subscription": lambda: household.set_newspaper_subscription(
        SIM, {"household_id": hid, "subscribed": True}),
    "household.set_building_address": lambda: household.set_building_address(
        SIM, {"building_id": bld, "address": "1 Test St"}),
    "household.create": lambda: household.create(SIM, {"name": "New"}),
    "admin.set_time_scale": lambda: admin.set_time_scale({"value": 1}, sim_id=SIM),
    "admin.set_movement_speed": lambda: admin.set_movement_speed({"value": 1}, sim_id=SIM),
    "admin.set_vision_settings": lambda: admin.set_vision_settings({"normal_m": 30}, sim_id=SIM),
    "admin.set_vision": lambda: admin.set_vision({"character_id": a, "vision": "normal"}, sim_id=SIM),
    "admin.clear_legal": lambda: admin.clear_legal({"character_ids": [a]}, sim_id=SIM),
    "admin.recall_characters": lambda: admin.recall_characters({"character_ids": [a]}, sim_id=SIM),
    "admin.impact": lambda: admin.impact_admin({"source": a, "target": b, "kind": "kindness"}, sim_id=SIM),
    "admin.register_worry": lambda: admin.register_worry_admin({"character_id": a, "label": "the test"}, sim_id=SIM),
    "admin.set_body_need": lambda: admin.set_body_need({"character_id": a, "need": "hunger", "value": 40}, sim_id=SIM),
    "admin.set_relationship": lambda: admin.set_relationship({"from_id": a, "to_id": b, "fields": {"trust": 0.5}},
                                                             sim_id=SIM),
    "admin.dedupe_long_term_memory": lambda: admin.dedupe_long_term_memory({"character_id": a}, sim_id=SIM),
    "director.start_session": lambda: director.start_session({"char_id": a}, sim_id=SIM),
    "director.interrupt_attention": lambda: director.interrupt_attention({"char_id": a}, sim_id=SIM),
    "director.set_preference": lambda: director.set_preference({"char_id": a, "field": "mood", "value": "calm"},
                                                               sim_id=SIM),
    "director.end_session": lambda: director.end_session({"char_id": a}, sim_id=SIM),
    "editor.remove_family_relation": lambda: editor.remove_family_relation({"sim_id": SIM, "a_id": a, "b_id": b}),
    "main.update_environment": lambda: main.update_environment({"test": True}),
    "main.clear_llm_logs": lambda: main.clear_llm_logs(),
}
if bld:
    CALLS["household.unassign_building_route"] = lambda: household.unassign_building_route(SIM, {"building_id": bld})
CALLS["household.remove_member"] = lambda: household.remove_member(SIM, {"character_id": b})

ran = []
for name, call in CALLS.items():
    before = dict(EL._undeclared)
    try:
        call()
    except Exception as exc:
        check(f"{name} runs", False, repr(exc)[:200])
        continue
    extra = {k: v - before.get(k, 0) for k, v in EL._undeclared.items() if v > before.get(k, 0)}
    ran.append(name)
    check(f"{name} reaches only what it declares", not extra, sorted(extra)[:6])
untried = sorted(declared - set(ran))
print(f"   not exercised here: {', '.join(untried) or 'none'}")
check("the declared commands are exercised (all but a few that need an LLM, a session or a fixture with more)",
      len(untried) <= 6, untried)

print()
print("all passed" if not failures else f"FAILED: {', '.join(failures)}")
sys.exit(1 if failures else 0)
