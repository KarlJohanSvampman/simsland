"""
Trigger evaluation.

`match` only reads; nothing is remembered until the registry actually SELECTS a
situation and calls `commit`. A situation that was eligible but outranked (or
had too few resolvable options) therefore stays eligible next time instead of
being silently used up.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from .definition import SituationContext, SituationDefinition, Trigger

_COND = re.compile(r"^\s*([\w.]+)\s*(>=|<=|==|!=|>|<)\s*(.+?)\s*$")
_OPS = {
    ">=": lambda a, b: a >= b, "<=": lambda a, b: a <= b, "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b, ">": lambda a, b: a > b, "<": lambda a, b: a < b,
}
IDLE_WAKES = (None, "idle")
URGENT_INTENTION_PRIORITY = 60   # an idle moment only exists when nothing pressing is queued


def _literal(text: str) -> Any:
    t = text.strip()
    if t.lower() in ("true", "false"):
        return t.lower() == "true"
    if len(t) >= 2 and t[0] == t[-1] and t[0] in "'\"":
        return t[1:-1]
    try:
        return float(t)
    except ValueError:
        return t


def eval_condition(expr: str, ctx: SituationContext) -> bool:
    """`path op literal`, joined by `&&`. e.g. "character.needs.body.hunger >= 60"."""
    for part in expr.split("&&"):
        m = _COND.match(part)
        if not m:
            raise ValueError(f"unsupported condition: {part!r}")
        path, op, raw = m.groups()
        left = ctx.get(path)
        if left is None:
            return False
        try:
            if not _OPS[op](left, _literal(raw)):
                return False
        except TypeError:
            return False
    return True


class TriggerEvaluator:
    @staticmethod
    def _ckey(sit: SituationDefinition, trig: Trigger, ctx: SituationContext) -> str:
        return f"{sit.id}:{trig.key(ctx) if trig.key else ''}"

    def _cooling(self, sit: SituationDefinition, trig: Trigger, ctx: SituationContext) -> bool:
        last = ctx.state.setdefault("cooldown", {}).get(self._ckey(sit, trig, ctx))
        return last is not None and ctx.tick - last < sit.cooldown_ticks

    @staticmethod
    def _idle(ctx: SituationContext) -> bool:
        if ctx.wake_reason not in IDLE_WAKES:
            return False
        top = max((i.get("priority") or 0 for i in ctx.res.get("character.intentions") or []), default=0)
        return top < URGENT_INTENTION_PRIORITY

    def _fires(self, sit: SituationDefinition, trig: Trigger, ctx: SituationContext) -> bool:
        if trig.type == "event":
            ok = ctx.wake_reason == trig.event
        elif trig.type == "idle":
            ok = self._idle(ctx)
        elif trig.type == "condition":
            ok = eval_condition(trig.condition or "", ctx)
        elif trig.type == "threshold_crossed":
            cur = ctx.get(trig.field or "")
            armed = ctx.state.setdefault("crossed", {})
            akey = f"{sit.id}:{trig.field}"
            if cur is None:
                return False
            if cur < (trig.threshold or 0):
                armed.pop(akey, None)          # dropped back below: re-arm
                return False
            ok = akey not in armed
        elif trig.type == "custom":
            ok = True
        else:
            raise ValueError(f"unknown trigger type: {trig.type}")
        if ok and trig.when is not None:
            ok = bool(trig.when(ctx))
        return ok and not self._cooling(sit, trig, ctx)

    def match(self, sit: SituationDefinition, ctx: SituationContext) -> Optional[Trigger]:
        for trig in sit.triggers:
            if self._fires(sit, trig, ctx):
                return trig
        return None

    def commit(self, sit: SituationDefinition, trig: Trigger, ctx: SituationContext) -> None:
        ctx.state.setdefault("cooldown", {})[self._ckey(sit, trig, ctx)] = ctx.tick
        if trig.type == "threshold_crossed":
            ctx.state.setdefault("crossed", {})[f"{sit.id}:{trig.field}"] = ctx.tick
