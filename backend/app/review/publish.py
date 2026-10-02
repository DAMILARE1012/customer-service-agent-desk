"""Turn approved review items into lasting value.

  knowledge gap → a Markdown article in content/help-center/ (the `local` source), indexed on the next
                  ingestion — or right away with `reindex()`, which runs the local source only.
  test question → a line in data/eval/reviewed.jsonl, which `baton-eval-rag --include-reviewed` adds to
                  the Langfuse evaluation dataset.
"""

import asyncio
import json
import logging
import re
from datetime import UTC, datetime

from app.config import settings
from app.conversation.lifecycle import ApiError
from app.db import repository

log = logging.getLogger(__name__)
ARTICLE_DIR = "help-center"
REVIEWED_FILE = "reviewed.jsonl"


def slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:60].strip("-") or "article"


def _yaml(value: str) -> str:
    """A front-matter value the local adapter reads back unchanged: one line, quoted, no `#` (which
    starts a comment there)."""
    return '"' + re.sub(r"\s+", " ", value).replace("#", "").replace('"', "'").strip() + '"'


def write_article(title: str, body: str, category: str = "Support answers") -> str:
    """Write the article; returns its path relative to the content directory."""
    folder = settings.content_path / ARTICLE_DIR
    folder.mkdir(parents=True, exist_ok=True)
    slug = slugify(title)
    path, n = folder / f"{slug}.md", 2
    while path.exists():
        path, n = folder / f"{slug}-{n}.md", n + 1
    front = f"---\ntitle: {_yaml(title)}\ncategory: {_yaml(category)}\naudience: customer\nurl: /help/{path.stem}\n---\n\n"
    path.write_text(front + body.strip() + "\n", encoding="utf-8")
    return path.relative_to(settings.content_path).as_posix()


async def publish_article(item: dict, reviewer: str) -> dict:
    if item["kind"] != "knowledge_gap":
        raise ApiError(400, "Only knowledge gaps become articles.")
    if not item["title"].strip() or len(item["answer"].strip()) < 40:
        raise ApiError(400, "Give the article a title and at least a few sentences before publishing.")
    item["publishedPath"] = write_article(item["title"].strip(), item["answer"])
    item.update(status="published", reviewedBy=reviewer, reviewedAt=datetime.now(UTC).isoformat())
    return await repository().save_review_item(item)


async def approve_test_question(item: dict, reviewer: str) -> dict:
    if item["kind"] != "test_question":
        raise ApiError(400, "Only test questions can be approved into the evaluation set.")
    path = settings.eval_path / REVIEWED_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = {json.loads(line)["id"] for line in path.read_text(encoding="utf-8").splitlines() if line.strip()} if path.exists() else set()
    if item["id"] not in existing:
        row = {"id": item["id"], "question": item["question"], "answer": item["answer"], "approvedBy": reviewer, "approvedAt": datetime.now(UTC).isoformat()}
        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")
    item.update(status="approved", reviewedBy=reviewer, reviewedAt=datetime.now(UTC).isoformat())
    return await repository().save_review_item(item)


def load_reviewed_questions() -> list[dict]:
    path = settings.eval_path / REVIEWED_FILE
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


async def reindex() -> dict:
    """Index the local help centre now (only changed articles are embedded). One run at a time."""
    from app.ingest.pipeline import run_ingestion

    async with repository().exclusive("ingest") as acquired:
        if not acquired:
            raise ApiError(409, "Indexing is already running.")
        report = await asyncio.to_thread(run_ingestion, check=True, rebuild=False, reembed=False, only=["local"], limit=None, log=log.info)
    return {"total": report["total"], "embedded": report["embedded"], "reused": report["reused"], "removed": report["removedChunks"],
            "seconds": round(report["duration"], 1)}  # fmt: skip
