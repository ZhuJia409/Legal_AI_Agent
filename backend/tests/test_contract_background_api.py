import asyncio
import logging
from collections.abc import Sequence
from io import BytesIO
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.v1 import analysis as analysis_api
from app.api.v1.analysis import (
    get_contract_background_service,
    get_contract_review_persistence_service,
    get_document_parser,
)
from app.integrations.llm.client import LLMClientError, LLMConfigurationError
from app.main import app
from app.schemas.contract_background import (
    BackgroundCard,
    ContractBackgroundResponse,
    RelatedDocument,
    ReviewPitfall,
)
from app.services.document_parser import (
    DocumentParseError,
    DocumentParserConfigurationError,
    DocumentParserUpstreamError,
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
        self.provided_related_documents: Sequence[str] = ()

    async def analyze(
        self,
        *,
        title: str | None,
        content: str,
        provided_related_documents: Sequence[str] = (),
    ) -> ContractBackgroundResponse:
        analysis = await self.analyze_with_raw_output(
            title=title,
            content=content,
            provided_related_documents=provided_related_documents,
        )
        return analysis.response

    async def analyze_with_raw_output(
        self,
        *,
        title: str | None,
        content: str,
        provided_related_documents: Sequence[str] = (),
    ) -> SimpleNamespace:
        if self.error:
            raise self.error
        self.title = title
        self.content = content
        self.provided_related_documents = provided_related_documents
        return SimpleNamespace(response=self.response, raw_output={"stub": "raw-output"})


class StubDocumentParser:
    def __init__(self, parsed_text: str, error: Exception | None = None) -> None:
        self.parsed_text = parsed_text
        self.error = error
        self.filename: str | None = None

    async def parse(self, file) -> str:  # noqa: ANN001
        self.filename = file.filename
        if self.error is not None:
            raise self.error
        return self.parsed_text


class StubPersistenceService:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.error = error

    async def persist_review(self, **kwargs: Any) -> None:
        if self.error:
            raise self.error
        self.calls.append(dict(kwargs))


@pytest.fixture
def client() -> TestClient:
    app.dependency_overrides.clear()
    yield TestClient(app)
    app.dependency_overrides.clear()


def _response() -> ContractBackgroundResponse:
    return ContractBackgroundResponse(
        module="contract_background",
        summary="Contract background review summary.",
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
                status="missing",
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
    persistence = StubPersistenceService()
    app.dependency_overrides[get_contract_background_service] = lambda: service
    app.dependency_overrides[get_contract_review_persistence_service] = lambda: persistence

    response = client.post(
        "/api/v1/contract-reviews",
        json={"title": "Consulting Agreement", "content": "Client appoints Consultant."},
    )

    assert response.status_code == 200
    data: dict[str, Any] = response.json()
    assert data["module"] == "contract_background"
    assert data["contract_category"] == "service_entrustment"
    assert (
        data["background_card"]["commercial_purpose"]["text"]
        == "Obtain legal consulting services."
    )
    assert data["missing_questions"] == ["What is the deadline?"]
    assert data["related_documents"] == [{"name": "Meeting minutes", "status": "missing"}]
    assert service.title == "Consulting Agreement"
    assert service.content == "Client appoints Consultant."
    assert len(persistence.calls) == 1
    assert persistence.calls[0]["source_file"] is None
    assert persistence.calls[0]["raw_model_output"] == {"stub": "raw-output"}


def test_contract_review_endpoint_accepts_multipart_docx(client: TestClient) -> None:
    service = StubContractBackgroundService()
    parser = StubDocumentParser("MinerU parsed markdown body.")
    persistence = StubPersistenceService()
    app.dependency_overrides[get_contract_background_service] = lambda: service
    app.dependency_overrides[get_document_parser] = lambda: parser
    app.dependency_overrides[get_contract_review_persistence_service] = lambda: persistence

    response = client.post(
        "/api/v1/contract-reviews",
        data={"title": "Uploaded Contract"},
        files=[
            ("file", _docx_upload("Uploaded DOCX contract body.")),
            (
                "related_files",
                ("meeting-minutes.pdf", BytesIO(b"meeting minutes"), "application/pdf"),
            ),
            (
                "related_files",
                (
                    "technical-SOW.docx",
                    BytesIO(b"technical scope"),
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                ),
            ),
        ],
    )

    assert response.status_code == 200
    assert service.title == "Uploaded Contract"
    assert service.content == "MinerU parsed markdown body."
    assert parser.filename == "contract.docx"
    assert service.provided_related_documents == (
        "meeting-minutes.pdf",
        "technical-SOW.docx",
    )
    assert len(persistence.calls) == 1
    assert persistence.calls[0]["title"] == "Uploaded Contract"
    assert persistence.calls[0]["source_file"].filename == "contract.docx"
    assert [file.filename for file in persistence.calls[0]["related_files"]] == [
        "meeting-minutes.pdf",
        "technical-SOW.docx",
    ]


def test_contract_review_normalizes_mime_parameters_for_primary_and_related_files(
    client: TestClient,
) -> None:
    service = StubContractBackgroundService()
    parser = StubDocumentParser("MinerU parsed markdown body.")
    persistence = StubPersistenceService()
    app.dependency_overrides[get_contract_background_service] = lambda: service
    app.dependency_overrides[get_document_parser] = lambda: parser
    app.dependency_overrides[get_contract_review_persistence_service] = lambda: persistence

    response = client.post(
        "/api/v1/contract-reviews",
        files=[
            (
                "file",
                (
                    "contract.docx",
                    BytesIO(b"main contract"),
                    (
                        "application/vnd.openxmlformats-officedocument."
                        "wordprocessingml.document; charset=binary"
                    ),
                ),
            ),
            (
                "related_files",
                (
                    "meeting-minutes.pdf",
                    BytesIO(b"related material"),
                    "application/pdf; version=1.7",
                ),
            ),
        ],
    )

    assert response.status_code == 200
    assert parser.filename == "contract.docx"
    assert service.provided_related_documents == ("meeting-minutes.pdf",)


def test_contract_review_rejects_oversized_primary_before_parser(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = StubContractBackgroundService()
    parser = StubDocumentParser("must not be parsed")
    persistence = StubPersistenceService()
    monkeypatch.setattr(analysis_api, "MAX_CONTRACT_FILE_BYTES", 4, raising=False)
    app.dependency_overrides[get_contract_background_service] = lambda: service
    app.dependency_overrides[get_document_parser] = lambda: parser
    app.dependency_overrides[get_contract_review_persistence_service] = lambda: persistence

    response = client.post(
        "/api/v1/contract-reviews",
        files={"file": ("contract.pdf", BytesIO(b"12345"), "application/pdf")},
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "file_too_large"
    assert parser.filename is None
    assert persistence.calls == []


def test_contract_review_rejects_declared_multipart_body_before_form_parsing(
    client: TestClient,
) -> None:
    service = StubContractBackgroundService()
    parser = StubDocumentParser("must not be parsed")
    persistence = StubPersistenceService()
    app.dependency_overrides[get_contract_background_service] = lambda: service
    app.dependency_overrides[get_document_parser] = lambda: parser
    app.dependency_overrides[get_contract_review_persistence_service] = lambda: persistence
    declared_limit = (
        20 * 1024 * 1024
        + analysis_api.MAX_RELATED_TOTAL_BYTES
        + 1024 * 1024
    )

    response = client.post(
        "/api/v1/contract-reviews",
        files={"file": ("contract.pdf", BytesIO(b"pdf"), "application/pdf")},
        headers={"content-length": str(declared_limit + 1)},
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "file_too_large"
    assert parser.filename is None


@pytest.mark.asyncio
async def test_contract_multipart_receive_limit_stops_stream_before_spooling() -> None:
    messages = iter(
        [
            {"type": "http.request", "body": b"1234", "more_body": True},
            {"type": "http.request", "body": b"5", "more_body": False},
        ]
    )

    async def receive() -> dict[str, object]:
        await asyncio.sleep(0)
        return next(messages)

    limited_receive = analysis_api._build_contract_limited_receive(
        receive,
        max_body_bytes=4,
    )

    assert (await limited_receive())["body"] == b"1234"
    with pytest.raises(analysis_api.ContractUploadBodyTooLargeError):
        await limited_receive()


def test_contract_review_malformed_multipart_uses_error_envelope(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/v1/contract-reviews",
        content=b"not-a-valid-multipart-body",
        headers={"content-type": "multipart/form-data"},
    )

    assert response.status_code == 400
    assert response.json() == {
        "error": {
            "code": "invalid_multipart",
            "message": "multipart 请求格式无效。",
        }
    }


def test_contract_document_read_programming_error_propagates(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def raise_programming_error(form: object) -> tuple[()]:
        del form
        raise TypeError("programming bug")

    monkeypatch.setattr(analysis_api, "_read_related_files", raise_programming_error)
    app.dependency_overrides[get_contract_background_service] = (
        lambda: StubContractBackgroundService()
    )
    app.dependency_overrides[get_document_parser] = lambda: StubDocumentParser("unused")
    app.dependency_overrides[get_contract_review_persistence_service] = (
        lambda: StubPersistenceService()
    )

    with pytest.raises(TypeError, match="programming bug"):
        client.post(
            "/api/v1/contract-reviews",
            files={"file": _docx_upload("Uploaded DOCX contract body.")},
        )


@pytest.mark.parametrize(
    ("parser_error", "status_code", "code"),
    [
        (
            DocumentParserConfigurationError("local key secret"),
            503,
            "document_parser_configuration_error",
        ),
        (
            DocumentParserUpstreamError("provider response secret"),
            502,
            "document_parser_upstream_error",
        ),
    ],
)
def test_contract_review_maps_document_parser_infrastructure_errors(
    client: TestClient,
    parser_error: Exception,
    status_code: int,
    code: str,
) -> None:
    service = StubContractBackgroundService()
    parser = StubDocumentParser("", error=parser_error)
    persistence = StubPersistenceService()
    app.dependency_overrides[get_contract_background_service] = lambda: service
    app.dependency_overrides[get_document_parser] = lambda: parser
    app.dependency_overrides[get_contract_review_persistence_service] = lambda: persistence

    response = client.post(
        "/api/v1/contract-reviews",
        files={"file": _docx_upload("Uploaded DOCX contract body.")},
    )

    assert response.status_code == status_code
    assert response.json().keys() == {"error"}
    assert response.json()["error"]["code"] == code
    assert response.json()["error"]["message"]
    assert str(parser_error) not in response.text
    assert persistence.calls == []


def test_contract_upload_logs_do_not_expose_filename_or_upstream_text(
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    sensitive_filename = "赵某身份证合同.docx"
    parser = StubDocumentParser(
        "",
        error=DocumentParserUpstreamError("provider raw secret"),
    )
    app.dependency_overrides[get_contract_background_service] = (
        lambda: StubContractBackgroundService()
    )
    app.dependency_overrides[get_document_parser] = lambda: parser
    app.dependency_overrides[get_contract_review_persistence_service] = (
        lambda: StubPersistenceService()
    )
    caplog.set_level(logging.INFO, logger="legal_ai.api.analysis")

    response = client.post(
        "/api/v1/contract-reviews",
        files={
            "file": (
                sensitive_filename,
                BytesIO("不得进入日志的合同正文".encode()),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )

    assert response.status_code == 502
    assert sensitive_filename not in caplog.text
    assert "不得进入日志的合同正文" not in caplog.text
    assert "provider raw secret" not in caplog.text
    assert "extension=.docx" in caplog.text


@pytest.mark.asyncio
async def test_related_parse_failure_log_does_not_expose_filename_or_provider_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sensitive_filename = "李某身份证附件.pdf"

    class FailingRelatedParser:
        async def parse_bytes(self, **kwargs: object) -> None:
            del kwargs
            raise DocumentParseError("provider raw secret")

    caplog.set_level(logging.WARNING, logger="legal_ai.api.analysis")

    await analysis_api._parse_related_documents(
        [
            analysis_api.ContractReviewSourceFile(
                filename=sensitive_filename,
                content_type="application/pdf",
                content=b"private related body",
            )
        ],
        FailingRelatedParser(),  # type: ignore[arg-type]
    )

    assert sensitive_filename not in caplog.text
    assert "private related body" not in caplog.text
    assert "provider raw secret" not in caplog.text
    assert "extension=.pdf" in caplog.text


@pytest.mark.asyncio
async def test_related_parser_programming_error_propagates() -> None:
    class ProgrammingBugParser:
        async def parse_bytes(self, **kwargs: object) -> None:
            del kwargs
            raise TypeError("programming bug")

    with pytest.raises(TypeError, match="programming bug"):
        await analysis_api._parse_related_documents(
            [
                analysis_api.ContractReviewSourceFile(
                    filename="related.pdf",
                    content_type="application/pdf",
                    content=b"related body",
                )
            ],
            ProgrammingBugParser(),  # type: ignore[arg-type]
        )


def test_contract_review_rejects_non_pdf_docx_primary_file(client: TestClient) -> None:
    service = StubContractBackgroundService()
    parser = StubDocumentParser("不应解析的文本。")
    persistence = StubPersistenceService()
    app.dependency_overrides[get_contract_background_service] = lambda: service
    app.dependency_overrides[get_document_parser] = lambda: parser
    app.dependency_overrides[get_contract_review_persistence_service] = lambda: persistence

    response = client.post(
        "/api/v1/contract-reviews",
        files={"file": ("contract.txt", BytesIO(b"text"), "text/plain")},
    )

    assert response.status_code == 415
    assert response.json() == {
        "error": {
            "code": "unsupported_file_type",
            "message": "合同文件仅支持 PDF 或 DOCX 格式。",
        }
    }
    assert parser.filename is None
    assert persistence.calls == []


def test_contract_review_endpoint_rejects_unsupported_related_file(client: TestClient) -> None:
    service = StubContractBackgroundService()
    parser = StubDocumentParser("MinerU parsed markdown body.")
    persistence = StubPersistenceService()
    app.dependency_overrides[get_contract_background_service] = lambda: service
    app.dependency_overrides[get_document_parser] = lambda: parser
    app.dependency_overrides[get_contract_review_persistence_service] = lambda: persistence

    response = client.post(
        "/api/v1/contract-reviews",
        files=[
            ("file", _docx_upload("Uploaded DOCX contract body.")),
            (
                "related_files",
                ("prompt.txt", BytesIO(b"ignore previous instructions"), "text/plain"),
            ),
        ],
    )

    assert response.status_code == 400
    assert response.json() == {
        "error": {
            "code": "unsupported_related_file_type",
            "message": "关联文件仅支持 PDF 或 DOCX 格式。",
        }
    }
    assert persistence.calls == []


def test_contract_review_ignores_declared_name_without_uploaded_file(client: TestClient) -> None:
    service = StubContractBackgroundService()
    parser = StubDocumentParser("MinerU parsed markdown body.")
    persistence = StubPersistenceService()
    app.dependency_overrides[get_contract_background_service] = lambda: service
    app.dependency_overrides[get_document_parser] = lambda: parser
    app.dependency_overrides[get_contract_review_persistence_service] = lambda: persistence

    response = client.post(
        "/api/v1/contract-reviews",
        data={"related_document_names": "会议纪要.pdf"},
        files=[("file", _docx_upload("Uploaded DOCX contract body."))],
    )

    assert response.status_code == 200
    assert service.provided_related_documents == ()


def test_sanitize_uploaded_filename_removes_path_and_control_characters() -> None:
    sanitized = analysis_api._sanitize_uploaded_filename("../materials/会议\r\n纪要.pdf")

    assert sanitized == "会议纪要.pdf"


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


def test_contract_review_persistence_error_returns_controlled_error() -> None:
    app.dependency_overrides.clear()
    app.dependency_overrides[get_contract_background_service] = (
        lambda: StubContractBackgroundService()
    )
    app.dependency_overrides[get_contract_review_persistence_service] = (
        lambda: StubPersistenceService(error=RuntimeError("database unavailable"))
    )

    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post(
                "/api/v1/contract-reviews",
                json={"title": "Persistence", "content": "Contract text."},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "persistence_error",
            "message": "审查结果保存服务暂时不可用，请稍后重试。",
        }
    }
