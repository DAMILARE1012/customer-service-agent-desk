"""uv run baton-eval-rag [--limit N] [--name TEXT] [--no-judge] [--concurrency N] [--include-reviewed]

End-to-end evaluation as a Langfuse experiment. Every question runs through the production answer step
(retrieve → gate → generate with citations) and is scored on four layers:

    retrieval   recall@5, nDCG@5, context precision@5          deterministic, from WixQA article labels
    context     context recall                                  LLM judge: are the reference answer's facts in the context?
    generation  faithfulness, answer relevance, correctness,    LLM judge (JUDGE_MODEL)
                citation correctness                            deterministic: does a citation come from a correct article?
    decision    answered (WixQA), handoff correct (off-topic)   deterministic

Results appear in Langfuse under Datasets → <dataset> → Runs, with a trace per question.
"""

import argparse
import hashlib
import json
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from app.config import ROOT, settings
from app.console import utf8_console
from app.eval.datasets import OFF_TOPIC_QUESTIONS, load_questions
from app.eval.judge import judge
from app.eval.metrics import context_precision_at_k, mean, ndcg_at_k, recall_at_k
from app.observability.tracing import get_langfuse, init_tracing, shutdown
from app.rag.answerer import answer_question, get_retriever

K = 5
# Keeps experiment traces and scores apart from live traffic; filter on it in Langfuse.
EXPERIMENT_ENVIRONMENT = "sdk-experiment"
METRICS = (
    "recall_at_5", "ndcg_at_5", "context_precision_at_5", "context_recall", "answered", "citation_correct",
    "faithfulness", "answer_relevance", "answer_correctness", "unsupported_claims", "handoff_correct",
)  # fmt: skip
LABELS = {
    "recall_at_5": ("Retrieval", "Recall@5"),
    "ndcg_at_5": ("Retrieval", "nDCG@5"),
    "context_precision_at_5": ("Retrieval", "Context precision@5"),
    "context_recall": ("Context", "Context recall (judge)"),
    "answered": ("Decision", "Answered (answerable questions)"),
    "handoff_correct": ("Decision", "Handed off (off-topic questions)"),
    "citation_correct": ("Generation", "Citation from a correct article"),
    "faithfulness": ("Generation", "Faithfulness (judge)"),
    "answer_relevance": ("Generation", "Answer relevance (judge)"),
    "answer_correctness": ("Generation", "Answer correctness (judge)"),
    "correct_and_grounded": ("End to end", "Correct and grounded answers"),
}


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


# ── 1. Dataset (idempotent upsert: stable ids from the question text) ──────────


def sync_dataset(langfuse, name: str, include_reviewed: bool = False) -> int:
    try:
        langfuse.create_dataset(
            name=name,
            description="WixQA expert questions (answerable) + off-topic questions (should hand off)",
            metadata={"source": "WixQA + hand-written off-topic set"},
        )
    except Exception:  # noqa: BLE001 — already exists
        pass
    items = [
        {"id": f"wixqa-{_hash(q['question'])}", "input": {"question": q["question"]},
         "expected_output": {"answer": q["answer"], "articleIds": q["articleIds"], "shouldAnswer": True},
         "metadata": {"kind": "wixqa"}}
        for q in load_questions("expert")
    ] + [
        {"id": f"offtopic-{_hash(q)}", "input": {"question": q}, "expected_output": {"shouldAnswer": False},
         "metadata": {"kind": "off_topic"}}
        for q in OFF_TOPIC_QUESTIONS
    ]  # fmt: skip
    if include_reviewed:
        # Agent-resolved cases an admin approved in the review queue: the agent's answer is the reference;
        # there are no gold articles, so retrieval metrics don't apply.
        from app.review.publish import load_reviewed_questions

        items += [
            {"id": f"reviewed-{r['id']}", "input": {"question": r["question"]},
             "expected_output": {"answer": r["answer"], "shouldAnswer": True}, "metadata": {"kind": "reviewed"}}
            for r in load_reviewed_questions()
        ]  # fmt: skip
    with ThreadPoolExecutor(max_workers=10) as pool:
        list(pool.map(lambda item: langfuse.create_dataset_item(dataset_name=name, **item), items))
    return len(items)


# ── 2. Task: the production answer step ───────────────────────────────────────


def _with_articles(r: dict) -> dict:
    return {"docId": r["docId"], "alsoIn": [a["docId"] for a in r["alsoIn"]], "title": r["title"]}


async def task(*, item, **_) -> dict:
    result = await answer_question(item.input["question"], purpose="eval")
    output = {
        "decision": "answered" if result.status == "answered" else "handed_off",
        "status": result.status,
        "answer": result.answer,
        "confidence": result.retrieval.confidence,
        "citations": [_with_articles(r) for r in result.citations],
        "contexts": [{**_with_articles(r), "text": r["text"]} for r in result.retrieval.results],
    }
    if result.error:
        output["error"] = result.error
    return output


# ── 3. Item evaluators ────────────────────────────────────────────────────────


def make_evaluator(use_judge: bool):
    from langfuse import Evaluation

    async def evaluate(*, input, output, expected_output, metadata, **_) -> list:  # noqa: A002 — SDK keyword
        if (metadata or {}).get("kind") == "off_topic":
            return [Evaluation(name="handoff_correct", value=1 if output["decision"] == "handed_off" else 0, comment=f"status: {output['status']}")]

        gold = expected_output.get("articleIds")  # None for reviewed (agent-answered) questions
        evals = [Evaluation(name="answered", value=1 if output["decision"] == "answered" else 0, comment=f"status: {output['status']}")]
        if gold:
            evals += [
                Evaluation(name="recall_at_5", value=recall_at_k(output["contexts"], gold, K)),
                Evaluation(name="ndcg_at_5", value=ndcg_at_k(output["contexts"], gold, K)),
                Evaluation(name="context_precision_at_5", value=context_precision_at_k(output["contexts"], gold, K)),
            ]
        answered = output["decision"] == "answered"
        if answered and gold:
            gold_set = set(gold)
            correct = any(c["docId"] in gold_set or gold_set.intersection(c["alsoIn"]) for c in output["citations"])
            evals.append(Evaluation(name="citation_correct", value=1 if correct else 0, comment=" | ".join(c["title"] for c in output["citations"])))

        if use_judge:
            try:
                verdict = await judge(
                    question=input["question"],
                    contexts=[c["text"] for c in output["contexts"]],
                    answer=output["answer"],
                    reference=expected_output["answer"],
                )
            except Exception as error:  # noqa: BLE001 — a failed judgment is reported, not fatal
                return [*evals, Evaluation(name="judge_error", value=1, comment=str(error)[:500])]

            def push(name: str, value, comment: str | None = None) -> None:
                if value is not None:
                    evals.append(Evaluation(name=name, value=value, comment=comment))

            push("context_recall", verdict["context_recall"], verdict["reasoning"])
            if answered:
                unsupported = verdict["unsupported_claims"]
                push("faithfulness", verdict["faithfulness"], f"Unsupported: {' | '.join(unsupported)}" if unsupported else "All claims supported")
                push("unsupported_claims", len(unsupported))
                push("answer_relevance", verdict["answer_relevance"])
                push("answer_correctness", verdict["answer_correctness"], verdict["reasoning"])
        return evals

    return evaluate


# ── 4. Run-level summary ──────────────────────────────────────────────────────


def _kind(result) -> str | None:
    return (getattr(result.item, "metadata", None) or {}).get("kind")


def summarize(item_results, use_judge: bool) -> dict:
    def values(name: str) -> list:
        return [e.value for r in item_results for e in r.evaluations if e.name == name]

    summary = {name: {"mean": mean(values(name)), "n": len(values(name))} for name in METRICS}
    # The number that matters most: of all answerable questions, how many got an answer that is right and grounded.
    wixqa = [r for r in item_results if _kind(r) == "wixqa"]

    def good(r) -> bool:
        score = {e.name: e.value for e in r.evaluations}
        return score.get("answered") == 1 and (score.get("answer_correctness") or 0) >= 0.75 and (score.get("faithfulness") or 0) >= 0.9

    summary["correct_and_grounded"] = {"mean": sum(map(good, wixqa)) / len(wixqa) if wixqa and use_judge else None, "n": len(wixqa)}
    return summary


def make_run_evaluator(use_judge: bool):
    from langfuse import Evaluation

    def averages(*, item_results, **_) -> list:
        return [
            Evaluation(name=f"avg_{name}", value=s["mean"], comment=f"n={s['n']}")
            for name, s in summarize(item_results, use_judge).items()
            if s["mean"] is not None
        ]

    return averages


# ── Run ───────────────────────────────────────────────────────────────────────


def pct(x) -> str:
    return "   —" if x is None else f"{x * 100:3.0f}%"


def main() -> None:
    utf8_console()
    parser = argparse.ArgumentParser(description="End-to-end RAG evaluation as a Langfuse experiment")
    parser.add_argument("--limit", type=int, default=settings.eval_rag_limit, help="WixQA questions to run; off-topic added at N/5")
    parser.add_argument("--name", help="run name shown in Langfuse (default: model + settings + time)")
    parser.add_argument("--no-judge", action="store_true", help="skip the LLM judge (retrieval and decision metrics only)")
    parser.add_argument("--concurrency", type=int, default=settings.eval_rag_concurrency, help="parallel questions")
    parser.add_argument("--include-reviewed", action="store_true", help="also run the test questions approved in the admin review queue")
    args = parser.parse_args()

    settings.langfuse_tracing_environment = EXPERIMENT_ENVIRONMENT
    if not init_tracing(EXPERIMENT_ENVIRONMENT):
        sys.exit("Langfuse is not configured. Set LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY and start the stack with `npm run obs:up`.")
    langfuse = get_langfuse()
    use_judge = not args.no_judge and bool(settings.groq_api_key)
    if not settings.groq_api_key:
        print("⚠ GROQ_API_KEY is empty: every answer will fail over to a handoff and the judge is off. Retrieval metrics are still measured.\n")

    try:
        dataset_name = settings.eval_rag_dataset
        print(f'Syncing dataset "{dataset_name}"…')
        total = sync_dataset(langfuse, dataset_name, include_reviewed=args.include_reviewed)
        dataset = langfuse.get_dataset(dataset_name)

        def by_kind(kind: str) -> list:
            active = [i for i in dataset.items if (i.metadata or {}).get("kind") == kind and "ARCHIVED" not in str(i.status).upper()]
            return sorted(active, key=lambda i: i.id)

        selected = by_kind("wixqa")[: args.limit] + by_kind("off_topic")[: max(1, math.ceil(args.limit / 5))]
        if args.include_reviewed:
            selected += by_kind("reviewed")
        kinds: dict[str, int] = {}
        for i in selected:
            kinds[i.metadata["kind"]] = kinds.get(i.metadata["kind"], 0) + 1
        print(
            f"Dataset has {total} items; running {len(selected)} ({', '.join(f'{n} {k}' for k, n in kinds.items())}) "
            f"with concurrency {args.concurrency}{f', judge {settings.judge_model}' if use_judge else ', no judge'}…\n"
        )

        get_retriever()  # load the index once, before questions run in parallel
        run_name = args.name or (
            f"{settings.groq_model} · k={settings.rag_context_chunks} · no-match {settings.rag_no_match_threshold} · "
            f"{datetime.now(UTC).strftime('%Y-%m-%dT%H:%M')}"
        )
        started = time.monotonic()
        result = langfuse.run_experiment(
            name="baton",
            run_name=run_name,
            description="End-to-end RAG evaluation: retrieval, context, generation and handoff decision.",
            metadata={
                "answerModel": settings.groq_model,
                "judgeModel": settings.judge_model if use_judge else "none",
                "contextChunks": str(settings.rag_context_chunks),
                "noMatchThreshold": str(settings.rag_no_match_threshold),
                "embedding": settings.embedding_model,
            },
            data=selected,
            task=task,
            evaluators=[make_evaluator(use_judge)],
            run_evaluators=[make_run_evaluator(use_judge)],
            max_concurrency=args.concurrency,
        )

        summary = summarize(result.item_results, use_judge)
        print(f'Run "{run_name}" finished in {time.monotonic() - started:.0f}s\n')
        for key, (layer, text) in LABELS.items():
            print(f"  {layer:<11} {text:<34} {pct(summary[key]['mean'])}   (n={summary[key]['n']})")
        if summary["unsupported_claims"]["mean"] is not None:
            print(f"  {'Generation':<11} {'Unsupported claims per answer':<34} {summary['unsupported_claims']['mean']:.2f}")
        failed = len(selected) - len(result.item_results)
        if failed:
            print(f"\n  {failed} item(s) failed outright and are missing from the run — see the log above.")
        errors = sum(1 for r in result.item_results if isinstance(r.output, dict) and r.output.get("error"))
        if errors:
            print(f'\n  {errors} question(s) hit an LLM error while answering — see "status" in the traces.')
        judge_errors = [e for r in result.item_results for e in r.evaluations if e.name == "judge_error"]
        if judge_errors:
            print(f"  {len(judge_errors)} judgment(s) failed, so judge metrics cover fewer items. First error: {(judge_errors[0].comment or '')[:200]}")
        if result.dataset_run_url:
            print(f"\nLangfuse run: {result.dataset_run_url}")

        settings.eval_path.mkdir(parents=True, exist_ok=True)
        path = settings.eval_path / f"rag-{datetime.now(UTC).strftime('%Y-%m-%dT%H-%M-%SZ')}.json"
        report = {
            "runName": run_name, "datasetRunUrl": result.dataset_run_url, "summary": summary,
            "config": {"model": settings.groq_model, "judge": settings.judge_model if use_judge else None,
                       "contextChunks": settings.rag_context_chunks, "noMatchThreshold": settings.rag_no_match_threshold},
        }  # fmt: skip
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Report saved to {path.relative_to(ROOT)}")
    finally:
        shutdown()


if __name__ == "__main__":
    main()
