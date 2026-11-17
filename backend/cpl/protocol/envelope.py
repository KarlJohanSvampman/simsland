"""
cpl/protocol/envelope.py -- one protocol message (docs/cpl_implementation_plan.md section 4).

Pydantic at the boundary (what a turn decision becomes, what the debug API shows); what is stored on the world is
`Envelope.model_dump(mode="json")`. The model never writes any of the ids, sequence numbers or timestamps here
(plan C3): CPL fills them in.
"""

import time
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from cpl.model.enums import ControlType, MessageType, ResponseType


class Emotion(BaseModel):
    primary: str | None = None
    intensity: float = Field(0.0, ge=0.0, le=1.0)
    stance: str | None = None                  # supportive | neutral | reluctant | opposed | hostile ...
    communicative_intent: str | None = None


class Audience(BaseModel):
    addressed: list[str] = []
    overheard_by: list[str] = []
    private: bool = False


class Metadata(BaseModel):
    priority: str = "normal"
    requires_response: bool = False
    generation_mode: str | None = None         # A | B | C
    source_decision_id: str | None = None
    causation_id: str | None = None
    legacy_speech_act: str | None = None
    deceptive: bool = False                    # a lie: visible only in the speaker's own records


class Question(BaseModel):
    id: str | None = None                      # q_...: assigned when stored
    text: str
    about: str | None = None


class Request(BaseModel):
    id: str | None = None                      # req_...
    action: str
    target: str | None = None
    deadline: float | None = None
    conditions: list[str] = []


class Proposal(BaseModel):
    id: str | None = None                      # prop_...
    terms: str
    conditions: list[str] = []


class Response(BaseModel):
    response_to: str                           # the q_/req_/prop_ id answered (never a raw message id)
    response_type: ResponseType
    content: str | None = None
    condition: str | None = None               # with conditional / counter


class Envelope(BaseModel):
    protocol_version: Literal["1.0"] = "1.0"
    message_id: str
    conversation_id: str
    sender_id: str
    recipient_ids: list[str]
    message_type: MessageType
    control: ControlType | None = None
    world_ts: float
    server_ts: float = Field(default_factory=time.time)
    sequence_number: int = 0                   # assigned by the store
    payload: dict = {}
    content: str | None = None                 # the rendered line, if any
    emotion: Emotion | None = None
    audience: Audience = Audience()
    metadata: Metadata = Metadata()

    @model_validator(mode="after")
    def _shape(self):
        if self.message_type == MessageType.CONTROL and self.control is None:
            raise ValueError("a control message names its control")
        if self.message_type != MessageType.CONTROL and self.control is not None:
            raise ValueError("only a control message carries a control")
        expects = {MessageType.QUESTION: Question, MessageType.REQUEST: Request, MessageType.PROPOSAL: Proposal,
                   MessageType.RESPONSE: Response}.get(self.message_type)
        if expects is not None:
            expects(**self.payload)            # raises a ValidationError naming what is missing
        return self

    def stored(self):
        return self.model_dump(mode="json")
