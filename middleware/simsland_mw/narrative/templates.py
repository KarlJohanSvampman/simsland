"""Small text helpers shared by the narrative layer."""

from __future__ import annotations

from typing import Iterable, List


def join_natural(items: Iterable[str]) -> str:
    items = [i for i in items if i]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


def humanize(identifier: str) -> str:
    """'expectation:buy_groceries' -> 'buy groceries'."""
    if not identifier:
        return ""
    return identifier.split(":")[-1].replace("_", " ").strip()


def sentence(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    return text if text[-1] in ".!?\"'" else text + "."


def capfirst(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


def paragraph(parts: Iterable[str]) -> str:
    return " ".join(sentence(p) for p in parts if p and p.strip())


def bullet_lines(lines: Iterable[str]) -> List[str]:
    return [f"- {l}" for l in lines if l]
