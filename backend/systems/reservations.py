# =========================================================
# IS RESERVED
# =========================================================

def is_reserved(

    obj
):

    return (
        obj.get(
            "reserved_by"
        )
        is not None
    )


# =========================================================
# RESERVE OBJECT
# =========================================================

def reserve_object(

    obj,

    character_id
):

    if is_reserved(obj):

        return False

    obj["reserved_by"] = (
        character_id
    )

    return True


# =========================================================
# RELEASE OBJECT
# =========================================================

def release_object(
    obj
):

    obj["reserved_by"] = None


# =========================================================
# RESERVED BY
# =========================================================

def reserved_by(
    obj
):

    return obj.get(
        "reserved_by"
    )