"""Application configuration loaded from environment variables.

All secrets come from the environment - nothing is committed.
See infra/.env.example for the full list.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- App ---
    app_name: str = "rag-platform"
    environment: str = Field(default="development")  # development | staging | production
    debug: bool = False
    api_v1_prefix: str = "/api/v1"

    # --- Database ---
    database_url: str = Field(
        default="postgresql+psycopg2://rag:rag@localhost:5432/rag",
        description="SQLAlchemy URL. Tests override with sqlite.",
    )

    # --- Redis ---
    redis_url: str = "redis://localhost:6379/0"

    # --- Auth ---
    jwt_secret_key: str = Field(default="CHANGE_ME_IN_PRODUCTION", description="HS256 signing key")
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 30

    # OAuth-ready: plug in real providers later (Google, Okta, Entra ID...)
    oauth_enabled: bool = False
    oauth_google_client_id: str = ""

    # --- Credits ---
    credits_per_chat_query: int = 1          # cost of one RAG chat call
    credits_per_1k_embed_tokens: float = 0.1  # reserved for future per-token billing
    signup_bonus_credits: int = 50           # granted on registration

    # --- Stripe (stubbed) ---
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_id_100_credits: str = ""

    # --- Embeddings / LLM (OpenAI-compatible) ---
    embedding_provider: str = "openai"       # openai | fake (tests/local)
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536
    chat_model: str = "gpt-4o-mini"

    # --- Vector store ---
    vector_backend: str = "pgvector"  # pgvector | memory (local dev fallback)

    # --- RAG tuning ---
    rag_top_k: int = 6
    rag_chunk_size: int = 800
    rag_chunk_overlap: int = 120
    rag_min_score: float = 0.0  # cosine similarity floor; raise to reduce noise
    hybrid_retrieval: bool = True  # dense + BM25 fused with RRF
    hybrid_rrf_k: int = 60  # RRF constant
    reranker: str = "late-interaction"  # late-interaction | none | cross-encoder (seam)

    # --- Free local LLM (llama-cpp GGUF, no API key) ---
    llm_provider: str = "openai"  # openai | local
    local_llm_model_path: str = "models/Qwen3-4B-Q4_K_M.gguf"  # 4B default; 0.5B fallback: models/qwen2.5-0.5b-instruct-q4_k_m.gguf
    local_llm_n_ctx: int = 8192
    local_llm_max_tokens: int = 512

    # --- Rate limiting ---
    rate_limit_chat_per_minute: int = 30
    rate_limit_upload_per_minute: int = 10

    # --- Uploads ---
    upload_dir: str = "/tmp/rag-uploads"
    max_upload_mb: int = 50

    # --- CORS ---
    cors_origins: str = "http://localhost:5173,http://localhost:3000"  # comma-separated

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
