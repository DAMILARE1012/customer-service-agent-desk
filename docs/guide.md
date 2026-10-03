# Baton guide — running, configuring and deploying

[← Back to the README](../README.md) · [How it works](how-it-works.md)

**Contents** · [Commands](#commands) · [Accounts](#accounts) · [Adding the widget to a website](#adding-the-widget-to-a-website) · [Deploying](#deploying) · [Secrets: HashiCorp Vault](#secrets-hashicorp-vault) · [Tech stack](#tech-stack) · [Results](#results) · [Project layout](#project-layout) · [Limitations](#limitations)

## Commands

| Command | Does |
|---|---|
| `npm start` · `npm stop` | Everything, in order (`-- --no-obs` skips Langfuse/Grafana, `-- --docker` runs the API and web as containers) · stop the containers (data is kept) |
| `npm run accounts` | Print every login with its URL and password |
| `npm run dev` · `npm run api` | Staff app, widget and demo store · API (OpenAPI docs at http://localhost:8787/docs) |
| `npm run ingest` | Build or update the knowledge index |
| `npm run eval` · `npm run eval:rag` | Retrieval metrics · end-to-end Langfuse experiment (`-- --include-reviewed` adds approved test questions) |
| `npm test` | Backend tests |
| `npm run infra:up` / `infra:down` · `npm run obs:up` / `obs:down` | Postgres, Keycloak, Vault, Mailpit · monitoring stack |
| `npm run vault:seed` | Copy secrets you’ve put in `.env` into Vault (merged; nothing is regenerated) |
| `npm run app:up` / `app:down` · `app:logs` · `app:ingest` | The whole app as containers · their logs · build the index in Docker |
| `npm run loadtest` · `loadtest:ci` | Load test with Locust (UI · headless with pass/fail thresholds) — see [`loadtest/README.md`](../loadtest/README.md) |

`npm start` runs, in order: `infra:up` (Vault first, unsealed, then Postgres, Keycloak, Mailpit) → `obs:up` → the API and web app from source with live reload. In Docker, build the index into the volume once with `npm run app:ingest`, or copy one you built from source:
`docker run --rm -v baton_baton_data:/data -v "$PWD/data:/src:ro" alpine sh -c "cd /src && tar -cf - index models | tar -C /data -xf - && chown -R 10001:10001 /data"`.

## Accounts

`npm run accounts` prints every login with its URL; passwords marked (Vault) are read from Vault.

| Who | Where | Username | Password |
|---|---|---|---|
| Customers | http://localhost:5173/demo-store | none — guests chat anonymously; the demo bar “signs in” to the shop as a seeded customer | — |
| Agents | http://localhost:5173 (staff app) | `alex.rivera`, `priya.shah` | `BATON_DEMO_PASSWORD` (Vault) |
| Admin | http://localhost:5173 (staff app) | `jade.kim` (admin and agent) | `BATON_DEMO_PASSWORD` (Vault) |
| Keycloak admin console | http://localhost:8080/admin | `KEYCLOAK_ADMIN_USER` (default `admin`) | `KEYCLOAK_ADMIN_PASSWORD` (Vault) |
| Langfuse | http://localhost:3000 | `LANGFUSE_INIT_USER_EMAIL` | `LANGFUSE_INIT_USER_PASSWORD` (Vault) |
| Grafana | http://localhost:3001 | `GRAFANA_ADMIN_USER` | `GRAFANA_ADMIN_PASSWORD` (Vault) |
| Mailpit (every email the app sends) | http://localhost:8025 | none | — |
| Vault | http://localhost:8200 | method: Token | root token in `infra/vault/local/init.txt` |

Keycloak holds staff only: add agents in its admin console and give them the `agent` role.

## Adding the widget to a website

One tag, anywhere on the page:

```html
<script src="https://YOUR-BATON-HOST/widget.js" async></script>
```

A launcher appears bottom right and opens the chat in an iframe (full screen on phones), so the site’s styles can’t break it and it can’t read the page. That is all guests need.

**Signed-in shoppers.** So a returning customer sees their own history on any device, the website’s backend signs an identity token — an HS256 JWT with `WIDGET_IDENTITY_SECRET` — and the page passes it in:

```js
// claims: sub = your user id (required), name, email, iat, exp (at most 24 h after iat)
Baton.identify(identityToken);   // on each page load while they're signed in
Baton.logout();                  // when they sign out of your site
Baton.open(); Baton.close();     // optional
```

The secret never reaches the browser. The demo store at `/demo-store` plays the website: its “Signed in to the shop as” menu gets tokens from a demo-only endpoint that exists only while `WIDGET_DEMO_IDENTITY=true` — keep it `false` in production.

## Deploying

Two images, configured only by environment variables (nothing secret is baked in; `.env` never reaches a build):

| Image | Built from | Notes |
|---|---|---|
| `baton-api` | `backend/Dockerfile` | Python 3.12 slim, CPU-only PyTorch, non-root. Mount `/app/data` (index + models) and `/app/content` (articles). `API_WORKERS` sets processes; see `.env.example` for the worker health check, math threads per worker and keep-alive (keep it above your load balancer’s idle timeout). |
| `baton-web` | `frontend/Dockerfile` | nginx (unprivileged). `VITE_*` settings are read **when the container starts**, so one image serves anyone’s URLs. `WIDGET_FRAME_ANCESTORS` lists the sites allowed to embed the chat widget; the staff app can’t be framed. |

**A sensible AWS shape.** A public subnet with the load balancer (HTTPS via ACM) and the NAT gateway; private subnets for the API and web containers (ECS Fargate or EC2), Keycloak, Vault, and Postgres (RDS). Then tighten: `CORS_ORIGIN` and `BATON_WEB_URL` to your domain, `WIDGET_FRAME_ANCESTORS` to your shop’s domains, `WIDGET_DEMO_IDENTITY=false`, Keycloak in production mode (`start`, behind TLS), and `SMTP_*` pointing at a real provider (for example Amazon SES).

## Secrets: HashiCorp Vault

No service reads a secret from `.env`; Vault starts first and everything that needs a secret waits for it:

```
vault ─▶ vault-init ─▶ secrets (Vault Agent) ─▶ db ─▶ keycloak ─▶ api
observability:  vault ─▶ secrets (Vault Agent) ─▶ postgres · clickhouse · redis · minio · grafana ─▶ langfuse
```

| Vault path | Holds | Read by |
|---|---|---|
| `secret/baton/api` | Groq key, widget secrets, SMTP password, webhook URL | API |
| `secret/baton/database` | the app database password | Postgres (via Vault Agent), API |
| `secret/baton/keycloak` | Keycloak’s database and admin passwords, the demo staff password | Keycloak (via Vault Agent) |
| `secret/baton/keycloak-client` | the API’s Keycloak service-account secret — one copy, read by both sides | Keycloak, API |
| `secret/baton/langfuse-project` | the Langfuse project keys — one copy | Langfuse, API |
| `secret/baton/observability` | Langfuse’s databases and secrets, the Grafana admin password | the observability stack (via Vault Agent) |

Vault keeps its data in its own volume, not in Postgres — otherwise each would need the other to start. On the first start, `vault-init` initialises and unseals Vault, creates a read-only policy and an AppRole per consumer, and fills each path from `.env` where you’ve set a value or with a strong generated one. Vault Agent renders the infrastructure’s passwords into Docker-only volumes; the API logs in with its AppRole and **refuses to start** if Vault is configured but unreachable — it never falls back to a value left in the environment. Rotating a secret is a change in Vault (plus `ALTER ROLE` for a database password) and a restart. Locally the unseal key and root token sit in `infra/vault/local/` (git-ignored) — back it up: without it Vault can’t be unsealed. In production: KMS auto-unseal (the `seal "awskms"` stanza in `infra/vault/config/vault.hcl`), raft storage on three nodes, TLS, and AWS IAM auth instead of secret_ids on disk.

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | React 19 · Vite 8 · Redux Toolkit 2 (RTK Query) · Tailwind CSS 4 · keycloak-js · embeddable widget (iframe + `postMessage`) |
| API | Python 3.12 · FastAPI · Pydantic 2 · PyJWT · psycopg 3 |
| Secrets | HashiCorp Vault 1.20 — KV v2, AppRole, Vault Agent |
| Identity | Keycloak 26 for staff · signed widget sessions and website identity tokens for customers |
| Database | PostgreSQL 17 — versioned schema, row-locked conversation transactions |
| Retrieval | sentence-transformers `bge-small-en-v1.5` (local CPU) · BM25 · reciprocal rank fusion |
| LLM | Groq · `openai/gpt-oss-20b` (answers, copilot) · `openai/gpt-oss-120b` (judge) |
| Observability | Langfuse 4 · Prometheus 3 · Grafana 13 |
| Notifications | SMTP (Mailpit locally) · Slack/Mattermost/Teams webhook · browser Notification API |
| Tooling | uv · ruff · pytest · Locust · Docker Compose |

## Results

**Retrieval** — 200 expert-written WixQA questions over 6,192 articles (`npm run eval`):

| Mode | hit@1 | hit@5 | hit@10 | MRR |
|---|---|---|---|---|
| Vector | 36% | 71% | 80% | 0.51 |
| Keyword (BM25) | 26% | 58% | 69% | 0.39 |
| **Hybrid (default)** | 35% | **73%** | 81% | 0.50 |
| Hybrid + `bge-reranker-base` | 40% | 72% | 83% | 0.53 |

A no-match threshold of 0.70 catches 98% of off-topic questions while flagging 5% of real ones. The reranker helps the top result but costs ~12 s per question on a CPU, so it’s off by default (`RERANKER_MODEL`).

**End to end** — 50 WixQA questions + 10 off-topic, `gpt-oss-20b` judged by `gpt-oss-120b` (`npm run eval:rag`): **97% faithful**, **100%** of off-topic questions handed off, 96% answered, 68% correct, **56% correct and grounded**. The bottleneck is retrieval: in a third of cases the right facts aren’t in the context (context recall 64%).

**Under load** — one API process serves about **150 people chatting at once** within the targets on a 12-core laptop, with zero errors; four processes roughly double throughput. Details: [`loadtest/README.md`](../loadtest/README.md).

## Project layout

```
frontend/       React app — widget (customer chat), demo store, desk and admin; public/widget.js · Dockerfile
backend/        FastAPI app (uv) — api/, auth.py, secrets.py (Vault), db/, conversation/, team.py, notify/, rag/, ingest/, review/, privacy/, eval/ · Dockerfile
infra/          compose (Vault, Postgres, Keycloak, Mailpit; the app with the "app" profile), realm import, Vault config/policies/init
observability/  Langfuse + Prometheus + Grafana: compose, Vault Agent config, dashboard, alert rules
content/        your own Markdown help-centre articles (published review articles land here)
docs/           this guide, how it works, architecture diagram (draw.io) and screenshots
loadtest/       Locust users, the fake LLM, and scripts to run the API under test
scripts/        start / stop / accounts
```

`npm test` runs 120 backend tests with no network or keys; 7 more test the Postgres repository against a disposable database (see the top of `backend/tests/test_postgres.py`).

## Limitations

- Several API processes are supported, with small caveats: disabling an agent takes up to 30 s everywhere, rate limits are counted per process, and Grafana should aggregate the desk gauges with `max`. On Windows, run several processes in Docker (uvicorn’s workers can’t reliably share a socket there).
- Redaction is rule-based, so an admin checks every review item before it is published.
- A guest’s session lives in the widget’s storage; browsers that block third-party storage may start a guest afresh. Identified shoppers are unaffected.
- The apps poll; Server-Sent Events would cut latency. Keycloak runs in development mode — use production mode with TLS for real deployments.
- Desk sound alerts start after the agent’s first click on the page; desktop notifications need the browser’s permission. Business hours can’t span midnight; customers can’t reply by email.
- The demo knowledge base is the Wix help centre, so some answers address a site owner rather than a shop customer.

**Data:** [WixQA](https://huggingface.co/datasets/Wix/WixQA) (MIT) · [ABCD](https://github.com/asappresearch/abcd) (MIT) · [bge-small-en-v1.5](https://huggingface.co/BAAI/bge-small-en-v1.5) (MIT).
