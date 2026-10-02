"""Download a remote file only when it changed upstream."""

import hashlib
from pathlib import Path

import httpx


def _remote_version(url: str) -> str | None:
    """Cheap version check: a HEAD request, no body. Hugging Face exposes the file's content hash as
    X-Linked-ETag on its redirect; GitHub and most CDNs send ETag or Last-Modified."""
    res = httpx.head(url, follow_redirects=False, timeout=20)
    if res.status_code >= 400:
        raise RuntimeError(f"HEAD {url} → {res.status_code}")
    return res.headers.get("x-linked-etag") or res.headers.get("etag") or res.headers.get("last-modified")


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with httpx.stream("GET", url, follow_redirects=True, timeout=120) as res:
        res.raise_for_status()
        with tmp.open("wb") as f:
            for chunk in res.iter_bytes(1 << 20):
                f.write(chunk)
    tmp.replace(dest)


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def sync_remote_file(url: str, dest: Path, previous: dict | None = None) -> dict:
    """Make `dest` match the remote file, downloading only when the version header changed.

    "Changed" is then decided by the content hash, because some servers vary the header for identical
    bytes (GitHub alternates weak and strong ETags). If the network is down but a cached copy exists,
    the cached copy is used.
    """
    previous = previous or {}
    cached = dest.exists()
    try:
        version = _remote_version(url)
    except (httpx.HTTPError, RuntimeError):
        if not cached:
            raise
        return {"changed": False, "version": previous.get("version"), "contentHash": previous.get("contentHash"), "offline": True}

    if cached and version and version == previous.get("version"):
        return {"changed": False, "version": version, "contentHash": previous.get("contentHash")}
    _download(url, dest)
    content_hash = hash_file(dest)
    return {"changed": content_hash != previous.get("contentHash"), "version": version, "contentHash": content_hash}
