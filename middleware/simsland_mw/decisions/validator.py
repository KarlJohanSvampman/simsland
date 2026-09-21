"""
Choice validation (spec section 4).

The model returns a selection, nothing more. Anything that is not one of the
options it was actually shown is rejected -- an out-of-range index, an
invented id, a fabricated `"action": "steal_money_from_bank"`. The model
cannot grant itself capabilities.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, List, Optional

from .options import Option

MAX_THOUGHT_CHARS = 300
MAX_SPEECH_CHARS = 240
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


class ChoiceRejected(ValueError):
    """The model's reply did not name one of the offered options."""


@dataclass
class Choice:
    option: Option
    via: str                       # "id" or "index"
    thought: Optional[str] = None  # private: kept in the session digest, never persisted to Simsland
    speech: Optional[str] = None   # only ever set for options that `speaks`; goes through Simsland's speech path


def extract_json(raw: str) -> Any:
    text = _FENCE.sub("", (raw or "").strip())
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass
    raise ChoiceRejected("reply was not valid JSON")


def parse_choice(raw: str, options: List[Option]) -> Choice:
    data = extract_json(raw)
    if not isinstance(data, dict):
        raise ChoiceRejected("reply was not a JSON object")
    if "choice" not in data:
        raise ChoiceRejected("reply has no 'choice' field")

    value = data["choice"]
    by_id = {o.id.lower(): o for o in options}
    option: Optional[Option] = None
    via = "id"

    if isinstance(value, bool):
        raise ChoiceRejected("choice must be an option id or number")
    if isinstance(value, str):
        key = value.strip().lower()
        option = by_id.get(key)
        if option is None and key.isdigit():           # "2" -> option number 2
            value = int(key)
    if option is None and isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and not value.is_integer():
            raise ChoiceRejected(f"choice {value!r} is not a whole number")
        index = int(value)
        if not 1 <= index <= len(options):
            raise ChoiceRejected(f"choice {index} is out of range 1..{len(options)}")
        option, via = options[index - 1], "index"
    if option is None:
        raise ChoiceRejected(f"choice {data['choice']!r} is not one of the offered options")

    thought = data.get("thought")
    if isinstance(thought, str) and thought.strip():
        thought = thought.strip()[:MAX_THOUGHT_CHARS]
    else:
        thought = None
    speech = data.get("speech")
    if option.speaks and isinstance(speech, str) and speech.strip():
        speech = speech.strip().strip('"')[:MAX_SPEECH_CHARS]
    else:
        speech = None
    return Choice(option=option, via=via, thought=thought, speech=speech)
