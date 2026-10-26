"""
core/entity_versions.py

What changed, per entity -- without proxies or hooks on the thousands of places that write to
the world (docs/distributed_architecture_plan.md, the state store).

Every character is described by its top-level keys. For a character that is looked at, the
JSON of each key is hashed; the hash differs from last time exactly when that key's value
changed. That gives:

  char_digests(c, tick)   {key: digest}, memoised per tick; refreshes the entity's version and
                          the set of keys that changed (also memoised, so many clients share it)
  version(kind, id)       increments each time anything in the entity changed
  last_changed(kind, id)  which keys changed in the latest step

Cost control: most of a character's weight is a few big blobs that change rarely and nobody
animates (LLM sessions, grievances, memories, ...). Those "cold" keys are re-hashed only every
COLD_EVERY ticks (staggered per character), so a change in one of them shows up within
COLD_EVERY ticks; everything else ("hot": position, activity, needs, speech, worn, inventory,
...) is hashed every tick. The selected character is always sent whole anyway.

The websocket uses it to send each client PATCHES (changed keys only) instead of the whole
character (~90 KB) every tick -- see main.py::_build_delta.
"""

import json
import zlib

COLD_EVERY = 15
COLD_KEYS = frozenset({
    "choice_llm_sessions", "grievances", "_llm_session", "_mentality_llm_session",
    "_situation_history", "memories", "long_term_memory", "conversation_log", "speech_log",
    "opinions", "relationships", "schedule", "expectations", "social_model", "beliefs",
    "behavior_patterns", "worries", "_daily_observations", "story_arc", "off_grid_story_arc",
    "life_narrative", "relationship_narratives", "identity", "contacts", "offgrid_summaries",
})

_memo = {}          # (kind, id) -> (tick, digests)
_versions = {}      # (kind, id) -> int
_changed = {}       # (kind, id) -> set of keys that changed at the last refresh
_cold_cache = {}    # (kind, id) -> {key: digest} -- last computed cold digests
_memo_cold_fresh = {}   # (kind, id) -> tick at which the cold keys were last re-hashed


_encode = json.JSONEncoder(separators=(",", ":"), default=str).encode     # one encoder, not one per call
_SCALARS = (bool, int, float, str, type(None))
_CONTAINERS = (list, dict)


def _digest(value):
    """Something that is equal across calls exactly when the value's JSON is. A scalar is its own
    digest (tagged with its type, so 1 and True differ): no serialising, which is most of a
    character's keys. Anything else is the CRC of its JSON."""
    cls = value.__class__
    if cls in _SCALARS:
        if cls is float and value != value:
            return "nan"                                 # NaN is never equal to itself
        return (cls, value)
    if cls in _CONTAINERS and not value:
        return (cls, 0)                                  # an empty list/dict: a lot of a character's keys
    try:
        text = _encode(value)
    except Exception:
        text = repr(value)
    return zlib.crc32(text.encode("utf-8", "replace"))


def _is_cold_tick(entity_id, tick):
    return (tick + zlib.crc32(entity_id.encode())) % COLD_EVERY == 0


def char_digests(c, tick, fresh_cold=False):
    """{key: digest} for this character as of `tick`. fresh_cold=True re-hashes the cold keys
    too (used for the character a client has selected: the Inspector shows those)."""
    key = ("char", c["id"])
    memo = _memo.get(key)
    if memo and memo[0] == tick and not (fresh_cold and not _memo_cold_fresh.get(key) == tick):
        return memo[1]
    prev = memo[1] if memo else None
    cold_cache = _cold_cache.setdefault(key, {})
    refresh_cold = fresh_cold or prev is None or _is_cold_tick(c["id"], tick)
    if refresh_cold:
        _memo_cold_fresh[key] = tick
    digests = {}
    for k, v in c.items():
        if k in COLD_KEYS:
            if refresh_cold or k not in cold_cache:
                cold_cache[k] = _digest(v)
            digests[k] = cold_cache[k]
        else:
            digests[k] = _digest(v)
    changed = set(digests) ^ set(prev) if prev is not None else set(digests)
    if prev is not None:
        changed |= {k for k in digests if k in prev and prev[k] != digests[k]}
    if changed:
        _versions[key] = _versions.get(key, 0) + 1
        _changed[key] = changed
    elif key not in _versions:
        _versions[key] = 0
    _memo[key] = (tick, digests)
    return digests


def version(kind, entity_id):
    return _versions.get((kind, entity_id), 0)


def last_changed(kind, entity_id):
    return set(_changed.get((kind, entity_id), ()))


def forget(kind, entity_id):
    for d in (_memo, _versions, _changed, _cold_cache, _memo_cold_fresh):
        d.pop((kind, entity_id), None)


def stats():
    return {"tracked": len(_memo), "versions": {f"{k[0]}:{k[1]}": v for k, v in _versions.items()}}
