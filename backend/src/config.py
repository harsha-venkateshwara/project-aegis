from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"

    embed_model: str = "sentence-transformers/all-MiniLM-L6-v2"

    postgres_url: str = "postgresql+asyncpg://sp_user:localdev@localhost:5432/supportpilot"

    redis_url: str = "redis://localhost:6379"

    secret_key: str = "change-this-in-production"
    admin_api_key: str = "admin-dev-key"

    sendgrid_api_key: str = ""
    from_email: str = "support@aegis.demo"
    imap_host: str = "imap.gmail.com"
    imap_user: str = ""
    imap_password: str = ""

    rag_confidence_threshold: float = 0.35
    rag_top_k: int = 5
    rag_chunk_size: int = 700
    rag_chunk_overlap: int = 80

    kb_index_path: str = "data/kb_index"
    kb_source_path: str = "data/kb_source_docs"

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