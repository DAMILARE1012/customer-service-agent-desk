# Deploying Baton on AWS — step by step

[← Back to the README](../README.md) · [Guide](guide.md)

A runbook, in the order to do things: each step depends only on the ones before it. It mirrors the local
stack — Vault first, then everything that needs a secret — with AWS services where they're simpler.

## Before you start: the shape, and four adjustments to the plan

**One public subnet isn't enough.** An Application Load Balancer must sit in public subnets in **at least two
Availability Zones**, and an RDS subnet group needs **two AZs** too. So the minimum is **2 public + 2 private**
subnets — the "public in front, private behind" idea, repeated in two AZs. This guide uses **six** (a separate
private tier for data), which costs nothing extra and keeps the database unreachable from anything but the app.

```
                                   Internet
                                      │
                         Route 53 (app./api./auth.example.com)
                                      │ HTTPS (ACM certificate)
┌─ VPC 10.0.0.0/16 ───────────────────┼──────────────────────────────────────────────────┐
│  AZ a                               │                       AZ b                        │
│  ┌ public 10.0.0.0/24 ──────────────┴───────────┐  ┌ public 10.0.1.0/24 ────────────┐  │
│  │  Application Load Balancer · NAT Gateway      │  │  Application Load Balancer     │  │
│  └───────────────────────────────────────────────┘  └────────────────────────────────┘  │
│  ┌ private-app 10.0.10.0/24 ────────────────────┐  ┌ private-app 10.0.11.0/24 ───────┐  │
│  │  ECS Fargate: web · api · keycloak            │  │  (second copies when you scale) │  │
│  │  Vault (EC2, KMS auto-unseal)                 │  │                                 │  │
│  └───────────────────────────────────────────────┘  └────────────────────────────────┘  │
│  ┌ private-data 10.0.20.0/24 ───────────────────┐  ┌ private-data 10.0.21.0/24 ──────┐  │
│  │  RDS PostgreSQL · EFS (index, models, articles)│  │  RDS subnet group · EFS mount   │  │
│  └───────────────────────────────────────────────┘  └────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────────────────────┘
     outbound (Groq, Langfuse Cloud, SES, image pulls) leaves through the NAT Gateway
```

**Three more suggestions:**

1. **Don't self-host the observability stack on AWS.** Langfuse needs ClickHouse, Redis, MinIO and its own
   Postgres — more than the app itself. Use **Langfuse Cloud's free tier** (same keys, one setting) and either
   **CloudWatch Container Insights** or **Grafana Cloud's free tier** (import `observability/grafana/dashboards/baton.json`).
2. **One NAT Gateway, not one per AZ**, for a demo. It's the largest fixed cost after compute; add the second
   for high availability later.
3. **Write it as code (Terraform or AWS CDK)** once you've clicked through it the first time. You'll want to
   `destroy` it when you're not demoing — AWS bills the load balancer and NAT Gateway by the hour.

**What it costs** (approximate, US/EU regions, on-demand — check the [AWS Pricing Calculator](https://calculator.aws/)):

| Item | Size | ≈ per month |
|---|---|---|
| Application Load Balancer | 1 | $18 |
| NAT Gateway | 1 (+ data) | $33 + traffic |
| ECS Fargate — api | 1 vCPU, 3 GB | $40 |
| ECS Fargate — keycloak | 0.5 vCPU, 1 GB | $18 |
| ECS Fargate — web | 0.25 vCPU, 0.5 GB | $9 |
| Vault on EC2 | t4g.small + 20 GB gp3 | $14 |
| RDS PostgreSQL | db.t4g.micro + 20 GB | $15 |
| EFS, Route 53, CloudWatch logs, SES | small | $5 |
| **Total** | | **≈ $150** (Langfuse Cloud, Grafana Cloud: free tiers) |

Too much for a demo? See the [budget option](#the-budget-option-one-server) at the end (≈ $70, and you can switch it off).

---

## Step 0 — Accounts, tooling and two small code changes

1. **AWS account**: turn on MFA for the root user, then work as an IAM Identity Center (or IAM) admin — never root.
2. **AWS Budgets**: create a monthly budget with alerts at, say, $50 and $150. Do this first.
3. **Pick a region** and stay in it (EU London `eu-west-2` or Ireland `eu-west-1` are good from West Africa;
   Cape Town `af-south-1` is closer but must be opted into and costs a little more).
4. **A domain** — in Route 53, or at another registrar with its name servers pointed to a Route 53 hosted zone.
   This guide uses `app.example.com` (staff app + widget), `api.example.com` and `auth.example.com` (Keycloak).
5. **Tools on your laptop**: AWS CLI v2 with the Session Manager plugin, Docker, and the Vault CLI.
6. **Code changes to make first** (ask me and I'll do them):
   - **A Keycloak image for production** — `infra/keycloak/Dockerfile`: build Keycloak once with `kc.sh build`
     (Postgres, health on), copy in the realm from `infra/keycloak/import`, run `start --optimized --import-realm`.
   - **Optional, for hardening: Vault's AWS IAM login in the API** (`app/secrets.py`), so ECS tasks prove who they are
     with their IAM role instead of an AppRole `secret_id`. This guide uses AppRole (works today) and keeps the
     `secret_id` in SSM Parameter Store.

## Step 1 — Network

1. **VPC** `10.0.0.0/16`, DNS hostnames and DNS resolution **on**.
2. **Six subnets**, two AZs: `public-a/b` (`10.0.0.0/24`, `10.0.1.0/24`), `private-app-a/b` (`10.0.10.0/24`,
   `10.0.11.0/24`), `private-data-a/b` (`10.0.20.0/24`, `10.0.21.0/24`). Public subnets: auto-assign public IPv4 **off**
   (only the load balancer and NAT need public addresses, and they get their own).
3. **Internet Gateway**, attached to the VPC.
4. **NAT Gateway** in `public-a`, with an Elastic IP.
5. **Route tables**:
   - `public`: `0.0.0.0/0 → Internet Gateway`; associate both public subnets.
   - `private-app`: `0.0.0.0/0 → NAT Gateway`; associate both app subnets (they call Groq, Langfuse Cloud, SES, ECR).
   - `private-data`: **no internet route**; associate both data subnets.
6. **S3 gateway endpoint** (free) on the private route tables — image layers and your data upload skip the NAT.
7. **Route 53 private hosted zone** `baton.internal` associated with the VPC (for `vault.baton.internal`).

## Step 2 — Security groups (who may talk to whom)

| Group | Inbound | Used by |
|---|---|---|
| `alb-sg` | 443 and 80 from `0.0.0.0/0` | the load balancer |
| `app-sg` | 8080 (web, keycloak), 8787 (api), 9000 (keycloak health) **from `alb-sg`** | ECS tasks |
| `vault-sg` | 8200 **from `app-sg`** | Vault |
| `db-sg` | 5432 **from `app-sg`** and **from `vault-sg`** (setup only, see step 5) | RDS |
| `efs-sg` | 2049 **from `app-sg`** | EFS mount targets |

No SSH anywhere: you'll reach machines with **Session Manager**.

## Step 3 — Certificates

1. **ACM certificate** (in the same region as the load balancer) for `example.com` and `*.example.com`,
   validated by DNS — let ACM create the Route 53 records.

## Step 4 — Load balancer (no targets yet)

1. **Application Load Balancer**, internet-facing, in `public-a` and `public-b`, with `alb-sg`. Idle timeout **60 s**
   (the API keeps connections open 65 s, longer than this — `API_KEEP_ALIVE_SECONDS`).
2. **Target groups** (type **IP**, for Fargate):
   - `tg-web` — HTTP 8080, health check `/healthz`.
   - `tg-api` — HTTP 8787, health check `/health`, deregistration delay 30 s.
   - `tg-keycloak` — HTTP 8080, health check on **port 9000**, path `/health/ready`.
3. **Listeners**: 80 → redirect to 443. 443 with the ACM certificate and these rules:
   - host `api.example.com` + path `/metrics` → fixed response 404 (the metrics endpoint isn't for the public);
   - host `auth.example.com` + path `/admin*` → forward to `tg-keycloak` **only from your IP** (a source-IP
     condition), otherwise 403 — the Keycloak admin console stays off the internet;
   - host `app.example.com` → `tg-web`; `api.example.com` → `tg-api`; `auth.example.com` → `tg-keycloak`.

## Step 5 — Vault (the root of trust)

1. **KMS key** `baton-vault-unseal` (symmetric).
2. **IAM role for the instance**: `kms:Encrypt`, `kms:Decrypt`, `kms:DescribeKey` on that key, plus the managed
   policy `AmazonSSMManagedInstanceCore` (Session Manager).
3. **EC2** `t4g.small`, Amazon Linux 2023 (ARM), in `private-app-a`, `vault-sg`, encrypted 20 GB gp3 volume,
   that instance role. Install Vault from HashiCorp's package repository.
4. **`/etc/vault.d/vault.hcl`** — the local `infra/vault/config/vault.hcl`, with three changes:
   integrated storage (`storage "raft" { path = "/opt/vault/data" node_id = "vault-1" }`), the **`seal "awskms"`**
   stanza (already in that file, commented) pointing at your key, and `api_addr`/`cluster_addr` using
   `vault.baton.internal`. For TLS, give the listener a certificate from your own small CA; for a first demo,
   `tls_disable` is acceptable *only* because `vault-sg` admits nothing but the app.
5. **DNS**: `vault.baton.internal` → the instance's private IP (private hosted zone).
6. **Start and initialise** from your laptop, through Session Manager port forwarding:
   ```bash
   aws ssm start-session --target <instance-id> --document-name AWS-StartPortForwardingSession \
     --parameters portNumber=8200,localPortNumber=8200
   export VAULT_ADDR=http://127.0.0.1:8200   # in another terminal
   vault operator init        # with KMS: no unseal keys, only recovery keys — store them offline, safely
   ```
   With auto-unseal, Vault unseals itself after every restart — no `init.txt` on a disk.
7. **Set it up** as `infra/vault/init.sh` does locally: `vault secrets enable -path=secret -version=2 kv`, write the
   policies from `infra/vault/policies/` (`baton-api`, `baton-infra`), enable AppRole and create those two roles.
8. **Put the secrets in** — the same paths as locally (`secret/baton/api`, `database`, `keycloak`,
   `keycloak-client`, `langfuse-project`). Generate new values for production; don't reuse your laptop's.
   You'll add `SMTP_PASSWORD` (step 13) and the Langfuse Cloud keys (step 13) later.
9. **Backups**: a systemd timer running `vault operator raft snapshot save` to an S3 bucket, nightly.

## Step 6 — Data: RDS and EFS

1. **DB subnet group** from `private-data-a/b`.
2. **RDS PostgreSQL 17**, `db.t4g.micro`, 20 GB gp3, encrypted, **not publicly accessible**, `db-sg`, automated
   backups 7 days. Master user `baton`, password = `BATON_DB_PASSWORD` from `secret/baton/database`.
3. **Keycloak's database and user** — connect through the Vault instance as a jump host:
   ```bash
   aws ssm start-session --target <vault-instance-id> --document-name AWS-StartPortForwardingSessionToRemoteHost \
     --parameters host=<rds-endpoint>,portNumber=5432,localPortNumber=5432
   psql "postgresql://baton@127.0.0.1:5432/postgres" \
     -c "CREATE ROLE keycloak LOGIN PASSWORD '<KEYCLOAK_DB_PASSWORD from Vault>'" -c "CREATE DATABASE keycloak OWNER keycloak" -c "CREATE DATABASE baton"
   ```
   Then remove the `vault-sg` rule from `db-sg`. (The API creates its own tables on first start.)
4. **EFS** file system, encrypted, mount targets in `private-data-a/b` with `efs-sg`; an **access point** for
   `/baton` with POSIX user and group **10001** (the API image's user).

## Step 7 — Container images

1. **ECR repositories**: `baton-api`, `baton-web`, `baton-keycloak`.
2. **Build and push** from the repository root, tagged with the git commit:
   ```bash
   aws ecr get-login-password | docker login --username AWS --password-stdin <account>.dkr.ecr.<region>.amazonaws.com
   docker build -f backend/Dockerfile -t <ecr>/baton-api:<sha> . && docker push <ecr>/baton-api:<sha>
   docker build -f frontend/Dockerfile -t <ecr>/baton-web:<sha> . && docker push <ecr>/baton-web:<sha>
   docker build -f infra/keycloak/Dockerfile -t <ecr>/baton-keycloak:<sha> . && docker push <ecr>/baton-keycloak:<sha>
   ```
   (Building on an ARM Mac? add `--platform linux/amd64`, or run Fargate on ARM — about 20 % cheaper.)

## Step 8 — ECS cluster, roles and the AppRole credentials

1. **ECS cluster** (Fargate) with Container Insights on.
2. **SSM Parameter Store** (SecureString): `/baton/vault/api/secret-id` and `/baton/vault/infra/secret-id`, each a
   fresh `secret_id` for its AppRole (`vault write -f auth/approle/role/<role>/secret-id`).
3. **Task execution role**: `AmazonECSTaskExecutionRolePolicy`, plus `ssm:GetParameters` on `/baton/*` and
   `kms:Decrypt` for the parameters' key.
4. **Task roles**: none needed by the app today (add `ses:SendRawEmail` if you later send through the SES API
   instead of SMTP).
5. **CloudWatch log groups** `/baton/api`, `/baton/web`, `/baton/keycloak` (14-day retention).

## Step 9 — Keycloak service

1. **Task definition** (0.5 vCPU, 1 GB), two containers sharing an ephemeral volume `/run/baton-secrets`:
   - `vault-agent` (image `hashicorp/vault`, **essential: false**): writes the role id and `secret_id` (from SSM,
     via `secrets`) to files, then runs `vault agent` with `infra/vault/agent/infra.hcl` (Vault address →
     `http://vault.baton.internal:8200`). It renders `keycloak.env` and exits.
   - `keycloak` (your `baton-keycloak` image), **depends on `vault-agent` reaching `SUCCESS`**, entrypoint sourcing
     `/run/baton-secrets/keycloak.env` (as locally) then `kc.sh start --optimized --import-realm`. Environment:
     `KC_DB_URL=jdbc:postgresql://<rds-endpoint>:5432/keycloak`, `KC_DB_USERNAME=keycloak`,
     `KC_HOSTNAME=https://auth.example.com`, `KC_PROXY_HEADERS=xforwarded`, `KC_HTTP_ENABLED=true`,
     `KC_HEALTH_ENABLED=true`, `BATON_WEB_URL=https://app.example.com` (the realm's redirect URL).
2. **Service**: 1 task, `private-app-a/b`, `app-sg`, **no public IP**, attached to `tg-keycloak`, health-check
   grace period 120 s. Wait for it to be healthy in the target group before going on.

## Step 10 — The knowledge index on EFS

The API needs `data/index` and `data/models` (≈ 1.4 GB). Faster than re-ingesting on AWS:
1. **Upload** your local `data/index` and `data/models` to a private S3 bucket (`aws s3 sync data s3://<bucket>/data`).
2. **One-off ECS task** (image `amazon/aws-cli`, EFS access point mounted at `/data`, a task role that can read
   the bucket): `aws s3 sync s3://<bucket>/data /data`. Or run the `baton-api` image with command `baton-ingest`
   instead (about an hour; give it 4 vCPU).

## Step 11 — API service

1. **Task definition** (1 vCPU, 3 GB): image `baton-api:<sha>`, port 8787, EFS access point mounted at `/app/data`
   (and a second for `/app/content`, where published articles go). Environment:

   | Variable | Value |
   |---|---|
   | `DATABASE_URL` | `postgresql://baton@<rds-endpoint>:5432/baton` (password added from Vault) |
   | `VAULT_ADDR` · `VAULT_ROLE_ID` | `http://vault.baton.internal:8200` · the `baton-api` role id |
   | `VAULT_SECRET_ID` | from SSM `/baton/vault/api/secret-id` (task definition `secrets`) |
   | `KEYCLOAK_URL` | `https://auth.example.com` |
   | `CORS_ORIGIN` · `BATON_WEB_URL` | `https://app.example.com` |
   | `API_WORKERS` · `CPU_THREADS_PER_WORKER` | `1` · `1` (scale with tasks; Fargate shows the host's cores) |
   | `API_KEEP_ALIVE_SECONDS` | `65` (above the ALB's 60) |
   | `SMTP_HOST` · `SMTP_PORT` · `SMTP_STARTTLS` · `SMTP_USERNAME` · `SMTP_FROM` | SES, step 13 |
   | `LANGFUSE_BASE_URL` | `https://cloud.langfuse.com` (step 13) |
   | `WIDGET_DEMO_IDENTITY` | `false` in production; `true` only if you want the demo shop's "sign in as" menu |
   | `SEED_DEMO_DATA` | `true` for a demo (seeded customers and agents), `false` for real use |

2. **Service**: 1 task to start, `private-app-a/b`, `app-sg`, no public IP, `tg-api`, health-check grace period
   **180 s** (the embedding model loads at start-up), rolling deploys (min 100 %, max 200 %).
   Stay on one task until you need more: publishing an article re-indexes in the process that did it, so with
   several tasks, redeploy after publishing to load the new index everywhere.

## Step 12 — Web service and DNS

1. **Task definition** (0.25 vCPU, 0.5 GB): image `baton-web:<sha>`, port 8080. Environment:
   `VITE_API_URL=https://api.example.com`, `VITE_KEYCLOAK_URL=https://auth.example.com`, `VITE_KEYCLOAK_REALM=baton`,
   `VITE_KEYCLOAK_CLIENT_ID=baton-web`, `WIDGET_FRAME_ANCESTORS=https://shop.example.com` (the sites allowed to
   embed the chat widget).
2. **Service**: 1 task, private-app subnets, `app-sg`, `tg-web`.
3. **Route 53**: alias records `app`, `api` and `auth` → the load balancer.

## Step 13 — Email and observability

1. **Amazon SES**: verify your domain (DKIM records in Route 53), **request production access** (in the sandbox it
   only sends to verified addresses), create **SMTP credentials**. API: `SMTP_HOST=email-smtp.<region>.amazonaws.com`,
   `SMTP_PORT=587`, `SMTP_STARTTLS=true`, `SMTP_USERNAME=<smtp user>`, `SMTP_FROM=Baton Support <support@example.com>`;
   put `SMTP_PASSWORD` in Vault at `secret/baton/api`.
2. **Langfuse Cloud** (free tier): create an organisation and project, put its public and secret keys in Vault at
   `secret/baton/langfuse-project`, set `LANGFUSE_BASE_URL` on the API (EU: `https://cloud.langfuse.com`,
   US: `https://us.cloud.langfuse.com`).
3. **Metrics**: Container Insights is already on. For the Baton dashboard and alert rules, add a Grafana Alloy
   sidecar scraping `localhost:8787/metrics` into Grafana Cloud, then import `observability/grafana/dashboards/baton.json`.
   Locally the API is scraped every 2 s (dashboard refresh 3 s) for near-real-time panels; Grafana Cloud's free tier
   is limited by samples per minute, so scrape every 10–15 s there unless you're on a paid tier.
4. **Redeploy the API** (`aws ecs update-service --force-new-deployment`) so it reads the new secrets.

## Step 14 — Smoke test

- [ ] `https://api.example.com/health` → `secrets: vault`, `storage: postgres`, `llmConfigured: true`.
- [ ] `https://api.example.com/metrics` → 404 from the load balancer; `https://auth.example.com/admin` → 403 except from your IP.
- [ ] `https://app.example.com` → staff sign-in through Keycloak; Alex sees the desk, Jade the admin pages.
- [ ] Embed `<script src="https://app.example.com/widget.js" async></script>` on a test page: ask a question, get a
      cited answer; ask for a person and see it in Alex's queue; reply.
- [ ] With every agent Away: the widget asks for an email and the alert email arrives (SES).
- [ ] A trace appears in Langfuse Cloud.
- [ ] Optionally, point Locust at it with a few users: `npm run loadtest -- --host https://api.example.com`.

## Step 15 — Running it

- **Deploy a new version**: build and push images with a new tag, register new task-definition revisions, update
  the services — ECS rolls them with no downtime. Automate later with GitHub Actions (OIDC to AWS, no stored keys).
- **Backups**: RDS automated backups (7 days), AWS Backup for EFS, Vault raft snapshots to S3 (step 5). Try a restore once.
- **Alarms** (CloudWatch → email): ALB 5xx rate, unhealthy targets, API task restarts, RDS CPU and free storage.
- **Rotate a secret**: change it in Vault (plus `ALTER ROLE` for a database password), then redeploy the service.
- **Save money**: scale services to 0 and stop the RDS instance when idle (it restarts itself after 7 days); the load
  balancer and NAT Gateway still bill hourly — with Terraform, `destroy` and re-`apply` instead.
- **Tear down**, in this order: ECS services → load balancer and target groups → NAT Gateway and its Elastic IP →
  RDS (final snapshot) → EFS → Vault instance and its volume → ECR repositories → VPC. Keep Vault's recovery keys
  and the snapshots if you'll rebuild.

## The budget option: one server

For a demo you switch on only when needed (≈ $70/month while running, a few dollars while stopped):

1. VPC with **one public subnet**, an Internet Gateway, and one **EC2 `t3.large`** (8 GB) with an Elastic IP and
   a security group allowing 80/443 from anywhere (Session Manager instead of SSH).
2. Install Docker, clone the repository, copy your `.env`, and run `npm start -- --docker --no-obs` — Vault,
   Postgres, Keycloak, the API and the web app, exactly as on your laptop. Put the knowledge index in the volume
   (copy it up, see the guide).
3. Put **Caddy** (or Traefik) in front for automatic Let's Encrypt certificates on `app.`, `api.` and `auth.` names
   pointing at the Elastic IP; keep Vault, Postgres and Keycloak's admin port unexposed.
4. Snapshot the EBS volume regularly; **stop the instance** when you're not demoing.

It's one machine — no high availability, and the database lives next to the app — but it's honest, cheap, and the
same images move to the full layout above when you're ready.
