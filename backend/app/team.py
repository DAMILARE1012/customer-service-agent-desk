"""Is anyone there to help? Business hours, agent presence and the customer's place in the queue.

    available   inside business hours AND at least one agent online (active, set to Online, and with the
                desk open in the last AGENT_PRESENCE_SECONDS — the desk polls, which refreshes lastSeenAt)
    business    admin-set opening hours in a time zone; not configured = always staffed

When nobody is available the bot says so honestly, asks for an email if it has none, and the request
stays in the queue for the team's return instead of being closed as abandoned (see sessions.py).
"""

import math
import re
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import settings
from app.conversation.constants import Status
from app.conversation.lifecycle import ApiError
from app.conversation.offline import mask_email, reply_email
from app.db import repository

KEY = "business_hours"
DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")
DEFAULT_HOURS = {"enabled": False, "timezone": "UTC", "days": [0, 1, 2, 3, 4], "open": "09:00", "close": "17:00"}

_hours: dict = dict(DEFAULT_HOURS)
_cache: dict = {"at": 0.0, "status": None, "wait": (0.0, None)}


# ── Business hours ───────────────────────────────────────────────────────────


def business_hours() -> dict:
    return dict(_hours)


def validate_hours(value: dict) -> dict:
    clean = {**DEFAULT_HOURS, **{k: v for k, v in value.items() if k in DEFAULT_HOURS}}
    if not isinstance(clean["enabled"], bool):
        raise ApiError(400, '"enabled" must be true or false.')
    try:
        ZoneInfo(str(clean["timezone"]))
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise ApiError(400, f'Unknown time zone "{clean["timezone"]}" — use a name like "Africa/Lagos" or "Europe/London".') from error
    days = clean["days"]
    if not isinstance(days, list) or not days or any(not isinstance(d, int) or isinstance(d, bool) or not 0 <= d <= 6 for d in days):
        raise ApiError(400, '"days" must list at least one day, 0 (Monday) to 6 (Sunday).')
    clean["days"] = sorted(set(days))
    for field in ("open", "close"):
        if not isinstance(clean[field], str) or not HHMM.match(clean[field]):
            raise ApiError(400, f'"{field}" must be a time like "09:00".')
    if clean["open"] >= clean["close"]:
        raise ApiError(400, "Opening time must be before closing time (overnight hours aren’t supported).")
    return clean


async def load_hours() -> None:
    stored = await repository().get_setting(KEY)
    _hours.clear()
    _hours.update(validate_hours(stored["value"]) if stored else DEFAULT_HOURS)
    _cache["status"] = None


async def save_hours(value: dict, updated_by: str) -> dict:
    clean = validate_hours(value)
    await repository().set_setting(KEY, clean, updated_by)
    _hours.clear()
    _hours.update(clean)
    _cache["status"] = None
    return business_hours()


def _minutes(hhmm: str) -> int:
    hours, minutes = hhmm.split(":")
    return int(hours) * 60 + int(minutes)


def is_open(now_ms: int, hours: dict | None = None) -> bool:
    hours = hours or _hours
    if not hours["enabled"]:
        return True
    local = datetime.fromtimestamp(now_ms / 1000, ZoneInfo(hours["timezone"]))
    minute = local.hour * 60 + local.minute
    return local.weekday() in hours["days"] and _minutes(hours["open"]) <= minute < _minutes(hours["close"])


def next_open(now_ms: int, hours: dict | None = None) -> int | None:
    """When the team is next scheduled to be in (epoch ms), or None if always open / open now."""
    hours = hours or _hours
    if not hours["enabled"] or is_open(now_ms, hours):
        return None
    zone = ZoneInfo(hours["timezone"])
    local = datetime.fromtimestamp(now_ms / 1000, zone)
    open_h, open_m = (int(x) for x in hours["open"].split(":"))
    for offset in range(8):
        day = local + timedelta(days=offset)
        start = day.replace(hour=open_h, minute=open_m, second=0, microsecond=0)
        if day.weekday() in hours["days"] and start > local:
            return int(start.timestamp() * 1000)
    return None


def describe(at_ms: int | None, hours: dict | None = None) -> str | None:
    """'Monday at 09:00 (WAT)' — in the business's own time zone, which the customer can read anywhere."""
    if at_ms is None:
        return None
    hours = hours or _hours
    local = datetime.fromtimestamp(at_ms / 1000, ZoneInfo(hours["timezone"]))
    return f"{DAY_NAMES[local.weekday()]} at {local:%H:%M} ({local.tzname()})"


# ── Presence and availability ────────────────────────────────────────────────


async def status(now_ms: int) -> dict:
    """{available, open, agentsOnline, backAt, backAtText}; cached briefly (customers poll every few seconds)."""
    if _cache["status"] and time.monotonic() - _cache["at"] < 10:
        return _cache["status"]
    online = len(await repository().available_agents(settings.agent_presence_seconds))
    open_now = is_open(now_ms)
    back_at = next_open(now_ms)
    result = {"available": open_now and online > 0, "open": open_now, "agentsOnline": online, "backAt": back_at, "backAtText": describe(back_at)}
    _cache.update(at=time.monotonic(), status=result)
    return result


def forget_status() -> None:
    _cache["status"] = None


async def _typical_wait_ms(now_ms: int) -> float | None:
    at, value = _cache["wait"]
    if time.monotonic() - at < 60:
        return value
    value = await repository().typical_handoff_wait_ms(since=now_ms - 7 * 86_400_000)
    _cache["wait"] = (time.monotonic(), value)
    return value


# ── What the waiting customer is told ────────────────────────────────────────

__all__ = ["mask_email", "reply_email"]  # re-exported for callers of this module


async def waiting_info(conversation: dict, now_ms: int) -> dict | None:
    """For a customer waiting for a person: their place in line, a typical wait, and whether anyone is in."""
    if conversation["status"] != Status.HANDOFF_PENDING:
        return None
    team = await status(now_ms)
    ahead = await repository().handoffs_ahead(conversation["id"])
    typical = await _typical_wait_ms(now_ms) if team["available"] else None
    email = reply_email(conversation)
    return {
        "position": ahead + 1,
        "estimatedMinutes": max(1, math.ceil(typical / 60_000)) if typical else None,
        "teamAvailable": team["available"],
        "backAtText": team["backAtText"],
        "replyEmail": mask_email(email),
        "askForEmail": email is None,
    }


def valid_email(value: str) -> str:
    email = value.strip()
    if not EMAIL.match(email) or len(email) > 254:
        raise ApiError(400, "That doesn’t look like an email address.")
    return email
