from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.v1.analysis import get_llm_client
from app.integrations.llm.client import LLMClientError
from app.main import app


class StubLLMClient:
    def __init__(
        self,
        payload: dict[str, Any] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.payload = payload or {
            "summary": "Structured summary.",
            "risk_level": "medium",
            "findings": ["Main issue"],
            "suggestions": ["Next step"],
        }
        self.error = error

    async def complete_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        if self.error:
            raise self.error
        return self.payload


@pytest.fixture
def client() -> TestClient:
    app.dependency_overrides.clear()
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_case_analysis_returns_structured_result(client: TestClient) -> None:
    app.dependency_overrides[get_llm_client] = lambda: StubLLMClient()

    response = client.post(
        "/api/v1/case-analyses",
        json={"title": "Sales dispute", "content": "Seller delivered late."},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["module"] == "case_analysis"
    assert data["summary"] == "Structured summary."
    assert data["risk_level"] == "medium"
    assert data["findings"] == ["Main issue"]
    assert data["suggestions"] == ["Next step"]
    assert data["disclaimer"]


def test_case_analysis_rejects_blank_content(client: TestClient) -> None:
    response = client.post("/api/v1/case-analyses", json={"title": "Blank", "content": "   "})

    assert response.status_code == 422


def test_llm_failure_returns_controlled_error(client: TestClient) -> None:
    app.dependency_overrides[get_llm_client] = lambda: StubLLMClient(
        error=LLMClientError("upstream timeout")
    )

    response = client.post(
        "/api/v1/case-analyses",
        json={"title": "Model failure", "content": "Facts to analyze."},
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "llm_upstream_error"
