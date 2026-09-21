import json

import pytest

from simsland_mw.simulation.mock import MockSimClient, dinner_world


class ScriptedLLM:
    """Returns queued replies (or calls a function) and records what it was sent."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    async def choose(self, messages, option_ids):
        self.calls.append({"messages": messages, "option_ids": list(option_ids)})
        r = self.replies.pop(0) if self.replies else json.dumps({"choice": option_ids[0]})
        return r(option_ids) if callable(r) else r

    async def aclose(self):
        return None


@pytest.fixture
def world():
    return dinner_world()


@pytest.fixture
def sim(world):
    return MockSimClient(world)
