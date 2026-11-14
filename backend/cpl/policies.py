"""
cpl/policies.py -- how long a conversation may take, by purpose and channel (docs/cpl_implementation_plan.md C6).

Today's hard caps (systems/conversation_outcome.py: 6 lines, 4 sim-minutes; conversation_floor: a minute to answer)
are the defaults for casual talk face to face. Other purposes and channels loosen them. Reaching max_lines or
max_seconds does not stop a conversation: it starts winding down (RESOLVING, a "wrap up" hint in the next turn).
The hard stop is HARD_CAP_FACTOR times that -- every conversation ends (spec invariant 15).

All times are sim seconds.
"""

from cpl.model.enums import Channel, Purpose

HARD_CAP_FACTOR = 2.0

DEFAULT = {
    "invite_s": 60,          # an invitation nobody answers expires
    "reply_s": 60,           # the floor holder's time to answer (a generation in progress does not count)
    "reply_attempts": 2,     # unanswered this many times: the conversation is abandoned
    "pause_s": 300,          # a pause longer than this ends the sitting (INTERRUPTED)
    "close_s": 20,           # winding down: the closing lines, or this long
    "idle_s": 120,           # nobody has said anything for this long: it's over (brain/conversations.py's idle timeout)
    "max_lines": 6,
    "max_seconds": 240,
}

# purpose -> overrides (face to face)
BY_PURPOSE = {
    Purpose.SOCIAL: {"max_lines": 8, "max_seconds": 300},
    Purpose.ROMANTIC: {"max_lines": 10, "max_seconds": 420},
    Purpose.SUPPORT: {"max_lines": 12, "max_seconds": 600},
    Purpose.EMOTIONAL: {"max_lines": 12, "max_seconds": 600},
    Purpose.NEGOTIATION: {"max_lines": 20, "max_seconds": 900},
    Purpose.PERSUASION: {"max_lines": 16, "max_seconds": 720},
    Purpose.CONFLICT: {"max_lines": 14, "max_seconds": 600, "reply_s": 30},
    Purpose.COORDINATION: {"max_lines": 10, "max_seconds": 420},
    Purpose.QUESTION: {"max_lines": 6, "max_seconds": 240},
    Purpose.REQUEST: {"max_lines": 8, "max_seconds": 300},
}

# channel -> overrides applied on top
BY_CHANNEL = {
    Channel.CALL: {"invite_s": 30},                              # it rings, then it doesn't
    Channel.TEXT: {"invite_s": 6 * 3600, "reply_s": 6 * 3600, "reply_attempts": 1, "pause_s": 24 * 3600,
                   "close_s": 3600, "idle_s": 24 * 3600, "max_seconds": 24 * 3600},
    Channel.EMAIL: {"invite_s": 48 * 3600, "reply_s": 48 * 3600, "reply_attempts": 1, "pause_s": 7 * 86400,
                    "close_s": 86400, "idle_s": 7 * 86400, "max_seconds": 14 * 86400},
}

URGENT = {"invite_s": 20, "reply_s": 20}


def policy(purpose=None, channel=None, urgent=False):
    """The policy row for this purpose x channel (x urgency)."""
    out = dict(DEFAULT)
    try:
        out.update(BY_PURPOSE.get(Purpose(purpose), {}))
    except ValueError:
        pass
    try:
        out.update(BY_CHANNEL.get(Channel(channel), {}))
    except ValueError:
        pass
    if urgent:
        out.update({k: min(out[k], v) for k, v in URGENT.items()})
    out["hard_lines"] = int(out["max_lines"] * HARD_CAP_FACTOR)
    out["hard_seconds"] = out["max_seconds"] * HARD_CAP_FACTOR
    return out


def key(purpose, channel, urgent=False):
    return f"{purpose}|{channel}|{'urgent' if urgent else 'normal'}"


def from_key(k):
    purpose, channel, urg = (k or "||").split("|")
    return policy(purpose or None, channel or None, urg == "urgent")
