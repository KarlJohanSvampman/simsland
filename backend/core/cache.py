import redis
import json
import os


REDIS_HOST = os.getenv(
    "REDIS_HOST",
    "redis"
)

r = redis.Redis(

    host=REDIS_HOST,

    port=6379,

    decode_responses=True
)


# =========================================================
# KEYS
# =========================================================

def world_key(sim_id):

    return f"world:{sim_id}"


def char_key(sim_id, cid):

    return f"char:{sim_id}:{cid}"


# =========================================================
# DEBUG JSON VALIDATION
# =========================================================

def validate_json_safe(

    obj,

    path="root"
):

    # =====================================================
    # DICT
    # =====================================================

    if isinstance(obj, dict):

        for k, v in obj.items():

            # =============================================
            # INVALID KEY
            # =============================================

            if not isinstance(

                k,

                (
                    str,
                    int,
                    float,
                    bool,
                    type(None)
                )
            ):

                raise TypeError(

                    f"\n"
                    f"INVALID JSON KEY\n"
                    f"PATH: {path}\n"
                    f"KEY TYPE: {type(k)}\n"
                    f"KEY VALUE: {k}\n"
                )

            validate_json_safe(

                v,

                f"{path}.{k}"
            )

    # =====================================================
    # LIST
    # =====================================================

    elif isinstance(obj, list):

        for i, item in enumerate(obj):

            validate_json_safe(

                item,

                f"{path}[{i}]"
            )

    # =====================================================
    # SAFE PRIMITIVES
    # =====================================================

    elif isinstance(

        obj,

        (
            str,
            int,
            float,
            bool,
            type(None)
        )
    ):

        return

    # =====================================================
    # TUPLES ARE OK AS VALUES
    # =====================================================

    elif isinstance(obj, tuple):

        return

    # =====================================================
    # OTHER TYPES
    # =====================================================

    else:

        raise TypeError(

            f"\n"
            f"INVALID JSON VALUE\n"
            f"PATH: {path}\n"
            f"VALUE TYPE: {type(obj)}\n"
            f"VALUE: {obj}\n"
        )


# =========================================================
# SAFE DUMPS
# =========================================================

def safe_json_dumps(data):

    validate_json_safe(data)

    return json.dumps(data)


# =========================================================
# WORLD CACHE
# =========================================================

def get_world_cache(sim_id):

    data = r.get(

        world_key(sim_id)
    )

    return json.loads(data) if data else None


def set_world_cache(

    sim_id,

    world
):

    try:

        serialized = safe_json_dumps(
            world
        )

        r.set(

            world_key(sim_id),

            serialized,

            ex=5
        )

    except Exception as e:

        print("\n" + "=" * 60)
        print("WORLD CACHE SERIALIZATION FAILED")
        print("=" * 60)
        print(e)
        print("=" * 60 + "\n")

        raise


# =========================================================
# CHARACTER CACHE
# =========================================================

def get_char_cache(

    sim_id,

    cid
):

    data = r.get(

        char_key(
            sim_id,
            cid
        )
    )

    return json.loads(data) if data else None


def set_char_cache(

    sim_id,

    cid,

    c
):

    try:

        serialized = safe_json_dumps(c)

        r.set(

            char_key(
                sim_id,
                cid
            ),

            serialized,

            ex=10
        )

    except Exception as e:

        print("\n" + "=" * 60)
        print("CHARACTER CACHE SERIALIZATION FAILED")
        print("=" * 60)
        print(e)
        print("=" * 60 + "\n")

        raise


# =========================================================
# INVALIDATE
# =========================================================

def invalidate_char(

    sim_id,

    cid
):

    r.delete(

        char_key(
            sim_id,
            cid
        )
    )