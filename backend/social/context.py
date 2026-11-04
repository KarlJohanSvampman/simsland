"""
social/context.py -- what a character is told about their social state, for their own AI turn (design section 19).

For the people around them (in view, in a conversation with them, or on their mind): how they regard them, how
frustrated they are and about what, whether they've been reaching out or keeping away; the open issues between them
(their own position, and the other's if they've heard it), agreements and mere expectations; a confrontation under
way (type, problem, what they want, stage, who is on which side, and -- once it's hostile -- the things to weigh before
it gets physical); what they've heard about people present; and the conversation they just had.

It describes; it doesn't steer. Low regard is shown with what it tends to do (shorter answers, less patience), and
avoiding someone is named as just as real a choice as confronting them.
"""

from social.core import DAY, chars, first, name, now


def _people_in_mind(c, world):
    ids = []
    for p in (c.get("perception") or {}).get("visible_people") or []:
        if p.get("id"):
            ids.append(p["id"])
    for conv in (world.get("conversations") or {}).values():
        if conv.get("active") and c["id"] in (conv.get("participants") or []):
            ids += [p for p in conv["participants"] if p != c["id"]]
    ids += list((c.get("wants_to_raise") or {}).keys()) + list((c.get("wants_to_repair") or {}).keys())
    from social import confrontations as X
    for conf in X.active_for(world, c["id"]):
        ids += [p for p in conf["participants"] if p != c["id"]]
    seen, out = set(), []
    for i in ids:
        if i not in seen and i in chars(world) and i != c["id"]:
            seen.add(i)
            out.append(i)
    return out[:6]


def _person(c, world, oid):
    from social import standing, frustration, initiative, issues as I, contracts as K
    lines = []
    nm = first(world, oid)
    s = standing.score(c, oid)
    f = frustration.value(c, oid, world)
    bits = [f"your regard for {nm}: {standing.label(s)} ({round(s)})"]
    if f["intensity"] >= 10 or f["score"] >= 15:
        bits.append(f"right now you're {frustration.word(f['intensity'])} with them"
                    + (f", and it's been building up ({round(f['score'])}/100)" if f["score"] >= 30 else ""))
    i = initiative.get(c, oid, create=False)
    if initiative.rebuffs(c, oid) >= 3:
        bits.append("you've reached out several times lately and been brushed off")
    elif i.get("avoidance", 0) >= 40:
        bits.append("you've been keeping your distance from them")
    if initiative.refresh_repair(c, oid, world) >= 40:
        bits.append("you'd like things to be better between you")
    line = "; ".join(bits) + "."
    lines.append(line[0].upper() + line[1:])
    if s <= -20:
        lines.append(f"Thinking little of {nm} makes you shorter with them, less patient, quicker to take what they say "
                     f"the wrong way -- though you can just as well keep out of their way as have it out.")
    for iss in I.between(world, c["id"], oid, status=("open", "reopened", "dormant"))[:3]:
        fi = frustration.value(c, oid, world, iss["id"])
        extra = f" [your frustration over it: {round(fi['score'])}]" if fi["score"] >= 10 else ""
        lines.append("Issue: " + I.summary(world, iss, me=c["id"]) + extra)
    lines += K.context_lines(world, c, oid)
    return lines


def _confrontation(c, world, conf):
    from social import confrontations as X
    me = conf["participants"].get(c["id"]) or {}
    a, b = conf["initiator_id"], conf["primary_target_id"]
    who = "You are taking up" if a == c["id"] else f"{first(world, a)} is taking up"
    target = "you" if b == c["id"] else first(world, b)
    lines = [f"{who} \"{conf['problem_statement']}\" with {target} "
             f"({conf['confrontation_type'].replace('_', ' ')}; it's at: {conf['stage'].replace('_', ' ')})."]
    if conf.get("desired_outcome"):
        lines.append(f"What {('you want' if a == c['id'] else first(world, a) + ' wants')}: {conf['desired_outcome']}.")
    other_pos = conf["target_position"] if a == c["id"] else conf["initiator_position"]
    if other_pos:
        lines.append(f"Their side of it, as they've put it: {other_pos}")
    sides = [f"{first(world, p)} ({x['role']}{', with ' + X._side_name(world, conf, x['side']).split(' ')[0] if x['side'] in ('initiator', 'target') and x['role'] not in ('initiator', 'target') else ''})"
             for p, x in conf["participants"].items() if p not in (a, b, c["id"])]
    if sides:
        lines.append("Also in it: " + ", ".join(sides) + ".")
    if me.get("role") not in ("initiator", "target") and me:
        lines.append(f"You're in it as {me['role']}" + (f", on {X._side_name(world, conf, me['side'])}'s side"
                                                        if me.get('side') in ('initiator', 'target') else "") + ".")
    if conf["stage_idx"] >= 3 and c["id"] in (a, b):
        other = b if c["id"] == a else a
        lines.append(_physical_considerations(c, world, other, conf))
    elif conf["stage_idx"] >= 2:
        lines.append("It's getting heated. You can push, hold your ground, calm it down, or walk away.")
    return lines


def _physical_considerations(c, world, other_id, conf):
    """Design 13.3: what to weigh before it gets physical. Stated, not decided."""
    o = chars(world).get(other_id) or {}
    traits = set(c.get("traits") or [])
    witnesses = conf["public_visibility"] > 0
    stake = []
    if c.get("job"):
        stake.append("your job")
    if any((chars(world).get(k) or {}).get("age", 99) < 18 for k in ((world.get("households") or {})
                                                                  .get(c.get("household_id"), {}).get("members") or [])):
        stake.append("the kids at home")
    bigger = (o.get("height") or 0) > (c.get("height") or 0) * 1.1 or "strong" in (o.get("traits") or [])
    return ("This is turning hostile. Before anything physical, weigh it: is it justified? are you actually "
            "threatened? " + ("they look like they could hurt you; " if bigger else "")
            + ("people are watching, and it could end with the police; " if witnesses else "it could end with the police; ")
            + (f"you have {', '.join(stake)} to lose; " if stake else "")
            + "and they may hit back." + (" Your temper runs hot." if traits & {"hot_headed", "aggressive", "volatile"} else ""))


def lines(c, world):
    out = []
    from social import confrontations as X, rumours as R, frustration
    t = now(world)
    for conf in X.active_for(world, c["id"]):
        out += _confrontation(c, world, conf)
    for oid in _people_in_mind(c, world):
        out += _person(c, world, oid)
    for oid, w in (c.get("wants_to_raise") or {}).items():
        if X.active_between(world, c["id"], oid):
            continue
        from social import issues as I
        iss = max(I.between(world, c["id"], oid), key=lambda i: frustration.value(c, oid, world, i["id"])["score"],
                  default=None)
        about = f" over {iss['subject']}" if iss else ""
        out.append(f"You've had about enough of {first(world, oid)}{about}. You could take it up with them "
                   f"(say what the problem is and what you want), let it go, or keep your distance.")
    for v in (c.get("_wants_to_vent") or []):
        if t - v["tick"] < DAY:
            out.append(f"What happened with {first(world, v['about'])} ({v['what']}) is still on your mind; "
                       f"you might want to talk to someone about it.")
    present = set(_people_in_mind(c, world))
    for r in R.known_by(world, c["id"], min_conf=0.35)[:8]:
        k = (c.get("known_rumours") or {}).get(r["id"]) or {}
        src = ", ".join(first(world, s) for s in k.get("heard_from") or []) or "someone"
        if r["subject_id"] in present or any(p != r["subject_id"] for p in present):
            line = f"You've heard (from {src}) that {name(world, r['subject_id'])}: {r['claim']} -- you {k.get('interpretation', 'half believe it')}."
            if r["subject_id"] in present:
                line += " They're right here."
            out.append(line)
    log = c.get("conversation_log") or []
    if log:
        last = log[-1]
        if t - (last.get("ended_tick") or 0) < 600 and not any(
                conv.get("active") and c["id"] in conv.get("participants", [])
                for conv in (world.get("conversations") or {}).values()):
            subj = last.get("subject") or (last.get("tags") or {}).get("subject") or last.get("topic")
            who = " and ".join(w.get("name") or "someone" for w in last.get("with") or [])
            if subj and subj not in ("general",):
                out.append(f"You were just talking with {who} about {subj} "
                           f"(it ended: {str(last.get('end_reason') or 'it wound down').replace('_', ' ')}).")
    return out
