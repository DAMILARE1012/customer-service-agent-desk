"""When the bot steps aside.

Conversation-level rules (sensitive topics, asking for a person, frustration) need no knowledge base
and are checked first — if one fires, the LLM isn't called at all. Knowledge-level rules use the
calibrated retrieval threshold and the LLM's own verdict on whether the sources answer the question.
"""

import re

from app.config import settings
from app.conversation.constants import PRECEDENCE, HandoffReason, Priority
from app.conversation.util import pct

HUMAN_REQUEST = re.compile(
    r"\b(human|real person|actual person|agent|representative|operator|someone real|live (chat|support)"
    r"|(speak|talk) (to|with) (a |an )?(person|someone|manager))\b",
    re.I,
)

SENSITIVE_TOPICS = [
    ("Unauthorized charge or fraud", re.compile(r"unauthori[sz]ed|fraud|didn['’]?t (make|authori[sz]e)|chargeback|dispute the charge", re.I)),
    ("Legal threat", re.compile(r"\b(lawyer|attorney|legal action|sue|court)\b", re.I)),
    ("Account closure & data deletion", re.compile(r"\b(close|delete|remove|erase)\b.{0,20}\b(account|data)\b|gdpr|right to be forgotten", re.I)),
    ("Product safety", re.compile(r"\b(injur\w*|caught fire|burn(ed|t)|unsafe|hazard|smok(e|ing))\b", re.I)),
]  # fmt: skip

_GREETING = re.compile(r"^(hi|hello|hey|good (morning|afternoon|evening))( there)?[\s!.]*$", re.I)
_THANKS = re.compile(
    r"^(ok(ay)?[,\s]*)?(thanks|thank you|thx|ty|great|perfect|awesome|cool|got it)([\s,!.]+(so much|a lot|again))?[\s!.]*$",
    re.I,
)


def detect_small_talk(text: str) -> str | None:
    trimmed = text.strip()
    if _GREETING.match(trimmed):
        return "greeting"
    if _THANKS.match(trimmed):
        return "thanks"
    return None


def conversation_signals(text: str, sentiment: float) -> list[dict]:
    signals = []
    sensitive = next((topic for topic, pattern in SENSITIVE_TOPICS if pattern.search(text)), None)
    if sensitive:
        signals.append({"reason": HandoffReason.SENSITIVE_TOPIC, "detail": f"{sensitive} — policy requires a human.", "topic": sensitive})
    if HUMAN_REQUEST.search(text):
        signals.append({"reason": HandoffReason.CUSTOMER_REQUEST, "detail": "Customer explicitly asked to speak with a person."})
    if sentiment <= settings.rag_sentiment_threshold:
        signals.append({
            "reason": HandoffReason.NEGATIVE_SENTIMENT,
            "detail": f"Sentiment fell to {sentiment:.2f} (threshold {settings.rag_sentiment_threshold}).",
        })
    return signals


def answer_signals(*, status: str, confidence: float, text: str, failed_attempts: int, error: str | None = None) -> list[dict]:
    """Signals from the answer attempt; [] means keep going (answer or ask to clarify)."""
    attempts = failed_attempts + 1
    if status == "error":
        return [{"reason": HandoffReason.ASSISTANT_UNAVAILABLE, "detail": f"The language model call failed: {error}"}]
    if status == "no_match" and len(text.split()) >= 4:
        # A substantive question with nothing relevant goes straight to a person; a vague one gets a clarifying question.
        return [{
            "reason": HandoffReason.LOW_CONFIDENCE,
            "detail": f"Best knowledge-base match was {pct(confidence)}, below the {pct(settings.rag_no_match_threshold)} no-match threshold.",
        }]
    if status in ("no_match", "unanswerable") and attempts >= settings.rag_max_failed_attempts:
        return [{
            "reason": HandoffReason.REPEATED_FAILURE,
            "detail": f"{attempts} turns in a row without a grounded answer (best match {pct(confidence)}).",
        }]
    return []


def decide(signals: list[dict]) -> dict:
    """Primary reason by precedence; every signal is kept for the agent's brief."""
    primary = next((s for reason in PRECEDENCE for s in signals if s["reason"] == reason), None)
    return {"should_handoff": primary is not None, "primary": primary, "signals": signals}


def compute_priority(reason: str, sentiment: float, tier: str) -> str:
    if reason == HandoffReason.SENSITIVE_TOPIC or sentiment <= -0.7:
        return Priority.URGENT
    if tier == "enterprise" or reason in (HandoffReason.NEGATIVE_SENTIMENT, HandoffReason.REPEATED_FAILURE):
        return Priority.HIGH
    return Priority.NORMAL
