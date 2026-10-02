"""Online evaluation: a sample of live answers is scored by the LLM judge in the background
(faithfulness, relevance — live traffic has no reference answer). Scores attach to the answer's trace
in Langfuse and feed the online_eval_score histogram in Prometheus. Never blocks a reply."""

import asyncio
import logging
import random

from app.config import settings
from app.eval.judge import judge
from app.observability.metrics import label, online_eval_score
from app.observability.tracing import get_langfuse, observe, trace_attributes

log = logging.getLogger(__name__)
MAX_QUEUE = 100  # under load, drop samples rather than pile up judge calls
_queue: asyncio.Queue | None = None
_worker: asyncio.Task | None = None


def start() -> None:
    global _queue, _worker
    _queue = asyncio.Queue(maxsize=MAX_QUEUE)
    _worker = asyncio.create_task(_drain())


async def stop() -> None:
    if _worker:
        _worker.cancel()


def maybe_score_answer(*, trace_id: str | None, question: str, contexts: list[str], answer: str) -> None:
    rate = settings.online_eval_sample_rate
    if not (_queue and trace_id and answer and rate > 0 and random.random() < rate):
        return
    try:
        _queue.put_nowait({"trace_id": trace_id, "question": question, "contexts": contexts, "answer": answer})
    except asyncio.QueueFull:
        pass


async def _drain() -> None:
    while True:
        job = await _queue.get()
        try:
            with trace_attributes(trace_name="online-eval", tags=["evaluation", "online"]):
                with observe("online-eval", as_type="evaluator", input={"question": job["question"], "answer": job["answer"]},
                             metadata={"scoredTraceId": job["trace_id"]}) as span:  # fmt: skip
                    verdict = await judge(question=job["question"], contexts=job["contexts"], answer=job["answer"])
                    span.update(output=verdict)
            _record(job["trace_id"], verdict)
        except Exception as error:  # noqa: BLE001 — evaluation must never take the API down
            log.warning("online eval skipped: %s", error)


def _record(trace_id: str, verdict: dict | None) -> None:
    if not verdict:
        return
    langfuse = get_langfuse()
    unsupported = verdict["unsupported_claims"]
    scores = [
        ("faithfulness", verdict["faithfulness"], f"Unsupported: {' | '.join(unsupported)}" if unsupported else verdict["reasoning"]),
        ("answer_relevance", verdict["answer_relevance"], verdict["reasoning"]),
    ]
    for name, value, comment in scores:
        if value is None:
            continue
        online_eval_score.labels(**label(metric=name)).observe(value)
        if langfuse:
            langfuse.create_score(trace_id=trace_id, name=name, value=value, comment=comment, data_type="NUMERIC")
