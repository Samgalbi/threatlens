"""Central settings, read from environment / .env (pydantic-settings)."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None
    qdrant_collection_name: str = "threatlens_kb"

    embedding_model_name: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = Field(default=384, gt=0)
    sparse_model_name: str = "Qdrant/bm25"
    fastembed_cache_path: str = "./models"

    raw_data_dir: str = "data/raw"
    processed_data_dir: str = "data/processed"


@lru_cache
def get_settings() -> Settings:
    return Settings()
