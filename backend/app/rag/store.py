"""File-based vector store — enough for tens of thousands of chunks with brute-force search.

Layout (data/index/):
    manifest.json   model, dimensions, pipeline fingerprint, per-source sync state
    chunks.jsonl    one chunk per line (text + metadata); row i ↔ vector i
    vectors.f32     float32 little-endian, row-major, count × dim
    documents.json  per-source {doc_id: content_hash} for change reports
    checkpoint.*    vectors appended while embedding, so an interrupted build resumes

Swap for pgvector/Qdrant/LanceDB later by keeping load_index()/save_index() the same shape.
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from app.config import settings


def _path(name: str) -> Path:
    return settings.index_path / name


def _write_atomic(name: str, data: bytes) -> None:
    """Write to a temp file and rename, so a crash mid-write never leaves a half-written file."""
    target = _path(name)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, target)


@dataclass
class Index:
    manifest: dict | None = None
    chunks: list[dict] = field(default_factory=list)
    vectors: np.ndarray = field(default_factory=lambda: np.zeros((0, 0), dtype=np.float32))
    documents: dict = field(default_factory=dict)


def load_index() -> Index:
    if not _path("manifest.json").exists():
        return Index()
    manifest = json.loads(_path("manifest.json").read_text(encoding="utf-8"))
    chunks = [json.loads(line) for line in _path("chunks.jsonl").read_text(encoding="utf-8").splitlines() if line]
    dim = manifest["dim"]
    vectors = np.fromfile(_path("vectors.f32"), dtype="<f4") if _path("vectors.f32").exists() else np.zeros(0, dtype=np.float32)
    if vectors.size != len(chunks) * dim:
        raise RuntimeError(f"Index is inconsistent ({len(chunks)} chunks, {vectors.size // max(dim, 1)} vectors). Re-run with --rebuild.")
    documents = json.loads(_path("documents.json").read_text(encoding="utf-8")) if _path("documents.json").exists() else {}
    return Index(manifest, chunks, vectors.reshape(len(chunks), dim), documents)


def save_index(index: Index) -> None:
    settings.index_path.mkdir(parents=True, exist_ok=True)
    # Data files first, manifest last: the manifest is what marks the new index as complete.
    _write_atomic("chunks.jsonl", "\n".join(json.dumps(c, ensure_ascii=False) for c in index.chunks).encode("utf-8"))
    _write_atomic("vectors.f32", np.ascontiguousarray(index.vectors, dtype="<f4").tobytes())
    _write_atomic("documents.json", json.dumps(index.documents).encode("utf-8"))
    save_manifest(index.manifest)


def save_manifest(manifest: dict) -> None:
    settings.index_path.mkdir(parents=True, exist_ok=True)
    _write_atomic("manifest.json", json.dumps(manifest, indent=2).encode("utf-8"))


# ── Checkpoint ────────────────────────────────────────────────────────────────


def append_checkpoint(keys: list[str], vectors: np.ndarray) -> None:
    settings.index_path.mkdir(parents=True, exist_ok=True)
    # Vectors first, keys second: a crash in between leaves extra vectors, which are ignored.
    with _path("checkpoint.f32").open("ab") as f:
        f.write(np.ascontiguousarray(vectors, dtype="<f4").tobytes())
    with _path("checkpoint.keys").open("a", encoding="utf-8") as f:
        f.write("".join(f"{k}\n" for k in keys))


def load_checkpoint(dim: int) -> dict[str, np.ndarray]:
    if not _path("checkpoint.keys").exists() or not _path("checkpoint.f32").exists():
        return {}
    keys = [k for k in _path("checkpoint.keys").read_text(encoding="utf-8").splitlines() if k]
    raw = _path("checkpoint.f32").read_bytes()
    vectors = np.frombuffer(raw[: len(raw) - len(raw) % 4], dtype="<f4")
    usable = min(len(keys), vectors.size // dim)  # more vectors than keys = the last write was cut short
    rows = vectors[: usable * dim].reshape(usable, dim)
    return {key: rows[i] for i, key in enumerate(keys[:usable])}


def clear_checkpoint() -> None:
    for name in ("checkpoint.keys", "checkpoint.f32"):
        _path(name).unlink(missing_ok=True)
