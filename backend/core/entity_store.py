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
"""

import json
import time

COLLECTIONS = {
    "characters": "dict",
    "households": "dict",
    "conversations": "dict",
    "conversation_archive": "dict",
    "props": "list",
}

_written = {}            # sim_id -> {(kind, id): json text} as last written
_stats = {"flushes": 0, "rows_written": 0, "rows_deleted": 0, "diff_ms": 0.0, "write_ms": 0.0, "last_tick": None}


def _dumps(obj):
    try:
        return json.dumps(obj)
    except TypeError:
        from core.cache import safe_json_dumps
        return safe_json_dumps(obj)


def _static_keys():
    from db import _STATIC_WORLD_KEYS
    return set(_STATIC_WORLD_KEYS)


def _list_id(item, i):
    return str(item.get("id")) if isinstance(item, dict) and item.get("id") is not None else f"#{i}"


def split(world):
    """{(kind, id): entity} for everything persisted, and the manifest that puts it back together."""
    static = _static_keys()
    out, keys, orders = {}, [], {}
    for k, v in world.items():
        if k in static:
            continue
        keys.append(k)
        shape = COLLECTIONS.get(k)
        if shape == "dict" and isinstance(v, dict):
            orders[k] = {"type": "dict", "order": [str(i) for i in v]}
            for i, e in v.items():
                out[(k, str(i))] = e
        elif shape == "list" and isinstance(v, list):
            ids = [_list_id(e, n) for n, e in enumerate(v)]
            if len(set(ids)) == len(ids):
                orders[k] = {"type": "list", "order": ids}
                for i, e in zip(ids, v):
                    out[(k, i)] = e
            else:
                out[("key", k)] = v          # ids not unique: kept as one record
        else:
            out[("key", k)] = v
    return out, {"keys": keys, "collections": orders}


def diff(sim_id, world, only=None):
    """What to write so the store matches `world`. `only`: the (kind, id) touched since the last flush -- just those
    are rendered and compared (plus the manifest); None compares everything."""
    t0 = time.perf_counter()
    last = _written.setdefault(sim_id, {})
    entities, manifest = split(world)
    upserts, deletes = {}, []
    keys = entities.keys() if only is None or not last else (set(only) & set(entities))
    for key in keys:
        text = _dumps(entities[key])
        if last.get(key) != text:
            upserts[key] = text
    for key in list(last):
        if key not in entities and key[0] != "meta":
            deletes.append(key)
    mtext = _dumps(manifest)
    if last.get(("meta", "manifest")) != mtext:
        upserts[("meta", "manifest")] = mtext
    _stats["diff_ms"] += (time.perf_counter() - t0) * 1000
    return upserts, deletes, mtext


def note_written(sim_id, upserts, deletes):
    """The diff has been handed to the writer: it is what the store will hold."""
    last = _written.setdefault(sim_id, {})
    last.update(upserts)
    for key in deletes:
        last.pop(key, None)


def forget(sim_id):
    _written.pop(sim_id, None)


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
    return world


def stats():
    return dict(_stats)
