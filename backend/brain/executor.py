from collections import deque

from brain.memory import store_memory
from brain.conversation import after_speech, maybe_end
from brain.relationships import apply_interaction
from brain.emotion import apply_emotion_inertia

from systems.offgrid import send_offgrid
from systems.emergency import create_911_call
from systems.activities import (
    update_activity,
    update_interaction_phases
)

from systems.payments import attempt_pay_bills

from systems.props import (
    find_nearest_prop,
    get_prop_by_id
)

from systems.occupancy import (
    find_free_anchor,
    reserve_anchor,
    release_anchor,
    release_reservation
)

from systems.phone import make_call
from systems.commitment import start_commitment
from systems.habits import record_habit

from systems.navgrid import (
    build_blocked_set,
    is_walkable
)


# ============================================
# EMOTION → ACTION OVERRIDES
# ============================================
EMOTION_BLOCKS = {
    "fearful": {
        "smash": "leave",
        "yell": "leave",
        "speak": "leave"
    },

    "sad": {
        "smash": "relax",
        "yell": "relax"
    },

    "awkward": {
        "smash": "wait",
        "yell": "wait"
    },

    "calm": {
        "smash": "speak",
        "yell": "speak"
    },

    "annoyed": {
        "smash": "yell"
    },

    "curious": {
        "smash": "observe"
    }
}


# ============================================
# HELPERS
# ============================================
def enqueue_anchor(c, prop, anchor):

    anchor.setdefault("queue", [])

    if c["id"] not in anchor["queue"]:
        anchor["queue"].append(c["id"])


def compute_facing(cx, cy, tx, ty):

    dx = tx - cx
    dy = ty - cy

    if abs(dx) > abs(dy):
        return "east" if dx > 0 else "west"

    return "south" if dy > 0 else "north"


def is_occupied(x, y, world, ignore_id=None):

    for c2 in world.get("characters", {}).values():

        if c2["id"] == ignore_id:
            continue

        if (c2["x"], c2["y"]) == (x, y):
            return True

    return False


def neighbors(x, y):

    return [
        (x + 1, y),
        (x - 1, y),
        (x, y + 1),
        (x, y - 1)
    ]


def is_adjacent(c, pos):

    return (
        abs(c["x"] - pos["x"])
        + abs(c["y"] - pos["y"])
    ) <= 1


def face_target(c, pos):

    c["facing"] = compute_facing(
        c["x"],
        c["y"],
        pos["x"],
        pos["y"]
    )


def snap_to_anchor(c, anchor):

    c["x"] = anchor["x"]
    c["y"] = anchor["y"]

# =========================================================
# SPEAK
# =========================================================

def execute_speak(

    c,

    world,

    action
):

    target_id = action.get(
        "target"
    )

    utterance = action.get(
        "utterance",
        ""
    )

    speech_act = action.get(
        "speech_act",
        "talk"
    )

    topic = action.get(
        "topic",
        "general"
    )

    # =====================================
    # FIND TARGET
    # =====================================

    target = world.get(
        "characters",
        {}
    ).get(target_id)

    if not target:
        return False

    # =====================================
    # STORE SPEECH
    # =====================================

    c["current_speech"] = {

        "text":
            utterance,

        "target":
            target_id,

        "topic":
            topic,

        "speech_act":
            speech_act
    }

    # =====================================
    # STORE MEMORY
    # =====================================

    from brain.memory import (
        store_memory
    )

    store_memory(

        c,

        text=utterance,

        tags=[

            "conversation",

            speech_act,

            topic
        ],

        people=[
            target_id
        ],

        importance=15,

        source="speech"
    )

    store_memory(

        target,

        text=utterance,

        tags=[

            "heard",

            speech_act,

            topic
        ],

        people=[
            c["id"]
        ],

        importance=15,

        source="speech"
    )

    return True

    # =========================================================
# MOVE
# =========================================================

def execute_move(

    c,

    world,

    action
):

    target = action.get(
        "target"
    )

    if not target:
        return False

    # =====================================
    # LOCATION TARGET
    # =====================================

    target_position = resolve_target_position(

        world,

        target
    )

    if not target_position:
        return False

    # =====================================
    # PATH
    # =====================================

    path = build_path(

        world,

        c,

        target_position
    )

    if not path:
        return False

    c["path"] = path

    c["path_index"] = 0

    c["activity"] = {

        "type": "walking",

        "target": target
    }

    return True

def execute_wait(

    c,

    world,

    action
):

    c["activity"] = {

        "type": "waiting",

        "duration":
            action.get(
                "duration",
                5
            )
    }

    return True
# ============================================
# PATHFINDING
# ============================================
def find_path(c, tx, ty, world):

    start = (c["x"], c["y"])
    goal = (tx, ty)

    blocked = build_blocked_set(world)

    queue = deque([(start, [])])
    visited = {start}

    while queue:

        (x, y), path = queue.popleft()

        if (x, y) == goal:
            return path

        for nx, ny in neighbors(x, y):

            if (nx, ny) in visited:
                continue

            # -----------------------------
            # GRID LIMITS
            # -----------------------------
            if nx < 0 or ny < 0:
                continue

            if nx >= world["grid"]["width"]:
                continue

            if ny >= world["grid"]["height"]:
                continue

            # -----------------------------
            # WALKABILITY
            # -----------------------------
            if (nx, ny) != goal:

                if not is_walkable(
                    nx,
                    ny,
                    world,
                    blocked
                ):
                    continue

                if is_occupied(
                    nx,
                    ny,
                    world,
                    ignore_id=c["id"]
                ):
                    continue

            visited.add((nx, ny))

            queue.append(
                (
                    (nx, ny),
                    path + [(nx, ny)]
                )
            )

    return []


# ============================================
# BUS
# ============================================
def find_bus_at_stop(c, world):

    for e in world.get("entities", {}).values():

        bus = e["components"].get("bus")
        pos = e["components"].get("position")

        if not bus:
            continue

        if bus["state"] != "stopped":
            continue

        dist = (
            abs(pos["x"] - c["x"])
            + abs(pos["y"] - c["y"])
        )

        if dist <= 1:

            return {
                "id": e["id"],
                "position": pos,
                "passengers": bus["passengers"]
            }

    return None


# ============================================
# ACTION HANDLERS
# ============================================

def handle_move(

    c,

    action,

    world
):

    tx = action.get("x")
    ty = action.get("y")

    if tx is None or ty is None:
        return

    path = find_path(
        c,
        tx,
        ty,
        world
    )

    if not path:

        release_reservation(
            c,
            world
        )

        c["activity"] = None

        return

    nx, ny = path[0]

    c["facing"] = compute_facing(
        c["x"],
        c["y"],
        nx,
        ny
    )

    c["x"] = nx
    c["y"] = ny

    c["is_moving"] = True

    c["animation_state"] = "walk"


def handle_wait(

    c,

    action,

    world
):

    c["activity"] = {

        "name": "wait",

        "phase": "loop",

        "phase_started":
            world["tick"],

        "duration":
            action.get(
                "duration",
                2
            )
    }

    c["animation_state"] = "idle"


def handle_speak(

    c,

    action,

    decision,

    world
):

    from brain.conversations import (

        get_or_create_conversation,

        add_message
    )
    utterance = (
        action.get("utterance")
        or ""
    ).strip()

    if not utterance:
        return

    target_id = action.get(
        "target"
    )

    target = world.get(
        "characters",
        {}
    ).get(target_id)

    if not target:
        return

    c["last_utterance"] = utterance

    c.setdefault(
        "speech_bubbles",
        []
    ).append({

        "text": utterance,

        "tick": world["tick"]
    })

    c["speech_bubbles"] = (
        c["speech_bubbles"][-4:]
    )

    speech_act = action.get(
        "speech_act",
        "statement"
    )

    topic = action.get(
        "topic",
        "general"
    )

    conv = get_or_create_conversation(

    world,

    c["id"],

    target["id"],

    topic
)

    after_speech(
        c,
        target,
        float(
            decision.get(
                "conversation_score",
                50
            )
        ),
        topic
    )

    store_memory(

        c,

        utterance,

        .55,

        [

            "conversation",

            topic,

            speech_act
        ],

        "conversation",

        world["tick"],

        people=[
            target["id"]
        ],

        speech_act=speech_act,

        emotional_impact=5
    )

    store_memory(

        target,

        utterance,

        .55,

        [

            "heard",

            topic,

            speech_act
        ],

        "conversation",

        world["tick"],

        people=[
            c["id"]
        ],

        speech_act=speech_act
    )

    add_message(

    conv,

    c["id"],

    utterance,

    speech_act,

    topic,

    world["tick"]
)

    apply_interaction(
        c,
        target,
        speech_act
    )
    from social.reputation import (
        apply_social_event
    )

    speech_act = action.get(
        "speech_act"
    )

    if speech_act == "comfort":

        apply_social_event(

            world,

            c["id"],

            "helped",

            0.05
        )

    elif speech_act == "insult":

        apply_social_event(

            world,

            c["id"],

            "insulted",

            0.08
        )

    elif speech_act == "threat":

        apply_social_event(

            world,

            c["id"],

            "threatened",

            0.12
        )

    from brain.beliefs import (
    update_belief
    )

    topic = action.get(
        "topic"
    )

    speech_act = action.get(
        "speech_act"
    )

    # persuasion
    if speech_act in [

        "argue",

        "persuade",

        "rant",

        "debate"
    ]:

        update_belief(

            target,

            topic,

            "positive",

            0.2,

            world["tick"]
        )


def handle_call(

    c,

    action,

    world
):

    target = world["characters"].get(
        action["target"]
    )

    if not target:
        return

    c["is_on_phone"] = True

    make_call(
        c,
        target,
        world
    )


def handle_call_911(

    c,

    action,

    world
):

    report = (

        action.get(
            "utterance"
        )

        or "There is an emergency here."
    )

    create_911_call(

        world,

        c,

        action.get(
            "emergency_type"
        ) or "police",

        report
    )

    c["last_utterance"] = report

# ============================================
# EXECUTION
# ============================================
def execute(c, decision, world):

    update_interaction_phases(c, world)

    # ========================================
    # BLOCK MOVEMENT DURING START/STOP PHASES
    # ========================================
    act = c.get("activity")

    if act and act.get("phase") in ["start", "stop"]:
        return

    # ========================================
    # ACTIVE ACTIVITY UPDATE
    # ========================================
    if update_activity(c, world):
        return

    if not decision:
        return

    emotion = decision.get(
        "emotion",
        c.get("emotion", "calm")
    )

    apply_emotion_inertia(c, emotion)

    c["emotion"] = emotion
    c["mood"] = emotion

    action = decision.get("action", {})
    raw_name = action.get(
        "type",
        "wait"
    )

    name = EMOTION_BLOCKS.get(
        emotion,
        {}
    ).get(raw_name, raw_name)

    utterance = (
        action.get("utterance")
        or ""
    ).strip()

    c["last_action"] = name

    c["internal_thought"] = decision.get(
        "thought",
        c.get("internal_thought", "")
    )

    c["is_moving"] = False

        
        # ========================================
    # MOVE
    # ========================================
    if name == "move":

        handle_move(
            c,
            action,
            world
        )

    # ========================================
    # WAIT
    # ========================================
    elif name == "wait":

        handle_wait(
            c,
            action,
            world
        )

    # ========================================
    # SPEAK
    # ========================================
    elif name in ["speak", "yell"]:

        handle_speak(
            c,
            action,
            decision,
            world
        )

    # ========================================
    # PHONE
    # ========================================
    elif name == "call":

        handle_call(
            c,
            action,
            world
        )

    # ========================================
    # EMERGENCY
    # ========================================
    elif name == "call_911":

        handle_call_911(
            c,
            action,
            world
        )

    # ========================================
    # LEAVE
    # ========================================
    elif name == "leave":

        c["conversation"] = None

        c["x"] = max(0, c["x"] - 1)

    # ========================================
    # OFFGRID
    # ========================================
    elif name == "go_work":

        c["transport"] = {"mode": "car"}

        send_offgrid(
            c,
            world,
            "work",
            40
        )

    elif name == "go_interview":

        send_offgrid(
            c,
            world,
            "interview",
            20
        )

    elif name == "go_shopping":

        send_offgrid(
            c,
            world,
            "shopping",
            18
        )

    elif name == "go_leisure":

        send_offgrid(
            c,
            world,
            "leisure",
            28
        )

    # ========================================
    # NEEDS
    # ========================================
    elif name == "eat":

        start_commitment(
            c,
            "eat",
            600
        )

        record_habit(
            c,
            "eat",
            world
        )

    elif name == "drink":

        start_commitment(
            c,
            "drink",
            10
        )

        record_habit(
            c,
            "drink",
            world
        )

    elif name == "sleep":

        record_habit(
            c,
            "sleep",
            world
        )



    elif name == "end_call":

        c["is_on_phone"] = False
 

    # ========================================
    # FALLBACK
    # ========================================
    else:

        c["last_utterance"] = ""

    maybe_end(c, world)