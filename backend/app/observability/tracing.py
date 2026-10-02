"""Langfuse tracing (OpenTelemetry-based SDK). Without keys every helper is a no-op, so instrumented
code runs unchanged."""

from contextlib import contextmanager, nullcontext

from app.config import settings

_client = None


def init_tracing(environment: str | None = None) -> bool:
    """Create the Langfuse client once. Returns whether tracing is active."""
    global _client
    if not settings.langfuse_enabled:
        return False
    if _client is None:
        from langfuse import Langfuse

        _client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_base_url,  # the Python SDK reads LANGFUSE_HOST; we keep one name in .env
            environment=environment or settings.langfuse_tracing_environment,
        )
    return True


def get_langfuse():
    """The Langfuse client (scores, datasets, experiments), or None when not configured."""
    return _client


def observe(name: str, as_type: str = "span", **attributes):
    """Context manager for one observation (span, generation, agent, retriever, evaluator…)."""
    if _client is None:
        return nullcontext(_NoopObservation())
    return _client.start_as_current_observation(name=name, as_type=as_type, **attributes)


@contextmanager
def trace_attributes(**attributes):
    """Session/user/tags/trace name for every observation created inside (Langfuse propagate_attributes)."""
    if _client is None:
        yield
        return
    from langfuse import propagate_attributes

    with propagate_attributes(**attributes):
        yield


def current_trace_id() -> str | None:
    return _client.get_current_trace_id() if _client else None


def flush() -> None:
    if _client:
        _client.flush()


def shutdown() -> None:
    """Flush and stop the client. It can't be reused afterwards (its worker threads are gone; a second
    shutdown would wait forever on their queue), so forget it — the next init_tracing() starts fresh."""
    global _client
    if _client:
        _client.shutdown()
        _client = None


class _NoopObservation:
    def update(self, **_):
        return self

    def update_trace(self, **_):
        return self

    def score(self, **_):
        return None
