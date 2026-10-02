"""Heading-aware chunking.

Sections never share a chunk, except that a section smaller than `min_tokens` is folded into the
next one (heading kept inline). That keeps edits local: changing one section only changes that
section's chunks, so only they get re-embedded. Fixed-size windows would shift every later chunk.

Bump CHUNKER_VERSION when the rules change (part of the pipeline fingerprint).
"""

import re
from collections.abc import Callable
from dataclasses import dataclass

CHUNKER_VERSION = 3

HEADING = re.compile(r"^(#{1,6})\s+(.+)$")
CountTokens = Callable[[str], int]


@dataclass
class Chunk:
    heading_path: list[str]
    text: str
    tokens: int


def _to_sections(markdown: str) -> list[dict]:
    sections, path = [], []
    current = {"heading_path": [], "heading": None, "blocks": []}
    for block in re.split(r"\n{2,}", markdown):
        # Hand-written markdown often has text directly under the heading ("# Title\nBody").
        first, *rest = block.strip().split("\n")
        match = HEADING.match(first)
        if not match:
            if block.strip():
                current["blocks"].append(block.strip())
            continue
        sections.append(current)
        level, title = len(match.group(1)), match.group(2).strip()
        while path and path[-1][0] >= level:
            path.pop()
        path.append((level, title))
        current = {"heading_path": [t for _, t in path], "heading": first, "blocks": []}
        body = "\n".join(rest).strip()
        if body:
            current["blocks"].append(body)
    sections.append(current)
    return [s for s in sections if s["blocks"]]


def _split_oversized(block: str, count: CountTokens, max_tokens: int) -> list[str]:
    """Break one oversized block into pieces that fit: by line, then sentence, then word."""
    splitters = [lambda t: t.split("\n"), lambda t: re.split(r"(?<=[.!?])\s+", t), lambda t: t.split()]
    joiners = ["\n", " ", " "]

    def split(text: str, level: int) -> list[str]:
        if count(text) <= max_tokens or level >= len(splitters):
            return [text]
        parts = [p for p in splitters[level](text) if p]
        if len(parts) == 1:
            return split(text, level + 1)
        pieces, buffer = [], ""
        for part in parts:
            candidate = f"{buffer}{joiners[level]}{part}" if buffer else part
            if count(candidate) <= max_tokens:
                buffer = candidate
            else:
                if buffer:
                    pieces.append(buffer)
                buffer = part
        if buffer:
            pieces.append(buffer)
        return [p for piece in pieces for p in split(piece, level + 1)]

    return split(block, 0)


def _glue_headings(pieces: list[str]) -> list[str]:
    """An inline heading (from a folded-in small section) must stay with the block after it."""
    glued, i = [], 0
    while i < len(pieces):
        if HEADING.match(pieces[i]) and i + 1 < len(pieces):
            glued.append(f"{pieces[i]}\n{pieces[i + 1]}")
            i += 2
        else:
            glued.append(pieces[i])
            i += 1
    return glued


def _pack(blocks: list[str], count: CountTokens, min_tokens: int, target_tokens: int, max_tokens: int) -> list[str]:
    pieces = [p for block in _glue_headings(blocks) for p in _split_oversized(block, count, max_tokens)]
    chunks, buffer, tokens = [], [], 0
    for piece in pieces:
        size = count(piece)
        # Close at the target — but never while still tiny (an intro like "do the following:" belongs
        # with the list after it), unless that would exceed max.
        over_target = tokens + size > target_tokens and tokens >= min_tokens
        if buffer and (over_target or tokens + size > max_tokens):
            chunks.append("\n\n".join(buffer))
            buffer, tokens = [], 0
        buffer.append(piece)
        tokens += size
    if buffer:
        tail = "\n\n".join(buffer)
        # A tiny remainder reads better as the end of the previous chunk than as a chunk of its own.
        if chunks and tokens < min_tokens and count(f"{chunks[-1]}\n\n{tail}") <= max_tokens:
            chunks[-1] = f"{chunks[-1]}\n\n{tail}"
        else:
            chunks.append(tail)
    return chunks


def chunk_markdown(markdown: str, count: CountTokens, *, min_tokens: int, target_tokens: int, max_tokens: int) -> list[Chunk]:
    merged, carry = [], None
    for section in _to_sections(markdown):
        if carry:
            blocks = [*carry["blocks"], *([section["heading"]] if section["heading"] else []), *section["blocks"]]
            heading_path = carry["heading_path"]
        else:
            blocks, heading_path = section["blocks"], section["heading_path"]
        candidate = {"heading_path": heading_path, "blocks": blocks}
        if count("\n\n".join(blocks)) < min_tokens:
            carry = candidate
        else:
            merged.append(candidate)
            carry = None

    # A small trailing section joins the previous one if it fits; otherwise it stands alone.
    if carry:
        last = merged[-1] if merged else None
        same = last is not None and carry["heading_path"] == last["heading_path"]
        tail = carry["blocks"] if same or not carry["heading_path"] else [f"## {carry['heading_path'][-1]}", *carry["blocks"]]
        if last is not None and count("\n\n".join([*last["blocks"], *tail])) <= max_tokens:
            last["blocks"].extend(tail)
        else:
            merged.append(carry)

    return [
        Chunk(heading_path=section["heading_path"], text=text, tokens=count(text))
        for section in merged
        for text in _pack(section["blocks"], count, min_tokens, target_tokens, max_tokens)
    ]
