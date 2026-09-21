"""LLM interface. The middleware talks to this, never to a vendor SDK."""

from __future__ import annotations

from typing import Dict, List, Protocol, Sequence


class LLMError(RuntimeError):
    """The model could not be reached or returned an unusable HTTP response."""


class LLMClient(Protocol):
    async def choose(self, messages: List[Dict[str, str]], option_ids: Sequence[str]) -> str:
        """Return the model's raw reply. `option_ids` lets a backend constrain
        decoding to the offered ids; the reply is still validated by the caller."""
        ...

    async def aclose(self) -> None: ...
