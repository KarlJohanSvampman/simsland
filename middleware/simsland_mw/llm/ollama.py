"""Ollama backend, with structured output constrained to the offered option ids."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

import httpx

from .client import LLMError


def choice_schema(option_ids: Sequence[str]) -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": {"choice": {"type": "string", "enum": list(option_ids)}},
        "required": ["choice"],
        "additionalProperties": False,
    }


class OllamaClient:
    def __init__(self, base_url: str, model: str, num_ctx: int = 8192, keep_alive: str = "10m",
                 temperature: float = 0.7, timeout: float = 120.0,
                 transport: Optional[httpx.AsyncBaseTransport] = None):
        self.model = model
        self.num_ctx = num_ctx
        self.keep_alive = keep_alive
        self.temperature = temperature
        self._http = httpx.AsyncClient(base_url=base_url, timeout=timeout, transport=transport)

    async def _chat(self, messages: List[Dict[str, str]], fmt: Any) -> httpx.Response:
        return await self._http.post("/api/chat", json={
            "model": self.model, "messages": messages, "stream": False, "format": fmt,
            "keep_alive": self.keep_alive,
            "options": {"temperature": self.temperature, "num_ctx": self.num_ctx},
        })

    async def choose(self, messages: List[Dict[str, str]], option_ids: Sequence[str]) -> str:
        try:
            r = await self._chat(messages, choice_schema(option_ids))
            if r.status_code == 400:  # older Ollama: no JSON-schema `format`, only "json"
                r = await self._chat(messages, "json")
        except httpx.HTTPError as e:
            raise LLMError(f"ollama unreachable: {type(e).__name__}: {e}") from e
        if r.status_code >= 400:
            raise LLMError(f"ollama HTTP {r.status_code}: {r.text[:300]}")
        try:
            return r.json()["message"]["content"]
        except (KeyError, ValueError) as e:
            raise LLMError(f"unexpected ollama response: {r.text[:300]}") from e

    async def ping(self) -> bool:
        try:
            return (await self._http.get("/api/tags")).status_code == 200
        except httpx.HTTPError:
            return False

    async def aclose(self) -> None:
        await self._http.aclose()
