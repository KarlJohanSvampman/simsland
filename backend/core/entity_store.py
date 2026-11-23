"""
core/entity_store.py -- the world persisted as per-entity records (docs/distributed_architecture_plan.md, step 4).

The live world is still the resident dict in the simulation core (core/world_state.py). What changes is how it is made
durable: instead of one JSON blob of the whole world, every entity is its own row --

    entities(sim_id, kind, id, data, commit_seq)
        kind = a collection ("characters", "households", "conversations", "conversation_archive", "props"): one row
               per entity in it, id = the entity's id;
        kind = "key": every other top-level key of the world, id = the key;
        kind = "meta", id = "manifest": the order of the top-level keys and of each collection's ids, so the world
               comes back iterating in the same order (the simulation's determinism depends on it).
    `data` is JSON, not JSONB: JSONB re-orders the keys of every object, and the order of keys inside an entity
    (relationships, needs, ...) is iteration order the simulation depends on too.
    entity_commits(sim_id, seq, tick, at, written, deleted)   one row per flush

A flush writes only the entities whose JSON differs from what was last written, deletes the ones that are gone, and
writes the manifest and a commit row -- all in ONE transaction, so whatever is read back is the world as of one flush
(never half of one). Which entities to look at: every entity (the default -- a full comparison, the cost of the old
blob render), or just the ones a unit of work touched when the WorldView façade (core/world_view.py) reports them.

    split(world)                      {(kind, id): entity} + manifest
    diff(sim_id, world, only=None)    (upserts {(kind, id): json}, deletes [(kind, id)], manifest json) -- against
                                      what was last written (process memory); `only` limits it to those entities
    write(sim_id, upserts, deletes, manifest, tick)   the transaction
    load(sim_id)                      the persisted world (no static map data), or None if this sim has no rows yet
    forget(sim_id)                    drop the in-memory "last written" (a reload, a test)

A world saved before this (only the blob in `world`) loads from the blob; its first flush writes every entity.

Characters are split hot/cold (2026-11-23). A character was one row, and any touch (a step, a need, one thought)
re-rendered and compared all of it -- ~1 MB with memories, logs and LLM sessions -- every flush (every 2 ticks), under
the world lock: 5 MB and 342 ms a flush, measured live. Now the big slow-changing keys (core/entity_versions.py's
COLD_KEYS, the same split the gateway replication uses) are rows of their own:
    kind = "characters", id = the character id     everything else, with {"$cold": 1} standing in for each cold key
                                                   (so the key order inside the character comes back the same)
    kind = "char_cold",  id = "<character id>/<key>"   that key's value
A cold row is only rendered when its key looks changed (length or end items) or its turn comes round
(COLD_RECHECK_FLUSHES); an old one-row character still loads, and its first flush writes it split.
"""

import json
import os
import time
import zlib

COLLECTIONS = {
    "characters": "dict",
    "households": "dict",
    "conversations": "dict",
    "conversation_archive": "dict",
    "cpl_requests": "dict",                # the conversation protocol layer (cpl/store.py)
    "props": "list",
}

COLD_KIND = "char_cold"
_COLD_MARK = {"$cold": 1}
# A cold value can change in place without its length changing (a memory's importance, the last line of a conversation
# in progress): every cold row is rendered and compared at least this often (flushes), staggered, as a backstop.
COLD_RECHECK_FLUSHES = int(os.getenv("WORLD_COLD_RECHECK_FLUSHES", "60"))   # ~2 minutes at a flush every 2 ticks

_written = {}            # sim_id -> {(kind, id): json text} as last written
_cold_sig = {}           # sim_id -> {(COLD_KIND, id): cheap signature when last rendered}
_flushes = {}            # sim_id -> diff count (the recheck rotation)
_stats = {"flushes": 0, "rows_written": 0, "rows_deleted": 0, "diff_ms": 0.0, "write_ms": 0.0, "last_tick": None}


def _dumps(obj):
    try:
        return json.dumps(obj)
    except TypeError:
        _stats["dumps_fallbacks"] = _stats.get("dumps_fallbacks", 0) + 1
        from core.cache import safe_json_dumps
        return safe_json_dumps(obj)


def _static_keys():
    from db import _STATIC_WORLD_KEYS
    return set(_STATIC_WORLD_KEYS)


def _list_id(item, i):
    return str(item.get("id")) if isinstance(item, dict) and item.get("id") is not None else f"#{i}"


# Persisted cold on top of the replication's COLD_KEYS: big logs and LLM sessions that grow by appending (measured live,
# 2026-11-23: with only COLD_KEYS the hot row was still 200-320 KB, mostly these). Not added to COLD_KEYS itself, which
# also decides how often the gateway re-hashes them for the page.
PERSIST_COLD_EXTRA = frozenset({
    "issue_log", "confrontation_log", "examine_llm_sessions", "worry_cases", "spotted", "move_log", "path_plans",
    "social_models", "influence_profile", "notable_stories", "llm_session", "offgrid_llm_sessions", "failed_intentions",
    "habits", "private_off_grid_history", "post_engagement_sessions", "offgrid_category_memory", "offgrid_summaries",
    "_activity_starts", "trait_log",
    # mid-sized and slow to change (measured live after the first split: the hot row was still ~42 KB, spread over these)
    "selected_situation", "_debug_event_last", "inventory", "grudges", "absorbed_traits", "health_state", "principles",
    "values", "belief_influence_profile", "attraction_profile", "food_taste", "child_cognition", "mentality",
    "_last_sighting_recall",
})

# World-level keys that change every tick but don't matter to the minute: written at most every this many flushes
# (~60 ticks at a flush every 2). Live 2026-11-23: the stock market (stocks 412 KB, market 134 KB) was rewritten every
# flush. A crash loses at most that long of price movement.
THROTTLED_KEYS = {"stocks": 30, "market": 30, "stock_sector_trends": 30}
_COLD = None


def _cold_keys():
    global _COLD
    if _COLD is None:
        from core.entity_versions import COLD_KEYS
        _COLD = frozenset(COLD_KEYS) | PERSIST_COLD_EXTRA
    return _COLD


def _hot(c, cold):
    """The character with a marker in place of each cold key (same key order)."""
    return {k: (_COLD_MARK if k in cold else v) for k, v in dict.items(c)}


def _cold_ids(cid, c, cold):
    return [f"{cid}/{k}" for k in dict.keys(c) if k in cold]


def _sig(v):
    """Cheap: does this cold value look changed? Length and which objects sit at its ends (appending to a capped list
    swaps both). In-place edits that keep these are caught by the COLD_RECHECK_FLUSHES rotation."""
    if isinstance(v, list):
        return ("l", len(v), id(v[0]) if v else 0, id(v[-1]) if v else 0)
    if isinstance(v, dict):
        if not v:
            return ("d", 0)
        last = next(reversed(dict.keys(v)))
        return ("d", len(v), last, id(dict.__getitem__(v, last)))
    try:
        hash(v)
        return ("v", v)
    except TypeError:
        return ("o", id(v))


def split(world):
    """{(kind, id): entity} for everything persisted, and the manifest that puts it back together."""
    static = _static_keys()
    out, keys, orders = {}, [], {}
    for k, v in dict.items(world):           # raw access: reading the world to persist it touches nothing
        # (core/world_view.py)
        if k in static:
            continue
        keys.append(k)
        shape = COLLECTIONS.get(k)
        if shape == "dict" and isinstance(v, dict):
            orders[k] = {"type": "dict", "order": [str(i) for i in dict.keys(v)]}
            cold = _cold_keys() if k == "characters" else None
            for i, e in dict.items(v):
                if cold is not None and isinstance(e, dict):
                    out[(k, str(i))] = _hot(e, cold)
                    for ck in dict.keys(e):
                        if ck in cold:
                            out[(COLD_KIND, f"{i}/{ck}")] = dict.__getitem__(e, ck)
                else:
                    out[(k, str(i))] = e
        elif shape == "list" and isinstance(v, list):
            items = list(list.__iter__(v))
            ids = [_list_id(e, n) for n, e in enumerate(items)]
            if len(set(ids)) == len(ids):
                orders[k] = {"type": "list", "order": ids}
                for i, e in zip(ids, items):
                    out[(k, i)] = e
            else:
                out[("key", k)] = v          # ids not unique: kept as one record
        else:
            out[("key", k)] = v
    return out, {"keys": keys, "collections": orders}


def _manifest_and_present(world):
    """The manifest, and the set of (kind, id) the world holds now -- without rendering any entity."""
    static = _static_keys()
    keys, orders, present = [], {}, set()
    for k, v in dict.items(world):
        if k in static:
            continue
        keys.append(k)
        shape = COLLECTIONS.get(k)
        if shape == "dict" and isinstance(v, dict):
            ids = [str(i) for i in dict.keys(v)]
            orders[k] = {"type": "dict", "order": ids}
            present.update((k, i) for i in ids)
            if k == "characters":
                cold = _cold_keys()
                for i, e in dict.items(v):
                    if isinstance(e, dict):
                        present.update((COLD_KIND, cid) for cid in _cold_ids(i, e, cold))
        elif shape == "list" and isinstance(v, list):
            ids = [_list_id(e, n) for n, e in enumerate(list.__iter__(v))]
            if len(set(ids)) == len(ids):
                orders[k] = {"type": "list", "order": ids}
                present.update((k, i) for i in ids)
            else:
                present.add(("key", k))
        else:
            present.add(("key", k))
    return {"keys": keys, "collections": orders}, present


def _entity(world, key):
    kind, i = key
    if kind == "key":
        return dict.__getitem__(world, i)
    if kind == COLD_KIND:
        cid, ck = i.split("/", 1)
        return dict.__getitem__(_raw_char(world, cid), ck)
    coll = dict.__getitem__(world, kind)
    if isinstance(coll, dict):
        e = dict.__getitem__(coll, i) if dict.__contains__(coll, i) else next(
            v for k, v in dict.items(coll) if str(k) == i)
        return _hot(e, _cold_keys()) if kind == "characters" and isinstance(e, dict) else e
    return next(e for n, e in enumerate(list.__iter__(coll)) if _list_id(e, n) == i)


def _list_index(world, kind):
    """{id: item} for a list collection -- built once per diff: finding each item by scanning the list from the start
    was quadratic (every prop is compared whenever one is touched)."""
    coll = dict.__getitem__(world, kind) if dict.__contains__(world, kind) else []
    return {_list_id(e, n): e for n, e in enumerate(list.__iter__(coll))} if isinstance(coll, list) else {}


def _raw_char(world, cid):
    coll = dict.__getitem__(world, "characters")
    return dict.__getitem__(coll, cid) if dict.__contains__(coll, cid) else next(
        v for k, v in dict.items(coll) if str(k) == cid)


def _cold_due(key, n):
    return (zlib.crc32(key[1].encode("utf-8", "replace")) + n) % max(1, COLD_RECHECK_FLUSHES) == 0


def diff(sim_id, world, only=None):
    """What to write so the store matches `world`. `only`: the (kind, id) touched since the last flush -- just those
    are rendered and compared (lists whole, plus the manifest); None compares everything."""
    t0 = time.perf_counter()
    last = _written.setdefault(sim_id, {})
    sigs = _cold_sig.setdefault(sim_id, {})
    n = _flushes[sim_id] = _flushes.get(sim_id, 0) + 1
    upserts, deletes = {}, []
    rendered, by_kind, list_idx = 0, {}, {}
    phase = {}
    _tp = time.perf_counter()
    manifest, present = _manifest_and_present(world)
    phase["manifest"] = (time.perf_counter() - _tp) * 1000
    if not last:
        want = present                                               # nothing written yet: everything, cold included
    elif only is None:
        want = present                                               # compare everything (cold rows: see below)
    else:
        whole = {k for kind, k in only if kind == "*list"}            # lists are compared whole (core/world_view.py)
        want = (set(only) & present) | {key for key in present if key[0] in whole}
        touched_chars = {i for kind, i in want if kind == "characters"}
        want |= {key for key in present if key[0] == COLD_KIND and key[1].split("/", 1)[0] in touched_chars}
    for key in want:
        _tk = time.perf_counter()
        _label = "cold" if key[0] == COLD_KIND else key[0]
        text = None
        if key[0] == COLD_KIND:
            value = _entity(world, key)
            sig = _sig(value)
            if not (last and key in last and sigs.get(key) == sig and not _cold_due(key, n)):
                sigs[key] = sig                                      # else: looks the same, not its turn -- skipped
                text = _dumps(value)
        else:
            every = THROTTLED_KEYS.get(key[1]) if key[0] == "key" else None
            if not (every and last and key in last and n % every):   # throttled (THROTTLED_KEYS): not its turn
                if COLLECTIONS.get(key[0]) == "list":
                    if key[0] not in list_idx:
                        list_idx[key[0]] = _list_index(world, key[0])
                    entity = list_idx[key[0]][key[1]]
                else:
                    entity = _entity(world, key)
                text = _dumps(entity)
        if text is not None:
            rendered += len(text)
            if last.get(key) != text:
                upserts[key] = text
                label = ("cold:" + key[1].split("/", 1)[1]) if key[0] == COLD_KIND else (
                    f"key:{key[1]}" if key[0] == "key" else key[0])
                by_kind[label] = by_kind.get(label, 0) + len(text)
        phase[_label] = phase.get(_label, 0.0) + (time.perf_counter() - _tk) * 1000
    _stats["last_diff_phase_ms"] = {k: round(v, 1) for k, v in sorted(phase.items(), key=lambda kv: -kv[1])[:10]}
    _stats["last_want"] = len(want)
    for key in list(last):
        if key not in present and key[0] != "meta":
            deletes.append(key)
            sigs.pop(key, None)
    mtext = _dumps(manifest)
    if last.get(("meta", "manifest")) != mtext:
        upserts[("meta", "manifest")] = mtext
    _stats["diff_ms"] += (time.perf_counter() - t0) * 1000
    _stats["last_rendered_bytes"] = rendered            # what was turned into JSON to compare
    _stats["last_written_by_kind"] = dict(sorted(by_kind.items(), key=lambda kv: -kv[1])[:15])
    return upserts, deletes, mtext


def note_written(sim_id, upserts, deletes):
    """The diff has been handed to the writer: it is what the store will hold."""
    last = _written.setdefault(sim_id, {})
    last.update(upserts)
    for key in deletes:
        last.pop(key, None)


def forget(sim_id):
    _written.pop(sim_id, None)
    _cold_sig.pop(sim_id, None)


def ensure_tables(cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS entities (
            sim_id TEXT NOT NULL, kind TEXT NOT NULL, id TEXT NOT NULL,
            data JSON, commit_seq BIGINT NOT NULL DEFAULT 0, updated_at TIMESTAMPTZ DEFAULT NOW(),
            PRIMARY KEY (sim_id, kind, id))""")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS entity_commits (
            sim_id TEXT NOT NULL, seq BIGINT NOT NULL, tick BIGINT, at TIMESTAMPTZ DEFAULT NOW(),
            written INT, deleted INT, PRIMARY KEY (sim_id, seq))""")


def write(sim_id, upserts, deletes, tick):
    """One transaction: the changed rows, the deleted ones, the commit."""
    import db
    from psycopg2.extras import execute_values
    t0 = time.perf_counter()
    with db._conn_lock, db.conn:
        with db.conn.cursor() as cur:
            ensure_tables(cur)
            cur.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM entity_commits WHERE sim_id=%s", (sim_id,))
            seq = cur.fetchone()[0]
            if upserts:
                execute_values(cur, """
                    INSERT INTO entities (sim_id, kind, id, data, commit_seq) VALUES %s
                    ON CONFLICT (sim_id, kind, id) DO UPDATE SET data = EXCLUDED.data, commit_seq = EXCLUDED.commit_seq,
                                                                 updated_at = NOW()""",
                               [(sim_id, k, i, text, seq) for (k, i), text in upserts.items()], page_size=500)
            if deletes:
                execute_values(cur, "DELETE FROM entities WHERE (sim_id, kind, id) IN (VALUES %s)",
                               [(sim_id, k, i) for k, i in deletes], page_size=500)
            cur.execute("INSERT INTO entity_commits (sim_id, seq, tick, written, deleted) VALUES (%s, %s, %s, %s, %s)",
                        (sim_id, seq, tick, len(upserts), len(deletes)))
    _stats["flushes"] += 1
    _stats["rows_written"] += len(upserts)
    _stats["rows_deleted"] += len(deletes)
    _stats["write_ms"] += (time.perf_counter() - t0) * 1000
    _stats["last_tick"] = tick
    return seq


def load(sim_id):
    """The persisted world as of the last commit, or None if this sim has never been written as entities."""
    import db
    with db._conn_lock, db.conn:
        with db.conn.cursor() as cur:
            ensure_tables(cur)
            cur.execute("SELECT kind, id, data FROM entities WHERE sim_id=%s", (sim_id,))
            rows = cur.fetchall()
    if not rows:
        return None
    by = {(k, i): d for k, i, d in rows}
    manifest = by.pop(("meta", "manifest"), None) or {"keys": [], "collections": {}}
    world = {}
    for k in manifest.get("keys", []):
        spec = (manifest.get("collections") or {}).get(k)
        if spec is None:
            if ("key", k) in by:
                world[k] = by.pop(("key", k))
            continue
        ids = spec.get("order", [])
        items = [(i, by.pop((k, i))) for i in ids if (k, i) in by]
        world[k] = dict(items) if spec.get("type") == "dict" else [e for _, e in items]
    cold_rows = {i: by.pop((k2, i)) for (k2, i) in [key for key in by if key[0] == COLD_KIND]}
    cold = _cold_keys()
    # characters stored the old way (one row, cold keys inline): not yet written split -- their first flush must write
    # the hot row and every cold row, so they are left out of "last written" below
    legacy = {cid for cid, c in (world.get("characters") or {}).items()
              if isinstance(c, dict) and any(k2 in cold and v != _COLD_MARK for k2, v in c.items())}
    for cid, c in (world.get("characters") or {}).items():
        if not isinstance(c, dict):
            continue
        for ck in [k2 for k2, v in c.items() if v == _COLD_MARK]:
            row = f"{cid}/{ck}"
            if row in cold_rows:
                c[ck] = cold_rows.pop(row)
            else:
                del c[ck]                      # its row is missing: dropped (schema defaults put an empty one back)
    for (k, i), d in by.items():           # rows the manifest doesn't list (shouldn't happen): not lost
        if k == "key":
            world.setdefault(i, d)
        elif COLLECTIONS.get(k) == "dict":
            world.setdefault(k, {})[i] = d
        elif COLLECTIONS.get(k) == "list":
            world.setdefault(k, []).append(d)
    # what is in the store now is what was last written
    _written[sim_id] = {}
    entities, man = split(world)
    _written[sim_id] = {key: _dumps(e) for key, e in entities.items()}
    _written[sim_id][("meta", "manifest")] = _dumps(man)
    for key in [key for key in _written[sim_id]
                if (key[0] == "characters" and key[1] in legacy)
                or (key[0] == COLD_KIND and key[1].split("/", 1)[0] in legacy)]:
        del _written[sim_id][key]
    _cold_sig[sim_id] = {key: _sig(e) for key, e in entities.items() if key[0] == COLD_KIND}
    return world


def stats():
    return dict(_stats)
