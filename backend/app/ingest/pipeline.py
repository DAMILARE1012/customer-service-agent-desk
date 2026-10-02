"""Incremental ingestion. Change detection runs at three levels, cheapest first:

1. source   — skipped inside its refresh window, or when upstream reports the same content
2. document — content hashes report added / changed / removed documents
3. chunk    — a vector is reused whenever the exact embedding input was seen before (same model)
"""

import hashlib
import json
import time
from collections.abc import Callable
from datetime import UTC, datetime

import numpy as np

from app.config import settings
from app.ingest.adapters import ADAPTERS
from app.ingest.chunker import CHUNKER_VERSION, chunk_markdown
from app.ingest.normalize import NORMALIZER_VERSION, clean_text, index_form
from app.rag.embedder import Embedder, get_embedder
from app.rag.retriever import embed_input
from app.rag.store import (
    Index,
    append_checkpoint,
    clear_checkpoint,
    load_checkpoint,
    load_index,
    save_index,
    save_manifest,
)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _fingerprint(embedder: Embedder) -> str:
    """Anything that changes how documents are parsed or chunked; a change forces sources to re-parse."""
    return _sha(json.dumps({
        "normalizer": NORMALIZER_VERSION,
        "chunker": CHUNKER_VERSION,
        "chunking": [settings.chunk_min_tokens, settings.chunk_target_tokens, settings.chunk_max_tokens],
        "model": embedder.signature,
    }))  # fmt: skip


def _process_source(adapter, embedder: Embedder, limit: int | None) -> tuple[list[dict], dict]:
    chunks, documents = [], {}
    context = {"raw_dir": settings.raw_path / adapter.id, "content_dir": settings.content_path, "limit": limit}
    for doc in adapter.documents(**context):
        title = clean_text(doc["title"])
        body = clean_text(doc["markdown"], adapter.boilerplate)
        if not body:
            continue
        documents[doc["id"]] = _sha(f"{title}\n{body}")
        pieces = chunk_markdown(
            body,
            embedder.count_tokens,
            min_tokens=settings.chunk_min_tokens,
            target_tokens=settings.chunk_target_tokens,
            max_tokens=settings.chunk_max_tokens,
        )
        for ordinal, piece in enumerate(pieces):
            chunk = {
                "id": f"{adapter.id}:{doc['id']}#{ordinal}",
                "source": adapter.id,
                "docId": doc["id"],
                "ordinal": ordinal,
                "title": title,
                "headingPath": piece.heading_path,
                "url": doc["url"],
                "category": doc["category"],
                "audience": doc["audience"],
                "text": piece.text,
                "tokens": piece.tokens,
            }
            chunk["key"] = _sha(f"{embedder.signature}\n{embed_input(chunk)}")
            chunks.append(chunk)
    return chunks, documents


def _mark_duplicates(chunks: list[dict]) -> int:
    """Identical text across documents (a FAQ pasted into 130 articles) is searched once. Duplicates stay
    in the index pointing at the canonical chunk, so nothing is lost if the canonical's article goes."""
    canonical_by_text: dict[str, dict] = {}
    duplicates = 0
    for chunk in chunks:
        text_hash = _sha(index_form(chunk["text"]))
        canonical = canonical_by_text.get(text_hash)
        if canonical and canonical["docId"] != chunk["docId"]:
            chunk["duplicateOf"] = canonical["id"]
            duplicates += 1
        else:
            chunk.pop("duplicateOf", None)
            canonical_by_text.setdefault(text_hash, chunk)
    return duplicates


def _diff_documents(previous: dict, current: dict) -> dict:
    return {
        "added": sum(1 for i in current if i not in previous),
        "changed": sum(1 for i, h in current.items() if i in previous and previous[i] != h),
        "removed": sum(1 for i in previous if i not in current),
        "unchanged": sum(1 for i, h in current.items() if previous.get(i) == h),
    }


def run_ingestion(*, check=False, rebuild=False, reembed=False, only: list[str] | None = None, limit: int | None = None, log: Callable[[str], None] = print) -> dict:
    started = time.time()
    embedder = get_embedder()
    previous = load_index()
    fingerprint = _fingerprint(embedder)
    same_pipeline = bool(previous.manifest) and previous.manifest["fingerprint"] == fingerprint
    now = int(time.time() * 1000)

    unknown = [s for s in settings.sources if s not in ADAPTERS]
    if unknown:
        raise ValueError(f"Unknown source(s) in INGEST_SOURCES: {', '.join(unknown)}. Known: {', '.join(ADAPTERS)}")
    if only and previous.manifest and not same_pipeline:
        raise ValueError("Model, normalizer or chunker settings changed since the last build, so every source must be rebuilt. Run without --source.")

    reports, next_sources, next_documents, all_chunks = [], {}, {}, []
    processed_any = False

    for source_id in settings.sources:
        adapter = ADAPTERS[source_id]
        state = (previous.manifest or {}).get("sources", {}).get(source_id)
        previous_chunks = [c for c in previous.chunks if c["source"] == source_id]
        reusable = same_pipeline and state is not None and state.get("limit") == limit and not rebuild

        def keep(reason: str, state=state, previous_chunks=previous_chunks, source_id=source_id):
            all_chunks.extend(previous_chunks)
            next_documents[source_id] = previous.documents.get(source_id, {})
            reports.append({"source": source_id, "action": "kept", "reason": reason, "chunks": len(previous_chunks)})

        if only and source_id not in only:  # carried over untouched (or left out if never ingested)
            if state:
                next_sources[source_id] = state
                keep("not selected")
            else:
                reports.append({"source": source_id, "action": "skipped", "reason": "not selected, never ingested", "chunks": 0})
            continue

        refresh_ms = settings.refresh_minutes.get(source_id, 0) * 60_000
        if reusable and not check and refresh_ms > 0 and now - state["checkedAt"] < refresh_ms:
            next_sources[source_id] = state
            keep(f"checked {round((now - state['checkedAt']) / 60_000)} min ago (refresh every {refresh_ms / 60_000:g} min)")
            continue

        log(f"[{source_id}] checking upstream…")
        sync = adapter.sync(raw_dir=settings.raw_path / source_id, content_dir=settings.content_path, previous=state or {})
        if reusable and not sync["changed"]:
            next_sources[source_id] = {**state, "version": sync["version"], "contentHash": sync.get("contentHash") or state.get("contentHash"), "checkedAt": now}
            keep("upstream unreachable — using cached copy" if sync.get("offline") else "unchanged upstream")
            continue

        why = (
            "first ingestion" if not state
            else "changed upstream" if sync["changed"]
            else "--rebuild" if rebuild
            else "normalizer, chunker or model settings changed" if not same_pipeline
            else "document limit changed"
        )  # fmt: skip
        log(f"[{source_id}] {why} — processing documents…")
        chunks, documents = _process_source(adapter, embedder, limit)
        all_chunks.extend(chunks)
        next_documents[source_id] = documents
        next_sources[source_id] = {
            "version": sync["version"], "contentHash": sync.get("contentHash"), "checkedAt": now, "processedAt": now,
            "limit": limit, "documents": len(documents), "chunks": len(chunks),
        }  # fmt: skip
        reports.append({"source": source_id, "action": "processed", "documents": _diff_documents(previous.documents.get(source_id, {}), documents), "chunks": len(chunks)})
        processed_any = True

    removed_sources = [s for s in (previous.manifest or {}).get("sources", {}) if s not in next_sources]
    if not processed_any and not removed_sources and same_pipeline and not reembed:
        save_manifest({**previous.manifest, "sources": next_sources})
        return {"sources": reports, "removedSources": [], "embedded": 0, "reused": len(previous.chunks), "resumed": 0,
                "removedChunks": 0, "total": len(previous.chunks), "duration": time.time() - started, "wrote": "manifest only"}  # fmt: skip

    # Reuse vectors by key; embed only what's new.
    duplicates = _mark_duplicates(all_chunks)
    previous_row = {}
    if not reembed and previous.manifest:
        previous_row = {c["key"]: i for i, c in enumerate(previous.chunks) if not c.get("duplicateOf")}  # a duplicate's row holds its canonical's vector
    if reembed:
        clear_checkpoint()
    checkpoint = {} if reembed else load_checkpoint(embedder.dim)

    vector_by_key: dict[str, np.ndarray] = {}
    to_embed: list[dict] = []
    resumed = 0
    for chunk in all_chunks:
        if chunk.get("duplicateOf") or chunk["key"] in vector_by_key:
            continue
        if chunk["key"] in previous_row:
            vector_by_key[chunk["key"]] = previous.vectors[previous_row[chunk["key"]]]
        elif chunk["key"] in checkpoint:
            vector_by_key[chunk["key"]] = checkpoint[chunk["key"]]
            resumed += 1
        else:
            to_embed.append(chunk)
    reused = len(vector_by_key) - resumed

    if to_embed:
        log(f"Embedding {len(to_embed)} new or changed chunks ({reused} reused{f', {resumed} resumed from an interrupted run' if resumed else ''})…")
        # Batches are padded to their longest input; similar lengths together waste less compute.
        to_embed.sort(key=lambda c: c["tokens"])
        embed_started = time.time()
        batch_size = settings.embedding_batch_size
        for start in range(0, len(to_embed), batch_size):
            batch = to_embed[start : start + batch_size]
            vectors = embedder.embed_documents([embed_input(c) for c in batch])
            for chunk, vector in zip(batch, vectors, strict=True):
                vector_by_key[chunk["key"]] = vector
            append_checkpoint([c["key"] for c in batch], vectors)  # an interruption resumes from here
            done = min(start + batch_size, len(to_embed))
            if done == len(to_embed) or (start // batch_size) % 25 == 0:
                rate = done / max(time.time() - embed_started, 1e-6)
                log(f"  {done}/{len(to_embed)} ({rate:.1f}/s, ~{(len(to_embed) - done) / rate:.0f}s left)")

    by_id = {c["id"]: c for c in all_chunks}
    dim = embedder.dim
    matrix = np.zeros((len(all_chunks), dim), dtype=np.float32)
    for row, chunk in enumerate(all_chunks):
        owner = by_id[chunk["duplicateOf"]] if chunk.get("duplicateOf") else chunk
        matrix[row] = vector_by_key[owner["key"]]

    current_keys = {c["key"] for c in all_chunks}
    removed_chunks = sum(1 for c in previous.chunks if c["key"] not in current_keys)
    save_index(Index(
        manifest={
            "formatVersion": 1,
            "builtAt": datetime.fromtimestamp(now / 1000, UTC).isoformat().replace("+00:00", "Z"),
            "fingerprint": fingerprint,
            "embedding": {"model": embedder.model, "signature": embedder.signature},
            "dim": dim,
            "normalizerVersion": NORMALIZER_VERSION,
            "chunkerVersion": CHUNKER_VERSION,
            "chunking": {"minTokens": settings.chunk_min_tokens, "targetTokens": settings.chunk_target_tokens, "maxTokens": settings.chunk_max_tokens},
            "count": len(all_chunks),
            "duplicates": duplicates,
            "sources": next_sources,
        },
        chunks=all_chunks,
        vectors=matrix,
        documents=next_documents,
    ))  # fmt: skip
    clear_checkpoint()  # everything is in the index now

    return {"sources": reports, "removedSources": removed_sources, "embedded": len(to_embed), "reused": reused, "resumed": resumed,
            "duplicates": duplicates, "removedChunks": removed_chunks, "total": len(all_chunks), "duration": time.time() - started, "wrote": "full index"}  # fmt: skip
