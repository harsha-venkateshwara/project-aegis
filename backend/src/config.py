from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Groq
    groq_api_key: str = ""
    groq_model: str = "llama3-8b-8192"

    # Embeddings
    embed_model: str = "sentence-transformers/all-MiniLM-L6-v2"

    # Database
    postgres_url: str = "postgresql+asyncpg://postgres:YOUR_PASSWORD@localhost:5433/supportpilot"

    # Redis
    redis_url: str = "redis://localhost:6379"

    # Auth
    secret_key: str = "change-this-in-production"
    admin_api_key: str = "admin-dev-key"

    # Email
    sendgrid_api_key: str = "SG..."
    from_email: str = "support@supportpilot.demo"
    imap_host: str = "imap.gmail.com"
    imap_user: str = "your@gmail.com"
    imap_password: str = "your-app-password"

    # RAG
    rag_confidence_threshold: float = 0.55
    rag_top_k: int = 4
    rag_chunk_size: int = 800
    rag_chunk_overlap: int = 100

    # Paths
    kb_index_path: str = "data/kb_index"
    kb_source_path: str = "data/kb_source_docs"

    # App
    app_env: str = "development"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def kb_index_dir(self) -> Path:
        return Path(self.kb_index_path)

    @property
    def kb_source_dir(self) -> Path:
        return Path(self.kb_source_path)


@lru_cache
def get_settings() -> Settings:
    return Settings()