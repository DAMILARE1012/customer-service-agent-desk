"""Prometheus metrics, served on GET /metrics.

Names and labels match the Grafana dashboard and alert rules in observability/. Labels only take a
handful of values (model, stage, reason…) — never conversation or customer IDs, which would explode
cardinality. Per-conversation detail lives in Langfuse traces instead.
"""

import sys
import time
from collections.abc import Callable
from contextlib import contextmanager

from prometheus_client import CollectorRegistry, Counter, Histogram, ProcessCollector
from prometheus_client.core import GaugeMetricFamily

registry = CollectorRegistry()
ProcessCollector(registry=registry)  # CPU and memory on Linux (e.g. in Docker); a psutil fallback covers Windows below


def _metric(cls, name: str, doc: str, labels: tuple[str, ...] = (), **kwargs):
    return cls(name, doc, labels, registry=registry, **kwargs)


# ── HTTP ──────────────────────────────────────────────────────────────────────
http_requests = _metric(Counter, "http_requests", "HTTP requests by route and status", ("method", "route", "status", "service"))
http_duration = _metric(Histogram, "http_request_duration_seconds", "HTTP request latency", ("method", "route", "service"),
                        buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 4, 8, 16))  # fmt: skip

# ── RAG pipeline ──────────────────────────────────────────────────────────────
stage_duration = _metric(Histogram, "rag_stage_duration_seconds", "Latency of each pipeline stage", ("stage", "service"),
                         buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 4, 8, 16))  # fmt: skip
retrieval_confidence = _metric(Histogram, "rag_retrieval_confidence", "Cosine similarity of the top retrieved chunk per bot turn", ("service",),
                               buckets=(0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95))  # fmt: skip
bot_turns = _metric(Counter, "rag_bot_turns", "Bot turns by outcome", ("outcome", "service"))

# ── LLM (Groq) ────────────────────────────────────────────────────────────────
llm_requests = _metric(Counter, "llm_requests", "LLM calls by model, purpose and result", ("model", "purpose", "status", "service"))
llm_duration = _metric(Histogram, "llm_request_duration_seconds", "LLM call latency including retries", ("model", "purpose", "service"),
                       buckets=(0.1, 0.25, 0.5, 1, 2, 4, 8, 16, 32))  # fmt: skip
llm_tokens = _metric(Counter, "llm_tokens", "Tokens used", ("model", "purpose", "type", "service"))
llm_cost = _metric(Counter, "llm_cost_usd", "Estimated LLM spend (from LLM_PRICES_PER_MILLION)", ("model", "purpose", "service"))

# ── Handoff & desk ────────────────────────────────────────────────────────────
handoffs = _metric(Counter, "handoffs", "Handoffs to a human by primary reason and priority", ("reason", "priority", "service"))
handoff_wait = _metric(Histogram, "handoff_wait_seconds", "Time from handoff to an agent accepting it", ("priority", "service"),
                       buckets=(15, 30, 60, 120, 300, 600, 1200, 1800, 3600))  # fmt: skip
conversations_closed = _metric(Counter, "conversations_closed", "Support sessions ended, by why they ended", ("reason", "service"))
copilot_drafts = _metric(Counter, "copilot_drafts", "What agents did with the copilot draft when they replied", ("action", "service"))
notifications = _metric(Counter, "notifications", "Emails and webhooks to customers and agents, by outcome", ("channel", "kind", "outcome", "service"))
online_eval_score = _metric(Histogram, "online_eval_score", "LLM-judge scores on sampled live answers (0–1)", ("metric", "service"),
                            buckets=(0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1))  # fmt: skip

SERVICE = "baton-api"


def label(**labels) -> dict:
    return {**labels, "service": SERVICE}


@contextmanager
def timed(histogram: Histogram, **labels):
    started = time.perf_counter()
    try:
        yield
    finally:
        histogram.labels(**label(**labels)).observe(time.perf_counter() - started)


class StateCollector:
    """Gauges computed at scrape time from live state (conversation store, knowledge index)."""

    def __init__(self, read_desk: Callable[[], dict], read_index: Callable[[], dict]):
        self.read_desk, self.read_index = read_desk, read_index

    def collect(self):
        desk, index = self.read_desk(), self.read_index()
        conversations = GaugeMetricFamily("conversations", "Open conversations by status", labels=["status", "service"])
        for status, count in desk["byStatus"].items():
            conversations.add_metric([status, SERVICE], count)
        yield conversations
        oldest = GaugeMetricFamily("handoff_queue_oldest_wait_seconds", "How long the longest-waiting handoff has been waiting", labels=["service"])
        oldest.add_metric([SERVICE], desk["oldestHandoffWaitSeconds"])
        yield oldest
        sla = GaugeMetricFamily("handoff_sla_breaches", "Handoffs currently waiting longer than the breach SLA", labels=["service"])
        sla.add_metric([SERVICE], desk["slaBreaches"])
        yield sla
        chunks = GaugeMetricFamily("knowledge_index_chunks", "Searchable chunks in the knowledge index", labels=["service"])
        chunks.add_metric([SERVICE], index["chunks"])
        yield chunks
        checked = GaugeMetricFamily("knowledge_source_last_checked_timestamp_seconds", "When each knowledge source was last checked for changes", labels=["source", "service"])
        for source, at in index["checkedAt"].items():
            checked.add_metric([source, SERVICE], at / 1000)
        yield checked
        if sys.platform != "linux":  # prometheus_client's process collector only works on Linux (/proc)
            import psutil

            memory = GaugeMetricFamily("process_resident_memory_bytes", "Resident memory size in bytes", labels=["service"])
            memory.add_metric([SERVICE], psutil.Process().memory_info().rss)
            yield memory
