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

# The server (main.py): SIM_PARTITIONS > 1 runs the simulation as that many partition processes, this one being
# SIM_PARTITION (0 = the core: commands, the replica for API gateways, world services, the backup blob).
import os as _os
SERVER_N = int(_os.getenv("SIM_PARTITIONS", "1"))
SERVER_P = int(_os.getenv("SIM_PARTITION", "0"))
_server_node = None


def server_node(world, sim_id):
    """This process's partition (created on first use, from the world as loaded): the owner map is made the same way in
    every partition (households in id order), so they agree without asking each other."""
    global _server_node
    if _server_node is None or _server_node.world is not world:
        if (world.get("_owners") or {}).get("n") != SERVER_N:
            ownership.assign(world, SERVER_N)
        _server_node = Node(world, SERVER_P, RedisTransport(SERVER_N, sim_id), sim_id=f"{sim_id}_p", exact=True,
                            lockstep=False)
    return _server_node


def is_core():
    return SERVER_N <= 1 or SERVER_P == 0


def persists(world, key):
    """Which partition writes an entity to the store: its owner (the manifest and the blob: partition 0)."""
    if SERVER_N <= 1:
        return True
    kind, eid = key
    if kind == "meta":
        return SERVER_P == 0
    if kind == "key" and str(eid) in LOCAL_KEYS:
        return SERVER_P == 0
    if kind == "char_cold":                       # a character's cold row (core/entity_store.py): its character's owner
        key = ("characters", str(eid).split("/", 1)[0])
    return _owner(world, key) == SERVER_P

LOCAL_KEYS = {"timers", "_timer_seq", "_sched_sig", "_dirty", "_perchar_members", "_active_loops", "_bg_work",
              "tick", "sim_time", "calendar", "_clock", "_owners_local", "cpl_dedupe", "_defaults_tick",
              "_known_char_ids", "_conv_tag_queue"}
_CHARACTER_LOOPS = {"movement", "nudity"}
_COLLECTIONS = ("characters", "households", "conversations", "conversation_archive", "cpl_requests")
_WORLD_TIMER_PREFIXES = ("cpl", "duty", "convidle", "flow")


_HANDING = {}                  # partition -> {(kind, id)} it is handing over (owns, but no longer runs)


def here(world, kind, eid):
    if CURRENT is None:
        return True
    if (kind, eid) in _HANDING.get(CURRENT, ()):
        return False
    return ownership.owner_of(world, kind, eid) == CURRENT


def conv_owner(world, cid, kind="conversations"):
    """A conversation belongs to the partition of its first participant (who started it): talk within a household
    stays in its partition. Read from the record itself, so every partition works it out the same way."""
    rec = dict.get(dict.get(world, kind) or {}, cid) if isinstance(dict.get(world, kind), dict) else None
    parts = (rec or {}).get("participants") or []
    if isinstance(parts, dict):
        parts = list(parts)
    return ownership.owner_of(world, "characters", parts[0]) if parts else 0


def loop_ids(world, name, ids):
    if CURRENT is None:
        return ids
    if name in _CHARACTER_LOOPS:
        return [i for i in ids if here(world, "characters", i)]
    if name == "floor":                                  # its members are conversations: their owner runs them
        return [i for i in ids if conv_owner(world, i) == CURRENT]
    return ids if CURRENT == 0 else []


def _perchar_names():
    from core import flow
    return set(flow._perchar_fns)


def runs_recurring(owner):
    """Recurring jobs: per-character ones (PERCHAR) everywhere, over their own members; the rest in partition 0."""
    return CURRENT is None or CURRENT == 0 or owner in _perchar_names()


def route(world, owner, key=None):
    """Which partition a timer belongs to: a character's (its id in the owner string) -> that character's owner; a
    conversation's (cpl:<id>, the idle timer) -> the conversation's owner; anything else -> partition 0.
    Per-character jobs' recurring timers stay where they are set."""
    if owner in _perchar_names():
        return CURRENT if CURRENT is not None else 0
    if str(owner).startswith("cpl:"):
        return conv_owner(world, str(owner)[4:])
    if owner == "convidle" and key:
        return conv_owner(world, key)
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
    p = route(world, owner, key)
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
        if k in _COLLECTIONS:
            if isinstance(v, dict):                      # an entity collection: its entities, never the whole of it
                out += [(k, str(i)) for i in dict.keys(v)]
            continue                                     # (not there yet, or None: nothing to share)
        elif k == "props":
            if not isinstance(v, list):
                continue
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


def _owner(world, key, incoming=None):
    """Who owns an entity. For the kinds whose owner is read off the record (a conversation: its first participant)
    and a record this world doesn't have yet, `incoming` (the copy that just arrived, as JSON) is read instead."""
    kind, eid = key
    if kind in ownership.KINDS:
        return ownership.owner_of(world, kind, eid)
    if kind in ("conversations", "conversation_archive", "cpl_requests"):
        rec = dict.get(dict.get(world, kind) or {}, eid) if isinstance(dict.get(world, kind), dict) else None
        if rec is None and incoming not in (None, "null"):
            rec = json.loads(incoming) if isinstance(incoming, str) else incoming
        if kind == "cpl_requests":
            return conv_owner(world, (rec or {}).get("conversation_id"))
        parts = (rec or {}).get("participants") or []
        return ownership.owner_of(world, "characters", list(parts)[0]) if parts else 0
    return owner_of_key(kind, eid)


def _dumps(v):
    return json.dumps(v, default=str)


class RedisTransport:
    """Messages between partition processes: one Redis stream per partition (part:<sim>:<p>), read in order from where
    this process last read. A message is a JSON blob in the field "m"."""

    def __init__(self, n, sim="default", client=None):
        from core.cache import r
        self.n, self.sim = n, sim
        self.r = client or r
        self.last = {}

    def _stream(self, p):
        return f"part:{self.sim}:{p}"

    def send(self, to, msg):
        self.r.xadd(self._stream(to), {"m": json.dumps(msg, default=str)}, maxlen=100000, approximate=True)

    def broadcast(self, frm, msg):
        for p in range(self.n):
            if p != frm:
                self.send(p, msg)

    def receive(self, p):
        out = []
        while True:
            got = self.r.xread({self._stream(p): self.last.get(p, "0")}, count=1000)
            if not got:
                return out
            for _stream, entries in got:
                for mid, fields in entries:
                    self.last[p] = mid
                    raw = fields.get(b"m") if b"m" in fields else fields.get("m")
                    out.append(json.loads(raw))

    def clear(self):
        for p in range(self.n):
            self.r.delete(self._stream(p))


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

    def __init__(self, world, p, transport, sim_id="part", exact=True, lockstep=True):
        from core import world_view
        self.id, self.transport, self.exact, self.lockstep = p, transport, exact, lockstep
        self.sim_id = f"{sim_id}{p}"
        self.world = world_view.install(world, self.sim_id)
        self._keep_own_timers()
        self.published = {k: _dumps(_get(self.world, k)) for k in _keys(self.world)}
        self.changed = set()
        self.pending = []                                # messages from a step not yet over (lockstep, see receive)
        self.seq = 0                                     # this partition's message counter (orders what it sent)
        self.handing = {}                                # (kind, id) -> partition it is going to (slice 4: moves)
        self.incoming = set()                            # (kind, id) coming here: patches for them wait in buffer
        self.forced = set()                              # handed-over state partition 0 publishes as is, once
        self.buffer = []
        _HANDING[p] = self.handing
        self.stats = {"ticks": 0, "patches_in": 0, "patches_out": 0, "ops_landed": 0, "frames_in": 0,
                      "frames_out": 0, "entities_out": 0, "creates": 0, "deletes": 0}

    def _keep_own_timers(self):
        global CURRENT
        prev, CURRENT = CURRENT, self.id
        try:
            w = self.world
            dict.__setitem__(w, "timers", [t for t in (dict.get(w, "timers") or [])
                                           if route(w, t["owner"], t.get("key")) == self.id and (t.get("key") != "recurring"
                                                                                   or runs_recurring(t["owner"]))])
        finally:
            CURRENT = prev

    # -- receiving ------------------------------------------------------------------------------------------------
    def receive(self, everything=False):
        """Take in messages. Only those from steps already over (step < this partition's own) unless `everything`:
        a faster partition's messages from the step now running wait, so a lockstep run is the same every time."""
        w = self.world
        msgs = self.pending + self.transport.receive(self.id)
        self.pending = [] if everything else [m for m in msgs if m.get("step", -1) >= self.stats["ticks"]]
        msgs = msgs if everything else [m for m in msgs if m.get("step", -1) < self.stats["ticks"]]
        msgs.sort(key=lambda m: (m.get("step", -1), m.get("from", 0), m.get("seq", 0)))   # not arrival order
        for m in msgs:
            if m["t"] in ("incoming", "handover", "handed", "adopt_timers"):
                self._move_message(m)
                continue
            if m["t"] == "frame":
                self.stats["frames_in"] += 1
                ents = sorted(m["entities"], key=lambda e: (e[0], e[1]) == ("key", "_owners"))   # the map last
                for kind, eid, text in ents:
                    key = (kind, eid)
                    if _owner(w, key, text) == self.id:
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
            if key in self.incoming and owner != self.id:
                self.buffer.append(m)                    # on its way here: wait for the owner map to say so
                continue
            if key in self.handing:
                self.transport.send(self.handing[key], m)    # handed over: to its new owner
                continue
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
        self._after_receive()

    def _after_receive(self):
        """A move completed (the owner map now says these are ours, or no longer ours): settle its loose ends."""
        w = self.world
        arrived = {k for k in self.incoming if _owner(w, k) == self.id}
        if arrived:
            self.incoming -= arrived
            held, self.buffer = [m for m in self.buffer if tuple(m.get("key", ())) in arrived], \
                [m for m in self.buffer if tuple(m.get("key", ())) not in arrived]
            for m in held:                               # patches that waited: now ours to apply
                self._apply_patch(tuple(m["key"]), m)
        gone = [k for k in self.handing if _owner(w, k) != self.id]
        for k in gone:
            del self.handing[k]
        pend = [m for m in self.buffer if m.get("t") == "adopt_timers"
                and all(_owner(w, ("characters", c)) == self.id for c in m.get("chars", []))]
        for m in pend:
            self.buffer.remove(m)
            self._adopt(m)

    def _apply_patch(self, key, m):
        w = self.world
        self.stats["patches_in"] += 1
        if m["what"] == "patch":
            ent = _get(w, key)
            if ent is not None:
                self.stats["ops_landed"] += entity_patch.apply(ent, m["body"])
        elif m["what"] == "create" and _get(w, key) is None:
            _put(w, key, m["body"])
        elif m["what"] == "delete":
            _put(w, key, None)
        self.changed.add(key)

    def _adopt(self, m):
        global CURRENT
        from core import scheduler
        prev, CURRENT = CURRENT, self.id
        try:
            for t in m.get("timers", []):
                scheduler.schedule_at(self.world, t["owner"], t["key"], t["due"], t.get("payload"), t.get("every"),
                                      t.get("spec"))
        finally:
            CURRENT = prev
        from brain import agent_wake
        for cid in m.get("chars", []):
            agent_wake.reindex(self.world, cid)
            agent_wake.wake_now((self.world.get("characters") or {}).get(cid), "moved_here")
        self.stats["moves_in"] = self.stats.get("moves_in", 0) + 1

    # -- moving a household (slice 4) ------------------------------------------------------------------------------
    def request_move(self, hid, to):
        """Partition 0: move household `hid` (members, props) to partition `to`. Four messages (docs/step5b_plan.md)."""
        if self.id != 0:
            raise RuntimeError("moves are made by partition 0")
        w = self.world
        frm = ownership.owner_of(w, "households", hid)
        if frm == to:
            return False
        keys = [("households", hid)] + [("characters", c) for c in ownership._members(w, hid)
                                         if ownership.owner_of(w, "characters", c) == frm] + \
               [("props", pid) for pid in ownership._props_of(w, hid)]
        msg = {"hid": hid, "to": to, "from": frm, "keys": [list(k) for k in keys], "step": -1}
        if to == 0:
            self.incoming |= set(keys)
        else:
            self.transport.send(to, dict(msg, t="incoming"))
        if frm == 0:
            self._move_message(dict(msg, t="handover"))
        else:
            self.transport.send(frm, dict(msg, t="handover"))
        return True

    def _move_message(self, m):
        global CURRENT
        w = self.world
        keys = [tuple(k) for k in m.get("keys", [])]
        if m["t"] == "incoming":
            self.incoming |= set(keys)
        elif m["t"] == "handover":                       # we own them: stop running them, hand over the final state
            for k in keys:
                self.handing[k] = m["to"]
            chars = [k[1] for k in keys if k[0] == "characters"]
            timers, keep = [], []
            prev, CURRENT = CURRENT, self.id
            try:
                for t in dict.get(w, "timers") or []:
                    (timers if route(w, t["owner"]) == self.id and any(
                        c in str(t["owner"]).split(":")[1:] for c in chars) else keep).append(t)
            finally:
                CURRENT = prev
            dict.__setitem__(w, "timers", keep)
            handed = dict(m, t="handed", entities=[[k[0], k[1], _dumps(_get(w, k))] for k in keys],
                          timers=timers, chars=chars)
            if self.id == 0:
                self._move_message(handed)
            else:
                self.transport.send(0, handed)
        elif m["t"] == "handed":                         # partition 0: the final state in, the owner map flipped
            for kind, eid, text in m["entities"]:
                _put(w, (kind, eid), None if text in (None, "null") else json.loads(text))
                self.forced.add((kind, eid))
            ownership.move_household(w, m["hid"], m["to"])
            self.changed.add(("key", "_owners"))
            adopt = {"t": "adopt_timers", "timers": m.get("timers", []), "chars": m.get("chars", []), "step": -1}
            if m["to"] == 0:
                self.buffer.append(adopt)
            else:
                self.transport.send(m["to"], adopt)
            self.stats["moves"] = self.stats.get("moves", 0) + 1
        elif m["t"] == "adopt_timers":
            self.buffer.append(m)                        # once the owner map says they are ours (_after_receive)

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
            self.receive(everything=not self.lockstep)   # free-running processes take what has arrived
            self._drain_inbox()
            tick_fn(self.world)
            if self.transport.n > 1:
                from core import event_bus
                event_bus.flush(self.world)              # what this tick set off is handled here, by its owner
        finally:
            CURRENT = None
        self.stats["ticks"] += 1
        self._send_changes(world_view.take_touched(self.sim_id) or set())

    def settle(self):
        self.receive(everything=True)
        self._send_changes(set())

    def _send_changes(self, touched):
        w, p = self.world, self.id
        cands = {k for k in touched if k[0] != "*list"} | self.changed | self.forced
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
            if key[0] == "key" and (key[1] in LOCAL_KEYS or key[1] in _static() or key[1] in _COLLECTIONS
                                    or key[1] == "props"):
                continue                                 # a collection is shared entity by entity, never whole
            now, before = _get(w, key), self.published.get(key)
            text = None if now is None else _dumps(now)
            owner = _owner(w, key)
            if key in self.forced:                       # a moved household's final state: everyone takes it as is
                frame.append([key[0], key[1], text])
                self.published[key] = text
                continue
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
                msg = {"t": "patch", "key": list(key), "what": "create", "body": copy.deepcopy(now), "from": p,
                       "step": self.stats["ticks"]}
            elif now is None:
                msg = {"t": "patch", "key": list(key), "what": "delete", "body": None, "from": p,
                       "step": self.stats["ticks"]}
            else:
                ops = entity_patch.diff(json.loads(before), json.loads(text))
                if not ops:
                    continue
                msg = {"t": "patch", "key": list(key), "what": "patch", "body": ops, "from": p,
                       "step": self.stats["ticks"]}
            self.seq += 1
            msg["seq"] = self.seq
            self.transport.send(owner, msg)
            self.stats["patches_out"] += 1
            _put(w, key, None if before is None else json.loads(before))      # back to the published copy
        self.changed = set()
        self.forced = set()
        if frame:
            self.seq += 1
            self.transport.broadcast(p, {"t": "frame", "from": p, "entities": frame, "step": self.stats["ticks"],
                                         "seq": self.seq})
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

    def move_household(self, hid, to):
        return self.nodes[0].request_move(hid, to)

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
