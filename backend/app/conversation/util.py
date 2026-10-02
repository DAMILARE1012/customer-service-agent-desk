import math
import time
import uuid


def next_id(prefix: str) -> str:
    """Unique across restarts and processes (conversations are persisted), e.g. conv_3f9c1a7e2b4d."""
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def now_ms() -> int:
    """Epoch milliseconds — the timestamp format the desk uses everywhere."""
    return int(time.time() * 1000)


def round2(value: float) -> float:
    """Half-up rounding to 2 decimals (matches JavaScript's Math.round, unlike Python's banker's round)."""
    return math.floor(value * 100 + 0.5) / 100


def truncate(text: str, limit: int = 80) -> str:
    return f"{text[: limit - 1].rstrip()}…" if len(text) > limit else text


def pct(value: float) -> str:
    return f"{math.floor(value * 100 + 0.5)}%"
