from . import character, environment, household, memories, relationships

ALL_PROVIDERS = [
    *character.PROVIDERS,
    *relationships.PROVIDERS,
    *memories.PROVIDERS,
    *environment.PROVIDERS,
    *household.PROVIDERS,
]
