# =========================================================
# BUSINESS SUPPORT
# Background job: for every business currently open on its phone line,
# walk its inbox in arrival order and generate a real reply for each
# unread call/voicemail/email -- the "common background process that
# deals with all of these messages in order, for all businesses, during
# their opening hours" the shared-inbox feature exists to feed. Mirrors
# systems/postal_service.py's cadence-gate shape; the actual reply text
# reuses llm/offgrid_narration.py's lightweight-LLM-wrapper pattern via
# llm/business_response.py, bridged synchronously with llm_gate.py's
# run_llm_call() since this runs inside the regular synchronous tick,
# not inside a character's own async agent turn.
# =========================================================

from core.definitions import load_definitions
from llm.llm_gate import run_llm_call
from llm.business_response import generate_business_response
from systems.business_hours import is_open
from systems.inbox import get_business_inbox, get_character_inbox, add_message


def process_business_inboxes(world):
    defs = load_definitions("default")
    company_templates = defs.get("company_templates") or {}
    businesses = world.get("businesses") or {}

    for business_key, state in businesses.items():
        business = company_templates.get(business_key)
        if not business or not is_open(business, world, "phone"):
            continue

        inbox = get_business_inbox(world, business_key)
        for entry in inbox:
            if entry.get("read"):
                continue
            # Only mark read on success -- a failed LLM call leaves the
            # entry unread so the next run picks it back up, rather than
            # silently dropping the inquiry.
            if _respond_to_inquiry(world, business_key, business, state, entry):
                entry["read"] = True


def _respond_to_inquiry(world, business_key, business, state, entry):
    """Returns True if the inquiry was answered (caller found, LLM call
    succeeded), False if it should be retried on the next run."""
    caller_id = entry.get("from")
    caller = world.get("characters", {}).get(caller_id)
    if not caller:
        return True  # character no longer exists -- nothing to reply to, drop it

    session = state.setdefault("_llm_session", {"history": []})
    inquiry = {
        "kind":              entry.get("kind"),
        "reason":            entry.get("metadata", {}).get("reason"),
        "caller_name":       entry.get("metadata", {}).get("caller_name") or caller.get("name"),
        "wants_appointment": entry.get("metadata", {}).get("wants_appointment", False),
    }

    reply = run_llm_call(
        generate_business_response(business, business_key, inquiry, world, session)
    )
    if not reply:
        return False

    tick = world.get("tick", 0)
    add_message(
        get_character_inbox(caller), "call", business_key, caller_id, reply, tick,
        metadata={"reason": inquiry["reason"], "business_name": business.get("name", business_key)},
    )
    return True
