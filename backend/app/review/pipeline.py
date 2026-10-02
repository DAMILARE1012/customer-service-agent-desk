"""The review pipeline: learn from closed conversations without feeding raw chats back into anything.

For every closed, not-yet-reviewed session:

  knowledge gaps    questions the help centre couldn't answer (retrieval below the no-match threshold,
                    or the bot failing turn after turn) are redacted, embedded and grouped with similar
                    ones. Each group is one "missing article" item, with how often it was asked, a few
                    example phrasings and how agents answered it.
  test questions    a handoff an agent resolved becomes a candidate evaluation question: the customer's
                    question and the agent's answer as the reference, both redacted.

Nothing is published automatically: an admin writes and publishes the article (it then goes through
the normal `local` ingestion) or approves the test question (it joins the evaluation set).
"""

import asyncio
import logging
import uuid
from datetime import UTC, datetime

import numpy as np

from app.config import settings
from app.conversation import store
from app.conversation.constants import ClosedReason, HandoffReason, Sender
from app.conversation.util import now_ms, truncate
from app.db import repository
from app.privacy.redact import customer_names, redact
from app.rag.embedder import get_embedder

log = logging.getLogger(__name__)

GAP_SIMILARITY = 0.82  # same missing article
DUPLICATE_TEST_SIMILARITY = 0.92  # same test question
MIN_WORDS = 4
MAX_EXAMPLES = 5
MAX_AGENT_ANSWERS = 3


def _words(text: str) -> int:
    return len(text.split())


# Handoffs decided by the conversation, not the knowledge base: the bot never tried to answer.
NOT_A_KNOWLEDGE_GAP = {HandoffReason.SENSITIVE_TOPIC, HandoffReason.CUSTOMER_REQUEST, HandoffReason.NEGATIVE_SENTIMENT}


def gap_questions(conversation: dict) -> list[str]:
    """Customer questions the knowledge base didn't cover."""
    packets = [*conversation["handoffHistory"], *([conversation["handoff"]] if conversation["handoff"] else [])]
    struggled = any(p["reason"] == HandoffReason.REPEATED_FAILURE for p in packets)
    skip = {(p.get("triggerMessage") or {}).get("id") for p in packets if p["reason"] in NOT_A_KNOWLEDGE_GAP}
    out = []
    for attempt in conversation["insights"]["attempts"]:
        if attempt["questionMessageId"] in skip:
            continue
        out_of_scope = attempt["confidence"] < settings.rag_no_match_threshold
        if attempt["outcome"] != "answered" and (out_of_scope or struggled) and _words(attempt["question"]) >= MIN_WORDS:
            out.append(attempt["question"])
    return list(dict.fromkeys(out))


def agent_replies(conversation: dict) -> list[str]:
    return [m["text"] for m in conversation["messages"] if m["sender"] == Sender.AGENT]


def test_question(conversation: dict) -> tuple[str, str] | None:
    """(question, reference answer) from a handoff an agent resolved, or None."""
    if conversation.get("closedReason") != ClosedReason.RESOLVED:
        return None
    packets = [*conversation["handoffHistory"], *([conversation["handoff"]] if conversation["handoff"] else [])]
    accepted = [p for p in packets if p.get("acceptedAt")]
    replies = agent_replies(conversation)
    if not accepted or not replies:
        return None
    packet = accepted[-1]
    question = (packet.get("triggerMessage") or {}).get("text") or next(iter(reversed(packet.get("openQuestions") or [])), "")
    answer = "\n\n".join(replies)
    if _words(question) < MIN_WORDS or len(answer) < 30:
        return None
    return question, truncate(answer, 1500)


def _cosine(a: list[float] | None, b: np.ndarray) -> float:
    return float(np.dot(np.asarray(a, dtype=np.float32), b)) if a else -1.0


async def _embed(texts: list[str]) -> np.ndarray:
    return await asyncio.to_thread(get_embedder().embed_documents, texts)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _new_item(kind: str, question: str, vector: np.ndarray, conversation_id: str) -> dict:
    return {
        "id": f"rev_{uuid.uuid4().hex[:10]}", "kind": kind, "status": "pending", "question": question, "answer": "",
        "title": "", "examples": [question], "agentAnswers": [], "conversationIds": [conversation_id], "count": 1,
        "embedding": vector.tolist(), "publishedPath": None, "createdAt": _now_iso(), "updatedAt": _now_iso(),
        "reviewedBy": None, "reviewedAt": None,
    }  # fmt: skip


async def review_conversation(conversation: dict, gaps: list[dict], tests: list[dict]) -> dict:
    repo = repository()
    names = customer_names(conversation)
    counts = {"gapsNew": 0, "gapsUpdated": 0, "testQuestions": 0}

    questions = [redact(q, names) for q in gap_questions(conversation)]
    replies = [truncate(redact(r, names), 400) for r in agent_replies(conversation)][:2]
    if questions:
        for question, vector in zip(questions, await _embed(questions), strict=True):
            best = max(gaps, key=lambda g: _cosine(g["embedding"], vector), default=None)
            if best and _cosine(best["embedding"], vector) >= GAP_SIMILARITY:
                best["count"] += 1
                if question not in best["examples"] and len(best["examples"]) < MAX_EXAMPLES:
                    best["examples"].append(question)
                for reply in replies:
                    if reply not in best["agentAnswers"] and len(best["agentAnswers"]) < MAX_AGENT_ANSWERS:
                        best["agentAnswers"].append(reply)
                if conversation["id"] not in best["conversationIds"]:
                    best["conversationIds"].append(conversation["id"])
                await repo.save_review_item(best)
                counts["gapsUpdated"] += 1
            else:
                item = _new_item("knowledge_gap", question, vector, conversation["id"])
                item["agentAnswers"] = replies[:MAX_AGENT_ANSWERS]
                gaps.append(await repo.save_review_item(item))
                counts["gapsNew"] += 1

    pair = test_question(conversation)
    if pair:
        question, answer = redact(pair[0], names), redact(pair[1], names)
        vector = (await _embed([question]))[0]
        if not any(_cosine(t["embedding"], vector) >= DUPLICATE_TEST_SIMILARITY for t in tests):
            item = _new_item("test_question", question, vector, conversation["id"])
            item["answer"] = answer
            tests.append(await repo.save_review_item(item))
            counts["testQuestions"] += 1
    return counts


async def run_review(limit: int = 200) -> dict:
    """Review closed sessions not yet reviewed. One run at a time across all API processes."""
    repo = repository()
    async with repo.exclusive("review") as acquired:
        if not acquired:
            return {"skipped": "A review run is already in progress."}
        conversations = await repo.conversations_to_review(limit)
        gaps = await repo.list_review_items("knowledge_gap")
        tests = await repo.list_review_items("test_question")
        totals = {"conversations": len(conversations), "gapsNew": 0, "gapsUpdated": 0, "testQuestions": 0}
        for conversation in conversations:
            for key, value in (await review_conversation(conversation, gaps, tests)).items():
                totals[key] += value
            async with store.transaction(conversation["id"]) as stored:
                stored["reviewedAt"] = now_ms()
        if conversations:
            log.info("review: %s", totals)
        return totals
