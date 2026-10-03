"""Domain vocabulary. Values are the wire format the React desk understands — keep them in sync with
frontend/src/constants/*.js.

Lifecycle (handoff is a state, not an error):

    bot_active ──(policy trigger)──▶ handoff_pending ──(accept)──▶ agent_active ──▶ resolved
         ▲                                                              │
         └──────────────────────────(return to bot)─────────────────────┘
"""

from enum import StrEnum


class Status(StrEnum):
    BOT_ACTIVE = "bot_active"
    HANDOFF_PENDING = "handoff_pending"
    AGENT_ACTIVE = "agent_active"
    RESOLVED = "resolved"


class Sender(StrEnum):
    CUSTOMER = "customer"
    BOT = "bot"
    AGENT = "agent"
    SYSTEM = "system"


class SystemEvent(StrEnum):
    HANDOFF_REQUESTED = "handoff_requested"
    AGENT_JOINED = "agent_joined"
    AGENT_TOOK_OVER = "agent_took_over"
    RETURNED_TO_BOT = "returned_to_bot"
    RESOLVED = "resolved"  # any close; the event's closedReason says why
    PRIORITY_RAISED = "priority_raised"  # something the customer added while waiting made it more urgent (agents only)
    CONTACT_LEFT = "contact_left"  # the customer left an email for the reply (agents only)
    CUSTOMER_LEFT = "customer_left"  # the customer closed the page (agents only)
    CUSTOMER_RETURNED = "customer_returned"  # …and came back before the chat closed (agents only)
    REOPENED = "reopened"  # legacy: closed conversations no longer reopen


class BotReplyKind(StrEnum):
    ANSWER = "answer"
    CLARIFY = "clarify"
    SMALL_TALK = "small_talk"
    HANDOFF_NOTICE = "handoff_notice"


class HandoffReason(StrEnum):
    SENSITIVE_TOPIC = "sensitive_topic"
    CUSTOMER_REQUEST = "customer_request"
    NEGATIVE_SENTIMENT = "negative_sentiment"
    REPEATED_FAILURE = "repeated_failure"
    LOW_CONFIDENCE = "low_confidence"
    AGENT_INITIATED = "agent_initiated"
    ASSISTANT_UNAVAILABLE = "assistant_unavailable"


# When several signals fire on one turn, the first one listed becomes the primary reason.
PRECEDENCE = [
    HandoffReason.SENSITIVE_TOPIC,
    HandoffReason.CUSTOMER_REQUEST,
    HandoffReason.NEGATIVE_SENTIMENT,
    HandoffReason.REPEATED_FAILURE,
    HandoffReason.LOW_CONFIDENCE,
    HandoffReason.ASSISTANT_UNAVAILABLE,
]

REASON_LABEL = {
    HandoffReason.SENSITIVE_TOPIC: "Sensitive topic",
    HandoffReason.CUSTOMER_REQUEST: "Asked for a human",
    HandoffReason.NEGATIVE_SENTIMENT: "Customer frustrated",
    HandoffReason.REPEATED_FAILURE: "Bot not getting there",
    HandoffReason.LOW_CONFIDENCE: "Outside knowledge base",
    HandoffReason.AGENT_INITIATED: "Agent took over",
    HandoffReason.ASSISTANT_UNAVAILABLE: "Assistant unavailable",
}

# What the customer is told when the bot steps aside.
HANDOFF_NOTICE = {
    HandoffReason.CUSTOMER_REQUEST: "Of course — I’m connecting you with a member of our support team now. I’ve passed along everything we’ve discussed, so you won’t need to repeat yourself.",
    HandoffReason.SENSITIVE_TOPIC: "This is something a member of our team should handle personally. I’m connecting you now and have shared the details you’ve given me.",
    HandoffReason.NEGATIVE_SENTIMENT: "I’m sorry this has been frustrating. I’m bringing in someone from our team who can sort this out — they’ll see our full conversation.",
    HandoffReason.REPEATED_FAILURE: "I don’t want to keep guessing. I’m connecting you with a teammate who can help, and I’ve shared what we’ve covered so far.",
    HandoffReason.LOW_CONFIDENCE: "That’s outside what I can answer reliably, so I’m connecting you with a teammate. They’ll have our conversation, so no need to start over.",
    HandoffReason.ASSISTANT_UNAVAILABLE: "I’m having trouble answering right now, so I’m connecting you with a member of our team. They’ll see everything you’ve told me.",
}


class HandoffStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    RETURNED = "returned"
    ABANDONED = "abandoned"  # the customer left before an agent picked it up


class ClosedReason(StrEnum):
    """Why a conversation (a support session) ended. Closed conversations never reopen: the customer
    starts a new one, optionally as a follow-up linked to this one."""

    RESOLVED = "resolved"  # an agent resolved it
    ENDED_BY_CUSTOMER = "ended_by_customer"
    INACTIVE = "inactive"  # nobody wrote for SESSION_IDLE_MINUTES
    ABANDONED = "abandoned"  # the customer left while waiting for an agent
    LEFT = "left"  # the customer left while the bot was helping (closed the page, or no sign of life)


# The agent-facing note added to the transcript when a session closes.
CLOSED_NOTE = {
    ClosedReason.RESOLVED: "Resolved by {actor}",
    ClosedReason.ENDED_BY_CUSTOMER: "The customer ended the chat",
    ClosedReason.INACTIVE: "Closed after {minutes} minutes without activity",
    ClosedReason.ABANDONED: "The customer left before an agent joined",
    ClosedReason.LEFT: "The customer left the chat",
}


class Priority(StrEnum):
    URGENT = "urgent"
    HIGH = "high"
    NORMAL = "normal"


TIER_LABEL = {"standard": "Standard", "plus": "Plus", "enterprise": "Enterprise"}
