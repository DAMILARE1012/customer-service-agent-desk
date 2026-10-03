# syntax=docker/dockerfile:1
# Baton API. Build from the project root:  docker build -f backend/Dockerfile -t baton-api .
#
# The knowledge index and embedding models are NOT baked in (1.3 GB+): they live in the /app/data
# volume. Build them once with `baton-ingest` (see the README), or copy an existing data/ folder in.
# Configuration comes from environment variables only — no .env file is copied into the image.

FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app/backend
# Dependencies first, so code changes don't reinstall them (CPU-only PyTorch: see pyproject.toml).
COPY backend/pyproject.toml backend/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project
COPY backend/app ./app
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev


FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PATH=/app/backend/.venv/bin:$PATH
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin baton
WORKDIR /app/backend
COPY --from=build --chown=baton:baton /app/backend /app/backend
# Help-centre articles you write; published review articles are added here too (mount a volume to keep them).
COPY --chown=baton:baton content /app/content
RUN mkdir -p /app/data && chown baton:baton /app/data
USER baton
VOLUME ["/app/data"]
EXPOSE 8787
HEALTHCHECK --interval=15s --timeout=5s --start-period=120s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8787/health', timeout=4).status == 200 else 1)"
CMD ["baton-api"]
