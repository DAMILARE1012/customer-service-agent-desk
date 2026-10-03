"""Bot turns run without holding the conversation locked (see engine.py): while the LLM is "thinking",
other operations on the same conversation go ahead, and the turn's result is only saved if it still
applies. The stand-in answerer here waits on a gate, so a request can be held mid-turn while another runs."""

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import Request

from app import auth
from app.db import repository
from tests.support import ALEX, MAYA, fake_answer, start

PEOPLE = {"maya": MAYA, "alex": ALEX}


@pytest.fixture()
def gated(client, monkeypatch):
    """The API with a bot that waits for `gate` before answering, and the caller chosen per request
    (an `X-As` header), so two people's requests can be in flight at once."""
    import app.api.main as main
    import app.conversation.bot as bot

    gate, thinking = threading.Event(), threading.Event()

    async def slow_answer(question, *, purpose="answer", **kwargs):
        if purpose == "answer" and not gate.is_set():
            thinking.set()
            await asyncio.to_thread(gate.wait, 10)
        return await fake_answer(question, purpose=purpose, **kwargs)

    async def from_header(request: Request):
        return PEOPLE[request.headers.get("x-as", "maya")]

    monkeypatch.setattr(bot, "answer_question", slow_answer)
    main.app.dependency_overrides[auth.principal] = from_header
    http = client.http
    pool = ThreadPoolExecutor(max_workers=4)
    try:
        yield http, gate, thinking, pool
    finally:
        gate.set()
        pool.shutdown(wait=True)


def say(http, conversation_id, text, who="maya"):
    return http.post(f"/me/conversations/{conversation_id}/messages", json={"text": text}, headers={"x-as": who})


def test_an_agent_can_take_over_while_the_bot_is_answering(client, gated):
    http, gate, thinking, pool = gated
    conversation_id = start(client)
    reply = pool.submit(say, http, conversation_id, "How long does a refund take?")
    assert thinking.wait(5)

    started = time.monotonic()
    taken = http.post(f"/conversations/{conversation_id}/takeover", headers={"x-as": "alex"})
    assert taken.status_code == 200 and taken.json()["status"] == "agent_active"
    assert time.monotonic() - started < 3  # not stuck behind the bot's LLM call

    gate.set()
    seen = reply.result(timeout=10).json()
    assert seen["status"] == "agent_active"
    assert "Refunds take 2 business days." not in [m["text"] for m in seen["messages"]]  # the late bot reply is dropped
    assert repository().conversations.get(conversation_id)["botTurn"] is None


def test_a_second_message_waits_for_the_bot_and_keeps_the_order(client, gated):
    http, gate, thinking, pool = gated
    conversation_id = start(client)
    first = pool.submit(say, http, conversation_id, "How long does a refund take?")
    assert thinking.wait(5)
    second = pool.submit(say, http, conversation_id, "And a refund to a gift card?")
    time.sleep(0.5)
    assert [m["text"] for m in repository().conversations.get(conversation_id)["messages"]] == ["How long does a refund take?"]

    gate.set()
    assert first.result(timeout=10).status_code == 200
    final = second.result(timeout=10).json()
    assert [(m["sender"], m["text"]) for m in final["messages"]] == [
        ("customer", "How long does a refund take?"),
        ("bot", "Refunds take 2 business days."),
        ("customer", "And a refund to a gift card?"),
        ("bot", "Refunds take 2 business days."),
    ]


def test_a_turn_left_by_a_crashed_process_expires(client, gated):
    http, gate, _, _ = gated
    gate.set()
    conversation_id = start(client)
    repository().conversations.get(conversation_id)["botTurn"] = {"messageId": "msg_lost", "startedAt": 0}
    body = say(http, conversation_id, "How long does a refund take?").json()
    assert body["messages"][-1]["text"] == "Refunds take 2 business days."
    assert repository().conversations.get(conversation_id)["botTurn"] is None
