"""
Proves the behaviour definitions before anything runs them (design doc: "Verifiable call paths").

check(data, definitions=None) -> [problem, ...]; problem = {"level": "error" | "warning", "where": "plan:cook_meal/ingr",
"text": "..."}. An intention can only be live with no errors in it or in any plan it reaches.
"""

from brain.plans.resolvers import RESOLVERS
from brain.plans.actions import ACTIONS

NODE_KINDS = ("gate", "decision", "step", "action", "wait", "plan", "end")
END_OUTCOMES_INTENTION = ("satisfied", "fallback", "blocked")
END_OUTCOMES_SUB = ("done", "blocked")
MAX_SIDETRACK_DEPTH = 2


def outputs_for(node):
    """The named outputs of a node -- the ports the flow editor draws, and what must each be wired once."""
    k = node.get("kind")
    if k == "gate":
        return ["yes", "no"]
    if k == "decision":
        outs = []
        for r in node.get("rules") or []:
            if r.get("output") and r["output"] not in outs:
                outs.append(r["output"])
        if node.get("default") and node["default"] not in outs:
            outs.append(node["default"])
        return outs
    if k in ("step", "action"):
        return ["done", "failed"]
    if k == "wait":
        return ["ready", "timed_out"]
    if k == "plan":
        return ["done", "blocked"]
    return []


def _offered_interactions(definitions):
    out = set()
    for t in (definitions or {}).get("prop_templates", {}).values():
        for a in t.get("anchors") or []:
            if a.get("interaction"):
                out.add(a["interaction"])
    return out


def check(data, definitions=None):
    from systems.activities import ACTIVITIES
    probs = []
    P = lambda level, where, text: probs.append({"level": level, "where": where, "text": text})
    drives = {d["id"]: d for d in data.get("drives") or []}
    intents = {i["id"]: i for i in data.get("intentions") or []}
    reqs = {r["id"]: r for r in data.get("requirements") or []}
    plans = {p["id"]: p for p in data.get("plans") or []}
    variables = {v["id"] for v in data.get("variables") or []}
    offered = _offered_interactions(definitions) if definitions else None

    for kind, items in (("drive", data.get("drives")), ("intention", data.get("intentions")),
                        ("requirement", data.get("requirements")), ("plan", data.get("plans"))):
        seen = set()
        for o in items or []:
            if not o.get("id"):
                P("error", kind, "an entry has no id")
            elif o["id"] in seen:
                P("error", f"{kind}:{o['id']}", "the id is used twice")
            seen.add(o.get("id"))

    for d in drives.values():
        if d.get("intention") not in intents:
            P("error", f"drive:{d['id']}", f"its intention '{d.get('intention')}' does not exist")
    owners = {}
    for i in intents.values():
        w = f"intention:{i['id']}"
        if i.get("drive") not in drives:
            P("error", w, f"its drive '{i.get('drive')}' does not exist")
        elif drives[i["drive"]].get("intention") != i["id"]:
            P("error", w, f"drive '{i['drive']}' raises '{drives[i['drive']].get('intention')}', not this intention (one intention per drive)")
        if i.get("drive") in owners:
            P("error", w, f"drive '{i['drive']}' already has intention '{owners[i['drive']]}'")
        owners[i.get("drive")] = i["id"]
        for pid in i.get("plans") or []:
            if pid not in plans:
                P("error", w, f"plan '{pid}' does not exist")
        if i.get("scout_plan") and i["scout_plan"] not in plans:
            P("error", w, f"scout plan '{i['scout_plan']}' does not exist")
        if i.get("status") == "live":
            usable = [pid for pid in i.get("plans") or [] if pid in plans and plans[pid].get("status") != "planned"]
            if not usable:
                P("error", w, "live, but none of its plans can run")

    for r in reqs.values():
        if r.get("resolver") not in RESOLVERS:
            P("error", f"requirement:{r['id']}", f"its resolver '{r.get('resolver')}' is not in brain/plans/resolvers.py")

    sub_of = {pid for p in plans.values() for n in p.get("nodes") or [] if n.get("kind") == "plan" for pid in [n.get("plan")]}
    for p in plans.values():
        _check_plan(p, plans, reqs, variables, offered, ACTIVITIES, P, sub_of)
    for p in plans.values():
        d = _depth(p["id"], plans, [])
        if d is None:
            P("error", f"plan:{p['id']}", "sidetracks into itself")
        elif d > MAX_SIDETRACK_DEPTH:
            P("error", f"plan:{p['id']}", f"sidetracks {d} deep (at most {MAX_SIDETRACK_DEPTH})")
    return probs


def _depth(pid, plans, stack):
    if pid in stack:
        return None
    best = 0
    for n in (plans.get(pid) or {}).get("nodes") or []:
        if n.get("kind") == "plan" and n.get("plan") in plans:
            d = _depth(n["plan"], plans, stack + [pid])
            if d is None:
                return None
            best = max(best, 1 + d)
    return best


def _check_plan(p, plans, reqs, variables, offered, activities, P, sub_of):
    w = f"plan:{p['id']}"
    nodes = {}
    for n in p.get("nodes") or []:
        if n.get("id") in nodes:
            P("error", f"{w}/{n.get('id')}", "the node id is used twice")
        nodes[n.get("id")] = n
    entries = p.get("entries") or ([{"id": "start", "node": p.get("start")}] if p.get("start") else [])
    if not entries:
        P("error", w, "has no entry point")
    for e in entries:
        if e.get("node") not in nodes:
            P("error", f"{w}#{e.get('id')}", f"entry point goes to '{e.get('node')}', which is not a node of this plan")
    is_sub = p.get("kind") in ("sidetrack", "scout") or p["id"] in sub_of
    for r in p.get("requires") or []:
        if r not in reqs:
            P("error", w, f"entry requirement '{r}' does not exist")
    set_vars = {v for e in entries for v in e.get("vars") or []} | {v for ed in p.get("edges") or [] for v in (ed.get("set") or {})}
    out_of = {}
    for ed in p.get("edges") or []:
        a, o, b = ed.get("from"), ed.get("output"), ed.get("to")
        if a not in nodes:
            P("error", w, f"a wire starts at '{a}', which is not a node")
            continue
        if o not in outputs_for(nodes[a]):
            P("error", f"{w}/{a}", f"has no output '{o}' (it has {', '.join(outputs_for(nodes[a])) or 'none'})")
        if b not in nodes:
            P("error", f"{w}/{a}", f"output '{o}' goes to '{b}', which is not a node")
        if (a, o) in out_of:
            P("error", f"{w}/{a}", f"output '{o}' is wired twice")
        out_of[(a, o)] = b
    for nid, n in nodes.items():
        where = f"{w}/{nid}"
        k = n.get("kind")
        if k not in NODE_KINDS:
            P("error", where, f"unknown kind '{k}'")
            continue
        for o in outputs_for(n):
            if (nid, o) not in out_of:
                P("error", where, f"output '{o}' is not wired to anything")
        if k in ("gate", "wait"):
            if n.get("requirement") not in reqs:
                P("error", where, f"requirement '{n.get('requirement')}' does not exist")
            if k == "wait" and not (n.get("timeout_seconds") or 0) > 0:
                P("error", where, "a wait needs a timeout")
        elif k == "decision":
            if not n.get("default"):
                P("error", where, "a decision needs a default output")
            for r in n.get("rules") or []:
                for cond in r.get("when") or []:
                    if cond.get("var") not in variables and cond.get("var") not in set_vars:
                        P("warning", where, f"weighs '{cond.get('var')}', which no variable list or wire provides")
        elif k == "step":
            act = activities.get(n.get("activity"))
            if not act:
                P("error", where, f"activity '{n.get('activity')}' is not in systems/activities.py")
            elif offered is not None and act.get("interaction") and act["interaction"] not in offered and not act.get("no_target"):
                P("error" if p.get("status") != "planned" else "warning", where,
                  f"activity '{n['activity']}' needs the interaction '{act['interaction']}', which no prop template offers")
        elif k == "action":
            if n.get("action") not in ACTIONS:
                P("error", where, f"action '{n.get('action')}' is not in brain/plans/actions.py")
        elif k == "plan":
            sub = plans.get(n.get("plan"))
            if not sub:
                P("error", where, f"plan '{n.get('plan')}' does not exist")
            elif n.get("entry") and n["entry"] not in [e["id"] for e in sub.get("entries") or []]:
                P("error", where, f"plan '{sub['id']}' has no entry point '{n['entry']}'")
        elif k == "end":
            allowed = END_OUTCOMES_SUB if is_sub else END_OUTCOMES_INTENTION
            if n.get("outcome") not in allowed:
                P("error", where, f"ends '{n.get('outcome')}'; this kind of plan ends {' / '.join(allowed)}")
    # every node can be reached, and every path ends: a loop must pass a plan (tried once per attempt) or a wait (timeout)
    reach = set()
    stack = [e.get("node") for e in entries if e.get("node") in nodes]
    while stack:
        x = stack.pop()
        if x in reach:
            continue
        reach.add(x)
        stack.extend(b for (a, _), b in out_of.items() if a == x and b in nodes)
    for nid in nodes:
        if nid not in reach:
            P("warning", f"{w}/{nid}", "nothing leads to this node")
    color = {}

    def dfs(x, guarded):
        color[x] = 1
        for (a, _), b in out_of.items():
            if a != x or b not in nodes:
                continue
            g = guarded or nodes[b].get("kind") in ("plan", "wait") or nodes[x].get("kind") in ("plan", "wait")
            if color.get(b) == 1 and not g:
                P("error", f"{w}/{x}", f"loops back to '{b}' with no plan or wait in between, so it could run forever")
            elif not color.get(b):
                dfs(b, g)
        color[x] = 2
    for e in entries:
        if e.get("node") in nodes and not color.get(e["node"]):
            dfs(e["node"], False)
