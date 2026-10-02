"""Backend settings, read from the project's single `.env` (shared with the frontend).

Invalid values fail at startup rather than half-working later. Variable names match `.env.example`.
"""

from functools import cached_property
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]  # project root (backend/app/config.py → ../../)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", env_file_encoding="utf-8", extra="ignore")

    # ── Paths ──────────────────────────────────────────────────────────────
    data_dir: str = "data"
    content_dir: str = "content"

    # ── Embeddings & chunking ──────────────────────────────────────────────
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_query_prefix: str = "Represent this sentence for searching relevant passages:"
    embedding_batch_size: int = Field(32, ge=1, le=256)
    chunk_min_tokens: int = Field(50, ge=0)
    chunk_target_tokens: int = Field(300, ge=50)
    chunk_max_tokens: int = Field(450, ge=50, le=500)  # the model reads 512 including the title line

    # ── Ingestion ──────────────────────────────────────────────────────────
    ingest_sources: str = "local,wixqa,abcd"  # priority order: earlier sources keep shared text
    source_local_refresh_minutes: float = Field(0, ge=0)
    source_wixqa_refresh_minutes: float = Field(10080, ge=0)
    source_abcd_refresh_minutes: float = Field(10080, ge=0)

    # ── Retrieval ──────────────────────────────────────────────────────────
    retrieval_top_k: int = Field(5, ge=1)
    retrieval_candidates: int = Field(50, ge=1)
    retrieval_rrf_k: float = Field(60, ge=1)
    reranker_model: str = ""  # cross-encoder; empty = no reranking
    rerank_candidates: int = Field(20, ge=1, le=100)

    # ── Evaluation ─────────────────────────────────────────────────────────
    eval_answer_precision: float = Field(0.8, ge=0, le=1)
    eval_copilot_precision: float = Field(0.6, ge=0, le=1)
    eval_no_match_max_miss_rate: float = Field(0.05, ge=0, le=1)
    eval_rag_limit: int = Field(50, ge=1)
    eval_rag_concurrency: int = Field(2, ge=1, le=16)
    eval_rag_dataset: str = "baton-eval"

    # ── API ────────────────────────────────────────────────────────────────
    server_port: int = Field(8787, ge=1, le=65535)
    cors_origin: str = "*"

    # ── Support sessions ───────────────────────────────────────────────────
    session_idle_minutes: float = Field(30, gt=0)  # bot or agent chat with no new message → closed (inactive)
    session_abandon_minutes: float = Field(10, gt=0)  # customer gone while waiting for an agent → closed (abandoned)
    session_sweep_seconds: float = Field(60, ge=5)  # how often idle sessions are checked

    # ── Data rules and the review pipeline ─────────────────────────────────
    retention_days: int = Field(365, ge=0)  # closed transcripts are wiped after this; 0 keeps them forever
    review_interval_minutes: float = Field(60, ge=0)  # how often closed sessions are reviewed; 0 = only on demand
    privacy_notice: str = ""  # shown in the customer chat; empty = a notice built from RETENTION_DAYS

    # ── Customer chat widget (customers never sign in to Baton) ────────────
    widget_signing_secret: str = ""  # signs widget session tokens; the widget is off until this is set
    widget_identity_secret: str = ""  # shared with your website's backend, which signs identity tokens for its signed-in customers
    widget_demo_identity: bool = False  # local demo only: the API signs identity tokens for seeded customers
    widget_visitor_days: int = Field(30, ge=1)  # an anonymous visitor's session (and chat history) lasts this long
    widget_identified_hours: int = Field(12, ge=1)  # a signed-in customer's session; your site re-identifies them after
    widget_messages_per_minute: int = Field(12, ge=1)  # per customer: protects the LLM budget from scripts
    widget_sessions_per_hour: int = Field(30, ge=1)  # new widget sessions per client IP

    # ── Identity (Keycloak) and the app database ───────────────────────────
    keycloak_url: str = "http://localhost:8080"  # public URL: tokens' issuer, links for people
    keycloak_internal_url: str = ""  # how the API reaches Keycloak for signing keys; default keycloak_url
    keycloak_realm: str = "baton"
    keycloak_audience: str = "baton-api"
    database_url: str = ""  # empty → in-memory store (tests, quick experiments)
    seed_demo_data: bool = True  # demo customer profiles and agents, matched to Keycloak users by email
    grafana_url: str = "http://localhost:3001"
    # Service account (client credentials) the API uses to delete a person's Keycloak account on erasure.
    keycloak_admin_client_id: str = "baton-api-admin"
    keycloak_admin_client_secret: str = ""
    # Shared with the desk UI so metrics and the screen agree on what "overdue" means.
    vite_handoff_sla_warn_seconds: float = Field(120, ge=1)
    vite_handoff_sla_breach_seconds: float = Field(300, ge=1)

    # ── LLM (Groq, OpenAI-compatible) ──────────────────────────────────────
    groq_api_key: str = ""
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_model: str = "llama-3.1-8b-instant"
    llm_temperature: float = Field(0.2, ge=0, le=2)
    llm_max_tokens: int = Field(512, ge=16)
    llm_timeout_ms: int = Field(15000, ge=1000)
    llm_max_retries: int = Field(2, ge=0, le=5)
    llm_reasoning_effort: str = ""  # reasoning models only (gpt-oss): low | medium | high
    llm_prices_per_million: dict[str, list[float]] = Field(default_factory=dict)  # model → [input, output] USD

    judge_model: str = "openai/gpt-oss-120b"
    judge_reasoning_effort: str = "medium"
    judge_max_tokens: int = Field(4096, ge=256)
    judge_concurrency: int = Field(1, ge=1, le=8)
    judge_max_retries: int = Field(6, ge=0, le=20)

    # ── Answer policy (cosine similarities, calibrated with baton-eval) ──
    rag_no_match_threshold: float = Field(0.70, ge=0, le=1)
    rag_context_chunks: int = Field(5, ge=1, le=20)
    rag_max_failed_attempts: int = Field(2, ge=1)
    rag_sentiment_threshold: float = Field(-0.5, ge=-1, le=1)
    rag_procedure_threshold: float = Field(0.72, ge=0, le=1)

    # ── Observability ──────────────────────────────────────────────────────
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_base_url: str = "http://localhost:3000"
    langfuse_tracing_environment: str = "development"
    online_eval_sample_rate: float = Field(0.2, ge=0, le=1)

    @model_validator(mode="after")
    def _check(self):
        if self.chunk_target_tokens > self.chunk_max_tokens:
            raise ValueError("CHUNK_TARGET_TOKENS must not exceed CHUNK_MAX_TOKENS")
        return self

    # ── Derived ────────────────────────────────────────────────────────────
    @cached_property
    def sources(self) -> list[str]:
        return [s.strip() for s in self.ingest_sources.split(",") if s.strip()]

    @property
    def refresh_minutes(self) -> dict[str, float]:
        return {
            "local": self.source_local_refresh_minutes,
            "wixqa": self.source_wixqa_refresh_minutes,
            "abcd": self.source_abcd_refresh_minutes,
        }

    @property
    def data_path(self) -> Path:
        return (ROOT / self.data_dir).resolve()

    @property
    def content_path(self) -> Path:
        return (ROOT / self.content_dir).resolve()

    @property
    def raw_path(self) -> Path:
        return self.data_path / "raw"

    @property
    def index_path(self) -> Path:
        return self.data_path / "index"

    @property
    def models_path(self) -> Path:
        return self.data_path / "models"

    @property
    def eval_path(self) -> Path:
        return self.data_path / "eval"

    @property
    def keycloak_issuer(self) -> str:
        return f"{self.keycloak_url.rstrip('/')}/realms/{self.keycloak_realm}"

    @property
    def keycloak_jwks_url(self) -> str:
        base = (self.keycloak_internal_url or self.keycloak_url).rstrip("/")
        return f"{base}/realms/{self.keycloak_realm}/protocol/openid-connect/certs"

    @property
    def langfuse_enabled(self) -> bool:
        return bool(self.langfuse_public_key and self.langfuse_secret_key)

    @property
    def sla_breach_ms(self) -> float:
        return self.vite_handoff_sla_breach_seconds * 1000


settings = Settings()
