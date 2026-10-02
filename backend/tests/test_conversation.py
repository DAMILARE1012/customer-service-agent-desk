"""Handoff policy, the brief, and the lifecycle — the behaviour the desk relies on."""

import pytest

from app.conversation import lifecycle
from app.conversation.constants import HandoffReason, Priority, Status
from app.conversation.people import AGENTS, CUSTOMERS
from app.conversation.policy import answer_signals, compute_priority, conversation_signals, decide, detect_small_talk
from app.conversation.signals import extract_entities, score_sentiment

ALEX, PRIYA, _JADE = AGENTS
JORDAN = next(c for c in CUSTOMERS if c["id"] == "cus_jordan")


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("There is an unauthorized charge of $249.99 on my card", HandoffReason.SENSITIVE_TOPIC),
        ("Please close my account and delete my data", HandoffReason.SENSITIVE_TOPIC),
        ("I'm calling my lawyer about this", HandoffReason.SENSITIVE_TOPIC),
        ("Can I talk to a real person please?", HandoffReason.CUSTOMER_REQUEST),
        ("I want a human", HandoffReason.CUSTOMER_REQUEST),
    ],
)
def test_conversation_signals_fire_without_the_knowledge_base(text, reason):
    assert decide(conversation_signals(text, 0))["primary"]["reason"] == reason


def test_sensitive_topic_outranks_a_request_for_a_person():
    signals = conversation_signals("I see a fraud charge, let me speak to an agent", 0)
    decision = decide(signals)
    assert decision["primary"]["reason"] == HandoffReason.SENSITIVE_TOPIC
    assert {s["reason"] for s in decision["signals"]} == {HandoffReason.SENSITIVE_TOPIC, HandoffReason.CUSTOMER_REQUEST}


def test_frustration_is_detected():
    sentiment = score_sentiment("This is ridiculous, I've asked three times already!!")
    assert sentiment <= -0.5
    assert decide(conversation_signals("anything", sentiment))["primary"]["reason"] == HandoffReason.NEGATIVE_SENTIMENT


def test_vague_no_match_clarifies_but_substantive_no_match_hands_off():
    assert answer_signals(status="no_match", confidence=0.6, text="it's broken", failed_attempts=0) == []
    [signal] = answer_signals(status="no_match", confidence=0.6, text="Do you offer bulk pricing for schools?", failed_attempts=0)
    assert signal["reason"] == HandoffReason.LOW_CONFIDENCE
    assert "60%" in signal["detail"] and "70%" in signal["detail"]


def test_second_ungrounded_turn_hands_off_and_llm_errors_degrade_to_a_person():
    assert answer_signals(status="unanswerable", confidence=0.8, text="x", failed_attempts=0) == []
    assert answer_signals(status="unanswerable", confidence=0.8, text="x", failed_attempts=1)[0]["reason"] == HandoffReason.REPEATED_FAILURE
    error = answer_signals(status="error", confidence=0.9, text="x", failed_attempts=0, error="Groq 404")[0]
    assert error["reason"] == HandoffReason.ASSISTANT_UNAVAILABLE and "Groq 404" in error["detail"]


def test_priority_rules():
    assert compute_priority(HandoffReason.SENSITIVE_TOPIC, 0, "standard") == Priority.URGENT
    assert compute_priority(HandoffReason.CUSTOMER_REQUEST, -0.8, "standard") == Priority.URGENT
    assert compute_priority(HandoffReason.CUSTOMER_REQUEST, 0, "enterprise") == Priority.HIGH
    assert compute_priority(HandoffReason.CUSTOMER_REQUEST, 0, "standard") == Priority.NORMAL


def test_small_talk_and_entities():
    assert detect_small_talk("hello!") == "greeting"
    assert detect_small_talk("Thanks so much!") == "thanks"
    assert detect_small_talk("Thanks! Also where is my order?") is None
    values = {e["value"] for e in extract_entities("Order #48213 for $249.99, code SAVE20, me@x.com", "m1")}
    assert values == {"#48213", "$249.99", "SAVE20", "me@x.com"}


def _handed_off_conversation():
    conversation = lifecycle.create_conversation(JORDAN, 1000)
    message = lifecycle.add_message(conversation, {"sender": "customer", "text": "Unauthorized charge of $89.00 on order #48213", "createdAt": 1000})
    lifecycle.track_signals(conversation, message)
    decision = decide(conversation_signals(message["text"], 0))
    lifecycle.request_handoff(conversation, decision, message, 1000)
    return conversation


def test_handoff_brief_carries_what_the_bot_knows():
    conversation = _handed_off_conversation()
    brief = conversation["handoff"]
    assert conversation["status"] == Status.HANDOFF_PENDING
    assert brief["reason"] == HandoffReason.SENSITIVE_TOPIC and brief["priority"] == Priority.URGENT
    assert {e["value"] for e in brief["entities"]} == {"#48213", "$89.00"}
    assert "Look up order #48213 in the order system." in brief["suggestedNextSteps"]
    assert "Confirm the $89.00 charge against billing records." in brief["suggestedNextSteps"]
    assert brief["summary"].startswith("Jordan Okafor (Enterprise customer) reached out.")
    assert [m["sender"] for m in conversation["messages"]] == ["customer", "bot", "system"]


def test_lifecycle_transitions_and_guards():
    conversation = _handed_off_conversation()
    with pytest.raises(lifecycle.ApiError) as error:
        lifecycle.post_agent_message(conversation, ALEX, "hi", 2000)
    assert error.value.status == 409

    lifecycle.accept_handoff(conversation, ALEX, 2000)
    assert conversation["status"] == Status.AGENT_ACTIVE and conversation["handoff"]["acceptedBy"]["id"] == ALEX["id"]
    with pytest.raises(lifecycle.ApiError) as error:
        lifecycle.post_agent_message(conversation, PRIYA, "hi", 2100)
    assert error.value.status == 403

    lifecycle.post_agent_message(conversation, ALEX, "On it.", 2200)
    lifecycle.return_to_bot(conversation, ALEX, 3000)
    assert conversation["status"] == Status.BOT_ACTIVE and conversation["handoff"] is None
    assert conversation["handoffHistory"][0]["status"] == "returned"

    lifecycle.resolve_conversation(conversation, None, 4000)
    assert conversation["status"] == Status.RESOLVED
    assert conversation["messages"][-1]["text"] == "Resolved by the bot"
