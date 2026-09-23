from ..registry import SituationRegistry
from .agenda import IDLE_AGENDA, INTENTION_GAPS
from .contracts import CONTRACTS
from .conversation import CONVERSATION
from .household import HOUSEHOLD
from .reactions import REACTIONS
from .romance import ROMANCE
from .vertical_slice import VERTICAL_SLICE
from .violence import VIOLENCE


def default_registry() -> SituationRegistry:
    reg = SituationRegistry(
        VERTICAL_SLICE + REACTIONS + CONVERSATION + CONTRACTS + HOUSEHOLD + ROMANCE + VIOLENCE
        + (IDLE_AGENDA,)
    )
    reg.register_gaps(IDLE_AGENDA.id, INTENTION_GAPS)
    return reg
