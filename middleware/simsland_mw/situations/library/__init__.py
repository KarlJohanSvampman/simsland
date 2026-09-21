from ..registry import SituationRegistry
from .vertical_slice import VERTICAL_SLICE


def default_registry() -> SituationRegistry:
    return SituationRegistry(VERTICAL_SLICE)
