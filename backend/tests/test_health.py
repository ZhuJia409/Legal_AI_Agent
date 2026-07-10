from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_returns_ok() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "legal-ai-agent-backend"}


def test_dependency_health_exposes_configured_models() -> None:
    response = client.get("/health/dependencies")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "configured"
    assert data["dependencies"]["neo4j"] == "bolt://127.0.0.1:7687"
    assert data["dependencies"]["embedding_model"] == "BAAI/bge-m3"
    assert data["dependencies"]["reranker_model"] == "Qwen/Qwen3-Reranker-4B"
