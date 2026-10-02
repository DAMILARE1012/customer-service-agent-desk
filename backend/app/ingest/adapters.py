"""Knowledge sources. Each adapter turns one source into documents of the same shape:

    {id, title, url, category, audience: "customer" | "agent", markdown}

and implements a cheap change check (`sync`). Adding a source = one class registered in ADAPTERS.
INGEST_SOURCES picks which run, in priority order (shared text is kept by the earlier source).
"""

import hashlib
import json
import re
from collections.abc import Iterator
from pathlib import Path

from app.ingest.html_to_markdown import html_to_markdown
from app.ingest.remote_file import sync_remote_file


class LocalMarkdown:
    """Your own content: Markdown files in CONTENT_DIR, with optional front matter
    (title, category, audience: customer|agent, url)."""

    id = "local"
    boilerplate: list[re.Pattern] = []

    @staticmethod
    def _files(content_dir: Path) -> list[Path]:
        if not content_dir.exists():
            return []
        return sorted(p for p in content_dir.rglob("*") if p.is_file() and p.suffix.lower() in (".md", ".mdx"))

    @staticmethod
    def _front_matter(source: str) -> tuple[dict, str]:
        match = re.match(r"^---\r?\n([\s\S]*?)\r?\n---\r?\n?", source)
        if not match:
            return {}, source
        meta = {}
        for line in re.split(r"\r?\n", match.group(1)):
            # "# comment" needs a leading space, so url: /a#b survives
            kv = re.match(r"^\s*([\w-]+)\s*:\s*(.*?)(?:\s+#.*)?\s*$", line)
            if kv:
                meta[kv.group(1)] = re.sub(r"^[\"']|[\"']$", "", kv.group(2))
        return meta, source[match.end() :]

    def sync(self, *, content_dir: Path, previous: dict, **_) -> dict:
        # Local files are cheap to hash, so the version is a hash over every file's path and contents.
        digest = hashlib.sha256()
        for file in self._files(content_dir):
            digest.update(file.relative_to(content_dir).as_posix().encode())
            digest.update(b"\0")
            digest.update(file.read_bytes())
            digest.update(b"\0")
        version = digest.hexdigest()
        return {"changed": version != previous.get("version"), "version": version, "contentHash": version}

    def documents(self, *, content_dir: Path, limit: int | None = None, **_) -> Iterator[dict]:
        for count, file in enumerate(self._files(content_dir)):
            if limit and count >= limit:
                return
            meta, body = self._front_matter(file.read_text(encoding="utf-8"))
            relative = file.relative_to(content_dir).as_posix()
            heading = re.search(r"^#\s+(.+)$", body, re.M)
            title_from_heading = heading.group(1) if heading else None
            yield {
                "id": re.sub(r"\.mdx?$", "", relative, flags=re.I),
                "title": meta.get("title") or title_from_heading or file.stem,
                "url": meta.get("url") or relative,
                "category": meta.get("category") or relative.split("/")[0],
                "audience": "agent" if meta.get("audience") == "agent" else "customer",
                # The H1 duplicates the title, which is already prepended to every chunk's embedding input.
                "markdown": re.sub(r"^#\s+.+$", "", body, count=1, flags=re.M) if title_from_heading and not meta.get("title") else body,
            }


class WixQA:
    """Wix Help Center snapshot (6,221 articles, MIT) from the WixQA benchmark."""

    id = "wixqa"
    URL = "https://huggingface.co/datasets/Wix/WixQA/resolve/main/wix_kb_corpus/wix_kb_corpus.jsonl"
    CATEGORY = {"article": "How-to", "feature_request": "Feature request", "known_issue": "Known issue"}
    # Found by counting text repeated across the corpus. Only text with no information is listed;
    # repeated *content* (a payments FAQ shared by ~130 articles) is kept and de-duplicated instead.
    boilerplate = [
        re.compile(r"We are always working to update and improve our products,? and your feedback is (?:greatly|hugely) appreciated\.?"),
        re.compile(r"^In this article,? (?:learn|you'll learn|we'll show you)[^\n]*$", re.I | re.M),
        re.compile(r"^Click (?:on )?a question below to learn more[^\n]*$", re.I | re.M),
    ]

    def sync(self, *, raw_dir: Path, previous: dict, **_) -> dict:
        return sync_remote_file(self.URL, raw_dir / "wix_kb_corpus.jsonl", previous)

    def documents(self, *, raw_dir: Path, limit: int | None = None, **_) -> Iterator[dict]:
        with (raw_dir / "wix_kb_corpus.jsonl").open(encoding="utf-8") as f:
            count = 0
            for line in f:
                if not line.strip():
                    continue
                if limit and count >= limit:
                    return
                record = json.loads(line)
                count += 1
                yield {
                    "id": record["id"],
                    "title": record["title"],
                    "url": record["url"],
                    "category": self.CATEGORY.get(record["article_type"], record["article_type"]),
                    "audience": "customer",
                    "markdown": html_to_markdown(record["html_content"], record["url"]),
                }


class ABCD:
    """Agent procedures from the ABCD dataset (ASAPP, MIT): 55 step-by-step flows (refunds, identity
    verification, order issues…). Agent-only — never used to answer customers directly."""

    id = "abcd"
    URL = "https://raw.githubusercontent.com/asappresearch/abcd/master/data/guidelines.json"
    REPO = "https://github.com/asappresearch/abcd"
    boilerplate: list[re.Pattern] = []

    @staticmethod
    def _slug(text: str) -> str:
        return re.sub(r"^-|-$", "", re.sub(r"[^a-z0-9]+", "-", text.lower()))

    @staticmethod
    def _render(flow: dict, subflow: dict) -> str:
        instructions = subflow.get("instructions") or []
        intro, outro = (instructions[0], instructions[1:]) if instructions else (None, [])
        steps = []
        for i, action in enumerate(subflow.get("actions") or [], start=1):
            button = f" [{action['button']}]" if action.get("button") and action["button"] != "N/A" else ""
            detail = "\n".join(f"  - {line}" for line in action.get("subtext") or [])
            text = re.sub(r"\s+", " ", action["text"]).strip()
            steps.append(f"{i}.{button} {text}" + (f"\n{detail}" if detail else ""))
        parts = [f"Flow: {flow['description']}." if flow.get("description") else None, intro, "\n".join(steps), *outro]
        return "\n\n".join(p for p in parts if p)

    def sync(self, *, raw_dir: Path, previous: dict, **_) -> dict:
        return sync_remote_file(self.URL, raw_dir / "guidelines.json", previous)

    def documents(self, *, raw_dir: Path, limit: int | None = None, **_) -> Iterator[dict]:
        guidelines = json.loads((raw_dir / "guidelines.json").read_text(encoding="utf-8"))
        count = 0
        for flow_name, flow in guidelines.items():
            for subflow_name, subflow in flow["subflows"].items():
                if limit and count >= limit:
                    return
                count += 1
                yield {
                    "id": f"{self._slug(flow_name)}/{self._slug(subflow_name)}",
                    "title": f"{flow_name}: {subflow_name}",
                    "url": f"{self.REPO}#{self._slug(subflow_name)}",
                    "category": flow_name,
                    "audience": "agent",
                    "markdown": self._render(flow, subflow),
                }


ADAPTERS = {adapter.id: adapter for adapter in (LocalMarkdown(), WixQA(), ABCD())}
