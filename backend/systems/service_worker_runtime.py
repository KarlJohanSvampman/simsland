import math


# =========================================================
# UPDATE SERVICE WORKERS
# =========================================================

def update_service_workers(world):

    workers = world.get(
        "service_workers",
        []
    )

    completed = []

    for worker in workers:

        done = update_worker(

            worker,

            world
        )

        if done:

            completed.append(
                worker
            )

    # =====================================================
    # CLEANUP
    # =====================================================

    for worker in completed:

        if worker in workers:

            workers.remove(
                worker
            )


# =========================================================
# UPDATE WORKER
# =========================================================

def update_worker(

    worker,

    world
):

    state = worker.get(
        "state"
    )

    # =====================================================
    # WALK TO TARGET
    # =====================================================

    if state in [

        "walking_to_mailbox",

        "walking_to_door"
    ]:

        arrived = move_worker_towards(

            worker,

            worker["target_x"],

            worker["target_y"]
        )

        worker[
            "animation_state"
        ] = "carry_box"

        if arrived:

            if state == (
                "walking_to_mailbox"
            ):

                worker["state"] = (
                    "depositing_mail"
                )

            else:

                worker["state"] = (
                    "dropping_package"
                )

        return False

    # =====================================================
    # DEPOSIT MAIL
    # =====================================================

    if state == "depositing_mail":

        if worker.get("service_type") == "newspaper":

            deposit_newspaper(

                worker,

                world
            )

        else:

            deposit_mail(

                worker,

                world
            )

        worker["state"] = (
            "returning"
        )

        return False

    # =====================================================
    # DROP PACKAGE
    # =====================================================

    if state == "dropping_package":

        drop_package(

            worker,

            world
        )

        worker["state"] = (
            "returning"
        )

        return False

    # =====================================================
    # RETURN
    # =====================================================

    if state == "returning":

        vehicle = find_vehicle(

            world,

            worker[
                "vehicle_id"
            ]
        )

        if not vehicle:
            return True

        arrived = move_worker_towards(

            worker,

            vehicle["x"],

            vehicle["y"]
        )

        worker[
            "animation_state"
        ] = "walk"

        if arrived:

            advance_vehicle_route(

                vehicle,

                world
            )

            return True

        return False

    return False


# =========================================================
# MOVE
# =========================================================

def move_worker_towards(

    worker,

    tx,

    ty
):

    speed = worker.get(
        "speed",
        0.045
    )

    dx = tx - worker["x"]
    dy = ty - worker["y"]

    dist = math.sqrt(

        dx * dx
        +
        dy * dy
    )

    if dist <= speed:

        worker["x"] = tx
        worker["y"] = ty

        return True

    worker["x"] += (
        dx / dist
    ) * speed

    worker["y"] += (
        dy / dist
    ) * speed

    return False


# =========================================================
# DEPOSIT MAIL
# =========================================================

def deposit_mail(

    worker,

    world
):

    household = world[
        "households"
    ].get(

        worker[
            "household_id"
        ]
    )

    if not household:
        return

    household.setdefault(
        "mailbox",
        {}
    )

    household[
        "mailbox"
    ][
        "has_mail"
    ] = True

    household.setdefault(
        "delivered_mail",
        []
    )

    pending = household.get(
        "mail",
        []
    )

    household[
        "delivered_mail"
    ].extend(pending)

    household["mail"] = []

    # =====================================================
    # SPAWN VISUAL MAIL
    # =====================================================

    world.setdefault(
        "world_objects",
        []
    )

    import uuid
    mail_bundle_id = f"wobj_mail_{uuid.uuid4().hex[:6]}"

    world[
        "world_objects"
    ].append({

        "id":
            mail_bundle_id,

        "type":
            "mail_bundle",

        "model":
            "mail_stack",

        "x":
            household[
                "mailbox"
            ]["x"],

        "y":
            household[
                "mailbox"
            ]["y"],

        "household_id":
            household["id"]
    })

    from sim_loop import _mark_dirty
    _mark_dirty(world, world_object_ids={mail_bundle_id})


# =========================================================
# DEPOSIT NEWSPAPER
# Paperboy's equivalent of deposit_mail() above -- see
# systems/newspaper_delivery.py, branched to here from
# update_worker()'s "depositing_mail" state on service_type=="newspaper".
# =========================================================

def deposit_newspaper(worker, world):
    household = world["households"].get(worker["household_id"])
    if not household:
        return

    mailbox = household.setdefault("mailbox", {})
    mailbox["has_newspaper"] = True

    from systems.personal_items import make_item
    item = make_item("newspaper", world=world)
    item["location"] = "placed"
    item["x"] = mailbox.get("x", 0)
    item["y"] = mailbox.get("y", 0)
    item["placed_at_tick"] = world.get("tick", 0)
    world.setdefault("placed_items", {})[item["id"]] = item

    from sim_loop import _mark_dirty
    _mark_dirty(world, placed_item_ids={item["id"]})


# =========================================================
# DROP PACKAGE
# =========================================================

def drop_package(

    worker,

    world
):

    household = world[
        "households"
    ].get(

        worker[
            "household_id"
        ]
    )

    if not household:
        return

    household.setdefault(
        "pending_packages",
        []
    )

    package = worker.get(
        "package"
    )

    if package:

        household[
            "pending_packages"
        ].append(package)

    # =====================================================
    # SPAWN PACKAGE ENTITY
    # =====================================================

    door = household.get(
        "front_door"
    )

    if not door:
        return

    world.setdefault(
        "world_objects",
        []
    )

    import uuid
    package_obj_id = f"wobj_package_{uuid.uuid4().hex[:6]}"

    world[
        "world_objects"
    ].append({

        "id":
            package_obj_id,

        "type":
            "package",

        "model":
            "cardboard_box",

        "x":
            door["x"],

        "y":
            door["y"],

        "household_id":
            household["id"],

        "package":
            package
    })

    from sim_loop import _mark_dirty
    _mark_dirty(world, world_object_ids={package_obj_id})


# =========================================================
# FIND VEHICLE
# =========================================================

def find_vehicle(

    world,

    vehicle_id
):

    for v in world.get(
        "service_vehicles",
        []
    ):

        if v["id"] == vehicle_id:

            return v

    return None


# =========================================================
# ADVANCE ROUTE
# =========================================================

# =========================================================
# ADVANCE VEHICLE ROUTE
# =========================================================

def advance_vehicle_route(

    vehicle,

    world
):

    vehicle[
        "current_target"
    ] += 1

    vehicle["state"] = (
        "driving"
    )

    from systems.service_vehicles import (
        assign_next_vehicle_route
    )

    assign_next_vehicle_route(

        vehicle,

        world
    )