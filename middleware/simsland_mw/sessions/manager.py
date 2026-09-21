"""Exactly one session per character."""

from __future__ import annotations

from typing import Dict, List

from .session import CharacterSession


class SessionManager:
    def __init__(self) -> None:
        self._sessions: Dict[str, CharacterSession] = {}

    def get(self, character_id: str) -> CharacterSession:
        s = self._sessions.get(character_id)
        if s is None:
            s = self._sessions[character_id] = CharacterSession(character_id)
        return s

    def all(self) -> List[CharacterSession]:
        return list(self._sessions.values())

    def reset(self, character_id: str) -> None:
        self._sessions.pop(character_id, None)
