"""Delete traces from Langfuse (they hold the same text as the transcript). Scores attached to a trace go
with it. Langfuse deletes asynchronously; the call returns once the deletion is accepted."""

import asyncio
import logging

from app.observability.tracing import get_langfuse

log = logging.getLogger(__name__)


async def delete_traces(trace_ids: list[str]) -> dict:
    trace_ids = sorted(set(trace_ids))
    if not trace_ids:
        return {"deleted": 0}
    client = get_langfuse()
    if client is None:
        return {"deleted": 0, "error": "Langfuse isn't configured, so no traces were deleted there."}
    try:
        for start in range(0, len(trace_ids), 100):
            await asyncio.to_thread(client.api.trace.delete_multiple, trace_ids=trace_ids[start : start + 100])
        return {"deleted": len(trace_ids)}
    except Exception as error:  # noqa: BLE001 — report it; the caller decides whether that blocks anything
        log.warning("Langfuse trace deletion failed: %s", error)
        return {"deleted": 0, "error": f"Langfuse trace deletion failed: {error}"}
