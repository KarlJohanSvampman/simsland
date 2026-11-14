"""
core/world_view.py -- the WorldView façade (docs/distributed_architecture_plan.md, step 4).

Every one of the ~325 systems modules reads and writes the world as a plain dict: world["characters"][cid]["x"] = ...
The façade keeps exactly that, and learns which ENTITIES are touched: the resident world is a WorldDict, its entity
collections are EntityMap / EntityList -- dict / list subclasses, so isinstance(), json.dumps (which reads the storage
directly and bypasses these methods) and every existing caller keep working.

    touch(kind, id)          noted when an entity is reached through its collection (item access, get, values(),
                             items(), iteration of a list, setdefault, assignment, deletion) -- iterating over a dict's
                             KEYS does not touch; top-level keys of the world are noted as ("key", name)
    take_touched(sim_id)     what was touched since the last call: the entities a flush has to look at
                             (core/entity_store.py); None when the façade is not in place (compare everything)
    install(world)           make a plain world dict a WorldDict (once, at load -- before anyone holds a reference)
    access_hooks             callables hook(kind, id) run on every touch -- per-entity locks (core/entity_locks.py)
                             hang off this

What it cannot see: an entity reached WITHOUT going through the world (a reference kept from an earlier step, a cache
of prop objects) and changed later. Every FULL_EVERY-th flush therefore compares every entity anyway, and reports any
that changed without being touched (missed(): kind, id) -- the code path that did it is worth routing through the world.
"""

import threading

ENTITY_COLLECTIONS = {"characters", "households", "conversations", "conversation_archive",
                      "cpl_conversations", "cpl_requests"}
ENTITY_LISTS = {"props"}      # a list is compared whole at every flush (iterating it -- a lookup by id -- is too common
                              # to note one by one); its entities are still noted when assigned, appended or removed

# What was touched since the last take_touched(), one set per kind ("key" for the world's own top-level keys). The
# collections hold references to these very sets, so they are cleared in place. The hot path is one membership test.
_seen = {k: set() for k in ENTITY_COLLECTIONS | ENTITY_LISTS | {"key"}}
_seen_lock = threading.Lock()
_installed = {}                  # sim_id -> True once its resident world is a WorldDict
access_hooks = []                # hook(kind, id) on every access while _LOCKS (core/entity_locks.py)
_LOCKS = False                   # per-entity locks need every access (per unit of work), not the first per flush
_missed = {}                     # (kind, id) -> count: changed but not touched (seen by a full flush)
_local = threading.local()


class untracked:
    """with world_view.untracked(): a read-only observer walking the world (the replication publisher, the websocket
    delta builder) -- nothing it reaches counts as touched."""
    def __enter__(self):
        _local.off = getattr(_local, "off", 0) + 1

    def __exit__(self, *exc):
        _local.off -= 1


def _note(kind, seen, key):
    """The slow path of a touch: the first one for this entity since the last flush (or every one, with locks on)."""
    if getattr(_local, "off", 0):
        return
    if key not in seen:
        with _seen_lock:
            seen.add(key)
    for hook in access_hooks:
        hook(kind, key)


def touch(kind, key):
    _note(kind, _seen[kind], key)


def take_touched(sim_id):
    """{(kind, id)} touched since the last call -- None if the façade is not in place (then: compare everything). The
    entity lists are always included whole."""
    if not _installed.get(sim_id):
        return None
    out = set()
    with _seen_lock:
        for kind, keys in _seen.items():
            out.update((kind, str(k)) for k in keys)
            keys.clear()
    return out | {("*list", k) for k in ENTITY_LISTS}


def note_missed(keys):
    for k in keys:
        _missed[k] = _missed.get(k, 0) + 1
    if keys:
        print(f"[world_view] {len(keys)} entities changed without being touched through the world: {sorted(keys)[:8]}")


def missed():
    return dict(_missed)


class EntityMap(dict):
    """A dict of entities by id (characters, households, ...): reaching an entity notes it as touched."""
    __slots__ = ("_kind", "_seen")

    def __init__(self, kind, *a, **k):
        dict.__init__(self, *a, **k)
        self._kind = kind
        self._seen = _seen[kind]

    def __reduce_ex__(self, protocol):                   # copy / deepcopy / pickle: a plain dict copy
        return (dict, (dict(self),))

    def __getitem__(self, key):
        v = dict.__getitem__(self, key)
        if _LOCKS or key not in self._seen:
            _note(self._kind, self._seen, key)
        return v

    def get(self, key, default=None):
        if dict.__contains__(self, key):
            if _LOCKS or key not in self._seen:
                _note(self._kind, self._seen, key)
            return dict.__getitem__(self, key)
        return default

    def values(self):
        seen = self._seen
        for key in dict.keys(self):
            if _LOCKS or key not in seen:
                _note(self._kind, seen, key)
        return dict.values(self)

    def items(self):
        seen = self._seen
        for key in dict.keys(self):
            if _LOCKS or key not in seen:
                _note(self._kind, seen, key)
        return dict.items(self)

    def __setitem__(self, key, value):
        _note(self._kind, self._seen, key)
        dict.__setitem__(self, key, value)

    def setdefault(self, key, default=None):
        _note(self._kind, self._seen, key)
        return dict.setdefault(self, key, default)

    def pop(self, key, *default):
        _note(self._kind, self._seen, key)
        return dict.pop(self, key, *default)

    def __delitem__(self, key):
        _note(self._kind, self._seen, key)
        dict.__delitem__(self, key)

    def update(self, *a, **k):
        other = dict(*a, **k)
        for key in other:
            _note(self._kind, self._seen, key)
        dict.update(self, other)


def _list_key(item, i):
    return item.get("id") if isinstance(item, dict) and item.get("id") is not None else f"#{i}"


class EntityList(list):
    """A list of entities with ids (props). Compared whole at every flush; assignment, append and removal are noted
    (for per-entity locks), reading and iterating are not."""
    __slots__ = ("_kind", "_seen")

    def __init__(self, kind, *a):
        list.__init__(self, *a)
        self._kind = kind
        self._seen = _seen[kind]

    def __reduce_ex__(self, protocol):
        return (list, (list(self),))

    def _t(self, item, i):
        _note(self._kind, self._seen, _list_key(item, i))

    def append(self, item):
        self._t(item, len(self))
        list.append(self, item)

    def extend(self, items):
        items = list(items)
        for n, item in enumerate(items):
            self._t(item, len(self) + n)
        list.extend(self, items)

    def insert(self, i, item):
        self._t(item, i)
        list.insert(self, i, item)

    def remove(self, item):
        self._t(item, 0)
        list.remove(self, item)

    def pop(self, *i):
        item = list.pop(self, *i)
        self._t(item, 0)
        return item

    def __setitem__(self, i, value):
        if isinstance(i, slice):
            value = list(value)
            for n, item in enumerate(value):
                self._t(item, n)
        else:
            self._t(value, i)
        list.__setitem__(self, i, value)

    def __delitem__(self, i):
        for n, item in enumerate(list.__getitem__(self, i) if isinstance(i, slice) else [list.__getitem__(self, i)]):
            self._t(item, n)
        list.__delitem__(self, i)


def _wrap(key, value):
    if key in ENTITY_COLLECTIONS and isinstance(value, dict) and not isinstance(value, EntityMap):
        return EntityMap(key, value)
    if key in ENTITY_LISTS and isinstance(value, list) and not isinstance(value, EntityList):
        return EntityList(key, value)
    return value


_KEY_SEEN = _seen["key"]
_COLLECTION_KEYS = ENTITY_COLLECTIONS | ENTITY_LISTS


class WorldDict(dict):
    """The resident world: top-level keys reached are noted as ("key", name); entity collections stored in it are
    EntityMap / EntityList, whoever assigns them."""
    __slots__ = ()

    def __reduce_ex__(self, protocol):
        return (dict, (dict(self),))

    def __getitem__(self, key):
        v = dict.__getitem__(self, key)
        if (_LOCKS or key not in _KEY_SEEN) and key not in _COLLECTION_KEYS:
            _note("key", _KEY_SEEN, key)
        return v

    def get(self, key, default=None):
        if dict.__contains__(self, key):
            if (_LOCKS or key not in _KEY_SEEN) and key not in _COLLECTION_KEYS:
                _note("key", _KEY_SEEN, key)
            return dict.__getitem__(self, key)
        return default

    def values(self):
        for key in dict.keys(self):
            if key not in _COLLECTION_KEYS:
                _note("key", _KEY_SEEN, key)
        return dict.values(self)

    def items(self):
        for key in dict.keys(self):
            if key not in _COLLECTION_KEYS:
                _note("key", _KEY_SEEN, key)
        return dict.items(self)

    def __setitem__(self, key, value):
        _note("key", _KEY_SEEN, key)
        dict.__setitem__(self, key, _wrap(key, value))

    def setdefault(self, key, default=None):
        _note("key", _KEY_SEEN, key)
        if not dict.__contains__(self, key):
            dict.__setitem__(self, key, _wrap(key, default))
        return dict.__getitem__(self, key)

    def pop(self, key, *default):
        _note("key", _KEY_SEEN, key)
        return dict.pop(self, key, *default)

    def __delitem__(self, key):
        _note("key", _KEY_SEEN, key)
        dict.__delitem__(self, key)

    def update(self, *a, **k):
        for key, value in dict(*a, **k).items():
            self[key] = value

    def clear(self):
        for key in dict.keys(self):
            _note("key", _KEY_SEEN, key)
        dict.clear(self)


def install(world, sim_id="default"):
    """A WorldDict holding the same contents as `world` (a plain dict) -- call it before anyone keeps a reference."""
    if isinstance(world, WorldDict):
        _installed[sim_id] = True
        return world
    wd = WorldDict()
    for key, value in world.items():
        dict.__setitem__(wd, key, _wrap(key, value))
    _installed[sim_id] = True
    with _seen_lock:
        for keys in _seen.values():
            keys.clear()
    return wd


def where(collection, pred):
    """The entities of a collection for which pred(entity) is true, in order -- pred sees each entity WITHOUT it being
    reached (it should only read), and only the matches are reached (touched, locked). For "every child", "everyone
    with X" loops that would otherwise reach every entity to filter it."""
    if not isinstance(collection, dict):
        return [e for e in collection if pred(e)]
    return [collection[k] for k, e in dict.items(collection) if pred(e)]
