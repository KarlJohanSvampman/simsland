from ..registry import SituationRegistry
from .agenda import IDLE_AGENDA, INTENTION_GAPS
from .vertical_slice import VERTICAL_SLICE


def default_registry() -> SituationRegistry:
    reg = SituationRegistry(VERTICAL_SLICE + (IDLE_AGENDA,))
    reg.register_gaps(IDLE_AGENDA.id, INTENTION_GAPS)
    return reg
