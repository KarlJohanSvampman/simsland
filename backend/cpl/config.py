"""cpl/config.py -- CPL_MODE (docs/cpl_implementation_plan.md section 11).

    on       CPL owns the conversation lifecycle (the default: there is one conversation store, and CPL's state is on
             each conversation's record)
    shadow   CPL follows along and decides nothing: its fields are kept on the record, the rest of the simulation's
             own rules end conversations (for comparing the two)
    off      CPL stays out: no CPL fields, the older rules alone (a kill switch)

A world can override the environment: world["cpl_mode"]."""

import os

PROTOCOL_VERSION = "1.0"
MODES = ("off", "shadow", "on")
_ENV = os.getenv("CPL_MODE", "on").lower()
CPL_MODE = _ENV if _ENV in MODES else "on"


def mode(world=None):
    m = (world or {}).get("cpl_mode") if world is not None else None
    return m if m in MODES else CPL_MODE
