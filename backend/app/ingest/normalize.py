"""Text normalization before chunking and indexing.

Bump NORMALIZER_VERSION when a rule changes: it's part of the pipeline fingerprint, so every source
re-parses on the next run (vectors are still reused wherever the text comes out identical).
"""

import re
import unicodedata

NORMALIZER_VERSION = 1

_INVISIBLE = re.compile(r"[\u00ad\u200b-\u200f\u2060-\u2064\ufeff]")  # soft hyphen, zero-width chars, BOM
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_ODD_SPACES = re.compile(r"[\u00a0\u1680\u2000-\u200a\u202f\u205f\u3000\t]")
_LINE_SEPARATORS = re.compile(r"\r\n?|[\u2028\u2029]")
_INNER_SPACES = re.compile(r"(\S) {2,}")

_SINGLE_QUOTES = re.compile(r"[\u2018\u2019\u201a\u201b\u2032]")
_DOUBLE_QUOTES = re.compile(r"[\u201c\u201d\u201e\u201f\u2033]")
_DASHES = re.compile(r"[\u2010-\u2015]")


def clean_text(text: str, boilerplate: list[re.Pattern] | None = None) -> str:
    """Meaning-preserving cleanup. The result is what agents see and the LLM quotes, so identifiers
    (#48213, $249.99, SAVE20), URLs and arrows are never rewritten."""
    result = unicodedata.normalize("NFKC", text)
    result = _LINE_SEPARATORS.sub("\n", result)
    result = _INVISIBLE.sub("", result)
    result = _CONTROL.sub("", result)
    result = _ODD_SPACES.sub(" ", result)
    for pattern in boilerplate or []:
        result = pattern.sub("", result)
    lines = [_INNER_SPACES.sub(r"\1 ", line).rstrip() for line in result.split("\n")]  # keep leading indentation
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def index_form(text: str) -> str:
    """Extra folding for what gets indexed only (embedding input + keyword index), never for display.
    Queries go through the same function so both sides match."""
    return _DASHES.sub("-", _DOUBLE_QUOTES.sub('"', _SINGLE_QUOTES.sub("'", text)))


def normalize_query(query: str) -> str:
    return index_form(clean_text(query))
