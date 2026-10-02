"""uv run baton-eval [--set expert|simulated|all]

Retrieval quality on WixQA (hit@k, Recall/Precision/nDCG@5, rank-aware context precision, MRR) for
vector, keyword and hybrid search, plus suggested handoff thresholds calibrated against off-topic
questions. No LLM calls."""

import argparse
import json
import math
from datetime import UTC, datetime

from app.config import settings
from app.console import utf8_console
from app.eval.datasets import OFF_TOPIC_QUESTIONS, QUESTION_SETS, load_questions
from app.eval.metrics import (
    context_precision_at_k,
    first_relevant_rank,
    hit_rates,
    mean,
    ndcg_at_k,
    no_match_threshold,
    precision_at_k,
    precision_threshold,
    recall_at_k,
    summarize,
)
from app.rag.reranker import get_reranker
from app.rag.retriever import Retriever

SEARCH = {"top_k": 10, "sources": ["wixqa"], "audience": "customer"}


def pct(x) -> str:
    return "   —" if x is None else f"{x * 100:3.0f}%"


def num(x) -> str:
    return "  —  " if x is None else f"{x:.3f}"


def main() -> None:
    utf8_console()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--set", default="expert", choices=[*QUESTION_SETS, "all"])
    args = parser.parse_args()
    sets = list(QUESTION_SETS) if args.set == "all" else [args.set]

    retriever = Retriever()
    modes = ("dense", "keyword", "hybrid", "rerank") if get_reranker() else ("dense", "keyword", "hybrid")
    production = modes[-1]  # the mode the answerer uses
    wixqa = retriever.manifest["sources"].get("wixqa")
    if not wixqa:
        raise SystemExit('The index has no WixQA articles. Add "wixqa" to INGEST_SOURCES and run `uv run baton-ingest`.')
    if wixqa.get("limit"):
        print(f"⚠ The index was built with --limit={wixqa['limit']}; most correct articles are missing, so scores will be low.\n")

    questions = [q for s in sets for q in load_questions(s)]
    print(f"Evaluating {len(questions)} questions ({' + '.join(sets)}) and {len(OFF_TOPIC_QUESTIONS)} off-topic questions against {wixqa['documents']} WixQA articles…\n")

    by_mode = {}
    for mode in modes:
        rows = []
        for q in questions:
            found = retriever.search(q["question"], mode=mode, **SEARCH)
            gold = q["articleIds"]
            rows.append({
                "confidence": found.confidence,
                "rank": first_relevant_rank(found.results, gold),
                "recall5": recall_at_k(found.results, gold, 5),
                "precision5": precision_at_k(found.results, gold, 5),
                "ndcg5": ndcg_at_k(found.results, gold, 5),
                "ctxp5": context_precision_at_k(found.results, gold, 5),
            })  # fmt: skip
        graded = {key: mean(r[key] for r in rows) for key in ("recall5", "precision5", "ndcg5", "ctxp5")}
        by_mode[mode] = {"metrics": {**hit_rates([r["rank"] for r in rows]), **graded}, "rows": rows}

    print("Retrieval (article level; hit@k = any correct article in the top k)")
    print("  mode       hit@1  hit@3  hit@10  Recall@5  Precision@5  nDCG@5  CtxPrecision@5    MRR")
    for mode in modes:
        m = by_mode[mode]["metrics"]
        print(f"  {mode:<9} {pct(m['hit1'])}   {pct(m['hit3'])}   {pct(m['hit10'])}     {pct(m['recall5'])}        {pct(m['precision5'])}"
              f"   {m['ndcg5']:.3f}          {m['ctxp5']:.3f}  {m['mrr']:.3f}")  # fmt: skip
    print("  (Precision@5 is capped near 26%: questions average 1.3 correct articles, so most of any top 5 cannot be relevant.)")

    positives = [{"confidence": r["confidence"], "correct": r["rank"] is not None and r["rank"] <= 3} for r in by_mode[production]["rows"]]
    negatives = [{"confidence": retriever.search(q, mode=production, **SEARCH).confidence} for q in OFF_TOPIC_QUESTIONS]
    distributions = {
        "real, right article in top 3": summarize([p["confidence"] for p in positives if p["correct"]]),
        "real, right article missed": summarize([p["confidence"] for p in positives if not p["correct"]]),
        "off-topic": summarize([n["confidence"] for n in negatives]),
    }
    print("\nConfidence (cosine similarity of the top result)")
    print("                                   p5     p25  median    p95     max    n")
    for name, d in distributions.items():
        if d:
            print(f"  {name:<30} {num(d['p5'])}  {num(d['p25'])}  {num(d['median'])}  {num(d['p95'])}  {num(d['max'])}  {d['n']:>3}")

    answer = precision_threshold(positives, negatives, settings.eval_answer_precision)
    copilot = precision_threshold(positives, negatives, settings.eval_copilot_precision)
    no_match = no_match_threshold(positives, negatives, settings.eval_no_match_max_miss_rate)
    ceil2 = lambda x: math.ceil(x * 100) / 100  # noqa: E731
    suggestions = {
        "answerThreshold": answer and ceil2(answer["threshold"]),
        "copilotThreshold": copilot and ceil2(copilot["threshold"]),
        "noMatchThreshold": math.floor(no_match["threshold"] * 100) / 100,
    }

    print(f"\nSuggested thresholds  ({retriever.manifest['embedding']['signature']}, {production} retrieval)")
    if answer:
        print(f"  answer    ≥ {suggestions['answerThreshold']:.2f}   bot answers {pct(answer['answeredShare']).strip()} of real questions alone; "
              f"{pct(answer['precision']).strip()} of those have the right article in the top 3; {pct(answer['offTopicAbove']).strip()} of off-topic slip through")  # fmt: skip
    else:
        print(f"  answer    —      no threshold reaches {pct(settings.eval_answer_precision).strip()} precision")
    if copilot:
        print(f"  copilot   ≥ {suggestions['copilotThreshold']:.2f}   drafts for {pct(copilot['answeredShare']).strip()} of real questions; "
              f"{pct(copilot['precision']).strip()} grounded in the right article")  # fmt: skip
    print(f"  no match  < {suggestions['noMatchThreshold']:.2f}   {pct(no_match['realBelow']).strip()} of real questions fall below; "
          f"catches {pct(no_match['offTopicBelow']).strip()} of off-topic questions → RAG_NO_MATCH_THRESHOLD")  # fmt: skip

    settings.eval_path.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
    report = {
        "createdAt": stamp, "sets": sets, "questions": len(questions),
        "index": {"signature": retriever.manifest["embedding"]["signature"], "chunks": retriever.size, "builtAt": retriever.manifest["builtAt"]},
        "reranker": get_reranker() and get_reranker().model,
        "retrieval": {m: by_mode[m]["metrics"] for m in modes}, "confidence": distributions,
        "thresholds": {"suggestions": suggestions, "answer": answer, "copilot": copilot, "noMatch": no_match},
    }  # fmt: skip
    path = settings.eval_path / f"report-{'+'.join(sets)}-{stamp}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    (settings.eval_path / "latest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nReport saved to {path}")


if __name__ == "__main__":
    main()
