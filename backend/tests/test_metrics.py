from app.eval.metrics import (
    context_precision_at_k,
    first_relevant_rank,
    hit_rates,
    ndcg_at_k,
    no_match_threshold,
    precision_at_k,
    precision_threshold,
    recall_at_k,
)


def r(doc_id, also_in=()):
    return {"docId": doc_id, "alsoIn": [{"docId": a} for a in also_in]}


def test_first_relevant_rank_counts_shared_chunks():
    results = [r("a"), r("b", ["gold"])]
    assert first_relevant_rank(results, ["gold"]) == 2
    assert first_relevant_rank(results, ["missing"]) is None


def test_hit_rates_and_mrr():
    m = hit_rates([1, 3, None, 2])
    assert m["hit1"] == 0.25 and m["hit3"] == 0.75
    assert abs(m["mrr"] - (1 + 1 / 3 + 0 + 1 / 2) / 4) < 1e-12


def test_recall_counts_each_correct_article_once():
    results = [r("x"), r("a"), r("a"), r("y", ["b"])]
    assert recall_at_k(results, ["a", "b"], 2) == 0.5
    assert recall_at_k(results, ["a", "b"], 4) == 1


def test_precision_at_k():
    assert precision_at_k([r("a"), r("x"), r("a"), r("y")], ["a"], 4) == 0.5


def test_ndcg():
    assert ndcg_at_k([r("a"), r("x")], ["a"], 2) == 1
    assert abs(ndcg_at_k([r("x"), r("a")], ["a"], 2) - 1 / 1.584962500721156) < 1e-9
    assert ndcg_at_k([r("a"), r("a")], ["a"], 2) == 1  # a second chunk of the same article adds no gain


def test_context_precision_is_rank_aware():
    assert context_precision_at_k([r("a"), r("a"), r("x")], ["a"], 3) == 1
    assert context_precision_at_k([r("x"), r("a")], ["a"], 2) == 0.5
    assert context_precision_at_k([r("x")], ["a"], 1) == 0


def test_precision_threshold_stops_at_the_first_dip():
    positives = [{"confidence": 0.9 - i * 0.01, "correct": True} for i in range(10)]
    positives += [{"confidence": 0.7 - i * 0.01, "correct": i % 4 == 0} for i in range(10)]
    result = precision_threshold(positives, [{"confidence": 0.5}], 0.8)
    # 0.70 → 11/11, 0.69 → 11/12, 0.68 → 11/13 = 85% (≥ 80%), 0.67 → 11/14 = 79% (stop)
    assert abs(result["threshold"] - 0.68) < 1e-9 and result["offTopicAbove"] == 0


def test_precision_threshold_unreachable():
    assert precision_threshold([{"confidence": 0.8 - i * 0.01, "correct": False} for i in range(20)], [], 0.5) is None


def test_no_match_threshold_respects_miss_rate():
    result = no_match_threshold([{"confidence": 0.5 + i * 0.004} for i in range(100)], [{"confidence": 0.3}, {"confidence": 0.6}], 0.05)
    assert result["realBelow"] <= 0.05 and result["offTopicBelow"] == 0.5
