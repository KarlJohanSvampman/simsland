"""
HTTP client for Simsland's /mw bridge (backend/api/middleware_bridge.py).

This is the only module that knows Simsland's URLs. Everything above it
works with plain dicts returned by `snapshot()`.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional, Protocol

import httpx


class SimError(RuntimeError):
    """Simsland was unreachable or rejected the request."""


class SimulationClient(Protocol):
    async def snapshot(self, char_id: str, sections: Iterable[str]) -> Dict[str, Any]: ...
    async def due(self) -> Dict[str, Any]: ...
    async def list_characters(self) -> Dict[str, Any]: ...
    async def execute(self, char_id: str, decision: Dict[str, Any],
                      wake_reason: Optional[str] = None, thought: Optional[str] = None) -> Dict[str, Any]: ...
    async def set_external_brain(self, char_id: str, enabled: bool) -> Dict[str, Any]: ...
    async def aclose(self) -> None: ...


class SimClient:
    def __init__(self, base_url: str, timeout: float = 30.0, transport: httpx.AsyncBaseTransport | None = None):
        self._http = httpx.AsyncClient(base_url=base_url, timeout=timeout, transport=transport)

    async def _request(self, method: str, path: str, **kw) -> Dict[str, Any]:
        try:
            r = await self._http.request(method, path, **kw)
        except httpx.HTTPError as e:
            raise SimError(f"{method} {path}: {type(e).__name__}: {e}") from e
        if r.status_code >= 400:
            raise SimError(f"{method} {path}: HTTP {r.status_code}: {r.text[:300]}")
        return r.json()

    async def snapshot(self, char_id: str, sections: Iterable[str]) -> Dict[str, Any]:
        return await self._request(
            "GET", f"/mw/characters/{char_id}/snapshot",
            params={"sections": ",".join(sorted(set(sections)))},
        )

    async def due(self) -> Dict[str, Any]:
        return await self._request("GET", "/mw/due")

    async def list_characters(self) -> Dict[str, Any]:
        return await self._request("GET", "/mw/characters")

    async def execute(self, char_id: str, decision: Dict[str, Any],
                      wake_reason: Optional[str] = None, thought: Optional[str] = None) -> Dict[str, Any]:
        return await self._request(
            "POST", f"/mw/characters/{char_id}/execute",
            # "thought" is separate from decision["thought"] (always None,
            # deliberately never persisted -- see executor.build_decision):
            # this is only ever shown (a thought bubble), never remembered.
            json={"decision": decision, "wake_reason": wake_reason, "thought": thought},
        )

    async def set_external_brain(self, char_id: str, enabled: bool) -> Dict[str, Any]:
        return await self._request(
            "POST", f"/mw/characters/{char_id}/external_brain", json={"enabled": enabled},
        )

    async def aclose(self) -> None:
        await self._http.aclose()
