"""Collect the facts for the flow map: every job in core/flow.py with what it calls, emits, and who listens."""
import ast, os, re, json, sys, collections
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))); os.chdir(ROOT); sys.path.insert(0, ROOT)
from core import flow
defs = {}
mods = {}
for dp, _, fs in os.walk("."):
    if "tests" in dp or "__pycache__" in dp: continue
    for f in fs:
        if f.endswith(".py"):
            p = os.path.join(dp, f)[2:]
            try: t = ast.parse(open(p).read())
            except Exception: continue
            mods[p] = t
            for n in ast.walk(t):
                if isinstance(n, ast.FunctionDef):
                    defs.setdefault(n.name, []).append((p, n))
SKIP = set("get values items list print isinstance len range getattr setdefault keys append pop int float dict set str min max any all sorted enumerate load_definitions _load_defs_pf bool next sum round _mark_dirty mark update uniform choice sample join lower format extend copy startswith split replace strip remove add discard emit _alive_characters".split())
def calls_of(node):
    out = []
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func; name = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else None)
            if name and name not in SKIP and name not in out: out.append(name)
    return out
def emits_of(node):
    ev = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func; name = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else None)
            if name == "emit" and n.args and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str):
                ev.add(n.args[0].value)
    return ev
def deep(fname, depth=3, seen=None):
    seen = seen if seen is not None else set()
    if fname in seen or fname not in defs or depth < 0: return set()
    seen.add(fname); out = set()
    p, n = defs[fname][0]
    out |= emits_of(n)
    for c in calls_of(n): out |= deep(c, depth - 1, seen)
    return out
# subscribers: subscribe("ev", handler)
subs = collections.defaultdict(list)
for p, t in mods.items():
    for n in ast.walk(t):
        if isinstance(n, ast.Call):
            f = n.func; name = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else None)
            if name == "subscribe" and len(n.args) >= 2 and isinstance(n.args[0], ast.Constant):
                h = n.args[1]
                hn = h.id if isinstance(h, ast.Name) else (h.attr if isinstance(h, ast.Attribute) else ast.unparse(h)[:40])
                subs[n.args[0].value].append(f"{hn} ({p})")
sim = mods["sim_loop.py"]
jobfns = {n.name: n for n in sim.body if isinstance(n, ast.FunctionDef)}
out = []
for j in flow.JOBS:
    run = j["run"]
    node = jobfns.get(run) if ":" not in run else None
    if ":" in run:
        mod, fn = run.split(":"); node = next((n for p, n in defs.get(fn, []) if p.replace("/", ".")[:-3] == mod), None)
    fns, emits = [], set()
    if node is not None:
        emits |= emits_of(node)
        for c in calls_of(node):
            if c in defs and c != run:
                p, n = defs[c][0]
                fns.append({"fn": c, "file": p, "doc": (ast.get_docstring(n) or "").strip().split("\n")[0][:120]})
                emits |= deep(c)
    out.append(dict(j, functions=fns, emits=sorted(emits)))
json.dump({"jobs": out, "subscribers": {k: v for k, v in subs.items()}, "emitted_at": flow.EMITTED_AT},
          open(sys.argv[1], "w"), indent=1)
print(len(out), "jobs;", sum(1 for j in out if j["kind"] == "event"), "event,", sum(1 for j in out if j["kind"] == "clock"), "clock,", sum(1 for j in out if j["kind"] == "process"), "process;", len(subs), "event types with subscribers")
