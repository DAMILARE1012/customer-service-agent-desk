"""Sliding-window rate limits for the public widget endpoints. Per process: with several API processes
behind a load balancer each enforces its own window, so the effective limit is a small multiple —
fine for abuse protection; put a shared limiter (e.g. at the proxy) in front for hard quotas."""

import time
from collections import defaultdict, deque

from app.conversation.lifecycle import ApiError


class RateLimiter:
    def __init__(self, limit: int, window_s: float, message: str) -> None:
        self.limit, self.window_s, self.message = limit, window_s, message
        self._hits: dict[str, deque] = defaultdict(deque)

    def check(self, key: str) -> None:
        now = time.monotonic()
        hits = self._hits[key]
        while hits and now - hits[0] > self.window_s:
            hits.popleft()
        if len(hits) >= self.limit:
            raise ApiError(429, self.message)
        hits.append(now)

    def reset(self) -> None:
        self._hits.clear()
