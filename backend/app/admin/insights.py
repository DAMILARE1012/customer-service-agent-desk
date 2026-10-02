"""Numbers for the admin overview, computed from the conversations themselves plus the latest offline
evaluation reports. Live time series (latency, cost, rates) stay in Grafana; traces in Langfuse."""

import json
from collections import Counter

from app.config import settings
from app.conversation.constants import REASON_LABEL, ClosedReason, Status


def _latest(pattern: str) -> dict | None:
    files = sorted(settings.eval_path.glob(pattern))
    if not files:
        return None
    try:
        return json.loads(files[-1].read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _retrieval_report() -> dict | None:
    report = _latest("report-*.json")
    if not report:
        return None
    mode = "rerank" if settings.reranker_model and "rerank" in report["retrieval"] else "hybrid"  # what production uses
    m = report["retrieval"][mode]
    return {
        "createdAt": report["createdAt"], "questions": report["questions"], "mode": mode,
        "hitAt5": m.get("hit5"), "mrr": m["mrr"], "recallAt5": m.get("recall5"), "ndcgAt5": m.get("ndcg5"),
        "noMatchThreshold": report["thresholds"]["suggestions"]["noMatchThreshold"],
    }  # fmt: skip


def _rag_report() -> dict | None:
    report = _latest("rag-*.json")
    if not report:
        return None
    s = report["summary"]
    pick = lambda name: (s.get(name) or {}).get("mean")  # noqa: E731
    return {
        "runName": report["runName"], "url": report.get("datasetRunUrl"), "model": report["config"]["model"],
        "faithfulness": pick("faithfulness"), "answerCorrectness": pick("answer_correctness"),
        "answerRelevance": pick("answer_relevance"), "contextRecall": pick("context_recall"),
        "citationCorrect": pick("citation_correct"), "handoffCorrect": pick("handoff_correct"),
        "correctAndGrounded": pick("correct_and_grounded"),
    }  # fmt: skip


def insights(conversations: list[dict]) -> dict:
    """From conversation heads with their handoff history (no transcripts needed)."""
    by_status = Counter(c["status"] for c in conversations)

    reasons, waits, handed_off = Counter(), [], 0
    for c in conversations:
        packets = [*c["handoffHistory"], *([c["handoff"]] if c["handoff"] else [])]
        handed_off += bool(packets)
        for packet in packets:
            reasons[packet["reason"]] += 1
            if packet.get("acceptedAt"):
                waits.append((packet["acceptedAt"] - packet["requestedAt"]) / 1000)

    outcomes = Counter(a["outcome"] for c in conversations for a in c["insights"]["attempts"])
    attempts = sum(outcomes.values())
    resolved = [c for c in conversations if c["status"] == Status.RESOLVED]
    resolved_by_bot = sum(1 for c in resolved if not c["handoffHistory"] and not c["handoff"])

    closed_by = Counter(c.get("closedReason") for c in resolved)
    return {
        "conversations": {"total": len(conversations), "byStatus": {s.value: by_status.get(s, 0) for s in Status}},
        "sessions": {
            "closed": len(resolved),
            "byClosedReason": {r.value: closed_by.get(r, 0) for r in ClosedReason},
            # Of the customers who were handed to a person, how many left before anyone picked up.
            "abandonmentRate": closed_by.get(ClosedReason.ABANDONED, 0) / handed_off if handed_off else None,
            "followUps": sum(1 for c in conversations if c.get("followUpOf")),
        },
        "handoffs": {
            "conversationsHandedOff": handed_off,
            "rate": handed_off / len(conversations) if conversations else None,
            "byReason": [{"reason": r, "label": REASON_LABEL[r], "count": n} for r, n in reasons.most_common()],
            "medianWaitSeconds": sorted(waits)[len(waits) // 2] if waits else None,
        },
        "bot": {
            "questions": attempts,
            "answerRate": outcomes["answered"] / attempts if attempts else None,
            "outcomes": dict(outcomes),
            "resolvedWithoutAgent": resolved_by_bot,
            "resolved": len(resolved),
        },
        "evaluation": {"retrieval": _retrieval_report(), "endToEnd": _rag_report()},
        "links": {
            "grafana": settings.grafana_url,
            "langfuse": settings.langfuse_base_url,
            "keycloakUsers": f"{settings.keycloak_url.rstrip('/')}/admin/master/console/#/{settings.keycloak_realm}/users",
        },
    }
