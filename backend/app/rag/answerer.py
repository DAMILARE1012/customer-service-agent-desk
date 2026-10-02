"""Retrieve → gate on confidence → generate an answer that must cite its sources.

status:
    answered      grounded answer with at least one valid citation
    unanswerable  the model found the sources insufficient (or answered without citing)
    no_match      retrieval confidence below RAG_NO_MATCH_THRESHOLD — the LLM isn't called
    skipped       generate=False (a handoff is already certain); retrieval still runs for the brief
    error         the LLM failed or timed out
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field

from app.config import settings
from app.llm.groq import LlmError, chat_json
from app.observability.metrics import label, retrieval_confidence, stage_duration, timed
from app.observability.tracing import observe
from app.rag.retriever import Retriever, SearchResult

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a customer-support assistant. Reply to the customer's latest message using ONLY the numbered knowledge-base sources provided.

Rules:
- If the sources do not contain what is needed to answer, set "answerable" to false and "answer" to "". Never guess and never use outside knowledge.
- Every statement in the answer must be supported by the sources. Put the numbers of the sources you used in "citations".
- Be concise (under 120 words), friendly and practical. Give step-by-step instructions when the source has them.
- Never invent order details, prices, deadlines, policies or links.
- Do not mention "sources", "documents" or the knowledge base in the answer.

Respond with a JSON object only, in this shape: {"answerable": true, "answer": "…", "citations": [1]}"""

SPEAKER = {"customer": "Customer", "bot": "Assistant", "agent": "Agent"}


@dataclass
class Answer:
    status: str
    retrieval: SearchResult
    answer: str = ""
    citations: list[dict] = field(default_factory=list)
    error: str | None = None
    uncited: bool = False


# ── Shared retriever, hot-reloaded when `baton-ingest` rebuilds the index ──

_RELOAD_CHECK_S = 60
_retriever: Retriever | None = None
_last_check = 0.0


def get_retriever() -> Retriever:
    global _retriever, _last_check
    if _retriever is None:
        _retriever = Retriever()
        _last_check = time.monotonic()
    elif time.monotonic() - _last_check > _RELOAD_CHECK_S:
        _last_check = time.monotonic()
        try:
            built_at = json.loads((settings.index_path / "manifest.json").read_text(encoding="utf-8"))["builtAt"]
            if built_at != _retriever.manifest["builtAt"]:
                _retriever = Retriever(_retriever.embedder)  # the old one serves until this returns
                log.info("reloaded knowledge index built at %s", built_at)
        except (OSError, KeyError, ValueError, RuntimeError) as error:
            log.warning("index reload check failed: %s", error)
    return _retriever


def to_source_ref(result: dict) -> dict:
    """Source shape the desk renders (Knowledge tab, citations, copilot)."""
    return {
        "id": result["id"],
        "docId": result["docId"],
        "title": result["title"],
        "url": result["url"],
        "category": result["category"],
        "snippet": " ".join(result["text"].split())[:180],
        "score": result["similarity"],
    }


def _format_sources(results: list[dict]) -> str:
    return "\n\n".join(
        f"[{i}] {r['title']}{' › ' + ' › '.join(r['headingPath']) if r['headingPath'] else ''}\n{r['text']}" for i, r in enumerate(results, 1)
    )


def _format_history(history: list[dict]) -> str:
    return "\n".join(f"{SPEAKER[m['sender']]}: {m['text']}" for m in [m for m in history if m["sender"] in SPEAKER][-6:])


def _retrieval_query(question: str, history: list[dict]) -> str:
    """Short follow-ups ("what about express?") are searched together with the previous question."""
    previous = next((m["text"] for m in reversed(history) if m["sender"] == "customer" and m["text"] != question), None)
    return f"{previous}\n{question}" if previous and len(question.split()) < 6 else question


async def retrieve(query: str, *, audience: str = "customer", top_k: int | None = None) -> SearchResult:
    top_k = top_k or settings.rag_context_chunks
    with observe("retrieve", as_type="retriever", input={"query": query, "audience": audience, "top_k": top_k}) as span:
        with timed(stage_duration, stage="retrieve"):
            # Embedding + numpy search are CPU-bound; keep the event loop free for other requests.
            result = await asyncio.to_thread(lambda: get_retriever().search(query, audience=audience, top_k=top_k))
        span.update(
            output=[{"id": r["id"], "title": r["title"], "section": " › ".join(r["headingPath"]), "similarity": r["similarity"]} for r in result.results],
            metadata={"confidence": result.confidence},
        )
        return result


async def answer_question(question: str, *, history: list[dict] | None = None, generate: bool = True, purpose: str = "answer") -> Answer:
    history = history or []
    retrieval = await retrieve(_retrieval_query(question, history))
    if purpose == "answer":
        retrieval_confidence.labels(**label()).observe(retrieval.confidence)
    if not generate:
        return Answer("skipped", retrieval)
    if retrieval.confidence < settings.rag_no_match_threshold:
        return Answer("no_match", retrieval)

    conversation = _format_history(history)
    user = f"Sources:\n{_format_sources(retrieval.results)}\n\n"
    if conversation:
        user += f"Conversation so far:\n{conversation}\n\n"
    user += f"Latest customer message:\n{question}"

    try:
        with timed(stage_duration, stage="copilot" if purpose == "copilot" else "generate"):
            reply = await chat_json(
                purpose=purpose,
                messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}],
                response_format={"type": "json_object"},
                reasoning_effort=settings.llm_reasoning_effort or None,
            )
    except (LlmError, ValueError) as error:
        return Answer("error", retrieval, error=str(error))

    data = reply["json"] if isinstance(reply["json"], dict) else {}
    numbers = []
    for n in data.get("citations") or []:
        try:
            numbers.append(int(n))
        except (TypeError, ValueError):
            continue
    cited = [retrieval.results[n - 1] for n in dict.fromkeys(numbers) if 1 <= n <= len(retrieval.results)]
    answer = data.get("answer").strip() if isinstance(data.get("answer"), str) else ""
    # No citation, no answer: an uncited reply can't be checked, so it counts as "can't answer".
    grounded = data.get("answerable") is True and bool(answer) and bool(cited)
    if grounded:
        return Answer("answered", retrieval, answer=answer, citations=cited)
    return Answer("unanswerable", retrieval, uncited=data.get("answerable") is True and bool(answer) and not cited)


async def find_procedure(query: str) -> dict | None:
    """The best-matching internal agent procedure (ABCD), if relevant enough to suggest."""
    result = await retrieve(query, audience="agent", top_k=1)
    top = result.results[0] if result.results else None
    return top if top and top["similarity"] >= settings.rag_procedure_threshold else None
