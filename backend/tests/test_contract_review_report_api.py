import asyncio
import hashlib
from datetime import datetime
from io import BytesIO
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

import app.api.v1.analysis as analysis_api
from app.api.v1.analysis import (
    get_contract_review_document_service,
    get_contract_review_graph_service,
    get_contract_review_pdf_renderer,
    get_contract_review_persistence_service,
    get_document_parser,
)
from app.main import app
from app.repositories.contract_review import ReviewDocumentRecord
from app.schemas.contract_background import BackgroundCard, ContractBackgroundResponse
from app.schemas.contract_review import (
    ContractReviewReport,
    ContractReviewReportResponse,
    ReviewModuleResult,
)
from app.services.contract_review_documents import (
    ReportDocumentDownload,
    ReportDocumentNotFoundError,
    ReportDocumentReadError,
)
from app.services.contract_review_graph import (
    ContractReviewGraphAnalysis,
    ParsedRelatedDocument,
)
from app.services.contract_review_pdf import (
    GeneratedReportPdf,
    PdfRendererUnavailableError,
    ReportPdfGenerationError,
)
from app.services.document_parser import DocumentParseError
from app.services.mineru_parser import MineruParseResult


class StubContractReviewGraphService:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def analyze(self, **kwargs: Any) -> ContractReviewGraphAnalysis:
        if self.error:
            raise self.error
        self.calls.append(dict(kwargs))
        return ContractReviewGraphAnalysis(
            response=_report_response(
                task_id=str(kwargs["task_id"]),
                perspective=str(kwargs["review_perspective"]),
            ),
            raw_outputs=[{"module": "report", "payload": {"ok": True}}],
        )


class StubReportDocumentParser:
    async def parse(self, file) -> str:  # noqa: ANN001
        return "采购合同\n\n甲方向乙方采购办公设备。"

    async def parse_bytes(self, *, filename: str, file_bytes: bytes) -> MineruParseResult:
        if filename.startswith("bad-"):
            raise DocumentParseError("关联文件解析失败")
        return MineruParseResult(
            batch_id=f"batch-{filename}",
            zip_bytes=b"zip",
            markdown=file_bytes.decode("utf-8"),
        )


class ConcurrencyTrackingParser(StubReportDocumentParser):
    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0

    async def parse_bytes(self, *, filename: str, file_bytes: bytes) -> MineruParseResult:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(0.01)
            return await super().parse_bytes(filename=filename, file_bytes=file_bytes)
        finally:
            self.active -= 1


class StubReportPersistenceService:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def persist_review(self, **kwargs: Any) -> None:
        if self.error:
            raise self.error
        self.calls.append(dict(kwargs))


class StubPdfRenderer:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def render(self, response, **kwargs: Any) -> GeneratedReportPdf:  # noqa: ANN001
        if self.error:
            raise self.error
        self.calls.append({"response": response, **kwargs})
        content = b"%PDF-report"
        return GeneratedReportPdf(
            filename="采购合同_合同审查报告_20260713_123e4567.pdf",
            content_type="application/pdf",
            content=content,
            sha256=hashlib.sha256(content).hexdigest(),
            generated_at=datetime(2026, 7, 13, 10, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
        )


class StubDocumentService:
    def __init__(
        self,
        result: ReportDocumentDownload | Exception | None = None,
    ) -> None:
        self.result = result or _downloadable_document()

    async def get_report_pdf(self, task_id: str) -> ReportDocumentDownload:
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.fixture
def client() -> TestClient:
    app.dependency_overrides.clear()
    app.dependency_overrides[get_contract_review_pdf_renderer] = lambda: StubPdfRenderer()
    app.dependency_overrides[get_contract_review_document_service] = (
        lambda: StubDocumentService()
    )
    yield TestClient(app)
    app.dependency_overrides.clear()


def _background() -> ContractBackgroundResponse:
    return ContractBackgroundResponse(
        module="contract_background",
        disclaimer="需复核",
        summary="采购背景",
        background_card=BackgroundCard(commercial_purpose="采购办公设备"),
        contract_category="commercial_transaction",
        related_documents=[],
        missing_questions=[],
        pitfalls=[],
    )


def _report_response(task_id: str, perspective: str) -> ContractReviewReportResponse:
    modules = [
        ReviewModuleResult(module=module, status="succeeded", summary="完成")
        for module in (
            "party_qualification",
            "form_structure",
            "general_substantive",
            "related_document_comparison",
            "contract_type_special",
        )
    ]
    return ContractReviewReportResponse(
        module="contract_review_report",
        task_id=task_id,
        status="complete",
        review_perspective=perspective,
        background=_background(),
        contract_types=[],
        modules=modules,
        report=ContractReviewReport(
            executive_summary="可在补充核验后签署。",
            overall_risk_level="medium",
            signing_recommendation="conditional",
        ),
        disclaimer="需由法律专业人士复核。",
    )


def _docx(filename: str, content: bytes) -> tuple[str, BytesIO, str]:
    return (
        filename,
        BytesIO(content),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


def _downloadable_document() -> ReportDocumentDownload:
    content = b"%PDF-report"
    return ReportDocumentDownload(
        metadata=ReviewDocumentRecord(
            task_id="123e4567-e89b-12d3-a456-426614174000",
            document_type="contract_review_report_pdf",
            filename="采购合同_合同审查报告.pdf",
            content_type="application/pdf",
            size_bytes=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            object_key="contract-reviews/task/reports/report.pdf",
            created_at=datetime(
                2026, 7, 13, 10, 30, tzinfo=ZoneInfo("Asia/Shanghai")
            ),
        ),
        content=content,
    )


def test_contract_review_report_endpoint_accepts_json_and_perspective(client: TestClient) -> None:
    graph = StubContractReviewGraphService()
    persistence = StubReportPersistenceService()
    renderer = StubPdfRenderer()
    app.dependency_overrides[get_contract_review_graph_service] = lambda: graph
    app.dependency_overrides[get_contract_review_persistence_service] = lambda: persistence
    app.dependency_overrides[get_contract_review_pdf_renderer] = lambda: renderer

    response = client.post(
        "/api/v1/contract-review-reports",
        json={
            "title": "采购合同",
            "content": "甲方向乙方采购设备。",
            "review_perspective": "party_a",
        },
    )

    assert response.status_code == 200
    assert response.json()["module"] == "contract_review_report"
    assert response.json()["review_perspective"] == "party_a"
    assert graph.calls[0]["review_perspective"] == "party_a"
    assert response.json()["report_document"]["filename"].endswith(".pdf")
    assert renderer.calls[0]["source_filename"] is None
    assert persistence.calls[0]["report_pdf"].content == b"%PDF-report"
    assert persistence.calls[0]["raw_model_outputs"] == [
        {"module": "report", "payload": {"ok": True}}
    ]


def test_contract_review_report_endpoint_parses_related_files_independently(
    client: TestClient,
) -> None:
    graph = StubContractReviewGraphService()
    parser = StubReportDocumentParser()
    persistence = StubReportPersistenceService()
    app.dependency_overrides[get_contract_review_graph_service] = lambda: graph
    app.dependency_overrides[get_document_parser] = lambda: parser
    app.dependency_overrides[get_contract_review_persistence_service] = lambda: persistence

    response = client.post(
        "/api/v1/contract-review-reports",
        data={"review_perspective": "neutral"},
        files=[
            ("file", _docx("contract.docx", b"main")),
            ("related_files", _docx("spec.docx", "三年质保".encode())),
            ("related_files", _docx("bad-minutes.docx", b"bad")),
        ],
    )

    assert response.status_code == 200
    related: list[ParsedRelatedDocument] = graph.calls[0]["related_documents"]
    assert related[0].filename == "spec.docx"
    assert related[0].content == "三年质保"
    assert related[1].filename == "bad-minutes.docx"
    assert related[1].content is None
    assert related[1].error == "document_parse_error"
    assert len(persistence.calls[0]["related_mineru_results"]) == 1


def test_contract_review_report_endpoint_rejects_invalid_perspective(client: TestClient) -> None:
    response = client.post(
        "/api/v1/contract-review-reports",
        json={
            "content": "合同正文",
            "review_perspective": "seller",
        },
    )

    assert response.status_code == 422


def test_contract_review_report_endpoint_rejects_malformed_json(client: TestClient) -> None:
    response = client.post(
        "/api/v1/contract-review-reports",
        content=b'{"content":',
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 400
    assert response.json() == {
        "error": {"code": "invalid_json", "message": "请求内容不是有效的 JSON。"}
    }


def test_contract_review_report_persistence_error_is_controlled(client: TestClient) -> None:
    graph = StubContractReviewGraphService()
    persistence = StubReportPersistenceService(error=RuntimeError("db unavailable"))
    app.dependency_overrides[get_contract_review_graph_service] = lambda: graph
    app.dependency_overrides[get_contract_review_persistence_service] = lambda: persistence

    response = client.post(
        "/api/v1/contract-review-reports",
        json={"content": "合同正文"},
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "persistence_error"


@pytest.mark.parametrize(
    ("error", "status_code", "error_code"),
    [
        (PdfRendererUnavailableError("missing"), 503, "pdf_renderer_unavailable"),
        (ReportPdfGenerationError("failed"), 500, "report_pdf_generation_error"),
    ],
)
def test_contract_review_report_pdf_error_is_controlled(
    client: TestClient,
    error: Exception,
    status_code: int,
    error_code: str,
) -> None:
    app.dependency_overrides[get_contract_review_graph_service] = (
        lambda: StubContractReviewGraphService()
    )
    app.dependency_overrides[get_contract_review_persistence_service] = (
        lambda: StubReportPersistenceService()
    )
    app.dependency_overrides[get_contract_review_pdf_renderer] = (
        lambda: StubPdfRenderer(error=error)
    )

    response = client.post("/api/v1/contract-review-reports", json={"content": "合同正文"})

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == error_code


def test_contract_review_report_document_download_headers(client: TestClient) -> None:
    task_id = "123e4567-e89b-12d3-a456-426614174000"

    response = client.get(f"/api/v1/contract-review-reports/{task_id}/document")

    expected = _downloadable_document()
    assert response.status_code == 200
    assert response.content == expected.content
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-length"] == str(len(expected.content))
    assert response.headers["etag"] == f'"{expected.metadata.sha256}"'
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    disposition = response.headers["content-disposition"]
    assert 'filename="contract-review-report.pdf"' in disposition
    assert "filename*=UTF-8''%E9%87%87%E8%B4%AD%E5%90%88%E5%90%8C" in disposition


def test_contract_review_report_document_rejects_invalid_uuid(client: TestClient) -> None:
    response = client.get("/api/v1/contract-review-reports/not-a-uuid/document")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


@pytest.mark.parametrize(
    ("error", "status_code", "error_code"),
    [
        (ReportDocumentNotFoundError("missing"), 404, "report_document_not_found"),
        (ReportDocumentReadError("failed"), 503, "report_document_read_error"),
    ],
)
def test_contract_review_report_document_error_is_controlled(
    client: TestClient,
    error: Exception,
    status_code: int,
    error_code: str,
) -> None:
    app.dependency_overrides[get_contract_review_document_service] = (
        lambda: StubDocumentService(error)
    )

    response = client.get(
        "/api/v1/contract-review-reports/123e4567-e89b-12d3-a456-426614174000/document"
    )

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == error_code


def test_contract_review_report_rejects_too_many_related_files(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(analysis_api, "MAX_RELATED_FILES", 2, raising=False)
    app.dependency_overrides[get_contract_review_graph_service] = (
        lambda: StubContractReviewGraphService()
    )
    app.dependency_overrides[get_document_parser] = lambda: StubReportDocumentParser()
    app.dependency_overrides[get_contract_review_persistence_service] = (
        lambda: StubReportPersistenceService()
    )
    files = [("file", _docx("contract.docx", b"main"))]
    files.extend(
        ("related_files", _docx(f"related-{index}.docx", b"content"))
        for index in range(3)
    )

    response = client.post(
        "/api/v1/contract-review-reports",
        data={"review_perspective": "neutral"},
        files=files,
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "too_many_related_files"


def test_contract_review_report_rejects_oversized_related_file(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(analysis_api, "MAX_RELATED_FILE_BYTES", 4, raising=False)
    app.dependency_overrides[get_contract_review_graph_service] = (
        lambda: StubContractReviewGraphService()
    )
    app.dependency_overrides[get_document_parser] = lambda: StubReportDocumentParser()
    app.dependency_overrides[get_contract_review_persistence_service] = (
        lambda: StubReportPersistenceService()
    )

    response = client.post(
        "/api/v1/contract-review-reports",
        data={"review_perspective": "neutral"},
        files=[
            ("file", _docx("contract.docx", b"main")),
            ("related_files", _docx("large.docx", b"12345")),
        ],
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "related_file_too_large"


def test_contract_review_report_limits_related_parse_concurrency(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(analysis_api, "RELATED_PARSE_CONCURRENCY", 2, raising=False)
    graph = StubContractReviewGraphService()
    parser = ConcurrencyTrackingParser()
    app.dependency_overrides[get_contract_review_graph_service] = lambda: graph
    app.dependency_overrides[get_document_parser] = lambda: parser
    app.dependency_overrides[get_contract_review_persistence_service] = (
        lambda: StubReportPersistenceService()
    )
    files = [("file", _docx("contract.docx", b"main"))]
    files.extend(
        ("related_files", _docx(f"related-{index}.docx", b"content"))
        for index in range(4)
    )

    response = client.post(
        "/api/v1/contract-review-reports",
        data={"review_perspective": "neutral"},
        files=files,
    )

    assert response.status_code == 200
    assert 1 < parser.max_active <= 2
