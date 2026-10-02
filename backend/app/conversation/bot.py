"""The RAG bot: one turn per customer message, and grounded copilot drafts for agents."""

from app.config import settings
from app.conversation.constants import BotReplyKind, HandoffReason, Sender
from app.conversation.lifecycle import add_bot_message, record_attempt, request_handoff
from app.conversation.policy import answer_signals, conversation_signals, decide, detect_small_talk
from app.conversation.util import truncate
from app.observability import online_eval
from app.observability.metrics import bot_turns, handoffs, label
from app.observability.tracing import current_trace_id, observe
from app.rag.answerer import Answer, answer_question, find_procedure, to_source_ref


def _history(conversation: dict, exclude_id: str | None = None) -> list[dict]:
    return [{"sender": m["sender"], "text": m["text"]} for m in conversation["messages"] if m["id"] != exclude_id and m["sender"] != Sender.SYSTEM]


def _top(result: Answer) -> dict | None:
    """The article an attempt is attributed to: the first citation, else the best retrieval hit."""
    best = (result.citations or result.retrieval.results or [None])[0]
    return {"id": best["docId"], "title": best["title"]} if best else None


def _update_intent(insights: dict, result: Answer) -> None:
    top = result.retrieval.results[0] if result.retrieval.results else None
    if top and top["similarity"] >= settings.rag_no_match_threshold and top["similarity"] >= ((insights["intent"] or {}).get("confidence") or 0):
        insights["intent"] = {"label": top["category"], "confidence": top["similarity"]}


async def _enrich_handoff(conversation: dict, result: Answer, question: str) -> None:
    """Add this turn's retrieval and the matching agent procedure to the brief."""
    handoff = conversation["handoff"]
    fresh = [to_source_ref(r) for r in result.retrieval.results if r["similarity"] >= settings.rag_no_match_threshold]
    best: dict[str, dict] = {}
    for source in [*handoff["sources"], *fresh]:
        if source["id"] not in best or source["score"] > best[source["id"]]["score"]:
            best[source["id"]] = source
    handoff["sources"] = sorted(best.values(), key=lambda s: s["score"], reverse=True)[:5]

    procedure = await find_procedure(question)
    if procedure:
        handoff["procedure"] = {"title": procedure["title"], "url": procedure["url"], "similarity": procedure["similarity"]}
        handoff["suggestedNextSteps"].append(f"Follow the internal “{procedure['title']}” procedure.")


def _clarifying_question(result: Answer) -> str:
    top = result.retrieval.results[0] if result.retrieval.results else None
    hint = f" Is this about {top['title'].rstrip('.?!').lower()}?" if top and top["similarity"] >= settings.rag_no_match_threshold else ""
    return f"I want to make sure I get this right.{hint} Could you tell me a bit more — what you're trying to do and where you're seeing the problem?"


async def _run_turn(conversation: dict, message: dict, sentiment: float, now: int) -> dict:
    insights = conversation["insights"]

    small_talk = detect_small_talk(message["text"])
    if small_talk and sentiment > settings.rag_sentiment_threshold:
        text = "Hi! How can I help today?" if small_talk == "greeting" else "You’re welcome! Is there anything else I can help with?"
        add_bot_message(conversation, text, now, {"kind": BotReplyKind.SMALL_TALK, "confidence": None, "sources": []})
        return {"kind": "small_talk", "reply": text}

    # Conversation-level signals first: if a handoff is already certain, skip the LLM entirely.
    early = conversation_signals(message["text"], sentiment)
    result = await answer_question(message["text"], history=_history(conversation, message["id"]), generate=not early)
    insights["lastConfidence"] = result.retrieval.confidence
    _update_intent(insights, result)

    later = [] if early else answer_signals(
        status=result.status, confidence=result.retrieval.confidence, text=message["text"],
        failed_attempts=insights["failedAttempts"], error=result.error,
    )  # fmt: skip
    decision = decide([*early, *later])

    if decision["should_handoff"]:
        reason = decision["primary"]["reason"]
        bare_request = reason == HandoffReason.CUSTOMER_REQUEST and result.retrieval.confidence < settings.rag_no_match_threshold
        if not bare_request:
            record_attempt(insights, message, None, "handed_off", result.retrieval.confidence, _top(result), now)
        request_handoff(conversation, decision, message, now)
        await _enrich_handoff(conversation, result, message["text"])
        handoffs.labels(**label(reason=reason, priority=conversation["handoff"]["priority"])).inc()
        return {"kind": "handed_off", "reason": reason, "signals": [s["reason"] for s in decision["signals"]], "status": result.status}

    if result.status == "answered":
        trace_id = current_trace_id()
        reply = add_bot_message(conversation, result.answer, now, {
            "kind": BotReplyKind.ANSWER, "confidence": result.retrieval.confidence,
            "sources": [to_source_ref(c) for c in result.citations], "traceId": trace_id,
        })  # fmt: skip
        record_attempt(insights, message, reply, "answered", result.retrieval.confidence, _top(result), now)
        insights["failedAttempts"] = 0
        online_eval.maybe_score_answer(trace_id=trace_id, question=message["text"], contexts=[r["text"] for r in result.retrieval.results], answer=result.answer)
        return {"kind": "answered", "reply": result.answer, "citations": [c["id"] for c in result.citations]}

    text = _clarifying_question(result)
    reply = add_bot_message(conversation, text, now, {
        "kind": BotReplyKind.CLARIFY, "confidence": result.retrieval.confidence,
        "sources": [to_source_ref(r) for r in result.retrieval.results[:3]],
    })  # fmt: skip
    record_attempt(insights, message, reply, "clarified", result.retrieval.confidence, _top(result), now)
    insights["failedAttempts"] += 1
    return {"kind": "clarified", "reply": text, "status": result.status}


async def bot_turn(conversation: dict, message: dict, sentiment: float, now: int) -> dict:
    """One bot turn, traced as a Langfuse agent observation and counted in Prometheus."""
    with observe("bot-turn", as_type="agent", input=message["text"]) as span:
        outcome = await _run_turn(conversation, message, sentiment, now)
        span.update(output=outcome, metadata={"conversationStatus": conversation["status"], "sentiment": sentiment})
        bot_turns.labels(**label(outcome=outcome["kind"])).inc()
        return outcome


async def draft_copilot(conversation: dict, question: str | None) -> dict | None:
    """A grounded draft for the agent, or None when the knowledge base can't support one."""
    if not question:
        return None
    with observe("copilot-draft", as_type="agent", input=question) as span:
        result = await answer_question(question, history=_history(conversation), purpose="copilot")
        span.update(output={"status": result.status, "answer": result.answer})
        if result.status != "answered":
            return None
        return {
            "text": result.answer,
            "basedOn": truncate(question, 120),
            "confidence": result.retrieval.confidence,
            "sources": [to_source_ref(c) for c in result.citations],
        }
