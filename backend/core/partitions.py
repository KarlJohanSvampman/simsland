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


class MemoryTransport:
    """Messages between partitions in one process (tests, the in-process cluster)."""

    def __init__(self, n):
        self.n = n
        self.queues = {p: [] for p in range(n)}

    def send(self, to, msg):
        self.queues[to].append(copy.deepcopy(msg))

    def broadcast(self, frm, msg):
        for p in range(self.n):
            if p != frm:
                self.send(p, msg)

    def receive(self, p):
        out, self.queues[p] = self.queues[p], []
        return out


class Node:
    """One partition: its world copy, what it last published / received of each entity, and the step around a tick.

        tick(tick_fn)   receive (patches for what it owns, frames for the rest), take in its inbox, run the tick for
                        what it owns, then send: patches to the owners of what it changed but doesn't own (its copy
                        goes back to the published one), a frame to everyone with what it owns and changed
        settle()        receive and publish, no tick (to let the copies catch up, e.g. before comparing them)
    """

    def __init__(self, world, p, transport, sim_id="part", exact=True):
        from core import world_view
        self.id, self.transport, self.exact = p, transport, exact
        self.sim_id = f"{sim_id}{p}"
        self.world = world_view.install(world, self.sim_id)
        self._keep_own_timers()
        self.published = {k: _dumps(_get(self.world, k)) for k in _keys(self.world)}
        self.changed = set()
        self.stats = {"ticks": 0, "patches_in": 0, "patches_out": 0, "ops_landed": 0, "frames_in": 0,
                      "frames_out": 0, "entities_out": 0, "creates": 0, "deletes": 0}

    def _keep_own_timers(self):
        global CURRENT
        prev, CURRENT = CURRENT, self.id
        try:
            w = self.world
            dict.__setitem__(w, "timers", [t for t in (dict.get(w, "timers") or [])
                                           if route(w, t["owner"]) == self.id and (t.get("key") != "recurring"
                                                                                   or runs_recurring(t["owner"]))])
        finally:
            CURRENT = prev

    # -- receiving ------------------------------------------------------------------------------------------------
    def receive(self):
        w = self.world
        for m in self.transport.receive(self.id):
            if m["t"] == "frame":
                self.stats["frames_in"] += 1
                for kind, eid, text in m["entities"]:
                    key = (kind, eid)
                    if _owner(w, key) == self.id:
                        continue                         # ours now (moved here since): our copy stands
                    _put(w, key, None if text is None else json.loads(text))
                    if text is None:
                        self.published.pop(key, None)
                    else:
                        self.published[key] = text
                    if kind == "characters":
                        from brain import agent_wake
                        agent_wake.reindex(w, eid)
                continue
            key = tuple(m["key"])
            owner = _owner(w, key)
            if owner != self.id:
                self.transport.send(owner, m)            # moved on: pass it to the owner now
                continue
            self.stats["patches_in"] += 1
            if m["what"] == "patch":
                ent = _get(w, key)
                if ent is None:
                    continue
                self.stats["ops_landed"] += entity_patch.apply(ent, m["body"])
            elif m["what"] == "create":
                if _get(w, key) is None:
                    _put(w, key, m["body"])
                    self.stats["creates"] += 1
                else:
                    self.stats["ops_landed"] += entity_patch.apply(_get(w, key), entity_patch.diff(_get(w, key),
                                                                                                    m["body"]))
            else:
                _put(w, key, None)
                self.stats["deletes"] += 1
            self.changed.add(key)
            if key[0] == "characters":
                from brain import agent_wake
                agent_wake.reindex(w, key[1])

    def _drain_inbox(self):
        w, p = self.world, self.id
        box = dict.get(w, f"_inbox_{p}") or []
        if not box:
            return
        dict.__setitem__(w, f"_inbox_{p}", [])
        self.changed.add(("key", f"_inbox_{p}"))
        from core import scheduler, flow
        for m in box:
            if m["t"] == "timer":
                scheduler.schedule_at(w, m["owner"], m["key"], m["ts"], m.get("payload"), m.get("every"), m.get("spec"))
            elif m["t"] == "duty":
                flow.wake_duty(w, m["name"])

    # -- a step ---------------------------------------------------------------------------------------------------
    def tick(self, tick_fn):
        global CURRENT
        from core import world_view
        CURRENT = self.id
        try:
            world_view.take_touched(self.sim_id)
            self.receive()
            self._drain_inbox()
            tick_fn(self.world)
        finally:
            CURRENT = None
        self.stats["ticks"] += 1
        self._send_changes(world_view.take_touched(self.sim_id) or set())

    def settle(self):
        self.receive()
        self._send_changes(set())

    def _send_changes(self, touched):
        w, p = self.world, self.id
        cands = {k for k in touched if k[0] != "*list"} | self.changed
        if self.exact:
            # every entity, not only those the façade saw reached: in ONE process the partitions share module state
            # (the event queue above all -- a decision can be applied during another partition's turn), so a change
            # can land outside the partition's own window; compared whole, it is found wherever it is
            cands |= set(_keys(w)) | set(self.published)
        cands |= {("props", str(x.get("id"))) for x in list.__iter__(dict.get(w, "props") or [])
                  if isinstance(x, dict) and x.get("id")}
        cands |= {k for k in self.published if k[0] == "props"}
        cands |= {("key", k) for k in dict.keys(w) if k.startswith("_inbox_")}
        frame = []
        for key in sorted(cands):
            if key[0] == "key" and (key[1] in LOCAL_KEYS or key[1] in _static()):
                continue
            now, before = _get(w, key), self.published.get(key)
            text = None if now is None else _dumps(now)
            owner = _owner(w, key)
            if owner == p:
                if text != before or key in self.changed:
                    frame.append([key[0], key[1], text])
                    if text is None:
                        self.published.pop(key, None)
                    else:
                        self.published[key] = text
                continue
            if text == before:
                continue
            if before is None:
                msg = {"t": "patch", "key": list(key), "what": "create", "body": copy.deepcopy(now), "from": p}
            elif now is None:
                msg = {"t": "patch", "key": list(key), "what": "delete", "body": None, "from": p}
            else:
                ops = entity_patch.diff(json.loads(before), json.loads(text))
                if not ops:
                    continue
                msg = {"t": "patch", "key": list(key), "what": "patch", "body": ops, "from": p}
            self.transport.send(owner, msg)
            self.stats["patches_out"] += 1
            _put(w, key, None if before is None else json.loads(before))      # back to the published copy
        self.changed = set()
        if frame:
            self.transport.broadcast(p, {"t": "frame", "from": p, "entities": frame})
            self.stats["frames_out"] += 1
            self.stats["entities_out"] += len(frame)


class Cluster:
    """N partitions in one process, stepped in turn over a MemoryTransport (tests/test_partitions.py)."""

    def __init__(self, world, n, sim_id="part", exact=True):
        ownership.assign(world, n)
        self.n = n
        self.transport = MemoryTransport(n)
        self.nodes = [Node(copy.deepcopy(dict(world)) if p else world, p, self.transport, sim_id, exact)
                      for p in range(n)]

    @property
    def parts(self):
        return [{"id": nd.id, "world": nd.world} for nd in self.nodes]

    @property
    def stats(self):
        out = {}
        for nd in self.nodes:
            for k, v in nd.stats.items():
                out[k] = out.get(k, 0) + v
        return out

    def world(self, p=0):
        return self.nodes[p].world

    def step(self, tick_fn):
        for nd in self.nodes:
            nd.tick(tick_fn)

    def settle(self, rounds=3):
        for _ in range(rounds):
            for nd in self.nodes:
                nd.settle()

    def divergence(self):
        """Entities whose copies differ between partitions (none once settled)."""
        bad = []
        base = self.nodes[0].world
        keys = set(_keys(base))
        for other in self.nodes[1:]:
            keys |= set(_keys(other.world))
        for key in sorted(keys):
            t = _dumps(_get(base, key))
            for other in self.nodes[1:]:
                if _dumps(_get(other.world, key)) != t:
                    bad.append((key, other.id))
        return bad
