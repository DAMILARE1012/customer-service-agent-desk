# Load testing (Locust)

Realistic users against a copy of the API — with a **fake LLM**, so a run costs nothing and never touches
your Groq quota. Everything else is real: retrieval runs the embedding model and index, conversations go
to Postgres, agents sign in through Keycloak.

| User | What it does |
|---|---|
| `Visitor` (×8) | opens the widget, asks 1–3 help-centre questions, keeps the chat open (polls every 4 s), leaves; a new visitor arrives |
| `WaitingCustomer` (×2) | asks for a person, adds details while waiting, stays until an agent replies or gives up after `LOADTEST_MAX_WAIT_S` |
| `Agent` (fixed: `LOADTEST_AGENT_USERS`, default 3) | signs in, watches the queue every 4 s, accepts handoffs up to capacity, replies, resolves |

## Run it

Needs the infrastructure (`npm run infra:up`) and `uv sync --group loadtest` in `backend/` once.

```bash
npm run loadtest:setup                        # once: a Keycloak client agents can sign in with (local only)
npm run loadtest:llm                          # terminal 1: the fake LLM on :8798
npm run loadtest:api                          # terminal 2: the API under test on :8799, its own database (baton_load)
npm run loadtest                              # terminal 3: Locust's UI → http://localhost:8089
npm run loadtest:ci                           # or headless: 150 users for 3 min; exits 1 if a threshold is missed
```

**Measuring several processes** — do it in the Linux container, as you'd deploy it (on Windows, uvicorn's
workers can't reliably share a socket), and run Locust inside Docker too (Docker Desktop's port forwarding
adds latency and drops connections at high rates):

```bash
npm run loadtest:api -- --docker --workers 4  # the API image + the fake LLM in Docker (stop the local fake LLM first)
npm run loadtest:docker -- -u 300 -r 5 -t 3m  # Locust in Docker, same network
npm run loadtest:api -- --docker --down       # stop
npm run loadtest:setup -- --remove            # remove the Keycloak client when you're done
```

## Thresholds

Checked when the run stops; the process exits 1 if one is missed (so `loadtest:ci` can gate a pipeline).

| Variable | Default | |
|---|---|---|
| `LOADTEST_MAX_FAILURE_RATIO` | 0.01 | share of failed requests |
| `LOADTEST_P95_POLL_MS` | 1000 | a customer's chat checking for news |
| `LOADTEST_P95_QUEUE_MS` | 1500 | an agent's queue refresh |
| `LOADTEST_P95_ANSWER_MS` | 15000 | a question answered by the bot (fake LLM ≈ 2 s) |

## What the first runs found

Four production bugs, all fixed:

1. **uvicorn killed busy workers.** Its worker health check gives up after 5 s — less than loading the
   embedding model or a busy moment — so workers were killed and restarted in a loop (9 deaths at start-up).
   Now `API_WORKER_HEALTHCHECK_SECONDS` (60).
2. **Workers fought over the CPU.** PyTorch and NumPy each used every core in every worker. Now each
   worker gets cores ÷ workers (`CPU_THREADS_PER_WORKER` to set it, e.g. on ECS).
3. **Keep-alive race.** uvicorn closed idle connections after 5 s, under the widget's 4-second polling
   plus a slow response — and any load balancer's idle timeout (ALB: 60 s). Clients reused closing
   connections: resets here, 502s behind a proxy. Now `API_KEEP_ALIVE_SECONDS` (65).
4. **Workers' logs were lost.** Logging was set up only in the parent process. Now in every worker.

## Results (developer laptop, 12 cores — everything on one machine)

Realistic mix; the fake LLM answers in about 2 s.

| Setup | Users | Chat checks p95 | Bot answers p95 | Requests/s | Errors | Thresholds |
|---|---|---|---|---|---|---|
| 1 process (Windows, from source) | 150 | 590 ms | 4.7 s | 41 | 0 | ✅ |
| 1 process (Windows, from source) | 300 | 6.5 s | 18 s | 47 | 0 | ❌ |
| Container, 1 worker | 300 | 12 s | 29 s | 30 | 0 | ❌ |
| Container, 4 workers | 300 | 3.9 s | 30 s | 58 | 0.15 %¹ | ❌ |

¹ one-second blip in Docker Desktop's port forwarding; zero errors once Locust ran inside Docker.

**Reading them:** one process comfortably serves about **150 people chatting at once**; four processes
roughly double throughput on the same (shared, busy) laptop — not 4×, because Postgres, Keycloak, the
Langfuse stack, Docker's VM and Locust all compete for the same CPU. Runs vary noticeably for the same
reason; on dedicated servers, measure again. Each worker is bound by Python's single core (the GIL), and
the biggest per-request costs are, in order:

- **Polling re-sends the whole transcript every 4 s,** even when nothing changed (~60 % of all requests).
  A cheap "anything new since …?" check (returning 304 Not Modified), or server-sent events, would cut most of it.
- **The keyword (BM25) search is pure Python** (~24 ms of the ~70 ms per question); a NumPy/sparse version would remove most of it.
- **The embedding model** (~42 ms per question) — already outside the GIL; batching concurrent questions would help.

The LLM itself isn't the limit here — on the free Groq tier, its rate limit is (see the main README).
