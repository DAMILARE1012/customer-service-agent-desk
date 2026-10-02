"""The handoff brief: everything the bot knows, frozen at the moment it steps aside."""

from app.conversation.constants import REASON_LABEL, TIER_LABEL, HandoffReason, HandoffStatus
from app.conversation.policy import compute_priority
from app.conversation.signals import sentiment_label

MIN_SOURCE_SCORE = 0.35

REASON_STEPS = {
    HandoffReason.CUSTOMER_REQUEST: ["Greet them by name and confirm you already have the context — don’t make them repeat themselves."],
    HandoffReason.SENSITIVE_TOPIC: [
        "Verify identity before discussing account or payment details.",
        "Follow the escalation playbook for this topic; avoid commitments the bot could not make.",
    ],
    HandoffReason.NEGATIVE_SENTIMENT: ["Acknowledge the frustration before troubleshooting.", "Consider a goodwill gesture if policy allows."],
    HandoffReason.REPEATED_FAILURE: [
        "Don’t repeat the bot’s earlier answers — they didn’t land.",
        "Ask one targeted question to pin down what they need.",
    ],
    HandoffReason.LOW_CONFIDENCE: [
        "The knowledge base had no good match — clarify the request directly.",
        "Flag a KB gap if this comes up often.",
    ],
    HandoffReason.AGENT_INITIATED: ["Review the bot’s last answer before replying."],
    HandoffReason.ASSISTANT_UNAVAILABLE: ["The assistant could not answer (model error or timeout) — the question itself may be simple."],
}


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _summary(conversation: dict, primary: dict) -> str:
    """Template summary. Deterministic and free; an LLM-written summary is a possible upgrade."""
    customer, insights = conversation["customer"], conversation["insights"]
    attempts, entities, intent = insights["attempts"], insights["entities"], insights["intent"]
    answered = [a for a in attempts if a["outcome"] == "answered"]
    open_ = [a for a in attempts if a["outcome"] != "answered"]
    tier = TIER_LABEL.get(customer["tier"], customer["tier"])
    titles = list(dict.fromkeys(a["sourceTitle"] for a in answered))
    parts = [
        f"{customer['name']} ({tier} customer) reached out{f' about {intent["label"].lower()}' if intent else ''}.",
        f"The bot answered {_plural(len(answered), 'question')} from the help centre ({', '.join(map(str, titles))})."
        if answered
        else "The bot was not able to answer anything confidently.",
        f"{_plural(len(open_), 'question')} still open." if open_ else None,
        f"Shared: {', '.join(f'{e['label'].lower()} {e['value']}' for e in entities)}." if entities else None,
        f"Stepped aside because: {primary['detail']}",
    ]
    return " ".join(p for p in parts if p)


def _next_steps(primary: dict, entities: list[dict]) -> list[str]:
    steps = list(REASON_STEPS.get(primary["reason"], []))
    order = next((e for e in entities if e["type"] == "order_id"), None)
    if order:
        steps.append(f"Look up order {order['value']} in the order system.")
    amount = next((e for e in entities if e["type"] == "amount"), None)
    if amount:
        steps.append(f"Confirm the {amount['value']} charge against billing records.")
    return steps


def _collect_sources(conversation: dict) -> list[dict]:
    best: dict[str, dict] = {}
    for message in conversation["messages"]:
        for source in (message.get("meta") or {}).get("sources") or []:
            if source["score"] < MIN_SOURCE_SCORE:
                continue
            if source["id"] not in best or source["score"] > best[source["id"]]["score"]:
                best[source["id"]] = {**source, "citedInMessageId": message["id"]}
    return sorted(best.values(), key=lambda s: s["score"], reverse=True)[:5]


def build_handoff_packet(conversation: dict, decision: dict, *, trigger_message: dict | None, now: int, packet_id: str) -> dict:
    insights, customer = conversation["insights"], conversation["customer"]
    primary = decision["primary"]
    current = insights["sentiment"]["current"]
    return {
        "id": packet_id,
        "status": HandoffStatus.PENDING,
        "reason": primary["reason"],
        "reasonLabel": REASON_LABEL[primary["reason"]],
        "reasonDetail": primary["detail"],
        "signals": decision["signals"],
        "priority": compute_priority(primary["reason"], current, customer["tier"]),
        "requestedAt": now,
        "acceptedAt": None,
        "acceptedBy": None,
        "triggerMessage": {"id": trigger_message["id"], "text": trigger_message["text"]} if trigger_message else None,
        "summary": _summary(conversation, primary),
        "intent": insights["intent"],
        "entities": insights["entities"],
        "botAttempts": insights["attempts"],
        "openQuestions": [a["question"] for a in insights["attempts"] if a["outcome"] != "answered"],
        "sources": _collect_sources(conversation),
        "sentiment": {"current": current, "label": sentiment_label(current), "trend": insights["sentiment"]["trend"]},
        "suggestedNextSteps": _next_steps(primary, insights["entities"]),
    }
