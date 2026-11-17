"""cpl/model/enums.py -- the protocol's vocabularies (docs/cpl_implementation_plan.md section 4). Stored as their
string values (plain JSON on the world)."""

from enum import Enum


class ConvState(str, Enum):
    CREATED = "created"
    PENDING = "pending"          # invited, not yet answered
    ACTIVE = "active"
    PAUSED = "paused"            # a gap within one sitting (C5)
    RESOLVING = "resolving"      # winding down: one closing line each
    RESOLVED = "resolved"
    EXPIRED = "expired"          # never got going (no answer, nobody reachable)


LIVE = {ConvState.CREATED, ConvState.PENDING, ConvState.ACTIVE, ConvState.PAUSED, ConvState.RESOLVING}
FINAL = {ConvState.RESOLVED, ConvState.EXPIRED}


class ResolutionReason(str, Enum):
    MUTUAL_AGREEMENT = "mutual_agreement"
    REQUEST_FULFILLED = "request_fulfilled"
    REQUEST_REJECTED = "request_rejected"
    QUESTION_ANSWERED = "question_answered"
    TOPIC_EXHAUSTED = "topic_exhausted"
    PARTICIPANT_LEFT = "participant_left"
    ANGRY_WITHDRAWAL = "angry_withdrawal"
    INTERRUPTED = "interrupted"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    CONFLICT_ESCALATION = "conflict_escalation"
    ABANDONED = "abandoned"
    DECLINED = "declined"        # the invitation was answered "no" (or "later")
    NO_ANSWER = "no_answer"      # the invitation was never answered


class Channel(str, Enum):
    IN_PERSON = "in_person"
    CALL = "call"
    TEXT = "text"
    EMAIL = "email"
    SOCIAL = "social"


class Purpose(str, Enum):
    INFORMATIVE = "informative"
    QUESTION = "question"
    REQUEST = "request"
    PRAGMATIC = "pragmatic"
    NEGOTIATION = "negotiation"
    SOCIAL = "social"
    EMOTIONAL = "emotional"
    CONFLICT = "conflict"
    PERSUASION = "persuasion"
    COORDINATION = "coordination"
    GOSSIP = "gossip"
    SUPPORT = "support"
    ROMANTIC = "romantic"


class MessageType(str, Enum):
    STATEMENT = "statement"
    QUESTION = "question"
    REQUEST = "request"
    PROPOSAL = "proposal"
    RESPONSE = "response"
    ARGUMENT = "argument"
    EMOTIONAL_STATEMENT = "emotional_statement"
    CONTROL = "control"


class ControlType(str, Enum):
    ACCEPT = "accept"            # accept the invitation
    DECLINE = "decline"
    DEFER = "defer"              # "not now, later"
    LEAVE = "leave"
    INTERRUPT = "interrupt"
    PAUSE = "pause"
    RESUME = "resume"
    CLOSE = "close"


class ResponseType(str, Enum):
    ACCEPT = "accept"
    REJECT = "reject"
    COUNTER = "counter"
    CONDITIONAL = "conditional"
    DEFER = "defer"
    CLARIFY = "clarify"
    PARTIAL = "partial"
    ACKNOWLEDGE = "acknowledge"
    ANSWER = "answer"
    CANT_ANSWER = "cant_answer"
    IGNORE = "ignore"


class RequestStatus(str, Enum):
    OPEN = "open"
    ACCEPTED = "accepted"
    CONDITIONAL = "conditional"
    REJECTED = "rejected"
    DEFERRED = "deferred"
    NEGOTIATING = "negotiating"
    CANCELLED = "cancelled"
    FULFILLED = "fulfilled"


class EpistemicStatus(str, Enum):
    ASSERTED = "asserted"
    REPORTED_CLAIM = "reported_claim"
    ACKNOWLEDGED = "acknowledged"
    CONFIRMED = "confirmed"
    DISPUTED = "disputed"
    REJECTED = "rejected"
    UNANSWERED = "unanswered"


class GenerationMode(str, Enum):
    STRUCTURED = "A"
    NATURAL = "B"
    REASONING = "C"


# today's speech_act (brain/conversations.py SPEECH_ACTS) -> message type (plan section 4); kept on the message as
# metadata.legacy_speech_act so the existing analysis, ledger and tone code keeps reading what it reads
LEGACY_SPEECH_ACT = {
    "question": MessageType.QUESTION, "ask": MessageType.QUESTION,
    "micro_request": MessageType.REQUEST, "request": MessageType.REQUEST,
    "smalltalk": MessageType.STATEMENT, "joke": MessageType.STATEMENT, "compliment": MessageType.STATEMENT,
    "flirt": MessageType.STATEMENT, "brag": MessageType.STATEMENT, "comfort": MessageType.STATEMENT,
    "supportive": MessageType.STATEMENT, "gossip": MessageType.STATEMENT, "urgent_report": MessageType.STATEMENT,
    "lie": MessageType.STATEMENT,
    "insult": MessageType.EMOTIONAL_STATEMENT, "challenge": MessageType.EMOTIONAL_STATEMENT,
    "defensive": MessageType.EMOTIONAL_STATEMENT, "dismissive": MessageType.EMOTIONAL_STATEMENT,
    "vulnerable": MessageType.EMOTIONAL_STATEMENT, "confession": MessageType.EMOTIONAL_STATEMENT,
    "apology": MessageType.EMOTIONAL_STATEMENT,
    "argue": MessageType.ARGUMENT,
}
