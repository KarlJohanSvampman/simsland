"""
cpl -- the Conversation Protocol Layer (docs/cpl_implementation_plan.md).

Conversations between characters as a protocol with one owner: an explicit lifecycle (cpl/state_machine.py),
messages with types and references (cpl/protocol/), requests that are tracked until they are settled, and timers
instead of polling. Its state lives on the world as entities (cpl/store.py).

Built in phases behind CPL_MODE (cpl/config.py). Phase 1, step 1 (this): the protocol, the data model, the state
machine, the store and the timer-driven engine (cpl/conversations.py). Not yet wired into apply_speech.
"""

from cpl.config import mode, CPL_MODE  # noqa: F401
