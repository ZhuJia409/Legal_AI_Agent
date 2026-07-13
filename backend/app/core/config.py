from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "local"
    api_host: str = "127.0.0.1"
    api_port: int = 8000

    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key: str = ""
    llm_model: str = "qwen3.7-plus"
    llm_fallback_model: str = "deepseek-v4-flash"
    embedding_model: str = "BAAI/bge-m3"
    reranker_model: str = "Qwen/Qwen3-Reranker-4B"
    langsmith_tracing: bool = False
    langsmith_api_key: str = Field(default="", repr=False)
    langsmith_project: str = "legal-ai-agent-local"
    langsmith_endpoint: str = "https://api.smith.langchain.com"

    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_database: str = "legal_ai_agent"
    mysql_user: str = "legal_agent"
    mysql_password: str = Field(default="", repr=False)

    redis_url: str = "redis://127.0.0.1:6379/0"
    mongodb_url: str = "mongodb://127.0.0.1:27017/legal_ai_agent"
    neo4j_uri: str = "bolt://127.0.0.1:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = Field(default="change-me-neo4j", repr=False)
    neo4j_database: str = "neo4j"
    milvus_host: str = "127.0.0.1"
    milvus_port: int = 19530
    minio_endpoint: str = "127.0.0.1:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = Field(default="minioadmin", repr=False)
    minio_bucket: str = "legal-ai-agent"

    mineru_api_key: str = Field(default="", repr=False)
    mineru_base_url: str = "https://mineru.net"
    mineru_model_version: str = "vlm"
    mineru_poll_interval_seconds: float = 2
    mineru_poll_timeout_seconds: float = 180

    tectonic_path: str = Field(default=".tools/tectonic/tectonic.exe", min_length=1)
    tectonic_timeout_seconds: float = Field(default=90, gt=0)

    @field_validator("tectonic_path", mode="before")
    @classmethod
    def _normalize_tectonic_path(cls, value: object) -> object:
        # 空白路径无法定位编译器，配置加载阶段即拒绝，避免延迟到报告生成时失败。
        return value.strip() if isinstance(value, str) else value

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
