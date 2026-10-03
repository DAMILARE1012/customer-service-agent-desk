"""A stand-in for Groq's chat-completions API, so load tests cost nothing and don't hit your rate limits.

Waits FAKE_LLM_DELAY seconds (± FAKE_LLM_JITTER, as a fraction) and returns a valid cited answer — the
same shape the answerer and the copilot expect. Everything else in the API is real: retrieval runs the
actual embedding model and index, conversations go to Postgres.

    npm run loadtest:llm           # http://127.0.0.1:8798 ; GET /stats shows calls and peak concurrency
"""

import asyncio
import json
import os
import random
import time

import uvicorn
from fastapi import FastAPI, Request

DELAY = float(os.environ.get("FAKE_LLM_DELAY", "2"))
JITTER = float(os.environ.get("FAKE_LLM_JITTER", "0.4"))
PORT = int(os.environ.get("FAKE_LLM_PORT", "8798"))
HOST = os.environ.get("FAKE_LLM_HOST", "127.0.0.1")  # 0.0.0.0 inside Docker

app = FastAPI(title="Fake LLM for load tests")
calls = {"n": 0, "inFlight": 0, "peak": 0}


@app.post("/chat/completions")
async def chat(request: Request):
    body = await request.json()
    calls["n"] += 1
    calls["inFlight"] += 1
    calls["peak"] = max(calls["peak"], calls["inFlight"])
    try:
        await asyncio.sleep(max(0.05, DELAY * random.uniform(1 - JITTER, 1 + JITTER)))
    finally:
        calls["inFlight"] -= 1
    content = json.dumps({"answerable": True, "answer": "You can do that from your dashboard — see the linked article for the steps.", "citations": [1]})
    return {
        "id": f"fake-{calls['n']}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": body.get("model", "fake"),
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1200, "completion_tokens": 40, "total_tokens": 1240},
    }


@app.get("/stats")
async def stats():
    return calls


@app.post("/reset")
async def reset():
    calls.update(n=0, inFlight=0, peak=0)
    return calls


if __name__ == "__main__":
    print(f"fake LLM on http://{HOST}:{PORT} — {DELAY}s per answer (±{int(JITTER * 100)}%)")
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")
