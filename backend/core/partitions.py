"""
core/partitions.py -- partitioned ownership, in one process (docs/step5b_plan.md, slice 2).

N partitions, each with its own copy of the world. Partition p is authoritative for what it owns (core/ownership.py);
every other entity in its copy is a replica. A step:

    1. each partition, in turn, takes in its inbox (timers and duty wake-ups others routed to it), then runs the
       simulation step for what it owns -- its characters' updates and timers, its loop members; partition 0 also
       runs the world jobs, duties, conversations;
    2. whatever a partition changed in an entity it doesn't own becomes a field-level patch (core/entity_patch.py)
       against that entity as last published, and its copy goes back to the published one;
    3. the owners apply the patches they received, in partition order;
    4. every owner publishes the entities it changed (or had patched): everyone's copy is replaced.

Per-process bookkeeping is not shared: the scheduler's timers, the dirty sets, loop and per-character-job membership
(LOCAL_KEYS) stay local; the clock advances the same way in every partition.

Hooks elsewhere (all no-ops outside a cluster): here() -- core/flow.py PERCHAR members, brain/agent_wake.py due
characters; loop_ids() -- core/active_loops.py; runs_recurring() / forward_timer() -- core/scheduler.py;
forward_duty() -- core/flow.py::wake_duty.

This module is the proving ground (the determinism harness runs it inline, tests/test_partitions.py); slice 3 moves
each partition into its own process, with frames and patches over Redis.
"""

import copy
import json

from core import entity_patch, ownership

CURRENT = None                 # the partition whose step is running (None: not partitioned)

LOCAL_KEYS = {"timers", "_timer_seq", "_sched_sig", "_dirty", "_perchar_members", "_active_loops", "_bg_work",
              "tick", "sim_time", "calendar", "_clock", "_owners_local", "cpl_dedupe", "_defaults_tick",
              "_known_char_ids", "_conv_tag_queue"}
_CHARACTER_LOOPS = {"movement", "nudity"}
_WORLD_TIMER_PREFIXES = ("cpl", "duty", "convidle", "flow")


def here(world, kind, eid):
    if CURRENT is None:
        return True
    return ownership.owner_of(world, kind, eid) == CURRENT


def loop_ids(world, name, ids):
    if CURRENT is None:
        return ids
    if name in _CHARACTER_LOOPS:
        return [i for i in ids if here(world, "characters", i)]
    return ids if CURRENT == 0 else []


def _perchar_names():
    from core import flow
    return set(flow._perchar_fns)


def runs_recurring(owner):
    """Recurring jobs: per-character ones (PERCHAR) everywhere, over their own members; the rest in partition 0."""
    return CURRENT is None or CURRENT == 0 or owner in _perchar_names()


def route(world, owner):
    """Which partition a timer belongs to: a character's (its id in the owner string) -> that character's owner;
    anything else -> partition 0. Per-character jobs' recurring timers stay where they are set."""
    if owner in _perchar_names():
        return CURRENT if CURRENT is not None else 0
    chars = world.get("characters") or {}
    for part in str(owner).split(":")[1:]:
        if dict.__contains__(chars, part):
            return ownership.owner_of(world, "characters", part)
    return 0


def _inbox(world, p):
    key = f"_inbox_{p}"
    box = world.get(key)
    if box is None:
        world[key] = box = []
    return box


def forward_timer(world, owner, key, ts, payload, every, spec):
    """In a partition: a timer for another partition's entity is sent to it. True if forwarded (not set here)."""
    if CURRENT is None:
        return False
    p = route(world, owner)
    if p == CURRENT:
        return False
    _inbox(world, p).append({"t": "timer", "owner": owner, "key": key, "ts": ts, "payload": payload,
                             "every": every, "spec": spec})
    return True


def forward_duty(world, name):
    if CURRENT is None or CURRENT == 0:
        return False
    _inbox(world, 0).append({"t": "duty", "name": name})
    return True


def owner_of_key(kind, eid):
    """Owner of a world-level key: a partition's inbox is its own; the rest is partition 0's."""
    if kind == "key" and str(eid).startswith("_inbox_"):
        return int(str(eid).rsplit("_", 1)[1])
    return 0


# ── the cluster ──────────────────────────────────────────────────────────────────────────────────────────────────────

def _keys(world):
    """(kind, id) of every shared entity in a world (raw: nothing touched)."""
    out = []
    for k, v in dict.items(world):
        if k in LOCAL_KEYS or k in _static():
            continue
        if k in ("characters", "households", "conversations", "conversation_archive", "cpl_conversations",
                 "cpl_requests") and isinstance(v, dict):
            out += [(k, str(i)) for i in dict.keys(v)]
        elif k == "props" and isinstance(v, list):
            out += [("props", str(p.get("id"))) for p in list.__iter__(v) if isinstance(p, dict) and p.get("id")]
        else:
            out.append(("key", k))
    return out


_STATIC = None


def _static():
    global _STATIC
    if _STATIC is None:
        from db import _STATIC_WORLD_KEYS
        _STATIC = set(_STATIC_WORLD_KEYS) | {"definitions"}
    return _STATIC


def _get(world, key):
    kind, eid = key
    if kind == "key":
        return dict.get(world, eid)
    coll = dict.get(world, kind)
    if isinstance(coll, dict):
        return dict.get(coll, eid)
    if isinstance(coll, list):
        return next((p for p in list.__iter__(coll) if isinstance(p, dict) and str(p.get("id")) == eid), None)
    return None


def _put(world, key, value):
    """Set (or with value None, remove) an entity, raw (the façade is not told: this is replication, not a write)."""
    kind, eid = key
    if kind == "key":
        if value is None:
            dict.pop(world, eid, None)
        else:
            dict.__setitem__(world, eid, value)
        return
    coll = dict.get(world, kind)
    if coll is None:
        dict.__setitem__(world, kind, [] if kind == "props" else {})
        coll = dict.get(world, kind)
    if isinstance(coll, dict):
        if value is None:
            dict.pop(coll, eid, None)
        else:
            dict.__setitem__(coll, eid, value)
    else:
        idx = next((n for n, p in enumerate(list.__iter__(coll)) if isinstance(p, dict) and str(p.get("id")) == eid),
                   None)
        if value is None:
            if idx is not None:
                list.__delitem__(coll, idx)
        elif idx is None:
            list.append(coll, value)
        else:
            list.__setitem__(coll, idx, value)


def _owner(world, key):
    kind, eid = key
    if kind in ownership.KINDS:
        return ownership.owner_of(world, kind, eid)
    return owner_of_key(kind, eid)


def _dumps(v):
    return json.dumps(v, default=str)


class Cluster:
    def __init__(self, world, n, sim_id="part", exact=True):
        from core import world_view
        self.exact = exact
        ownership.assign(world, n)
        self.n = n
        self.parts = []
        for p in range(n):
            w = copy.deepcopy(dict(world)) if p else world
            w = world_view.install(w, f"{sim_id}{p}")
            self._keep_own_timers(w, p)
            self.parts.append({"id": p, "world": w, "sim_id": f"{sim_id}{p}",
                               "published": {k: _dumps(_get(w, k)) for k in _keys(w)}})
        self.stats = {"steps": 0, "patches": 0, "ops": 0, "ops_landed": 0, "published": 0, "creates": 0,
                      "deletes": 0}

    def _keep_own_timers(self, w, p):
        global CURRENT
        prev, CURRENT = CURRENT, p
        try:
            dict.__setitem__(w, "timers", [t for t in (dict.get(w, "timers") or [])
                                           if route(w, t["owner"]) == p and (t.get("key") != "recurring"
                                                                             or runs_recurring(t["owner"]))])
        finally:
            CURRENT = prev

    def world(self, p=0):
        return self.parts[p]["world"]

    def _drain_inbox(self, part):
        w, p = part["world"], part["id"]
        box = dict.get(w, f"_inbox_{p}") or []
        if not box:
            return
        dict.__setitem__(w, f"_inbox_{p}", [])
        from core import scheduler, flow
        for m in box:
            if m["t"] == "timer":
                scheduler.schedule_at(w, m["owner"], m["key"], m["ts"], m.get("payload"), m.get("every"), m.get("spec"))
            elif m["t"] == "duty":
                flow.wake_duty(w, m["name"])

    def step(self, tick_fn):
        global CURRENT
        from core import world_view
        outgoing = []                                  # (owner, key, op): "patch" ops | "create" value | "delete"
        changed = {p["id"]: set() for p in self.parts}
        for part in self.parts:
            w, p = part["world"], part["id"]
            CURRENT = p
            try:
                world_view.take_touched(part["sim_id"])
                self._drain_inbox(part)
                tick_fn(w)
            finally:
                CURRENT = None
            touched = world_view.take_touched(part["sim_id"]) or set()
            cands = {k for k in touched if k[0] != "*list"}
            if self.exact:
                # every entity, not only those the façade saw reached: in ONE process the partitions share module
                # state (the event queue above all -- a decision can be applied during another partition's turn), so
                # a change can land outside the partition's own window; compared whole, it is found wherever it is
                cands |= set(_keys(w)) | set(part["published"])
            cands |= {("props", str(x.get("id"))) for x in list.__iter__(dict.get(w, "props") or [])
                      if isinstance(x, dict) and x.get("id")}
            cands |= {k for k in part["published"] if k[0] == "props"}
            cands |= {("key", k) for k in dict.keys(w) if k.startswith("_inbox_")}
            for key in cands:
                if key[0] == "key" and (key[1] in LOCAL_KEYS or key[1] in _static()):
                    continue
                now, before = _get(w, key), part["published"].get(key)
                text = None if now is None else _dumps(now)
                if text == before:
                    continue
                owner = _owner(w, key)
                if owner == p:
                    changed[p].add(key)
                    continue
                if before is None:
                    outgoing.append((owner, key, "create", copy.deepcopy(now)))
                elif now is None:
                    outgoing.append((owner, key, "delete", None))
                else:
                    ops = entity_patch.diff(json.loads(before), json.loads(text))
                    if ops:
                        outgoing.append((owner, key, "patch", ops))
                _put(w, key, None if before is None else json.loads(before))      # back to the published copy
        for owner, key, what, body in outgoing:          # partition order: deterministic
            w = self.parts[owner]["world"]
            if what == "patch":
                ent = _get(w, key)
                if ent is None:
                    continue
                self.stats["patches"] += 1
                self.stats["ops"] += len(body)
                self.stats["ops_landed"] += entity_patch.apply(ent, body)
            elif what == "create":
                if _get(w, key) is None:
                    _put(w, key, body)
                    self.stats["creates"] += 1
                else:
                    ops = entity_patch.diff(_get(w, key), body)
                    self.stats["ops_landed"] += entity_patch.apply(_get(w, key), ops)
            else:
                _put(w, key, None)
                self.stats["deletes"] += 1
            changed[owner].add(key)
            if key[0] == "characters":
                from brain import agent_wake
                agent_wake.reindex(w, key[1])
        for part in self.parts:                          # publish: every owner's changed entities to everyone
            src = part["world"]
            for key in changed[part["id"]]:
                ent = _get(src, key)
                text = None if ent is None else _dumps(ent)
                self.stats["published"] += 1
                for other in self.parts:
                    other["published"][key] = text
                    if other is not part:
                        _put(other["world"], key, None if ent is None else json.loads(text))
                    if text is None:
                        other["published"].pop(key, None)
        self.stats["steps"] += 1

    def divergence(self):
        """Entities whose copies differ between partitions (should be none after a step)."""
        bad = []
        base = self.parts[0]["world"]
        for key in _keys(base):
            t = _dumps(_get(base, key))
            for other in self.parts[1:]:
                if _dumps(_get(other["world"], key)) != t:
                    bad.append((key, other["id"]))
        return bad
