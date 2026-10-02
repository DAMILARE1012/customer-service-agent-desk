"""The review pipeline: knowledge gaps and test questions from closed sessions, redacted and grouped,
then published or approved by an admin."""

import hashlib
import json

import numpy as np
import pytest

from app.config import settings
from app.review import pipeline, publish
from tests.support import ALEX, JADE, JORDAN, MAYA, SAM, say, start


def fake_embed(texts):
    """Same topic → same vector: 'bulk' questions cluster, everything else gets its own direction."""
    vectors = []
    for text in texts:
        key = "bulk" if "bulk" in text.lower() else text
        seed = int(hashlib.sha256(key.encode()).hexdigest()[:8], 16)
        v = np.random.default_rng(seed).normal(size=16).astype(np.float32)
        vectors.append(v / np.linalg.norm(v))
    return np.stack(vectors)


@pytest.fixture()
def review_env(client, monkeypatch, tmp_path):
    async def embed(texts):
        return fake_embed(texts)

    monkeypatch.setattr(pipeline, "_embed", embed)
    monkeypatch.setattr(settings, "content_dir", str(tmp_path / "content"))
    monkeypatch.setattr(settings, "data_dir", str(tmp_path / "data"))
    return client


def closed_out_of_scope(client, who, question):
    conversation_id = start(client, who)
    say(client, conversation_id, question, who)  # fake answerer: "bulk" → no match → handoff
    client.as_(ALEX).post(f"/conversations/{conversation_id}/handoff/accept")
    client.as_(ALEX).post(f"/conversations/{conversation_id}/agent-messages",
                          json={"text": "Yes — teams of 10+ get 15% off; we invoice net-30. Write to sales@baton.example."})
    client.as_(ALEX).post(f"/conversations/{conversation_id}/resolve")
    return conversation_id


def test_review_groups_gaps_and_proposes_test_questions(review_env):
    client = review_env
    closed_out_of_scope(client, MAYA, "Do you offer bulk pricing for a team of 40? I'm maya.chen@example.com")
    closed_out_of_scope(client, SAM, "Is there a bulk discount for schools ordering many seats?")
    open_one = start(client, JORDAN)
    say(client, open_one, "Do you offer bulk pricing for non-profits?", JORDAN)  # still open: not reviewed yet

    report = client.as_(JADE).post("/admin/review/run").json()
    assert report == {"conversations": 2, "gapsNew": 1, "gapsUpdated": 1, "testQuestions": 1}
    assert client.as_(JADE).post("/admin/review/run").json()["conversations"] == 0  # each session once

    gaps = client.as_(JADE).get("/admin/review", params={"kind": "knowledge_gap"}).json()
    assert len(gaps) == 1 and gaps[0]["count"] == 2 and len(gaps[0]["examples"]) == 2
    assert "[EMAIL]" in gaps[0]["examples"][0] and "maya.chen" not in json.dumps(gaps)
    assert gaps[0]["agentAnswers"] and "[EMAIL]" in gaps[0]["agentAnswers"][0]  # the agent's sales@ address is redacted too

    tests = client.as_(JADE).get("/admin/review", params={"kind": "test_question"}).json()
    assert len(tests) == 1 and "15% off" in tests[0]["answer"]  # the second near-identical case was a duplicate
    assert client.as_(ALEX).get("/admin/review").status_code == 403


def test_publishing_a_gap_writes_an_article_for_ingestion(review_env, monkeypatch):
    client = review_env
    closed_out_of_scope(client, MAYA, "Do you offer bulk pricing for a team of 40 people?")
    client.as_(JADE).post("/admin/review/run")
    gap = client.as_(JADE).get("/admin/review", params={"kind": "knowledge_gap"}).json()[0]

    assert client.as_(JADE).post(f"/admin/review/{gap['id']}/publish").status_code == 400  # no article yet
    client.as_(JADE).patch(f"/admin/review/{gap['id']}", json={
        "title": "Team and bulk pricing #discounts",
        "answer": "Teams of 10 or more get 15% off every seat. We can invoice on net-30 terms; contact sales to set it up.",
    })  # fmt: skip
    published = client.as_(JADE).post(f"/admin/review/{gap['id']}/publish").json()
    assert published["status"] == "published" and published["publishedPath"] == "help-center/team-and-bulk-pricing-discounts.md"

    article = (settings.content_path / published["publishedPath"]).read_text(encoding="utf-8")
    assert article.startswith('---\ntitle: "Team and bulk pricing discounts"\n') and "audience: customer" in article
    from app.ingest.adapters import LocalMarkdown

    meta, body = LocalMarkdown._front_matter(article)
    assert meta["title"] == "Team and bulk pricing discounts" and meta["url"] == "/help/team-and-bulk-pricing-discounts" and "15% off" in body
    assert client.as_(JADE).patch(f"/admin/review/{gap['id']}", json={"title": "x"}).status_code == 409

    calls = []
    monkeypatch.setattr("app.ingest.pipeline.run_ingestion", lambda **kw: calls.append(kw) or
                        {"total": 10, "embedded": 2, "reused": 8, "removedChunks": 0, "duration": 1.2})  # fmt: skip
    assert client.as_(JADE).post("/admin/knowledge/reindex").json()["embedded"] == 2 and calls[0]["only"] == ["local"]


def test_approving_a_test_question_adds_it_to_the_evaluation_set(review_env):
    client = review_env
    closed_out_of_scope(client, MAYA, "Do you offer bulk pricing for a team of 40 people?")
    client.as_(JADE).post("/admin/review/run")
    candidate = client.as_(JADE).get("/admin/review", params={"kind": "test_question"}).json()[0]

    client.as_(JADE).post(f"/admin/review/{candidate['id']}/approve")
    client.as_(JADE).post(f"/admin/review/{candidate['id']}/approve")  # idempotent
    rows = publish.load_reviewed_questions()
    assert [r["id"] for r in rows] == [candidate["id"]] and rows[0]["approvedBy"] == "Jade Kim"

    rejected = client.as_(JADE).post(f"/admin/review/{client.as_(JADE).get('/admin/review', params={'kind': 'knowledge_gap'}).json()[0]['id']}/reject").json()
    assert rejected["status"] == "rejected"
    actions = {e["action"] for e in client.as_(JADE).get("/admin/audit").json()}
    assert {"review.run", "review.approve", "review.reject"} <= actions


def test_gap_detection_skips_answered_vague_and_non_knowledge_handoffs():
    frustrated = {"reason": "negative_sentiment", "triggerMessage": {"id": "m4", "text": "This is ridiculous, nothing works at all!!"}}
    conversation = {
        "handoffHistory": [frustrated], "handoff": None,
        "insights": {"attempts": [
            {"questionMessageId": "m1", "question": "How long does a refund take?", "outcome": "answered", "confidence": 0.84},
            {"questionMessageId": "m2", "question": "help??", "outcome": "clarified", "confidence": 0.4},
            {"questionMessageId": "m3", "question": "Do you ship pianos to Antarctica by boat?", "outcome": "handed_off", "confidence": 0.55},
            {"questionMessageId": "m4", "question": "This is ridiculous, nothing works at all!!", "outcome": "handed_off", "confidence": 0.5},
        ]},
    }  # fmt: skip
    # The frustrated message was handed off for its tone, not because the help centre lacked an answer.
    assert pipeline.gap_questions(conversation) == ["Do you ship pianos to Antarctica by boat?"]
