"""Signals read from customer messages: sentiment and structured entities (order IDs, emails…)."""

import re

from app.conversation.util import round2

# Prefix → weight. Deterministic on purpose (no model call per message).
NEGATIVE = {
    "frustrat": 2, "ridiculous": 2, "terrible": 2, "awful": 2, "worst": 2, "useless": 2, "unacceptable": 2.5,
    "angry": 2, "furious": 3, "hate": 2, "scam": 3, "annoy": 1.5, "disappoint": 1.5, "upset": 1.5, "waste": 1.5,
    "joke": 1, "seriously": 1, "again": 0.5, "never": 0.5, "wrong": 0.75, "bad": 1, "not help": 1.5,
}  # fmt: skip
POSITIVE = {
    "thank": 1.5, "thx": 1, "great": 1.5, "perfect": 2, "awesome": 2, "helpful": 1.5, "love": 1.5,
    "appreciate": 1.5, "good": 1, "nice": 1,
}  # fmt: skip

_NEGATIVE_RE = {prefix: re.compile(rf"\b{re.escape(prefix)}") for prefix in NEGATIVE}
_POSITIVE_RE = {prefix: re.compile(rf"\b{re.escape(prefix)}") for prefix in POSITIVE}


def _sum_matches(text: str, lexicon: dict[str, float], patterns: dict[str, re.Pattern]) -> float:
    return sum(len(patterns[prefix].findall(text)) * weight for prefix, weight in lexicon.items())


def score_sentiment(raw: str) -> float:
    """-1 (furious) … +1 (delighted)."""
    text = raw.lower()
    negative = _sum_matches(text, NEGATIVE, _NEGATIVE_RE)
    positive = _sum_matches(text, POSITIVE, _POSITIVE_RE)
    if re.search(r"!{2,}", raw):
        negative += 0.75
    if re.search(r"\b[A-Z]{4,}\b", raw):
        negative += 0.75
    if negative == 0 and positive == 0:
        return 0.0
    return round2((positive - negative) / (positive + negative + 1))


def sentiment_label(score: float) -> str:
    if score <= -0.5:
        return "Frustrated"
    if score < -0.15:
        return "Negative"
    if score > 0.25:
        return "Positive"
    return "Neutral"


_ENTITY_PATTERNS = [
    ("order_id", "Order", re.compile(r"(?:order\s*(?:number|no\.?)?\s*#?\s*|#)(\d{4,})", re.I), lambda m: f"#{m.group(1)}"),
    ("email", "Email", re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), lambda m: m.group(0)),
    ("amount", "Amount", re.compile(r"\$\s?\d{1,3}(?:,\d{3})*(?:\.\d{2})?"), lambda m: re.sub(r"\s", "", m.group(0))),
    ("promo_code", "Promo code", re.compile(r"\b[A-Z]{3,}\d{1,3}\b"), lambda m: m.group(0)),
]


def extract_entities(text: str, message_id: str) -> list[dict]:
    return [
        {"type": kind, "label": label, "value": fmt(match), "messageId": message_id}
        for kind, label, pattern, fmt in _ENTITY_PATTERNS
        for match in pattern.finditer(text)
    ]


def merge_entities(existing: list[dict], incoming: list[dict]) -> list[dict]:
    seen = {(e["type"], e["value"]) for e in existing}
    merged = list(existing)
    for entity in incoming:
        key = (entity["type"], entity["value"])
        if key not in seen:
            seen.add(key)
            merged.append(entity)
    return merged
