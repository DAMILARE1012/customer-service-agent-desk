"""Shared test doubles: signed-in people, a stand-in RAG answerer, and request helpers."""

from fastapi.testclient import TestClient

from app.auth import Principal
from app.rag.answerer import Answer
from app.rag.retriever import SearchResult

SOURCE = {
    "id": "local:help-center/refunds#0", "docId": "help-center/refunds", "title": "Refund processing times",
    "headingPath": [], "url": "/help/refunds", "category": "Returns & refunds", "audience": "customer",
    "text": "Refunds go back to your original payment method within 2 business days.", "alsoIn": [], "similarity": 0.84, "keywordScore": 9.1,
}  # fmt: skip


def person(sub, username, name, email, *roles, verified=True):
    """A staff member signed in with Keycloak."""
    return Principal(sub=sub, username=username, name=name, email=email, email_verified=verified, roles=frozenset(roles))


def customer(customer_id, name):
    """A customer holding a widget session for this (seeded) profile."""
    return Principal(sub=customer_id, username=customer_id, name=name, email=None, email_verified=False,
                     roles=frozenset({"customer"}), customer_id=customer_id)  # fmt: skip


LENA = customer("cus_lena", "Lena Fischer")
MAYA = customer("cus_maya", "Maya Chen")
SAM = customer("cus_sam", "Sam Patel")
JORDAN = customer("cus_jordan", "Jordan Okafor")
ALEX = person("kc-alex", "alex.rivera", "Alex Rivera", "alex.rivera@baton.example", "agent")
PRIYA = person("kc-priya", "priya.shah", "Priya Shah", "priya.shah@baton.example", "agent")
JADE = person("kc-jade", "jade.kim", "Jade Kim", "jade.kim@baton.example", "admin", "agent")


async def fake_answer(question, *, history=None, generate=True, purpose="answer"):
    retrieval = SearchResult(confidence=0.84, results=[SOURCE])
    if not generate:
        return Answer("skipped", retrieval)
    if "refund" in question.lower():
        return Answer("answered", retrieval, answer="Refunds take 2 business days.", citations=[SOURCE])
    if "bulk" in question.lower():
        return Answer("no_match", SearchResult(confidence=0.6, results=[]))
    return Answer("error", retrieval, error="Groq 404: model not available")


async def no_procedure(_):
    return None


class Client:
    """TestClient whose requests are made as whoever `as_()` last selected (None = signed out)."""

    def __init__(self, http: TestClient, holder: dict):
        self.http, self.holder = http, holder

    def as_(self, who: Principal | None) -> TestClient:
        self.holder["who"] = who
        return self.http


def start(c: Client, who=MAYA) -> str:
    res = c.as_(who).post("/me/conversations")
    assert res.status_code == 200, res.text
    return res.json()["id"]


def say(c: Client, conversation_id: str, text: str, who=MAYA):
    return c.as_(who).post(f"/me/conversations/{conversation_id}/messages", json={"text": text})
