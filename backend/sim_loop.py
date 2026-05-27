import time
from datetime import datetime

from systems.jobs import generate_job_listings, maybe_fire, apply_for_job, process_interview
from brain.agent_loop import maybe_go_offgrid, process_return
from systems.economy import apply_expenses
from systems.market import update_market, produce, consume_households
from systems.events import maybe_generate_shared_event
from systems.emergency import trigger_incident, auto_report_incidents, dispatch, resolve
from systems.law import maybe_arrest_from_incidents, process_trials, process_jail
from systems.health import trigger_health_event, process_health
from systems.politics import process_pending_effects, check_election
from systems.influence import apply_public_figure_influence, apply_social_influence
from systems.media import generate_news
from systems.migration import consider_migration
from systems.story import update_story_arc
from systems.hierarchy import update_hierarchy
from systems.crisis import check_crises, process_crises
from systems.faction_ai import apply_faction_influence
from systems.traffic import (
    update_ambient_traffic
)
from systems.deliveries import (
    update_deliveries
)

from systems.postal_service import (
    update_postal_service
)

from systems.service_vehicles import (
    update_service_vehicles
)
from systems.household_monitoring import (
    update_household_monitoring
)
from systems.appliance_degradation import (
    update_appliance_degradation
)
from brain.memory import decay_memories
from brain.beliefs import polarization_drift, compute_alignment
from brain.relationships import first_impression, update_relationship_state
from systems.scheduling import generate_week_schedule,adjust_for_household
from systems.messaging import deliver_messages
from systems.service_worker_runtime import (
    update_service_workers
)
from brain.perception import perceive
# =========================
# 🕒 REAL-TIME CALENDAR
# =========================
def advance_calendar(world):
    now = datetime.now()

    world["calendar"] = {
        "year": now.year,
        "month": now.month,
        "day": now.day,
        "hour": now.hour,
        "minute": now.minute,
        "second": now.second,
        "weekday": now.strftime("%A"),
        "timestamp": time.time()
    }


# =========================
# 🔁 MAIN TICK
# =========================
def tick(world):
    world["tick"] += 1

    advance_calendar(world)

    if world["calendar"]["weekday"] == "Monday" and world["calendar"]["hour"] == 0:
        for c in world["characters"].values():
            c["schedule"] = generate_week_schedule(c, world)
            adjust_for_household(c, world)

    for c in world["characters"].values():

        perceive(
            c,
            world
        )
    deliver_messages(world)
    generate_job_listings(world)
    update_household_monitoring(world)
    process_pending_effects(world)
    update_service_workers(world)
    update_market(world)
    produce(world)
    consume_households(world)
    update_ambient_traffic(world)
    maybe_generate_shared_event(world)
    generate_news(world)

    check_crises(world)
    process_crises(world)
    check_election(world)
    apply_faction_influence(world)
    update_appliance_degradation(world)
    update_deliveries(world)
    update_postal_service(world)
    update_service_vehicles(world)
    for c in list(world["characters"].values()):
        decay_memories(c)
        polarization_drift(c)
        compute_alignment(c)

        maybe_fire(c, world)
        apply_for_job(c, world)
        process_interview(c, world)

        maybe_go_offgrid(c, world)
        process_return(c, world)

        trigger_incident(world, c)
        trigger_health_event(c, world)
        process_health(c, world)

        process_jail(c, world)
        process_evictions(world)

        process_migration(world)
        update_story_arc(c)

        for o in world["characters"].values():
            if o["id"] != c["id"]:
                first_impression(c, o)
                update_relationship_state(c, o)

    auto_report_incidents(world)
    dispatch(world)
    resolve(world)

    maybe_arrest_from_incidents(world)
    process_trials(world)

    apply_public_figure_influence(world)
    apply_social_influence(world)
    update_hierarchy(world)

    apply_expenses(world)