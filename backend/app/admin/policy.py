"""Handoff policy that admins can change at runtime.

Defaults come from .env; an admin's values are stored in the settings table and override them until
reset. The policy code reads `settings.*` on every turn, so a change applies to the next message.
"""

from app.config import settings
from app.conversation.lifecycle import ApiError
from app.db import repository

KEY = "handoff_policy"

# wire name → (settings attribute, min, max, type, help)
FIELDS = {
    "noMatchThreshold": ("rag_no_match_threshold", 0.0, 1.0, float,
                         "Below this retrieval similarity a question counts as outside the knowledge base: the bot hands off without calling the LLM."),
    "sentimentThreshold": ("rag_sentiment_threshold", -1.0, 1.0, float,
                           "At or below this sentiment (−1…1) the customer counts as frustrated and goes to a person."),
    "maxFailedAttempts": ("rag_max_failed_attempts", 1, 10, int,
                          "Turns in a row without a grounded answer before the bot stops trying."),
    "procedureThreshold": ("rag_procedure_threshold", 0.0, 1.0, float,
                           "Minimum similarity for suggesting an internal agent procedure in the handoff brief."),
}  # fmt: skip

DEFAULTS = {name: getattr(settings, attr) for name, (attr, *_rest) in FIELDS.items()}
_meta: dict = {"updatedAt": None, "updatedBy": None}


def _apply(values: dict) -> None:
    for name, value in values.items():
        attr, *_rest = FIELDS[name]
        setattr(settings, attr, value)


def current() -> dict:
    return {
        "values": {name: getattr(settings, attr) for name, (attr, *_rest) in FIELDS.items()},
        "defaults": DEFAULTS,
        "fields": {name: {"min": lo, "max": hi, "integer": kind is int, "help": text} for name, (_, lo, hi, kind, text) in FIELDS.items()},
        **_meta,
    }


async def load() -> None:
    """Apply the admin's stored values over the .env defaults (called at startup)."""
    stored = await repository().get_setting(KEY)
    if stored:
        _apply({k: v for k, v in stored["value"].items() if k in FIELDS})
        _meta.update(updatedAt=stored["updatedAt"], updatedBy=stored["updatedBy"])


def validate(values: dict) -> dict:
    clean = {}
    for name, value in values.items():
        if name not in FIELDS:
            raise ApiError(400, f'Unknown policy setting "{name}".')
        _, lo, hi, kind, _ = FIELDS[name]
        if isinstance(value, bool) or not isinstance(value, int | float) or (kind is int and int(value) != value):
            raise ApiError(400, f'"{name}" must be {"a whole number" if kind is int else "a number"}.')
        if not lo <= value <= hi:
            raise ApiError(400, f'"{name}" must be between {lo} and {hi}.')
        clean[name] = kind(value)
    return clean


async def update(values: dict, admin: dict) -> dict:
    clean = validate(values)
    merged = {**current()["values"], **clean}
    stored = await repository().set_setting(KEY, merged, admin["name"])
    _apply(merged)
    _meta.update(updatedAt=stored["updatedAt"], updatedBy=stored["updatedBy"])
    return current()


async def reset(admin: dict) -> dict:
    stored = await repository().set_setting(KEY, DEFAULTS, admin["name"])
    _apply(DEFAULTS)
    _meta.update(updatedAt=stored["updatedAt"], updatedBy=stored["updatedBy"])
    return current()
