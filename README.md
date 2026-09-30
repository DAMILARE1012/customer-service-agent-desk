# Handoff Desk

An agent desk for a customer-service RAG assistant where **human handoff is a first-class state**, not an error path. The bot decides when to step aside, and it passes the agent everything it already knows.

React 19 · Redux Toolkit (RTK Query + slices + listener middleware) · Tailwind CSS v4 · Vite

```bash
npm install
npm run dev
```

The app runs against an in-browser mock backend by default. Open **Customer simulator** in the top bar to play the customer and trigger each handoff path live.

## The handoff model

```
bot_active ──(policy trigger)──▶ handoff_pending ──(accept)──▶ agent_active ──▶ resolved
     ▲                                                              │
     └──────────────────────────(return to bot)─────────────────────┘
```

**When the bot steps aside** (`HANDOFF_POLICY` in `src/constants/handoff.js`). The policy checks every customer turn. When several signals fire on the same turn, the primary one is picked in this order:

| Reason | Trigger |
|---|---|
| `sensitive_topic` | Fraud or unauthorised charge, legal threat, account or data deletion, safety |
| `customer_request` | The customer asks for a person or agent |
| `negative_sentiment` | Sentiment ≤ −0.5 |
| `repeated_failure` | 2 turns in a row without a confident answer |
| `low_confidence` | The best KB match is < 25% on a substantive question |
| `agent_initiated` | An agent clicks **Take over** from the live bot queue |

**What the agent receives** is the handoff packet, built in `src/api/mock/engine/handoffPacket.js`:
- the primary reason and every other signal that fired
- a priority and a live SLA wait timer
- the message that triggered the handoff
- a summary and the detected intent
- the questions that are still open
- suggested next steps
- the entities it extracted (order IDs, emails, amounts, promo codes)
- a timeline of what the bot tried, with a confidence score for each attempt
- the sentiment trend
- the knowledge-base sources it retrieved

**After the handoff** the bot works as a copilot. It drafts replies grounded in the knowledge base, and the agent can insert them with one click.

## Project structure

```
src/
  app/            store (combineSlices) + listener middleware (auto-follow accepted chats, handoff toasts)
  api/
    baseApi.js    RTK Query root; swaps to fetchBaseQuery when VITE_API_URL is set
    mock/         in-browser backend: routes, seeded DB, and the engine:
      engine/     retrieval · sentiment · entities · handoffPolicy · handoffPacket · conversationEngine
  constants/      conversation lifecycle, handoff reasons/priority/policy, queue views
  components/ui/  presentational primitives (Badge, Button, Section, Tabs, ScoreMeter, Icon…)
  features/
    conversations/  queue: API, desk UI slice, memoised selectors, list components
    thread/         transcript: header, bubbles, system events, bot retrieval trace
    composer/       agent reply box, optimistic send, copilot suggestion, state-aware gate
    handoff/        lifecycle mutations, useHandoffActions hook, context panel & brief sections
    customer/       customer profile
    simulator/      customer-side widget for exercising the bot
    notifications/  handoff toasts
    agent/          signed-in agent, availability, capacity
  layout/         TopBar, QueueStats, three-pane DeskLayout
server/
  config.js       server settings from .env (invalid values stop the run)
  ingest/         cli · pipeline · remoteFile
    adapters/     local (Markdown) · wixqa · abcd — one file per source
    transform/    htmlToMarkdown · normalize · chunker (+ unit tests)
  rag/            embedder (Transformers.js) · vectorStore · keywordIndex (BM25) · retriever (hybrid) · cli
  eval/           WixQA question sets · off-topic questions · metrics · cli
content/          your own Markdown knowledge (the `local` source)
data/             git-ignored: downloads, model weights, the built index, eval reports
```

Each feature owns its own API endpoints (added with `injectEndpoints`), its slice, and its components. Server data lives only in the RTK Query cache. The slices hold only UI state: selection, filters, drafts, and the simulator.

## Knowledge ingestion (RAG index)

The backend's knowledge index is built from several sources into one searchable store. Embeddings are computed on this machine with Transformers.js (`bge-small-en-v1.5`), so no API key is needed.

```bash
npm run ingest              # build, or update incrementally
npm run search -- "how do I connect my domain?"
npm run eval                # retrieval accuracy + suggested handoff thresholds
npm test                    # unit tests for normalization, chunking and metrics
```

**Sources** (`INGEST_SOURCES`, in priority order):

| Source | What | Audience |
|---|---|---|
| `local` | Markdown files in `content/` (your own help centre and policies). Starts with the demo shop's 10 articles. | set per file |
| `wixqa` | Wix help centre, 6,221 articles ([WixQA](https://huggingface.co/datasets/Wix/WixQA), MIT) | customer |
| `abcd` | 55 agent procedures ([ABCD](https://github.com/asappresearch/abcd), MIT) | agent only |

`audience` keeps internal procedures out of customer answers. To add a source, add one adapter file in `server/ingest/adapters/`.

**Pipeline:** adapter → HTML to structured markdown → normalization → heading-aware chunking → de-duplication → incremental embedding → vector + keyword index (`data/index/`).

- **Normalization** ([normalize.js](server/ingest/transform/normalize.js)): Unicode NFKC, removal of invisible characters, whitespace cleanup, and per-source boilerplate rules. Order numbers, prices, codes and URLs are never rewritten. Agents and the LLM see the cleaned original; quote and dash folding applies only to the search copy, and queries go through the same steps.
- **Boilerplate vs. shared content:** the WixQA boilerplate rules came from counting repeated text across the corpus. Text that carries no information (a feedback sentence repeated in 1,551 articles) is removed. Real content repeated across articles (a payments FAQ in ~130 articles) is kept once and linked to every article it appears in.
- **Chunking** ([chunker.js](server/ingest/transform/chunker.js)) splits at headings, so editing one section changes only that section's chunks.

**Freshness without unnecessary re-embedding.** Changes are detected at three levels, cheapest first:

1. **Source:** each source has a refresh window (`SOURCE_*_REFRESH_MINUTES`). Outside it, a cheap version check runs (an HTTP HEAD, or a hash of local files), and data is downloaded only if the version changed.
2. **Document:** content hashes report added, changed and removed documents.
3. **Chunk:** each vector is stored under a hash of its exact input text plus the model settings. Unchanged text is never re-embedded, and removed text is deleted in the same run.

Changing normalizer or chunker rules means bumping `NORMALIZER_VERSION` / `CHUNKER_VERSION`. Every source is then re-parsed, but vectors are still reused wherever the text came out the same. An interrupted build resumes from a checkpoint.

**Retrieval** is hybrid: vector search plus BM25, merged with reciprocal rank fusion. BM25 catches exact strings (order numbers, promo codes) that embeddings miss. The retriever's `confidence` is the cosine similarity of the top result, and `npm run eval` calibrates the handoff thresholds against it.

### Evaluation results

`npm run eval` on the 200 expert-written WixQA questions (6,192 articles, 24,047 chunks) plus 40 off-topic questions. Model: `bge-small-en-v1.5` (q8).

| Mode | hit@1 | hit@3 | hit@5 | hit@10 | MRR |
|---|---|---|---|---|---|
| vector only | 36% | 61% | 67% | 78% | 0.502 |
| keyword only | 26% | 48% | 58% | 69% | 0.393 |
| **hybrid** | **38%** | 58% | **71%** | **82%** | **0.513** |

- **Out-of-scope detection works well.** Off-topic questions never scored above 0.73. A "no match" threshold of **0.70** catches 98% of them and flags only 5% of real questions.
- **The similarity score does not tell a correct retrieval from a wrong one.** For real questions it's a median of 0.82 when the right article is in the top 3 and 0.79 when it isn't. Reaching 80% answer precision would need a threshold of 0.89, where the bot answers only 6% of questions alone.
- **So the similarity score should gate "is this in scope?", not "is this answer right?".** The next step is a cross-encoder reranker (for more accurate ranking and a relevance score that separates right from wrong) plus an LLM answerability check before the bot answers on its own.

The 40 off-topic questions are a small hand-written set, so treat the numbers above as estimates.

## Backend, monitoring and evaluation

```bash
npm run obs:up          # Langfuse + Prometheus + Grafana (Docker); first start takes a few minutes
npm run server          # support API on :8787 — traces to Langfuse, metrics on /metrics
VITE_API_URL=http://localhost:8787 npm run dev   # the desk, against the real backend
npm run eval:rag        # end-to-end experiment in Langfuse (see below)
npm run obs:down
```

| Tool | URL | Login |
|---|---|---|
| Langfuse (traces, scores, datasets, experiments) | http://localhost:3000 | `LANGFUSE_INIT_USER_EMAIL` / `LANGFUSE_INIT_USER_PASSWORD` in `.env` |
| Grafana (dashboard "Support desk — bot, handoff and LLM") | http://localhost:3001 | `GRAFANA_ADMIN_USER` / `GRAFANA_ADMIN_PASSWORD` |
| Prometheus (metrics, 9 alert rules) | http://localhost:9092 | — |

The Langfuse project and its API keys are created on first start from `.env`, so no manual setup is needed.

**The backend** (`server/api`) serves the same REST contract as the in-browser mock and reuses its conversation state machine, so the handoff model is identical. A bot turn works like this:

1. **Conversation checks first.** A sensitive topic, a request for a person, or frustration hands off without calling the LLM.
2. **Retrieval** (hybrid).
3. **No-match gate.** If confidence is below `RAG_NO_MATCH_THRESHOLD`, the question is out of scope and the LLM isn't called.
4. **Generation** with `GROQ_MODEL`. The answer must cite the numbered sources; an uncited answer counts as "can't answer".

Beyond that:
- **Failures:** if the LLM fails or times out, the bot hands off with the reason *Assistant unavailable*. It never shows the customer an error.
- **Copilot:** after a handoff, the same pipeline drafts cited replies for the agent.
- **Handoff brief:** also suggests the matching internal (ABCD) procedure.

**Monitoring (Prometheus → Grafana).**
- Desk state: waiting, longest wait, SLA breaches.
- Bot turns by outcome, handoffs by reason, and retrieval confidence.
- LLM latency, errors, rate limits, tokens and cost.
- What agents do with copilot drafts (used / edited / ignored).
- Live judge scores and knowledge-index freshness.

Alert rules: API down, LLM failing, rate limited, slow LLM, SLA breaches, stuck queue, handoff-rate spike, faithfulness drop, stale index. Labels never contain conversation or customer IDs; per-conversation detail lives in Langfuse.

**Tracing (Langfuse).**
- Every customer message is a trace, grouped by conversation (session) and customer (user). It contains the agent turn, the retrieval (the chunks and their similarity) and the LLM generation (prompt, output, tokens, cost).
- `ONLINE_EVAL_SAMPLE_RATE` of live answers are scored in the background by the judge (faithfulness, answer relevance), and the scores attach to the answer's trace.

**Evaluation**, in four layers:

| Layer | Metric | How |
|---|---|---|
| Retrieval | Recall@K, Precision@K, nDCG@K, context precision (rank-aware), MRR | deterministic, from WixQA article labels — `npm run eval` |
| Context | Context recall: are the reference answer's facts in what was retrieved? | LLM judge |
| Generation | Faithfulness (supported claims ÷ claims), unsupported claims, answer relevance, answer correctness vs the expert answer, citation from a correct article | LLM judge + deterministic |
| Decision | Answered (answerable questions), handed off (off-topic questions), correct-and-grounded rate | deterministic + judge |

`npm run eval:rag` uploads the dataset (200 WixQA + 40 off-topic questions, idempotent), runs `EVAL_RAG_LIMIT` of them through the production answer step, and records everything as a Langfuse experiment (Datasets → `support-bot-eval` → Runs) so configurations can be compared side by side.

- **Judge model:** `JUDGE_MODEL`, deliberately larger than the answering model.
- **Rate limits:** on Groq's on-demand tier `gpt-oss-120b` allows **8,000 tokens per minute** (about 2–3 judgments), so judgments queue and wait out rate limits. Expect about 20 judged questions per 10 minutes.

**Known issue:** the Langfuse worker logs `Socket timeout… 30000ms` against Redis on idle queues ([langfuse#13601](https://github.com/langfuse/langfuse/issues/13601)). Traces, scores and datasets still work. Langfuse's [guidance](https://langfuse.com/self-hosting/deployment/infrastructure/cache) is to give the container more CPU rather than raise `LANGFUSE_REDIS_SOCKET_TIMEOUT_MS`.

## Connecting a real backend

All configuration lives in `.env` (copy `.env.example`, which documents every variable). Set `VITE_API_URL=https://your-api` there. The endpoints stay the same; only the base query changes.

Only `VITE_*` variables reach the browser, so secrets such as `GROQ_API_KEY` must not use that prefix. `vite.config.js` refuses to start if a `VITE_*` name looks like a key or token. The backend must implement these routes:

| Method | Path | Body |
|---|---|---|
| GET | `/conversations` | — (returns summaries) |
| GET | `/conversations/:id` | — (returns the full conversation with `messages`, `insights`, `handoff`, `copilot`) |
| POST | `/conversations` | `{ customerId }` |
| POST | `/conversations/:id/customer-messages` | `{ text }` |
| POST | `/conversations/:id/agent-messages` | `{ agentId, text }` |
| POST | `/conversations/:id/handoff/accept` | `{ agentId }` |
| POST | `/conversations/:id/handoff/return` | `{ agentId }` |
| POST | `/conversations/:id/takeover` | `{ agentId }` |
| POST | `/conversations/:id/resolve` | `{ agentId? }` |

`src/api/mock/routes.js` is a reference implementation of these response shapes. For production:
- Answer from the hybrid retriever in `server/rag/` (already built; see above) instead of the mock's keyword search.
- Replace the template summary in `handoffPacket.js` with an LLM call.
- Replace polling with WebSockets or SSE, using RTK Query's `onCacheEntryAdded`.
