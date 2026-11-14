"""cpl/config.py -- CPL_MODE (docs/cpl_implementation_plan.md section 11).

    off      today's conversation code only (the default until each phase is proven)
    shadow   CPL runs alongside: it builds its conversations from what happens, changes nothing outside its own
             entities, and its state can be compared with the legacy one
    on       CPL owns the conversation lifecycle

A world can override the environment: world["cpl_mode"]."""

import os

PROTOCOL_VERSION = "1.0"
MODES = ("off", "shadow", "on")
_ENV = os.getenv("CPL_MODE", "off").lower()
CPL_MODE = _ENV if _ENV in MODES else "off"


def mode(world=None):
    m = (world or {}).get("cpl_mode") if world is not None else None
    return m if m in MODES else CPL_MODE
