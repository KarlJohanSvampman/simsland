"""
systems/duties.py -- what each DUTY job in core/flow.py checks to know whether it has work (cheap, world-level), and the
one-off timers for things that are due at a known moment (a delivery arriving).

A duty runs on its old cadence only while its check is true; whatever starts its work calls
core.flow.wake_duty(world, name). See core/flow.py::DUTY.
"""


def grapples_active(world):
    return bool(world.get("grapples"))


def scripted_active(world):
    return bool(world.get("scripted_conversations"))


def household_processes_active(world):
    return bool(world.get("household_processes"))


def messages_active(world):
    return bool(world.get("message_queue"))


def rideshare_active(world):
    return bool(world.get("rideshare_vehicles"))


def service_vehicles_active(world):
    return bool(world.get("service_vehicles"))


def intercourse_active(world):
    return any(not s.get("ended") for s in (world.get("intercourse_sessions") or {}).values())


def convtags_active(world):
    return bool(world.get("_conv_tag_queue"))


def fires_active(world):
    return any(i.get("type") == "fire" and not i.get("extinguished") and not i.get("resolved")
               for i in world.get("incidents") or [])


def _on_incident(data, world):
    from core.flow import wake_duty
    wake_duty(world, "fires")


# ── deliveries: each arrives at a known tick ─────────────────────────────────────────────────────────────────────────

def arm_delivery(world, delivery):
    """A timer for the moment this delivery arrives (systems/deliveries.py::update_deliveries handles it then)."""
    from core import scheduler
    if delivery.get("status") == "in_transit" and delivery.get("arrival_tick") is not None:
        scheduler.schedule(world, "delivery", str(delivery.get("id") or id(delivery)), delivery["arrival_tick"])


def _on_delivery_timer(world, entry):
    from systems.deliveries import update_deliveries
    update_deliveries(world)


def on_world_loaded(world, entry=None):
    """A loaded world: every duty with work is armed, every delivery in transit is timed."""
    from core.flow import check_duties
    check_duties(world, {"event": "world.loaded"})
    for d in world.get("deliveries") or []:
        arm_delivery(world, d)
    # games planned before kickoff had timers: each upcoming fixture with attendees gets one
    from core import scheduler
    tick = world.get("tick", 0)
    for sport, leagues in (world.get("sports_leagues") or {}).items():
        for scope, league in (leagues or {}).items():
            for fx in (league or {}).get("schedule") or []:
                if fx.get("attendees") and fx.get("scheduled_tick", -1) >= tick:
                    scheduler.schedule(world, "kickoff", f"{sport}:{scope}:{fx.get('id', fx['scheduled_tick'])}",
                                       fx["scheduled_tick"])


def _register():
    from core.event_bus import subscribe
    from core import scheduler
    subscribe("incident_created", _on_incident)
    scheduler.register("delivery", _on_delivery_timer)


_register()
