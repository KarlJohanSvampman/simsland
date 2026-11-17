"""
cpl/adapters/contracts.py -- an accepted request becomes a social contract (docs/cpl_implementation_plan.md C7,
decided: commitments ARE contracts).

On `cpl.commitment_created` (cpl/turns.py: a request answered accept, or conditional): a one-term contract between
the two (social/contracts.py::create) -- the recipient is responsible for what was asked, under the conditions they
named. The agreement reaches both of their prompts the way every contract does (brain/context_builder.py's
contracts section); completion and violation stay with contracts and the systems that already check terms. The request records the contract it became (request["contract_id"]): delivered
twice, the commitment makes one contract.
"""

from core.event_bus import subscribe


def _on_commitment(data, world):
    if world is None:
        return
    req = (world.get("cpl_requests") or {}).get((data.get("request") or {}).get("id"))
    if req is None or req.get("contract_id"):
        return
    from social import contracts as K
    responsible, requester = req.get("recipient_id"), req.get("requester_id")
    if not responsible or not requester:
        return
    conds = list(req.get("conditions") or [])
    last = (req.get("history") or [{}])[-1]
    if last.get("condition"):
        conds.append(last["condition"])
    k = K.create(world, [requester, responsible],
                 [{"responsible_party": responsible, "obligation": req.get("action") or "what was asked",
                   "deadline": req.get("deadline"), "conditions": conds}],
                 title=(req.get("action") or "an agreement")[:80], created_by=requester,
                 conversation_id=data.get("conversation_id"),
                 description=f"agreed in conversation ({data.get('commitment_id')})")
    req["contract_id"] = k["id"]


subscribe("cpl.commitment_created", _on_commitment)
