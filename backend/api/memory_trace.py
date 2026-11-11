"""
/admin/memtrace/{id} -- a character's memory accesses for VR "Memory debug" (systems/memory_trace.py), oldest first,
with the sizes of their short- and long-term memory now. ?since=<tick> for only newer ones.
"""

from fastapi import APIRouter, HTTPException

from db import load_world

router = APIRouter(prefix="/admin/memtrace", tags=["memtrace"])

KINDS = {
    "stm_write": "stored (short-term)", "stm_read": "recalled (short-term)", "ltm_read": "recalled (long-term)",
    "ltm_commit": "committed to long-term", "aggregation": "aggregation", "forget": "forgotten",
}


@router.get("/{char_id}")
def memtrace(char_id: str, since: int | None = None, sim_id: str = "default"):
    world = load_world(sim_id)
    c = (world.get("characters") or {}).get(char_id)
    if not c:
        raise HTTPException(404, f"no character '{char_id}'")
    trace = c.get("memory_trace") or []
    if since is not None:
        trace = [e for e in trace if e.get("tick", 0) > since]
    return {"tick": world.get("tick", 0), "name": c.get("name"), "kinds": KINDS,
            "short_term": len(c.get("memories") or []), "long_term": len(c.get("long_term_memory") or []),
            "events": trace}
