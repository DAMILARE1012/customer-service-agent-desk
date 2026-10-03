<p align="center"><img src="frontend/public/favicon.svg" width="64" alt="Baton logo" /></p>

<h1 align="center">Baton</h1>

<p align="center"><strong>Customer support that knows when to pass the baton.</strong><br/>
A RAG assistant that answers from your help centre with citations — and when it shouldn’t answer, hands the customer to a person with everything it already knows.</p>

<p align="center"><img src="docs/screenshots/agent-handoff-brief.png" alt="The agent desk: a waiting handoff, the transcript and the bot's handoff brief" width="900" /></p>

## The problem

Support bots fail in two ways. They don’t know when to stop — they guess, invent policies and loop on “could you rephrase?” while fraud reports get the same canned treatment as “where’s my order?”. And when they do give up, the context is lost: the agent opens a blank chat and the customer explains everything again.

Baton treats the handoff as a **first-class state** of every conversation, with its own policy, its own data (the handoff brief), its own queue and SLA.

## How it works

1. **A customer asks** in a chat bubble on the company’s website — no account needed.
2. **The bot answers from the help centre**, citing the articles. Hybrid retrieval (vectors + keywords) finds the sources; an answer without a citation counts as “can’t answer”.
3. **It steps aside when it should**: a sensitive topic (fraud, legal), the customer asks for a person, frustration, a question outside the knowledge base, or two failed attempts in a row.
4. **The agent gets a brief, not a blank chat**: why the bot stepped aside, a summary, what it tried, order numbers and amounts, sentiment, sources and a drafted reply. Anything the customer adds while waiting updates it, and urgency moves them up the queue.
5. **Nobody in?** The customer is told when the team is back and answered by email; agents are alerted.
6. **It learns**: closed chats become missing help articles and test questions, after an admin approves them.

More detail: [how it works](docs/how-it-works.md).

## Screenshots

| Chat widget on a website | Cited answer | An agent took over |
|---|---|---|
| ![The chat launcher over a shop page](docs/screenshots/widget-closed.png) | ![Cited answer in the widget](docs/screenshots/widget-open.png) | ![Agent reply in the widget](docs/screenshots/widget-agent-reply.png) |
| **Agent: handoff brief** | **Agent: customer timeline** | **Team away: reply by email** |
| ![Handoff brief](docs/screenshots/agent-handoff-brief.png) | ![Follow-up and timeline](docs/screenshots/agent-timeline.png) | ![Team away, email form](docs/screenshots/widget-team-away.png) |

## Architecture

<p align="center"><img src="docs/architecture.png" alt="Baton architecture: the staff app with Keycloak, the chat widget on a customer’s website, FastAPI API, Postgres, knowledge index, Groq, Vault, observability and offline ingestion" width="1000" /></p>

Customers use the **widget** on the company’s website; agents and admins use the **staff app**, signed in with Keycloak. The **FastAPI** API keeps conversations in Postgres, answers from a local index and Groq, and gets every secret from **Vault**. Langfuse, Prometheus and Grafana watch the bot, the desk and the LLM. Edit the diagram in [draw.io](https://app.diagrams.net) with [`docs/architecture.drawio`](docs/architecture.drawio).

## Getting started

Needs Docker Desktop, Node 20+, Python 3.12+ with [uv](https://docs.astral.sh/uv/), and a free [Groq API key](https://console.groq.com/keys).

```bash
cp .env.example .env    # set GROQ_API_KEY, VITE_API_URL=http://localhost:8787, VITE_KEYCLOAK_URL=http://localhost:8080
npm run ingest          # once: builds the knowledge index (about an hour on a CPU, resumable)
npm start               # everything, in order — then open http://localhost:5173
```

- **Customer:** http://localhost:5173/demo-store — a pretend shop with the chat widget.
- **Staff:** http://localhost:5173 — logins with `npm run accounts`.
- **Stop:** `Ctrl+C`, then `npm stop`. Skip Langfuse and Grafana with `npm start -- --no-obs`; run everything as containers with `npm start -- --docker`.

No time for the full stack? `cd frontend && npm install && npm run dev` runs the app on an in-browser demo backend (leave `VITE_API_URL` and `VITE_KEYCLOAK_URL` empty).

**More:** [commands, accounts, embedding the widget, Vault, results](docs/guide.md) · [deploying on AWS](docs/deploy-aws.md) · [load testing](loadtest/README.md)
