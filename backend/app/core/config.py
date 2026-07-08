from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "local"
    api_host: str = "127.0.0.1"
    api_port: int = 8000

    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4.1-mini"
    llm_fallback_model: str = "qwen-plus"
    embedding_model: str = "BAAI/bge-m3"
    reranker_model: str = "Qwen/Qwen3-Reranker-4B"

    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_database: str = "legal_ai_agent"
    mysql_user: str = "legal_agent"
    mysql_password: str = Field(default="", repr=False)

    redis_url: str = "redis://127.0.0.1:6379/0"
    mongodb_url: str = "mongodb://127.0.0.1:27017/legal_ai_agent"
    milvus_host: str = "127.0.0.1"
    milvus_port: int = 19530
    minio_endpoint: str = "127.0.0.1:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = Field(default="minioadmin", repr=False)
    minio_bucket: str = "legal-ai-agent"

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
