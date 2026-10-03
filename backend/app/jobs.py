"""Background jobs for the API's lifetime. Every API process runs them; the ones that must not run twice
at once take a cross-process lock, the rest are safe to repeat.

    sessions    close idle and abandoned sessions          every SESSION_SWEEP_SECONDS
    policy      pick up handoff-policy and business-hours changes from admins  every 15 s (made in any process)
    alerts      escalate handoffs waiting too long (email / webhook)            every 30 s
    retention   wipe transcripts past RETENTION_DAYS        hourly
    review      learn from closed sessions                  every REVIEW_INTERVAL_MINUTES
"""

import asyncio
import logging

from app import team
from app.admin import policy as admin_policy
from app.config import settings
from app.conversation import sessions
from app.db import repository
from app.notify import alerts
from app.privacy.retention import apply_retention
from app.review.pipeline import run_review

log = logging.getLogger(__name__)


async def _every(name: str, seconds, job, *, exclusive: bool) -> None:
    while True:
        await asyncio.sleep(seconds())
        try:
            if exclusive:
                async with repository().exclusive(f"job:{name}") as acquired:
                    if acquired:
                        await job()
            else:
                await job()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — one failed run must never stop the loop
            log.exception("background job %s failed", name)


async def _reload_settings() -> None:
    await admin_policy.load()
    await team.load_hours()


def start() -> list[asyncio.Task]:
    jobs = [
        ("sessions", lambda: settings.session_sweep_seconds, sessions.sweep, False),  # row locks make it safe to overlap
        ("policy", lambda: 15, _reload_settings, False),
        ("alerts", lambda: 30, alerts.escalate_waiting_handoffs, True),
        ("retention", lambda: 3600, apply_retention, True),
    ]
    if settings.review_interval_minutes > 0:
        jobs.append(("review", lambda: settings.review_interval_minutes * 60, run_review, False))  # run_review locks itself
    return [asyncio.create_task(_every(name, seconds, job, exclusive=exclusive), name=f"job:{name}") for name, seconds, job, exclusive in jobs]


async def stop(tasks: list[asyncio.Task]) -> None:
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
