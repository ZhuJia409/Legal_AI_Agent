from fastapi import APIRouter

from app.core.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "legal-ai-agent-backend"}


@router.get("/health/dependencies")
def dependency_health() -> dict[str, object]:
    settings = get_settings()
    return {
        "status": "configured",
        "dependencies": {
            "mysql": settings.mysql_host,
            "redis": settings.redis_url,
            "mongodb": settings.mongodb_url,
            "milvus": f"{settings.milvus_host}:{settings.milvus_port}",
            "minio": settings.minio_endpoint,
            "llm_model": settings.llm_model,
            "embedding_model": settings.embedding_model,
            "reranker_model": settings.reranker_model,
        },
    }
