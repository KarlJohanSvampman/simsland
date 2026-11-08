"""
/admin/behaviour -- the definitions behind intentions (simulations/<sim>/behaviour.json), for the admin page
frontend/behaviour.html: drives, intentions, requirements, plans and the variables decisions can weigh.

    GET    /admin/behaviour                 everything, the catalogues the editor picks from, and the checker's problems
    PUT    /admin/behaviour/{kind}/{id}     create or replace one object (the body is the object; its "id" must match)
    DELETE /admin/behaviour/{kind}/{id}     remove one object (refused while something still refers to it)
    POST   /admin/behaviour/check           check a draft without saving it

Every save is checked; a save is refused if it would leave a LIVE intention with an error (brain/actionplans/checker.py).
The file is shared by the gateways and the core (the core re-reads it when it changes), so no command round trip.
"""

from fastapi import APIRouter, HTTPException

from brain.actionplans import store, checker
from brain.actionplans.resolvers import RESOLVERS
from brain.actionplans.actions import ACTIONS

router = APIRouter(prefix="/admin/behaviour", tags=["behaviour"])

KINDS = ("drives", "intentions", "requirements", "plans", "variables")


def _catalogue(sim_id):
    from systems.activities import ACTIVITIES
    from core.definitions import load_definitions
    defs = load_definitions(sim_id)
    offered = checker._offered_interactions(defs)
    return {
        "activities": sorted(({"id": a, "interaction": cfg.get("interaction"), "category": cfg.get("category"),
                               "available": (not cfg.get("interaction")) or cfg.get("no_target") or cfg.get("interaction") in offered}
                              for a, cfg in ACTIVITIES.items()), key=lambda x: x["id"]),
        "actions": [{"id": k, "doc": (fn.__doc__ or "").strip().split("\n")[0]} for k, fn in sorted(ACTIONS.items())],
        "resolvers": [{"id": k, "doc": (fn.__doc__ or "").strip().split("\n")[0]} for k, fn in sorted(RESOLVERS.items())],
        "node_kinds": {
            "gate": {"outputs": ["yes", "no"], "picks": "requirement"},
            "decision": {"outputs": "from its rules, plus its default", "picks": "rules"},
            "step": {"outputs": ["done", "failed"], "picks": "activity"},
            "action": {"outputs": ["done", "failed"], "picks": "action"},
            "wait": {"outputs": ["ready", "timed_out"], "picks": "requirement"},
            "plan": {"outputs": ["done", "blocked"], "picks": "plan"},
            "end": {"outputs": [], "picks": "outcome"},
        },
        "end_outcomes": {"intention": list(checker.END_OUTCOMES_INTENTION), "sub": list(checker.END_OUTCOMES_SUB)},
    }


def _problems(data, sim_id):
    from core.definitions import load_definitions
    return checker.check(data, load_definitions(sim_id))


def _live_errors(data, problems):
    """Errors that would touch a live intention: on the intention itself or on a plan it can reach."""
    live = [i for i in data.get("intentions") or [] if i.get("status") == "live"]
    plans = {p["id"]: p for p in data.get("plans") or []}
    reach = set()
    for i in live:
        stack = list(i.get("plans") or []) + ([i["scout_plan"]] if i.get("scout_plan") else [])
        while stack:
            pid = stack.pop()
            if pid in reach or pid not in plans or plans[pid].get("status") == "planned":
                continue
            reach.add(pid)
            stack.extend(n.get("plan") for n in plans[pid].get("nodes") or [] if n.get("kind") == "plan")
    keys = {f"intention:{i['id']}" for i in live} | {f"plan:{p}" for p in reach}
    return [p for p in problems if p["level"] == "error" and any(p["where"] == k or p["where"].startswith(k + "/")
                                                                  or p["where"].startswith(k + "#") for k in keys)]


@router.get("")
def get_all(sim_id: str = "default"):
    data = store.load(sim_id)
    return {"data": data, "catalogue": _catalogue(sim_id), "problems": _problems(data, sim_id)}


@router.post("/check")
def check_draft(payload: dict, sim_id: str = "default"):
    return {"problems": _problems(payload, sim_id)}


@router.put("/{kind}/{oid}")
def put_object(kind: str, oid: str, obj: dict, sim_id: str = "default"):
    if kind not in KINDS:
        raise HTTPException(404, f"no such kind: {kind}")
    if obj.get("id") != oid:
        raise HTTPException(400, "the object's id must match the address")
    data = dict(store.load(sim_id))
    items = [o for o in data.get(kind) or [] if o.get("id") != oid]
    old = next((o for o in data.get(kind) or [] if o.get("id") == oid), None)
    items.insert(next((i for i, o in enumerate(data.get(kind) or []) if o.get("id") == oid), len(items)), obj)
    data[kind] = items
    problems = _problems(data, sim_id)
    bad = _live_errors(data, problems)
    if bad:
        raise HTTPException(409, {"text": "this would break a live intention", "problems": bad})
    store.save(data, sim_id)
    return {"saved": oid, "created": old is None, "problems": problems}


@router.delete("/{kind}/{oid}")
def delete_object(kind: str, oid: str, sim_id: str = "default"):
    if kind not in KINDS:
        raise HTTPException(404, f"no such kind: {kind}")
    data = dict(store.load(sim_id))
    if not any(o.get("id") == oid for o in data.get(kind) or []):
        raise HTTPException(404, f"no {kind[:-1]} '{oid}'")
    data[kind] = [o for o in data[kind] if o.get("id") != oid]
    problems = _problems(data, sim_id)
    dangling = [p for p in problems if p["level"] == "error" and f"'{oid}'" in p["text"]]
    if dangling:
        raise HTTPException(409, {"text": f"still in use: {len(dangling)} reference(s)", "problems": dangling})
    store.save(data, sim_id)
    return {"deleted": oid, "problems": problems}
