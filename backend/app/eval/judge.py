"""LLM-as-judge on a stronger model than the answering one (JUDGE_MODEL, default gpt-oss-120b).

Scores are decomposed rather than asked for directly, which is more reliable:
    faithfulness   = supported claims / claims in the answer          (no reference needed)
    context_recall = reference facts present in the context / facts   (needs a reference answer)
    answer_relevance, answer_correctness = 1–5 ratings scaled to 0–1
"""

import asyncio

from app.config import settings
from app.llm.groq import chat_json
from app.observability.metrics import stage_duration, timed

_CLAIMS = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {"claim": {"type": "string"}, "supported": {"type": "boolean"}},
        "required": ["claim", "supported"],
        "additionalProperties": False,
    },
}
_FACTS = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {"fact": {"type": "string"}, "in_context": {"type": "boolean"}},
        "required": ["fact", "in_context"],
        "additionalProperties": False,
    },
}
_CLAIMS_RULE = '"claims": split the ANSWER into short atomic factual claims (ignore greetings and pleasantries). For each, "supported" is true only if the CONTEXT explicitly states or directly implies it.'
_FACTS_RULE = '"reference_facts": split the REFERENCE into its key facts. For each, "in_context" is true if the CONTEXT contains that information.'

MODES = {
    # Live traffic: no reference answer exists.
    "answer": (
        {"claims": _CLAIMS, "answer_relevance": {"type": "integer"}, "reasoning": {"type": "string"}},
        f"1. {_CLAIMS_RULE}\n2. \"answer_relevance\" (1–5): how directly and completely the ANSWER addresses the QUESTION, regardless of correctness. 5 = fully on point; 1 = off-topic.",
    ),
    # Offline evaluation: a reference answer is available.
    "reference": (
        {
            "claims": _CLAIMS,
            "answer_relevance": {"type": "integer"},
            "answer_correctness": {"type": "integer"},
            "reference_facts": _FACTS,
            "reasoning": {"type": "string"},
        },
        f"1. {_CLAIMS_RULE}\n2. \"answer_relevance\" (1–5): how directly and completely the ANSWER addresses the QUESTION, regardless of correctness.\n"
        '3. "answer_correctness" (1–5): agreement between the ANSWER and the REFERENCE on the key facts and steps. 5 = same key facts, nothing contradicted; '
        "3 = partly right or missing important steps; 1 = wrong, contradicts the reference, or misses the point.\n"
        f"4. {_FACTS_RULE}",
    ),
    # The bot didn't answer: only judge whether the retrieved context could have supported an answer.
    "context": ({"reference_facts": _FACTS, "reasoning": {"type": "string"}}, f"1. {_FACTS_RULE}"),
}

# Judgments share one per-minute token budget (8,000 TPM for gpt-oss-120b on Groq's on-demand tier),
# so they queue JUDGE_CONCURRENCY at a time, no matter how many questions run in parallel.
_slots: asyncio.Semaphore | None = None


def _semaphore() -> asyncio.Semaphore:
    global _slots
    if _slots is None:
        _slots = asyncio.Semaphore(settings.judge_concurrency)
    return _slots


def _scale5(value) -> float | None:
    return (min(5, max(1, value)) - 1) / 4 if isinstance(value, int | float) else None


def _share(items, key: str) -> float | None:
    return sum(1 for i in items if i.get(key)) / len(items) if items else None


async def judge(*, question: str, contexts: list[str], answer: str = "", reference: str = "") -> dict | None:
    mode = ("reference" if reference else "answer") if answer else ("context" if reference else None)
    if mode is None:
        return None
    properties, instructions = MODES[mode]
    prompt = "\n\n".join(
        p
        for p in (
            f"QUESTION:\n{question}",
            "CONTEXT (what the assistant retrieved):\n" + ("\n\n".join(f"[{i}] {c}" for i, c in enumerate(contexts, 1)) or "(nothing retrieved)"),
            f"ANSWER (from the assistant):\n{answer}" if answer else "",
            f"REFERENCE (correct answer written by a support expert):\n{reference}" if reference else "",
        )
        if p
    )

    async with _semaphore():
        with timed(stage_duration, stage="judge"):
            reply = await chat_json(
                purpose="judge",
                model=settings.judge_model,
                temperature=0,
                max_tokens=settings.judge_max_tokens,
                reasoning_effort=settings.judge_reasoning_effort,
                max_retries=settings.judge_max_retries,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": f"judge_{mode}",
                        "strict": True,
                        "schema": {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False},
                    },
                },
                messages=[
                    {
                        "role": "system",
                        "content": "You are a strict, impartial evaluator of a customer-support assistant. Judge only against the material given; do not use outside knowledge."
                        f"\n\n{instructions}\n\nKeep \"reasoning\" to one or two sentences.",
                    },
                    {"role": "user", "content": prompt},
                ],
            )

    data = reply["json"]
    claims = data.get("claims") or []
    return {
        "faithfulness": _share(claims, "supported"),
        "unsupported_claims": [c["claim"] for c in claims if not c.get("supported")],
        "answer_relevance": _scale5(data.get("answer_relevance")),
        "answer_correctness": _scale5(data.get("answer_correctness")),
        "context_recall": _share(data.get("reference_facts") or [], "in_context"),
        "reasoning": data.get("reasoning", ""),
    }
