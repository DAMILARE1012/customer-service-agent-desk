"""Retrieval metrics and threshold calibration.

`results` are chunks in rank order; each belongs to docId plus any articles sharing its text (alsoIn).
Relevance is judged per *article*: several chunks of one correct article count once.
"""

import math
import statistics


def _articles(result: dict) -> list[str]:
    return [result["docId"], *[a["docId"] if isinstance(a, dict) else a for a in result.get("alsoIn", [])]]


def first_relevant_rank(results: list[dict], gold: list[str]) -> int | None:
    gold_set = set(gold)
    return next((i for i, r in enumerate(results, 1) if any(a in gold_set for a in _articles(r))), None)


def _relevance(results: list[dict], gold: list[str], k: int) -> list[tuple[bool, int, int]]:
    """Per position: (relevant?, gain from a not-yet-credited correct article, credited so far)."""
    gold_set, credited, out = set(gold), set(), []
    for result in results[:k]:
        articles = _articles(result)
        new = [a for a in articles if a in gold_set and a not in credited]
        credited.update(new)
        out.append((any(a in gold_set for a in articles), 1 if new else 0, len(credited)))
    return out


def recall_at_k(results: list[dict], gold: list[str], k: int) -> float:
    """Share of the correct articles that appear in the top k."""
    rel = _relevance(results, gold, k)
    return (rel[-1][2] if rel else 0) / len(set(gold))


def precision_at_k(results: list[dict], gold: list[str], k: int) -> float:
    """Share of the top k results that come from a correct article."""
    return sum(1 for relevant, _, _ in _relevance(results, gold, k) if relevant) / k


def ndcg_at_k(results: list[dict], gold: list[str], k: int) -> float:
    """Normalized discounted cumulative gain: rewards correct articles ranked higher."""
    dcg = sum(gain / math.log2(i + 2) for i, (_, gain, _) in enumerate(_relevance(results, gold, k)))
    ideal = sum(1 / math.log2(i + 2) for i in range(min(len(set(gold)), k)))
    return dcg / ideal if ideal else 0.0


def context_precision_at_k(results: list[dict], gold: list[str], k: int) -> float:
    """Rank-aware context precision (ID-based, as in RAGAS): mean of precision@i over the positions i
    holding a relevant chunk. 1 when every relevant chunk sits above every irrelevant one."""
    hits, total = 0, 0.0
    for i, (relevant, _, _) in enumerate(_relevance(results, gold, k), 1):
        if relevant:
            hits += 1
            total += hits / i
    return total / hits if hits else 0.0


def hit_rates(ranks: list[int | None]) -> dict:
    n = len(ranks)
    hit = lambda k: sum(1 for r in ranks if r is not None and r <= k) / n  # noqa: E731
    return {"hit1": hit(1), "hit3": hit(3), "hit5": hit(5), "hit10": hit(10), "mrr": sum(1 / r for r in ranks if r) / n}


def mean(values) -> float | None:
    numbers = [v for v in values if isinstance(v, int | float) and math.isfinite(v)]
    return sum(numbers) / len(numbers) if numbers else None


def quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lower, upper = math.floor(position), math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def summarize(values: list[float]) -> dict | None:
    if not values:
        return None
    return {"p5": quantile(values, 0.05), "p25": quantile(values, 0.25), "median": statistics.median(values),
            "p95": quantile(values, 0.95), "max": max(values), "n": len(values)}  # fmt: skip


def precision_threshold(positives: list[dict], negatives: list[dict], target: float, min_answered: int = 10) -> dict | None:
    """Lowest confidence at which answering keeps `target` precision, scanning from the most confident
    question down and stopping at the first dip (conservative). A real question is a good answer when its
    right article is in the top 3; an off-topic question above the threshold is always a bad one."""
    points = sorted([(p["confidence"], p["correct"]) for p in positives] + [(n["confidence"], False) for n in negatives], reverse=True)
    answered = good = 0
    best = None
    for i, (score, is_good) in enumerate(points):
        answered += 1
        good += is_good
        if i + 1 < len(points) and points[i + 1][0] == score:
            continue  # evaluate between distinct scores
        if answered < min_answered:
            continue
        if good / answered < target:
            break
        best = {"threshold": score, "precision": good / answered}
    if not best:
        return None
    t = best["threshold"]
    return {
        **best,
        "coverage": sum(1 for p in positives if p["confidence"] >= t and p["correct"]) / len(positives),
        "answeredShare": sum(1 for p in positives if p["confidence"] >= t) / len(positives),
        "offTopicAbove": sum(1 for n in negatives if n["confidence"] >= t) / len(negatives) if negatives else 0,
    }


def no_match_threshold(positives: list[dict], negatives: list[dict], max_miss_rate: float) -> dict:
    """Below this, a question is almost certainly outside the knowledge base."""
    t = quantile([p["confidence"] for p in positives], max_miss_rate)
    return {
        "threshold": t,
        "realBelow": sum(1 for p in positives if p["confidence"] < t) / len(positives),
        "offTopicBelow": sum(1 for n in negatives if n["confidence"] < t) / len(negatives) if negatives else 0,
    }
