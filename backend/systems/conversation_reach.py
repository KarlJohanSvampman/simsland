"""
systems/conversation_reach.py

Catching conversations that couldn't really be happening face to face: every in-person line said
(brain/conversations.py::add_message) is checked against each listener --

    different rooms     speaker and listener stand in different rooms (or one inside, one out)
    no line of sight    a wall, closed door or blocking prop is between them (where: the point it stopped at)
    too far             the listener couldn't hear that volume from there (the same muffled-distance test
                        perception uses: brain/perception.py::sound_modifier / volume_range)

A line with any of these is an incident: logged (world["conversation_reach_log"], the latest INCIDENTS_KEPT, and a
[talk-reach] line in the server log) and the latest check of each pair is kept on the conversation (conv["reach"]) so
VR Debug Draw (api/debug_draw.py) can draw it. Phone calls, texts and emails are never checked.
"""

import math

INCIDENTS_KEPT = 100


def check_pair(world, speaker, listener, volume=None):
    """{"ok", "issues": [...], "distance", "hit", "by", "rooms": [a, b], "carries"} for speaker -> listener now."""
    from brain.perception import los_trace, volume_range, sound_modifier, DEFAULT_VOLUME
    from systems.room_assignment import room_at
    volume = volume or (speaker.get("current_speech") or {}).get("volume") or DEFAULT_VOLUME
    d = math.hypot(speaker.get("x", 0) - listener.get("x", 0), speaker.get("y", 0) - listener.get("y", 0))
    ra, rb = room_at(world, speaker.get("x", 0), speaker.get("y", 0)), room_at(world, listener.get("x", 0), listener.get("y", 0))
    trace = los_trace(speaker, listener, world)
    carries = volume_range(listener, volume)
    try:
        effective = (abs(speaker["x"] - listener["x"]) + abs(speaker["y"] - listener["y"])) / max(1e-6, sound_modifier(listener, speaker, volume))
    except Exception:
        effective = d
    issues = []
    if ra != rb:
        issues.append("different rooms")
    if not trace["ok"]:
        issues.append(f"no line of sight ({trace['by']})")
    if effective > carries:
        issues.append(f"too far ({d:.1f} tiles; a {volume} voice carries {carries:.0f})")
    hit = trace.get("hit")
    return {"ok": not issues, "issues": issues, "distance": round(d, 2), "volume": volume,
            "hit": [round(hit[0], 2), round(hit[1], 2)] if hit else None, "by": trace.get("by"),
            "rooms": [ra, rb], "carries": round(carries, 1)}


def note_unheard(world, speaker, listener, utterance, reach, tell_speaker=True):
    """A line said to someone who couldn't hear it: logged (delivered False) and the speaker is told (wake
    "not_heard", through the event bus -- this runs on the speaker's own worker thread)."""
    entry = dict(reach, tick=world.get("tick", 0), speaker=speaker["id"], listener=listener["id"],
                 speaker_name=speaker.get("name"), listener_name=listener.get("name"), line=str(utterance or "")[:140],
                 delivered=False, conv_id=None,
                 **{"from": [round(speaker.get("x", 0), 2), round(speaker.get("y", 0), 2)],
                    "to": [round(listener.get("x", 0), 2), round(listener.get("y", 0), 2)]})
    log = world.setdefault("conversation_reach_log", [])
    log.append(entry)
    del log[:-INCIDENTS_KEPT]
    speaker["_unheard"] = {"target": listener["id"], "tick": entry["tick"], "volume": reach.get("volume")}   # call out next time
    where = "in another room" if reach["rooms"][0] != reach["rooms"][1] else "too far away"
    print(f"[talk-reach] tick {entry['tick']}: {speaker.get('name')} -> {listener.get('name')}: not heard "
          f"({', '.join(reach['issues'])})", flush=True)
    if not tell_speaker:
        return
    from core.event_bus import emit
    emit("speech_unheard", {"speaker_id": speaker["id"], "listener_name": listener.get("name") or listener["id"],
                            "where": where, "utterance": str(utterance or "")[:120]})



def on_line(world, conv, speaker_id):
    """After a line is said in conv: check it against every listener; log any incident."""
    if (conv.get("medium") or "in_person") != "in_person":
        return
    chars = world.get("characters") or {}
    sp = chars.get(speaker_id)
    if not sp or sp.get("x") is None:
        return
    tick = world.get("tick", 0)
    reach = conv.setdefault("reach", {})
    last_line = (conv.get("history") or [{}])[-1]
    for lid in conv.get("participants") or []:
        if lid == speaker_id:
            continue
        li = chars.get(lid)
        if not li or li.get("x") is None or li.get("off_grid") or li.get("is_workplace_npc"):
            continue
        r = check_pair(world, sp, li)
        r.update({"tick": tick, "speaker": speaker_id, "listener": lid,
                  "from": [round(sp["x"], 2), round(sp["y"], 2)], "to": [round(li["x"], 2), round(li["y"], 2)]})
        reach[f"{speaker_id}>{lid}"] = r
        if r["ok"]:
            continue
        entry = dict(r, conv_id=conv.get("id"), speaker_name=sp.get("name"), listener_name=li.get("name"),
                     line=str(last_line.get("utterance") or "")[:140])
        log = world.setdefault("conversation_reach_log", [])
        log.append(entry)
        del log[:-INCIDENTS_KEPT]
        print(f"[talk-reach] tick {tick}: {sp.get('name')} -> {li.get('name')}: {', '.join(r['issues'])} "
              f"(\"{entry['line'][:60]}\")", flush=True)
