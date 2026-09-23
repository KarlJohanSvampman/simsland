"""
systems/social_projects.py

Social Projects / Activity Plans -- shared undertakings (a dinner, a trip, a
club, a household renovation, a recurring game night, ...) evaluated against
a ChatGPT-authored canonical data model spec the user gave explicitly
because "I would make the canonical project model considerably stricter...
this gives Claude an unambiguous source of truth for implementation."

Built as a genuinely separate system from systems/social_contracts.py and
systems/proposals.py, per the spec's own explicit boundary: "A project is
not itself necessarily a contract, and a contract does not necessarily
require a project. A family curfew is a contract but not a project. A
concert with friends is a project/activity plan, which may contain several
contracts and commitments." A ProjectTask MAY reference a SocialContract
(see assign_task()'s commitment_required path, which calls
social_contracts.create_contract() directly) but a project never becomes
one itself.

CANONICAL ENTITIES BUILT THIS PASS (flat, ID-referenced dicts in world --
per the spec's own section 35 rationale: independent lifecycles, partial
updates, no deep nesting -- exactly the shape systems/social_contracts.py
and systems/proposals.py already use for their own top-level collections):

    world["social_projects"][id]    -- SocialProject
    world["project_participants"][id] -- ProjectParticipant
    world["project_objectives"][id] -- ProjectObjective
    world["project_tasks"][id]      -- ProjectTask
    world["project_proposals"][id]  -- ProjectProposal

KNOWN, DELIBERATE OVERLAP -- NOT RESOLVED THIS PASS: systems/social_events.py
(942 lines, pre-existing) already covers "organize a dinner/party/trip" as a
discoverable, RSVP'd event (draft -> co-organizer approval -> publish,
yes/no/maybe, invites, comments, social-media discovery). Its own category
list is nearly identical to this module's project_type vocabulary. It has
ZERO concept of objectives/tasks/delegation/completion tracking, and this
module has zero concept of RSVP/discovery/comments -- the two are not
duplicates -- but nothing here references social_events.py or vice versa,
so "let's have a dinner party" can be represented through either system
today with no relationship between them. Flagged explicitly (per the
user's own call when this was found) rather than silently linked or
merged -- a real follow-up, not an oversight.

DELIBERATELY DEFERRED, NOT BUILT THIS PASS (honestly named, not faked --
same "confirmed real gap" convention this codebase uses everywhere else):
ActivityPlan / PlannedActivity (the day-by-day "how" sequencing), Scheduled-
SocialActivity (a separate concrete-calendar projection distinct from the
plan), ProjectRecurrence / ProjectOccurrence (recurring projects generating
independent per-instance state), ProjectAttendance (arrival/departure
distinct from participation), ActivityDeviation (explicit plan-vs-reality
diffing). A project can exist, have real objectives/tasks/participants, and
reach real completion without any of those -- they're a genuine second
layer on top of this core, not required to make it useful, and not
pretended to exist here via some flattened substitute.

TASK COMPLETION (spec section 17: "the LLM cannot simply claim 'I bought
the food'; completion requires an actual world event or authoritative
execution result"): a task may set completion_action_type (not itself part
of the spec's own ProjectTask fields, but necessary to satisfy this
invariant without a bespoke per-task-type evaluator) -- a real action_type
string. maybe_complete_tasks_for_action(), called from action_router.py's
central route_action() dispatch point (the same choke point every
dispatched action already passes through for last_action_target), auto-
completes any of the assignee's open tasks whose completion_action_type
matches what they just actually did. A task with no completion_action_type
falls back to the weaker complete_project_task action (self-reported) --
named here as the honest limitation it is, not disguised as equivalent.

NEGOTIATION (spec section 30-31): simplified to plain accept/decline, no
counter-proposal rounds -- systems/proposals.py's chore engine already
covers "negotiate the exact details back and forth" for two-party asks;
reusing that machinery for a project's fundamentally different shape
(N-ary participants, embedded draft objectives/tasks rather than a single
chore_id+params) would mean forcing two genuinely different data shapes
through one engine. A real, if simpler, project proposal is still a
proposal, not a project (a project is never created just because someone
says "we should go camping sometime" -- section 31's own canonical rule).
"""

from uuid import uuid4

SCHEMA_VERSION = "1.0"

PROJECT_DEFAULT_EXPIRES_TICKS = 48 * 3600   # 48 sim-hours to respond, mirrors
                                              # proposals.py's timeout-fallback shape

# Permitted project status transitions (spec section 44). Enforced by
# _transition_project() below -- not just documentation.
_PROJECT_TRANSITIONS = {
    "idea":       {"proposed", "abandoned"},
    "proposed":   {"planning", "rejected", "cancelled"},
    "planning":   {"scheduled", "abandoned", "cancelled"},
    "scheduled":  {"active", "cancelled", "abandoned"},
    "active":     {"paused", "completing", "failed", "cancelled", "abandoned"},
    "paused":     {"active", "cancelled", "abandoned"},
    "completing": {"completed", "failed"},
    # Terminal states (spec section 5) -- no transitions out.
    "completed":  set(),
    "failed":     set(),
    "cancelled":  set(),
    "abandoned":  set(),
    "rejected":   set(),
}

TASK_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


# =========================================================
# PROPOSE
# =========================================================

def propose_project(proposer, world, recipients, project_type, title,
                     description="", proposed_objectives=None, proposed_tasks=None,
                     planned_start_tick=None, planned_end_tick=None,
                     source_type="conversation", source_id=None, importance=0.5,
                     location=None, location_type=None, cost_per_person=0.0,
                     min_age=None, max_age=None, max_attendees=None,
                     popularity=50, tags=None, visible_to=None):
    """
    recipients: list of character dicts (not ids), same convention
    systems/proposals.py::propose() uses.
    proposed_objectives/proposed_tasks: list of draft dicts (title,
    description, required, priority, ...) -- embedded, NOT real
    ProjectObjective/ProjectTask records yet (spec section 30's own
    guidance: don't create authoritative project entities before
    acceptance). Materialized for real by _materialize_project() only
    once the proposal actually resolves with at least one acceptance.

    Dedupes against an already-open identical proposal from this same
    proposer to these same recipients, same reason as proposals.py's own
    dedup (a slow-LLM retry loop re-offering the same decision must not
    mint a fresh proposal every cycle).
    """
    recipient_ids = [r["id"] for r in recipients]
    for existing in world.get("project_proposals", {}).values():
        if (existing.get("status") == "proposed"
                and existing.get("proposer_id") == proposer["id"]
                and existing.get("title") == title
                and set(existing.get("recipient_ids", [])) == set(recipient_ids)):
            return existing

    tick = world.get("tick", 0)
    proposal = {
        "schema_version":         SCHEMA_VERSION,
        "proposal_id":            str(uuid4()),
        "proposer_id":            proposer["id"],
        "recipient_ids":          recipient_ids,
        "responses":              {rid: "pending" for rid in recipient_ids},
        "considering_deadlines":  {},   # rid -> tick, see respond_to_project()'s "considering"
        "project_type":           project_type,
        "title":                  title,
        "description":            description,
        "proposed_objectives":    [dict(o) for o in (proposed_objectives or [])],
        "proposed_tasks":         [dict(t) for t in (proposed_tasks or [])],
        "proposed_start_tick":    planned_start_tick,
        "proposed_end_tick":      planned_end_tick,
        "expires_tick":           tick + PROJECT_DEFAULT_EXPIRES_TICKS,
        "status":                 "proposed",
        "source_conversation_id": None,
        "source_type":            source_type,
        "source_id":              source_id,
        "importance":             max(0.0, min(1.0, importance)),
        "created_tick":           tick,
        "resolved_tick":          None,
        "project_id":             None,   # set once materialized
        # Pragmatic fields beyond the canonical spec's own SocialProject
        # dataclass -- ported from the retired systems/social_events.py,
        # which needed them for real (discovery weighting, affordability,
        # age-gating, venue narration).
        "location":               location,
        "location_type":          location_type,
        "cost_per_person":        max(0.0, cost_per_person),
        "min_age":                min_age,
        "max_age":                max_age,
        "max_attendees":          max_attendees,
        "popularity":             max(0, min(100, popularity)),
        "tags":                   list(tags or []),
        "visible_to":             list(visible_to or []),
    }
    world.setdefault("project_proposals", {})[proposal["proposal_id"]] = proposal

    from brain.cognition_scheduler import wake_character
    for r in recipients:
        wake_character(r, world, "project_proposal_received", {
            "from_name":    proposer.get("name", "someone"),
            "from_id":      proposer["id"],
            "title":        title,
            "project_type": project_type,
            "proposal_id":  proposal["proposal_id"],
        })

    return proposal


# =========================================================
# RESPOND
# =========================================================

CONSIDERING_DEFAULT_DEADLINE_TICKS = 24 * 3600   # 24 sim-hours, mirrors the
                                                   # retired social_events.py's
                                                   # "maybe" nudge shape


def respond_to_project(recipient, world, proposal_id, response, decide_by_tick=None):
    """response: "accepted" | "declined" | "considering" (a real RSVP
    "maybe" -- ported from the retired systems/social_events.py's rsvp()).
    No counter-proposing (see module docstring) -- a recipient who wants
    different terms says so in conversation and the proposer can issue a
    fresh proposal; this isn't the two-party back-and-forth systems/
    proposals.py's chore engine already covers well.

    "considering" keeps the proposal open (same as "pending") rather than
    resolving it, but arms a real deadline nudge (see
    tick_social_projects()) instead of leaving it to linger forever."""
    proposal = world.get("project_proposals", {}).get(proposal_id)
    if not proposal or proposal["status"] != "proposed":
        return {"ok": False, "reason": "no_active_proposal"}

    rid = recipient["id"]
    if rid not in proposal["responses"]:
        return {"ok": False, "reason": "not_a_recipient"}
    if proposal["responses"][rid] not in ("pending", "considering"):
        return {"ok": False, "reason": "already_resolved"}
    if response not in ("accepted", "declined", "considering"):
        return {"ok": False, "reason": "unknown_response"}

    proposal["responses"][rid] = response
    if response == "considering":
        proposal["considering_deadlines"][rid] = decide_by_tick or (
            world.get("tick", 0) + CONSIDERING_DEFAULT_DEADLINE_TICKS
        )
    else:
        proposal["considering_deadlines"].pop(rid, None)
    _maybe_resolve_proposal(proposal, world)
    return {"ok": True, "state": response}


def _maybe_resolve_proposal(proposal, world):
    """Resolves once every recipient has answered accepted/declined (or
    tick_social_projects()'s expiry forces the rest to "declined" -- "
    considering" counts as still-waiting, same as "pending", just with its
    own deadline). Materializes a real project once the proposer plus at
    least one accepting recipient exist -- or immediately for a solo
    project with no recipients at all (e.g. a personal household task)."""
    if proposal["status"] != "proposed":
        return
    if any(v in ("pending", "considering") for v in proposal["responses"].values()):
        return

    tick = world.get("tick", 0)
    accepted_ids = [proposal["proposer_id"]] + [
        rid for rid, resp in proposal["responses"].items() if resp == "accepted"
    ]
    all_accepted = all(v == "accepted" for v in proposal["responses"].values())

    if not proposal["responses"] or any(v == "accepted" for v in proposal["responses"].values()):
        project = _materialize_project(proposal, world, accepted_ids)
        proposal["project_id"] = project["project_id"]
        proposal["status"] = "accepted" if all_accepted else "partially_accepted"
    else:
        proposal["status"] = "rejected"

    proposal["resolved_tick"] = tick


# =========================================================
# MATERIALIZE
# =========================================================

def _materialize_project(proposal, world, accepted_ids):
    """Creates the real SocialProject + ProjectParticipant + ProjectObjective
    + ProjectTask records from the proposal's embedded drafts -- the one
    moment "someone suggested it" becomes "this is a real, authoritative
    shared undertaking" (spec section 31's canonical proposal rule)."""
    tick = world.get("tick", 0)
    pid = f"project_{uuid4().hex[:8]}"

    project = {
        "schema_version":        SCHEMA_VERSION,
        "project_id":            pid,
        "project_type":          proposal["project_type"],
        "status":                "planning",
        "title":                 proposal["title"],
        "description":           proposal["description"],
        "organizer_id":          proposal["proposer_id"],
        "visibility":            "participants",
        "participant_ids":       [],   # filled below via ProjectParticipant records
        "objective_ids":         [],
        "task_ids":              [],
        "activity_plan_id":      None,   # deferred -- see module docstring
        "recurrence_id":         None,   # deferred
        "occurrence_ids":        [],     # deferred
        "contract_ids":          [],
        "scheduled_activity_ids": [],    # deferred
        "deviation_ids":         [],     # deferred
        "source_type":           proposal["source_type"],
        "source_id":             proposal["source_id"],
        "source_conversation_id": proposal.get("source_conversation_id"),
        "parent_project_id":     None,
        "created_by_character_id": proposal["proposer_id"],
        "created_tick":          tick,
        "planned_start_tick":    proposal.get("proposed_start_tick"),
        "planned_end_tick":      proposal.get("proposed_end_tick"),
        "actual_start_tick":     None,
        "actual_end_tick":       None,
        "importance":            proposal.get("importance", 0.5),
        "optional":              False,
        "completion_policy":     "all_required_objectives",  # see _compute_completion_policy()
        "metadata":              {},
        # Pragmatic fields ported from the retired systems/social_events.py
        # -- see propose_project()'s own note on why these exist.
        "location":              proposal.get("location"),
        "location_type":         proposal.get("location_type"),
        "cost_per_person":       proposal.get("cost_per_person", 0.0),
        "min_age":               proposal.get("min_age"),
        "max_age":               proposal.get("max_age"),
        "max_attendees":         proposal.get("max_attendees"),
        "popularity":            proposal.get("popularity", 50),
        "tags":                  list(proposal.get("tags") or []),
        "visible_to":            list(proposal.get("visible_to") or []),
        "comments":              [],
        "invited_ids":           list(proposal.get("recipient_ids") or []),
    }
    world.setdefault("social_projects", {})[pid] = project

    chars = world.get("characters", {})
    for cid in accepted_ids:
        role = "organizer" if cid == proposal["proposer_id"] else "participant"
        part = {
            "schema_version":         SCHEMA_VERSION,
            "participant_id":         f"partic_{uuid4().hex[:8]}",
            "project_id":             pid,
            "character_id":           cid,
            "role":                   role,
            "status":                 "accepted",
            "joined_tick":            tick,
            "status_changed_tick":    tick,
            "optional":               False,
            "consented":              True,
            "responsibilities":       [],
            "task_ids":               [],
            "joined_via":             proposal.get("proposal_id"),
            "invited_by_character_id": proposal["proposer_id"] if cid != proposal["proposer_id"] else None,
            "notes":                  None,
        }
        world.setdefault("project_participants", {})[part["participant_id"]] = part
        project["participant_ids"].append(cid)
        char = chars.get(cid)
        if char is not None:
            char.setdefault("project_ids", []).append(pid)

    for draft in proposal["proposed_objectives"]:
        obj = {
            "schema_version":     SCHEMA_VERSION,
            "objective_id":       f"objective_{uuid4().hex[:8]}",
            "project_id":         pid,
            "title":              draft.get("title", "unnamed objective"),
            "description":        draft.get("description", ""),
            "priority":           max(0.0, draft.get("priority", 0.5)),
            "required":           draft.get("required", True),
            "measurable":         draft.get("measurable", False),
            "completion_condition": draft.get("completion_condition"),
            "progress":           0.0,
            "completed":          False,
            "created_tick":       tick,
            "completed_tick":     None,
        }
        world.setdefault("project_objectives", {})[obj["objective_id"]] = obj
        project["objective_ids"].append(obj["objective_id"])

    for draft in proposal["proposed_tasks"]:
        task = {
            "schema_version":            SCHEMA_VERSION,
            "task_id":                   f"task_{uuid4().hex[:8]}",
            "project_id":                pid,
            "title":                     draft.get("title", "unnamed task"),
            "description":               draft.get("description", ""),
            "task_type":                 draft.get("task_type", "other"),
            "status":                    "unassigned",
            "required":                  draft.get("required", True),
            "priority":                  max(0.0, draft.get("priority", 0.5)),
            "assigned_character_ids":    [],
            "dependency_task_ids":       [],
            "deadline_tick":             draft.get("deadline_tick"),
            "estimated_duration_ticks":  draft.get("estimated_duration_ticks"),
            "completion_condition":      draft.get("completion_condition"),
            "commitment_required":       draft.get("commitment_required", False),
            "social_contract_id":        None,
            # Not a canonical spec field -- see module docstring's Task
            # Completion section for why this exists.
            "completion_action_type":    draft.get("completion_action_type"),
            "created_tick":              tick,
            "assigned_tick":             None,
            "started_tick":              None,
            "completed_tick":            None,
            "failed_tick":               None,
            "cancelled_tick":            None,
        }
        world.setdefault("project_tasks", {})[task["task_id"]] = task
        project["task_ids"].append(task["task_id"])

    from brain.cognition_scheduler import wake_character
    for cid in accepted_ids:
        if cid == proposal["proposer_id"]:
            continue
        char = chars.get(cid)
        if char:
            wake_character(char, world, "project_created", {
                "project_id": pid, "title": project["title"],
                "organizer_name": chars.get(proposal["proposer_id"], {}).get("name", "someone"),
            })

    return project


def create_project_directly(world, organizer, project_type, title, description="",
                             invite_ids=None, proposed_objectives=None, proposed_tasks=None,
                             planned_start_tick=None, planned_end_tick=None,
                             source_type="system", source_id=None, importance=0.5,
                             location=None, location_type=None, cost_per_person=0.0,
                             min_age=None, max_age=None, max_attendees=None,
                             popularity=50, tags=None, visible_to=None):
    """Materializes a project immediately, with only the organizer as an
    accepted participant -- no accept/decline gate. This is the direct
    replacement for the retired systems/social_events.py::
    create_event_draft()'s common case (a single organizer -- its own
    multi-co-organizer draft-approval path had zero real callers anywhere
    in this codebase, confirmed dead, not ported). invite_ids are people
    who'll see it and can RSVP via rsvp_to_project() below -- being
    invited never implies participation, same "consent is not assumed"
    principle propose_project()'s gated flow already follows, just
    resolved differently: here the PROJECT is real from the start (an
    organizer throwing a party doesn't need their guests' permission for
    the party to exist), only participation is."""
    fake_proposal = {
        "proposer_id": organizer["id"], "project_type": project_type, "title": title,
        "description": description, "proposed_objectives": proposed_objectives or [],
        "proposed_tasks": proposed_tasks or [], "proposed_start_tick": planned_start_tick,
        "proposed_end_tick": planned_end_tick, "source_type": source_type, "source_id": source_id,
        "importance": importance, "location": location, "location_type": location_type,
        "cost_per_person": cost_per_person, "min_age": min_age, "max_age": max_age,
        "max_attendees": max_attendees, "popularity": popularity, "tags": tags,
        "visible_to": visible_to, "recipient_ids": list(invite_ids or []),
        "source_conversation_id": None,
    }
    project = _materialize_project(fake_proposal, world, [organizer["id"]])

    from brain.cognition_scheduler import wake_character
    chars = world.get("characters", {})
    for cid in (invite_ids or []):
        char = chars.get(cid)
        if char:
            wake_character(char, world, "project_invited", {
                "project_id": project["project_id"], "title": project["title"],
                "organizer_name": organizer.get("name", "someone"),
            })

    return project


def rsvp_to_project(recipient, world, project_id, response, decide_by_tick=None):
    """RSVP to an ALREADY-REAL project (one created via propose_project's
    gated flow once resolved, or create_project_directly) -- direct
    ProjectParticipant status, no proposal to resolve. response:
    "accepted" | "declined" | "considering" (mirrors respond_to_project's
    same three-way shape, ported from systems/social_events.py::rsvp())."""
    if response not in ("accepted", "declined", "considering"):
        return {"ok": False, "reason": "unknown_response"}
    project = world.get("social_projects", {}).get(project_id)
    if not project:
        return {"ok": False, "reason": "no_such_project"}

    tick = world.get("tick", 0)
    part = _find_participant(world, project_id, recipient["id"])
    if part is None:
        part = {
            "schema_version":         SCHEMA_VERSION,
            "participant_id":         f"partic_{uuid4().hex[:8]}",
            "project_id":             project_id,
            "character_id":           recipient["id"],
            "role":                   "guest",
            "status":                 "invited",
            "joined_tick":            tick,
            "status_changed_tick":    tick,
            "optional":               True,
            "consented":              False,
            "responsibilities":       [],
            "task_ids":               [],
            "joined_via":             None,
            "invited_by_character_id": project.get("organizer_id"),
            "notes":                  None,
            "considering_deadline_tick": None,
        }
        world.setdefault("project_participants", {})[part["participant_id"]] = part

    part["status"] = response
    part["status_changed_tick"] = tick
    part["consented"] = response == "accepted"
    part["considering_deadline_tick"] = (
        (decide_by_tick or tick + CONSIDERING_DEFAULT_DEADLINE_TICKS)
        if response == "considering" else None
    )

    if response == "accepted" and recipient["id"] not in project["participant_ids"]:
        project["participant_ids"].append(recipient["id"])
        chars = world.get("characters", {})
        char = chars.get(recipient["id"])
        if char is not None and project_id not in char.get("project_ids", []):
            char.setdefault("project_ids", []).append(project_id)
    elif response == "declined" and recipient["id"] in project["participant_ids"]:
        project["participant_ids"].remove(recipient["id"])

    return {"ok": True, "state": response}


# =========================================================
# TASK ASSIGNMENT / COMPLETION
# =========================================================

def assign_task(world, task_id, character_id, commitment_required=None):
    """Assignment and commitment are separate (spec section 15): being
    assigned makes a character operationally responsible; only when
    commitment_required is true does this also create a real
    SocialContract (systems/social_contracts.py -- "manual" check_type,
    since there's no existing automatic-violation shape for "do this
    project task," just tracked/negotiated like any other manual
    commitment), whose id is stored on the task."""
    task = world.get("project_tasks", {}).get(task_id)
    if not task or task["status"] in TASK_TERMINAL_STATUSES:
        return None

    tick = world.get("tick", 0)
    if character_id not in task["assigned_character_ids"]:
        task["assigned_character_ids"].append(character_id)
    task["status"] = "assigned"
    task["assigned_tick"] = tick

    part = _find_participant(world, task["project_id"], character_id)
    if part and task_id not in part["task_ids"]:
        part["task_ids"].append(task_id)

    if commitment_required is not None:
        task["commitment_required"] = commitment_required

    if task["commitment_required"] and not task["social_contract_id"]:
        project = world.get("social_projects", {}).get(task["project_id"])
        organizer_id = project.get("organizer_id") if project else None
        if organizer_id and organizer_id != character_id:
            from systems.social_contracts import create_contract
            contract = create_contract(
                [organizer_id, character_id],
                [{
                    "party":      character_id,
                    "commitment": task["title"],
                    "check_type": "manual",
                    "params":     {},
                }],
                world,
            )
            task["social_contract_id"] = contract["id"]
            project.setdefault("contract_ids", []).append(contract["id"])

    return task


def maybe_complete_tasks_for_action(c, world, action_type):
    """Called from action_router.py's route_action() dispatch point (the
    same central choke point last_action_target already goes through) for
    EVERY dispatched action, regardless of type -- completes any of this
    character's open, assigned tasks whose completion_action_type matches
    what they just actually did. Cheap: this sim's scale is a handful of
    characters and open tasks, not thousands -- a full scan per dispatch
    is fine, no index needed."""
    for task in world.get("project_tasks", {}).values():
        if task["status"] in TASK_TERMINAL_STATUSES:
            continue
        if task.get("completion_action_type") != action_type:
            continue
        if c["id"] not in task.get("assigned_character_ids", []):
            continue
        complete_task(world, task["task_id"])


def complete_task(world, task_id):
    """The one real completion path (spec section 17) -- either reached
    via maybe_complete_tasks_for_action() above (real evidence: the
    assignee actually performed the matching action) or directly from
    _route_complete_project_task() for a task with no completion_action_type
    mapped (the weaker, self-reported fallback -- see module docstring)."""
    task = world.get("project_tasks", {}).get(task_id)
    if not task or task["status"] in TASK_TERMINAL_STATUSES:
        return False

    task["status"] = "completed"
    task["completed_tick"] = world.get("tick", 0)

    project = world.get("social_projects", {}).get(task["project_id"])
    if project:
        _maybe_advance_project_status(project, world)

    return True


# =========================================================
# OBJECTIVES / PROGRESS
# =========================================================

def complete_objective(world, objective_id, completed=True):
    obj = world.get("project_objectives", {}).get(objective_id)
    if not obj:
        return False
    obj["completed"] = completed
    obj["progress"] = 1.0 if completed else obj["progress"]
    obj["completed_tick"] = world.get("tick", 0) if completed else None
    project = world.get("social_projects", {}).get(obj["project_id"])
    if project:
        _maybe_advance_project_status(project, world)
    return True


def compute_project_progress(world, project_id):
    """Derived, not stored (spec section 37) -- computed fresh every call
    from real objective/task completion, weighted per the spec's own
    example split (40/35/25 objectives/tasks/activities), with the
    activities term dropped entirely (not double-counted as 0) since
    PlannedActivity isn't built this pass -- objective/task weights
    renormalized to fill that share instead of quietly under-reporting
    progress for every project."""
    objective_ids = []
    task_ids = []
    project = world.get("social_projects", {}).get(project_id)
    if project:
        objective_ids = project.get("objective_ids", [])
        task_ids = project.get("task_ids", [])

    objectives = [world["project_objectives"][oid] for oid in objective_ids
                  if oid in world.get("project_objectives", {})]
    tasks = [world["project_tasks"][tid] for tid in task_ids
             if tid in world.get("project_tasks", {})]

    req_objectives = [o for o in objectives if o.get("required", True)]
    req_tasks = [t for t in tasks if t.get("required", True)]

    objective_progress = (
        sum(1.0 if o["completed"] else o.get("progress", 0.0) for o in objectives) / len(objectives)
        if objectives else 1.0
    )
    task_progress = (
        sum(1.0 if t["status"] == "completed" else 0.0 for t in tasks) / len(tasks)
        if tasks else 1.0
    )
    overall = objective_progress * (0.40 / 0.75) + task_progress * (0.35 / 0.75)

    return {
        "objective_progress":          objective_progress,
        "task_progress":               task_progress,
        "overall_progress":            max(0.0, min(1.0, overall)),
        "required_objectives_complete": all(o["completed"] for o in req_objectives),
        "required_tasks_complete":     all(t["status"] == "completed" for t in req_tasks),
    }


# =========================================================
# STATUS TRANSITIONS
# =========================================================

def _transition_project(project, new_status, world):
    """Enforces the permitted-transitions table (spec section 44) rather
    than allowing an arbitrary status write -- a caller asking for an
    invalid transition is silently refused (returns False), same
    "unresolved reason, not a crash" shape as everything else in this
    codebase that validates a requested state change."""
    current = project["status"]
    if new_status == current:
        return True
    if new_status not in _PROJECT_TRANSITIONS.get(current, set()):
        return False
    project["status"] = new_status
    return True


def _maybe_advance_project_status(project, world):
    """Auto-advances ACTIVE -> COMPLETING -> COMPLETED once the project's
    completion_policy is satisfied. Only ever moves FORWARD automatically;
    PAUSED/CANCELLED/FAILED/ABANDONED always need a deliberate call (no
    plausible automatic signal for any of those from task/objective
    completion alone)."""
    if project["status"] not in ("active", "completing"):
        return

    progress = compute_project_progress(world, project["project_id"])
    policy = project.get("completion_policy", "all_required_objectives")

    satisfied = (
        progress["required_objectives_complete"] if policy == "all_required_objectives" else
        progress["required_tasks_complete"] if policy == "all_required_tasks" else
        False   # "manual"/"final_activity"/"occurrence_complete" all need an explicit close-out
    )

    if satisfied:
        if project["status"] == "active":
            _transition_project(project, "completing", world)
        _transition_project(project, "completed", world)
        project["actual_end_tick"] = world.get("tick", 0)


def withdraw_from_project(world, character_id, project_id):
    """Project participation is not permanent commitment (spec invariant
    #7) -- a real, always-available way out, distinct from being REMOVED
    by the organizer."""
    part = _find_participant(world, project_id, character_id)
    if not part:
        return False
    part["status"] = "withdrawn"
    part["status_changed_tick"] = world.get("tick", 0)
    project = world.get("social_projects", {}).get(project_id)
    if project and character_id in project.get("participant_ids", []):
        project["participant_ids"].remove(character_id)
    return True


# =========================================================
# CADENCE SWEEP
# =========================================================

def tick_social_projects(world):
    """Called on a moderate cadence (see core/tick_schedule.py's CADENCE
    ["social_projects"], sim_loop.py). Two jobs: (1) force-resolve any
    proposal past its expires_tick, defaulting every still-pending
    recipient to "declined" -- same "timeout fallback is decline, never
    auto-accept" principle systems/proposals.py already follows; (2)
    ACTIVE-transition any SCHEDULED project whose planned_start_tick has
    arrived."""
    tick = world.get("tick", 0)

    chars = world.get("characters", {})

    for proposal in world.get("project_proposals", {}).values():
        if proposal["status"] != "proposed":
            continue

        # "considering" past its own individual deadline gets nudged once
        # (ported from social_events.py::check_maybe_deadlines' shape),
        # separately from the whole proposal's overall expiry below.
        for rid, deadline in list(proposal["considering_deadlines"].items()):
            if tick < deadline:
                continue
            char = chars.get(rid)
            if char:
                char.setdefault("notifications", []).append({
                    "type": "project_decide_now", "proposal_id": proposal["proposal_id"],
                    "title": proposal["title"], "tick": tick,
                })
            proposal["responses"][rid] = "declined"
            del proposal["considering_deadlines"][rid]

        if tick < proposal["expires_tick"]:
            continue
        for rid, resp in proposal["responses"].items():
            if resp in ("pending", "considering"):
                proposal["responses"][rid] = "declined"
        proposal["considering_deadlines"].clear()
        _maybe_resolve_proposal(proposal, world)
        if proposal["status"] == "proposed":
            proposal["status"] = "expired"
            proposal["resolved_tick"] = tick

    for part in world.get("project_participants", {}).values():
        deadline = part.get("considering_deadline_tick")
        if deadline is not None and tick >= deadline:
            char = chars.get(part["character_id"])
            if char:
                char.setdefault("notifications", []).append({
                    "type": "project_decide_now", "project_id": part["project_id"], "tick": tick,
                })
            part["status"] = "declined"
            part["status_changed_tick"] = tick
            part["considering_deadline_tick"] = None

    for project in world.get("social_projects", {}).values():
        if project["status"] == "scheduled" and project.get("planned_start_tick") is not None:
            if tick >= project["planned_start_tick"]:
                if _transition_project(project, "active", world):
                    project["actual_start_tick"] = tick
        elif project["status"] == "planning" and project.get("planned_start_tick") is not None:
            _transition_project(project, "scheduled", world)


# =========================================================
# DISCOVERY (ported from the retired systems/social_events.py::
# maybe_discover_events -- tick-based instead of unix-timestamp-based)
# =========================================================

_DISCOVERY_CHANCE = 0.25   # per social-media session

_PROJECT_TEMPLATES = [
    # (project_type, titles, tags, location_type, cost_range, duration_hours,
    #  description, min_age, max_age, popularity_range)
    ("party",
     ["House Party", "Birthday Bash", "Block Party", "Garden Party"],
     ["social", "alcohol", "music"], "home", (0, 20), 4,
     "A casual gathering with drinks, music and good company.", 18, None, (30, 70)),
    ("dinner",
     ["Dinner Night", "Potluck Dinner", "BBQ Night", "Wine & Dine"],
     ["food", "wine", "social"], "home", (0, 40), 3,
     "An intimate dinner get-together. Bring your appetite.", None, None, (20, 60)),
    ("group_date",
     ["Live Music Night", "Open Mic", "Jazz Evening", "DJ Set"],
     ["music", "nightlife"], "venue", (10, 80), 3,
     "Live performances from local and visiting artists.", 18, None, (40, 90)),
    ("sports_activity",
     ["Football Match", "Tennis Doubles", "Running Club", "Pickup Basketball"],
     ["sports", "fitness", "outdoor"], "outdoor", (0, 15), 2,
     "Friendly match -- all skill levels welcome.", None, None, (20, 55)),
    ("meeting",
     ["Neighbourhood Meetup", "Book Club", "Tech Talk", "Startup Night"],
     ["networking", "community"], "venue", (0, 25), 2,
     "Connect with like-minded people in the area.", None, None, (10, 40)),
    ("community_event",
     ["Street Food Festival", "Craft Beer Fest", "Art Market", "Film Screening"],
     ["culture", "outdoor", "food"], "outdoor", (0, 30), 6,
     "A public event celebrating local culture and community.", None, None, (50, 95)),
    ("outing",
     ["Gallery Opening", "Photography Show", "Art Exhibition"],
     ["art", "culture"], "venue", (0, 20), 3,
     "Opening night for a new collection. Free drinks on arrival.", None, None, (20, 60)),
    ("trip",
     ["Day Trip", "Hiking Excursion", "Beach Day", "Road Trip"],
     ["outdoor", "adventure", "travel"], "outdoor", (10, 60), 8,
     "A group outing -- meet at the departure point.", None, None, (25, 65)),
]
MAX_WORLD_PROJECTS = 12   # never generate more than this many discoverable world-authored projects at once


def generate_world_projects(world):
    """Called once at world generation (world/generate_world.py) so there
    are always some publicly-discoverable, NPC-organized projects for a
    character to stumble into -- ported from the retired systems/
    social_events.py::generate_world_events (its own docstring claimed
    "called periodically," but confirmed it was actually only ever
    invoked once, at genesis -- not repeated here either, since nothing
    else in this codebase re-seeds discoverable content periodically)."""
    import random

    chars = world.get("characters", {})
    if not chars:
        return
    existing = sum(
        1 for p in world.get("social_projects", {}).values()
        if p.get("source_type") == "system" and p["status"] not in
        ("completed", "failed", "cancelled", "abandoned", "rejected")
    )
    to_create = max(0, MAX_WORLD_PROJECTS - existing)
    char_ids = list(chars.keys())
    tick = world.get("tick", 0)

    for _ in range(to_create):
        weights = [t[9][1] for t in _PROJECT_TEMPLATES]
        (ptype, titles, tags, loc_type, cost_range, dur_h, desc,
         min_age, max_age, pop_range) = random.choices(_PROJECT_TEMPLATES, weights=weights, k=1)[0]

        organizer_id = random.choice(char_ids)
        organizer = chars[organizer_id]
        title = random.choice(titles)
        start_tick = tick + random.randint(3600 * 24, 3600 * 24 * 14)   # 1-14 days out

        cost = round(random.uniform(*cost_range), 2) if cost_range[1] > 0 else 0.0
        if random.random() < 0.3:   # ~30% chance of free even for a paid template
            cost = 0.0

        create_project_directly(
            world, organizer, ptype, title, description=desc,
            planned_start_tick=start_tick, planned_end_tick=start_tick + int(dur_h * 3600),
            source_type="system", cost_per_person=cost, min_age=min_age, max_age=max_age,
            max_attendees=random.choice([None, 10, 20, 30, 50, 100]),
            popularity=random.randint(*pop_range), tags=tags + [ptype],
            location="online" if loc_type == "online" else f"Near {organizer.get('name', 'someone')}'s area",
            location_type=loc_type, visible_to=[],   # public
        )


def discover_projects(c, world, channel="social_media"):
    """Called during social media browsing or phone scrolling. Small
    chance of surfacing a real, existing public project from the
    character's network. Returns the list of project summaries shown --
    same shape/purpose as the retired social_events.py's own function,
    now weighted/filtered on real project fields (popularity, min/max
    age, planned_start_tick vs. current tick) instead of unix timestamps."""
    import random

    if random.random() > _DISCOVERY_CHANCE:
        return []

    tick = world.get("tick", 0)
    c_age = c.get("age")
    visible = [
        p for p in world.get("social_projects", {}).values()
        if p["status"] in ("planning", "scheduled", "active")
        and c["id"] not in (p.get("invited_ids") or [])
        and c["id"] not in p.get("participant_ids", [])
        and (not p.get("visible_to") or c["id"] in p["visible_to"])
        and (p.get("planned_start_tick") is None or p["planned_start_tick"] > tick)
        and (c_age is None or p.get("min_age") is None or c_age >= p["min_age"])
        and (c_age is None or p.get("max_age") is None or c_age <= p["max_age"])
    ]
    if not visible:
        return []

    weights = [p.get("popularity", 50) for p in visible]
    k = min(3, len(visible))
    shown = random.choices(visible, weights=weights, k=k)
    seen_ids = set()
    shown = [p for p in shown if not (p["project_id"] in seen_ids or seen_ids.add(p["project_id"]))]

    for p in shown:
        if c["id"] not in (p.get("invited_ids") or []):
            p.setdefault("invited_ids", []).append(c["id"])
        c.setdefault("notifications", []).append({
            "type": "project_discovered", "project_id": p["project_id"],
            "channel": channel, "tick": tick, "title": p.get("title"),
        })

    return [{"project_id": p["project_id"], "title": p.get("title"),
             "project_type": p.get("project_type"), "description": p.get("description")}
            for p in shown]


# =========================================================
# COMMENTS
# =========================================================

def add_project_comment(world, project_id, character_id, text):
    project = world.get("social_projects", {}).get(project_id)
    if not project or not text:
        return None
    comment = {"character_id": character_id, "text": text, "tick": world.get("tick", 0),
               "likes": [], "dislikes": []}
    project.setdefault("comments", []).append(comment)
    return comment


def react_project_comment(world, project_id, character_id, comment_index, reaction):
    project = world.get("social_projects", {}).get(project_id)
    if not project:
        return False
    comments = project.get("comments", [])
    if not (0 <= comment_index < len(comments)):
        return False
    comment = comments[comment_index]
    if reaction == "like" and character_id not in comment["likes"]:
        comment["likes"].append(character_id)
        comment["dislikes"] = [cid for cid in comment["dislikes"] if cid != character_id]
    elif reaction == "dislike" and character_id not in comment["dislikes"]:
        comment["dislikes"].append(character_id)
        comment["likes"] = [cid for cid in comment["likes"] if cid != character_id]
    return True


# =========================================================
# ATTENDANCE (real off-grid execution -- ported from the retired
# systems/social_events.py::_route_social_event_attend in action_router.py,
# fixing a confirmed real bug along the way: that code computed a
# duration in TICKS but passed it to send_offgrid()'s duration_minutes
# parameter -- a 1-hour project would have sent the character off-grid
# for 60 hours)
# =========================================================

_HARD_CONFLICT_CATEGORIES = {"survival", "health"}


def _hard_conflict(c, world):
    """The one-sided case worth auto-declining without a real LLM turn --
    a due/overdue survival- or health-category expectation the project
    would clash with. Affordability is checked separately, in
    attend_project() below, since it needs the project's own cost.
    Returns the conflicting expectation's label, or None."""
    defs = world.get("definitions", {})
    templates = defs.get("expectation_templates", {})
    for eid, nd in c.get("expectations", {}).items():
        if nd.get("category") in _HARD_CONFLICT_CATEGORIES and nd.get("status") in ("pending", "missed"):
            return templates.get(eid, {}).get("label", eid)
    return None


def attend_project(c, world, project_id):
    """Character actually goes and attends -- sends them off-grid for the
    project's real planned duration (reason "event:<project_id>", same
    prefix systems/offgrid.py::send_offgrid/_TRAVEL_ELIGIBLE_REASONS and
    _social_event_details already special-case, now reading this module's
    projects instead of the retired social_events.py's events)."""
    project = world.get("social_projects", {}).get(project_id)
    if not project or project["status"] not in ("scheduled", "active"):
        return {"ok": False, "reason": "not_attendable"}

    conflict = _hard_conflict(c, world)
    if conflict:
        c.setdefault("notifications", []).append({
            "type": "project_conflict_declined", "project_id": project_id,
            "conflict": conflict, "tick": world.get("tick", 0),
        })
        return {"ok": False, "reason": "hard_conflict", "conflict": conflict}

    cost = project.get("cost_per_person", 0.0)
    if cost > 0:
        wallet_found = False
        for item in c.get("inventory", []):
            if item.get("object_type") == "wallet":
                cash = item.get("cash", 0.0)
                if cash < cost:
                    c.setdefault("notifications", []).append({
                        "type": "project_cant_afford", "project_id": project_id,
                        "title": project.get("title"), "cost": cost, "tick": world.get("tick", 0),
                    })
                    return {"ok": False, "reason": "cant_afford"}
                item["cash"] = round(cash - cost, 2)
                wallet_found = True
                break
        if not wallet_found:
            return {"ok": False, "reason": "no_wallet"}

    rsvp_to_project(c, world, project_id, "accepted")

    tick = world.get("tick", 0)
    end_tick = project.get("planned_end_tick") or (tick + 3 * 3600)
    from core.tick_schedule import TICK_RATE_SECONDS
    duration_minutes = max(1, int((end_tick - tick) * TICK_RATE_SECONDS / 60))

    from systems.offgrid import send_offgrid
    sent = send_offgrid(c, world, f"event:{project_id}", duration_minutes)
    if sent:
        part = _find_participant(world, project_id, c["id"])
        if part:
            part["status"] = "attending"
    return {"ok": bool(sent)}


# =========================================================
# QUERIES
# =========================================================

def _find_participant(world, project_id, character_id):
    for part in world.get("project_participants", {}).values():
        if part["project_id"] == project_id and part["character_id"] == character_id:
            return part
    return None


def get_projects_for_character(world, character_id):
    chars = world.get("characters", {})
    char = chars.get(character_id)
    ids = char.get("project_ids", []) if char else []
    return [world["social_projects"][pid] for pid in ids if pid in world.get("social_projects", {})]


def get_open_tasks_for_character(world, character_id):
    return [
        t for t in world.get("project_tasks", {}).values()
        if character_id in t.get("assigned_character_ids", [])
        and t["status"] not in TASK_TERMINAL_STATUSES
    ]


def get_pending_project_proposals_for_character(world, character_id):
    return [
        p for p in world.get("project_proposals", {}).values()
        if p["status"] == "proposed" and p.get("responses", {}).get(character_id) == "pending"
    ]
