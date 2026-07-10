from io import BytesIO
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.v1.analysis import get_contract_background_service, get_document_parser
from app.integrations.llm.client import LLMClientError, LLMConfigurationError
from app.main import app
from app.schemas.contract_background import (
    BackgroundCard,
    ContractBackgroundResponse,
    RelatedDocument,
    ReviewPitfall,
)


class StubContractBackgroundService:
    def __init__(
        self,
        response: ContractBackgroundResponse | None = None,
        error: Exception | None = None,
    ) -> None:
        self.response = response or _response()
        self.error = error
        self.title: str | None = None
        self.content = ""

    async def analyze(self, *, title: str | None, content: str) -> ContractBackgroundResponse:
        if self.error:
            raise self.error
        self.title = title
        self.content = content
        return self.response


class StubDocumentParser:
    def __init__(self, parsed_text: str) -> None:
        self.parsed_text = parsed_text
        self.filename: str | None = None

    async def parse(self, file) -> str:  # noqa: ANN001
        self.filename = file.filename
        return self.parsed_text


@pytest.fixture
def client() -> TestClient:
    app.dependency_overrides.clear()
    yield TestClient(app)
    app.dependency_overrides.clear()


def _response() -> ContractBackgroundResponse:
    return ContractBackgroundResponse(
        module="contract_background",
        summary="Phase 0 background summary.",
        contract_category="service_entrustment",
        background_card=BackgroundCard(
            commercial_purpose="Obtain legal consulting services.",
            party_position="Client-side reviewer.",
            counterparty_identity="Consulting service provider.",
            amount_term_scope=None,
            business_focus=None,
            urgency_deadline=None,
        ),
        related_documents=[
            RelatedDocument(
                name="Meeting minutes",
                status="unknown",
                reason="No negotiation materials were provided.",
            )
        ],
        missing_questions=["What is the deadline?"],
        pitfalls=[
            ReviewPitfall(
                name="LOI effectiveness",
                risk="Some expressions may create binding obligations.",
                review_action="Review wording clause by clause.",
            )
        ],
        disclaimer=(
            "This AI-generated result is for reference only; professional legal review is required."
        ),
    )


def _docx_upload(content: str) -> tuple[str, BytesIO, str]:
    buffer = BytesIO(content.encode("utf-8"))
    return (
        "contract.docx",
        buffer,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


def test_contract_review_endpoint_returns_background_result(client: TestClient) -> None:
    service = StubContractBackgroundService()
    app.dependency_overrides[get_contract_background_service] = lambda: service

    response = client.post(
        "/api/v1/contract-reviews",
        json={"title": "Consulting Agreement", "content": "Client appoints Consultant."},
    )

    assert response.status_code == 200
    data: dict[str, Any] = response.json()
    assert data["module"] == "contract_background"
    assert data["contract_category"] == "service_entrustment"
    assert data["background_card"]["commercial_purpose"] == "Obtain legal consulting services."
    assert data["missing_questions"] == ["What is the deadline?"]
    assert service.title == "Consulting Agreement"
    assert service.content == "Client appoints Consultant."


def test_contract_review_endpoint_accepts_multipart_docx(client: TestClient) -> None:
    service = StubContractBackgroundService()
    parser = StubDocumentParser("MinerU parsed markdown body.")
    app.dependency_overrides[get_contract_background_service] = lambda: service
    app.dependency_overrides[get_document_parser] = lambda: parser

    response = client.post(
        "/api/v1/contract-reviews",
        data={"title": "Uploaded Contract"},
        files={"file": _docx_upload("Uploaded DOCX contract body.")},
    )

    assert response.status_code == 200
    assert service.title == "Uploaded Contract"
    assert service.content == "MinerU parsed markdown body."
    assert parser.filename == "contract.docx"


def test_contract_review_endpoint_rejects_blank_content(client: TestClient) -> None:
    response = client.post(
        "/api/v1/contract-reviews",
        json={"title": "Blank", "content": "   "},
    )

    assert response.status_code == 422


def test_contract_review_configuration_error_returns_controlled_error(
    client: TestClient,
) -> None:
    app.dependency_overrides[get_contract_background_service] = (
        lambda: StubContractBackgroundService(error=LLMConfigurationError("missing key"))
    )

    response = client.post(
        "/api/v1/contract-reviews",
        json={"title": "Config", "content": "Contract text."},
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "llm_configuration_error"


@pytest.mark.parametrize(
    "error",
    [LLMClientError("upstream failed"), LLMClientError("invalid structured output")],
)
def test_contract_review_model_or_structure_error_returns_bad_gateway(
    client: TestClient,
    error: Exception,
) -> None:
    app.dependency_overrides[get_contract_background_service] = (
        lambda: StubContractBackgroundService(error=error)
    )

    response = client.post(
        "/api/v1/contract-reviews",
        json={"title": "Failure", "content": "Contract text."},
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "llm_upstream_error"
