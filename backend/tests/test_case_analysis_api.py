from __future__ import annotations

from io import BytesIO
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.v1.case_analyses.dependencies import (
    get_case_analysis_document_renderer,
    get_case_analysis_graph_service,
    get_case_analysis_persistence_service,
    get_case_document_parser,
)
from app.api.v1.case_analyses.request_parsing import (
    CaseUploadBodyTooLargeError,
    _build_limited_receive,
)
from app.core.config import Settings, get_settings
from app.integrations.llm.client import LLMClientError, LLMConfigurationError
from app.main import app
from app.schemas.case_analysis import CaseAnalysisResponse
from app.services.case_analysis.agents import CaseAnalysisStructuredOutputError
from app.services.case_analysis.document import (
    CaseDocumentGenerationError,
    GeneratedCaseDocument,
)
from app.services.case_analysis.graph import CaseAnalysisCriticalStageError
from app.services.document_parser import (
    DocumentParseError,
    DocumentParserConfigurationError,
    DocumentParserUpstreamError,
)


class FakeCaseAnalysisService:
    def __init__(
        self,
        response: CaseAnalysisResponse | None = None,
        error: Exception | None = None,
    ) -> None:
        self.response = response or _case_response()
        self.error = error
        self.calls: list[dict[str, str | None]] = []

    async def analyze(
        self,
        *,
        title: str | None,
        content: str,
        analysis_id: str | None = None,
    ) -> CaseAnalysisResponse:
        self.calls.append(
            {"title": title, "content": content, "analysis_id": analysis_id}
        )
        if self.error is not None:
            raise self.error
        return self.response


class FakeDocumentParser:
    def __init__(
        self,
        parsed_text: str = "MinerU 解析后的案件材料。",
        error: Exception | None = None,
    ) -> None:
        self.parsed_text = parsed_text
        self.error = error
        self.filenames: list[str | None] = []

    async def parse(self, file: Any) -> str:
        self.filenames.append(file.filename)
        if self.error is not None:
            raise self.error
        return self.parsed_text


class FakeCasePersistenceService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def persist(self, **kwargs: object) -> None:
        self.calls.append(kwargs)
        response = kwargs["response"]
        document = kwargs["document"]
        response.draft_document = document.to_document_info(response.analysis_id)  # type: ignore[attr-defined]


class FakeCaseDocumentRenderer:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[dict[str, object]] = []

    async def render(self, **kwargs: object) -> GeneratedCaseDocument:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        content = b"%PDF-case"
        return GeneratedCaseDocument(
            filename="案件处理方案与文书草稿.pdf",
            content_type="application/pdf",
            content=content,
            sha256=__import__("hashlib").sha256(content).hexdigest(),
            generated_at=__import__("datetime").datetime.now(
                __import__("datetime").UTC
            ),
        )


@pytest.fixture
def client() -> TestClient:
    app.dependency_overrides.clear()
    app.dependency_overrides[get_case_analysis_persistence_service] = (
        lambda: FakeCasePersistenceService()
    )
    app.dependency_overrides[get_case_analysis_document_renderer] = (
        lambda: FakeCaseDocumentRenderer()
    )
    yield TestClient(app)
    app.dependency_overrides.clear()


def _case_response(*, status: str = "complete") -> CaseAnalysisResponse:
    base_stage = {
        "status": "succeeded",
        "summary": "阶段完成。",
        "missing_information": [],
        "requires_human_review": True,
        "error": None,
    }
    return CaseAnalysisResponse.model_validate(
        {
            "module": "case_analysis",
            "analysis_id": "analysis-123",
            "status": status,
            "summary": "案件分析摘要。",
            "risk_level": "medium",
            "findings": ["存在履约争议。"],
            "suggestions": ["补充原始合同。"],
            "stages": [
                {
                    **base_stage,
                    "stage": "intake_screening",
                    "parties": [],
                    "claims": [],
                    "case_route": None,
                    "red_flags": [],
                },
                {
                    **base_stage,
                    "stage": "fact_reconstruction",
                    "timeline": [],
                    "key_facts": [],
                    "conflicts": [],
                },
                {
                    **base_stage,
                    "stage": "evidence_review",
                    "evidence_clues": [],
                    "gaps": [],
                    "reinforcement_plan": [],
                },
                {
                    **base_stage,
                    "stage": "legal_classification",
                    "legal_relations": [],
                    "candidate_causes": [],
                    "procedure_questions": [],
                },
                {**base_stage, "stage": "deep_analysis", "issues": []},
                {
                    **base_stage,
                    "stage": "risk_assessment",
                    "overall_risk_level": "medium",
                    "risks": [],
                },
                {**base_stage, "stage": "strategy_options", "strategies": []},
                {
                    **base_stage,
                    "stage": "document_draft",
                    "draft_title": "案件分析报告草稿",
                    "draft_sections": [],
                    "quality_checks": [],
                },
                {**base_stage, "stage": "deadline_management", "deadlines": []},
            ],
            "report": {
                "executive_summary": "案件分析摘要。",
                "overall_risk_level": "medium",
                "key_findings": ["存在履约争议。"],
                "recommended_actions": ["补充原始合同。"],
                "limitations": ["尚未接入外部法律检索。"],
                "failed_stages": [],
            },
            "disclaimer": "本结果仅供参考，必须由专业法律人士复核。",
        }
    )


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "out_of_order"])
def test_case_analysis_response_requires_exact_stage_order(mutation: str) -> None:
    payload = _case_response().model_dump(mode="json")
    stages = payload["stages"]
    if mutation == "missing":
        payload["stages"] = stages[:-1]
    elif mutation == "duplicate":
        payload["stages"] = [*stages[:-1], stages[0]]
    else:
        payload["stages"] = [stages[1], stages[0], *stages[2:]]

    with pytest.raises(ValidationError):
        CaseAnalysisResponse.model_validate(payload)


def _override_case_dependencies(
    service: FakeCaseAnalysisService,
    parser: FakeDocumentParser | None = None,
) -> FakeDocumentParser:
    resolved_parser = parser or FakeDocumentParser()
    app.dependency_overrides[get_case_analysis_graph_service] = lambda: service
    app.dependency_overrides[get_case_document_parser] = lambda: resolved_parser
    return resolved_parser


def _assert_error(response: Any, status_code: int, code: str) -> None:
    assert response.status_code == status_code
    assert response.json().keys() == {"error"}
    error = response.json()["error"]
    assert error.keys() == {"code", "message"}
    assert error["code"] == code
    assert error["message"]


def test_case_analysis_json_returns_full_compatible_response(client: TestClient) -> None:
    service = FakeCaseAnalysisService()
    _override_case_dependencies(service)

    response = client.post(
        "/api/v1/case-analyses",
        json={"title": "买卖合同纠纷", "content": "卖方逾期交货。"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["module"] == "case_analysis"
    assert data["summary"] == "案件分析摘要。"
    assert data["risk_level"] == "medium"
    assert data["findings"] == ["存在履约争议。"]
    assert data["suggestions"] == ["补充原始合同。"]
    assert data["analysis_id"] == "analysis-123"
    assert data["status"] == "complete"
    assert len(data["stages"]) == 9
    assert data["report"]["overall_risk_level"] == "medium"
    assert data["disclaimer"]
    assert data["draft_document"]["format"] == "pdf"
    assert service.calls == [
        {"title": "买卖合同纠纷", "content": "卖方逾期交货。", "analysis_id": None}
    ]


def test_case_analysis_partial_response_keeps_http_200(client: TestClient) -> None:
    service = FakeCaseAnalysisService(response=_case_response(status="partial"))
    _override_case_dependencies(service)

    response = client.post("/api/v1/case-analyses", json={"content": "案件事实。"})

    assert response.status_code == 200
    assert response.json()["status"] == "partial"


def test_case_document_generation_failure_is_controlled_and_not_persisted(
    client: TestClient,
) -> None:
    service = FakeCaseAnalysisService()
    persistence = FakeCasePersistenceService()
    _override_case_dependencies(service)
    app.dependency_overrides[get_case_analysis_document_renderer] = lambda: (
        FakeCaseDocumentRenderer(CaseDocumentGenerationError("compile failed"))
    )
    app.dependency_overrides[get_case_analysis_persistence_service] = lambda: persistence

    response = client.post("/api/v1/case-analyses", json={"content": "案件事实。"})

    _assert_error(response, 503, "case_document_generation_error")
    assert "compile failed" not in response.text
    assert persistence.calls == []


@pytest.mark.parametrize(
    ("filename", "content_type"),
    [
        ("case.pdf", "application/pdf"),
        (
            "case.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
        ("case.PDF", "application/octet-stream"),
        ("case.DOCX", "application/octet-stream"),
    ],
)
def test_pdf_and_docx_use_mineru_parser(
    client: TestClient,
    filename: str,
    content_type: str,
) -> None:
    service = FakeCaseAnalysisService()
    parser = _override_case_dependencies(service)

    response = client.post(
        "/api/v1/case-analyses",
        data={"title": "上传案件"},
        files={"file": (filename, BytesIO(b"binary document"), content_type)},
    )

    assert response.status_code == 200
    assert parser.filenames == [filename]
    assert service.calls[0]["content"] == "MinerU 解析后的案件材料。"


@pytest.mark.parametrize(
    ("filename", "content_type", "source_bytes"),
    [
        ("case.md", "text/markdown", "# 标题\n\n案件事实。".encode()),
        ("case.md", "text/plain", "案件事实。".encode("utf-8-sig")),
        ("case.MD", "application/octet-stream", "案件事实。".encode()),
        ("case.txt", "text/plain; charset=utf-8", "案件事实。".encode("utf-8-sig")),
        ("case.TXT", "application/octet-stream", "案件事实。".encode()),
    ],
)
def test_markdown_and_text_are_read_as_utf8_without_mineru(
    client: TestClient,
    filename: str,
    content_type: str,
    source_bytes: bytes,
) -> None:
    service = FakeCaseAnalysisService()
    parser = _override_case_dependencies(service)

    response = client.post(
        "/api/v1/case-analyses",
        files={"file": (filename, BytesIO(source_bytes), content_type)},
    )

    assert response.status_code == 200
    assert parser.filenames == []
    assert service.calls[0]["content"] in {"# 标题\n\n案件事实。", "案件事实。"}


@pytest.mark.parametrize(
    ("payload", "expected_code"),
    [
        ({}, "missing_content"),
        ({"content": None}, "missing_content"),
        ({"content": "   "}, "missing_content"),
    ],
)
def test_json_requires_non_blank_content(
    client: TestClient,
    payload: dict[str, object],
    expected_code: str,
) -> None:
    _override_case_dependencies(FakeCaseAnalysisService())

    response = client.post("/api/v1/case-analyses", json=payload)

    _assert_error(response, 422, expected_code)


def test_invalid_json_returns_controlled_error(client: TestClient) -> None:
    _override_case_dependencies(FakeCaseAnalysisService())

    response = client.post(
        "/api/v1/case-analyses",
        content=b"{invalid",
        headers={"content-type": "application/json"},
    )

    _assert_error(response, 400, "invalid_json")


def test_invalid_json_shape_returns_validation_error(client: TestClient) -> None:
    _override_case_dependencies(FakeCaseAnalysisService())

    response = client.post(
        "/api/v1/case-analyses",
        json={"title": "x" * 201, "content": "案件事实。"},
    )

    _assert_error(response, 422, "validation_error")


def test_malformed_multipart_returns_controlled_error(client: TestClient) -> None:
    service = FakeCaseAnalysisService()
    _override_case_dependencies(service)

    response = client.post(
        "/api/v1/case-analyses",
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
    assert service.calls == []


def test_missing_multipart_file_returns_controlled_error(client: TestClient) -> None:
    _override_case_dependencies(FakeCaseAnalysisService())

    response = client.post(
        "/api/v1/case-analyses",
        data={"title": "未上传文件"},
        files={"unused": ("placeholder.txt", b"x", "text/plain")},
    )

    _assert_error(response, 400, "missing_file")


@pytest.mark.parametrize(
    ("filename", "content_type"),
    [
        ("case.pdf", "application/pdf"),
        ("case.txt", "text/plain"),
    ],
)
def test_empty_upload_is_rejected(
    client: TestClient,
    filename: str,
    content_type: str,
) -> None:
    service = FakeCaseAnalysisService()
    parser = _override_case_dependencies(service)

    response = client.post(
        "/api/v1/case-analyses",
        files={"file": (filename, BytesIO(b""), content_type)},
    )

    _assert_error(response, 400, "empty_file")
    assert parser.filenames == []
    assert service.calls == []


def test_invalid_utf8_text_is_rejected_without_mineru(client: TestClient) -> None:
    service = FakeCaseAnalysisService()
    parser = _override_case_dependencies(service)

    response = client.post(
        "/api/v1/case-analyses",
        files={"file": ("case.txt", BytesIO(b"\xff\xfe\x00"), "text/plain")},
    )

    _assert_error(response, 400, "invalid_text_encoding")
    assert parser.filenames == []
    assert service.calls == []


@pytest.mark.parametrize(
    ("filename", "content_type"),
    [
        ("case.exe", "application/octet-stream"),
        ("case.pdf", "text/plain"),
        ("case.txt", "application/pdf"),
    ],
)
def test_extension_and_mime_must_both_be_allowed(
    client: TestClient,
    filename: str,
    content_type: str,
) -> None:
    _override_case_dependencies(FakeCaseAnalysisService())

    response = client.post(
        "/api/v1/case-analyses",
        files={"file": (filename, BytesIO(b"content"), content_type)},
    )

    _assert_error(response, 415, "unsupported_file_type")


def test_unsupported_request_media_type_is_rejected(client: TestClient) -> None:
    _override_case_dependencies(FakeCaseAnalysisService())

    response = client.post(
        "/api/v1/case-analyses",
        content=b"case material",
        headers={"content-type": "text/plain"},
    )

    _assert_error(response, 415, "unsupported_media_type")


def test_upload_size_limit_uses_settings(client: TestClient) -> None:
    service = FakeCaseAnalysisService()
    parser = _override_case_dependencies(service)
    settings = Settings(_env_file=None, case_analysis_max_upload_bytes=4)
    app.dependency_overrides[get_settings] = lambda: settings

    response = client.post(
        "/api/v1/case-analyses",
        files={"file": ("case.txt", BytesIO(b"12345"), "text/plain")},
    )

    _assert_error(response, 413, "file_too_large")
    assert parser.filenames == []
    assert service.calls == []


def test_declared_multipart_body_limit_is_rejected_before_form_parsing(
    client: TestClient,
) -> None:
    service = FakeCaseAnalysisService()
    _override_case_dependencies(service)
    settings = Settings(_env_file=None, case_analysis_max_upload_bytes=4)
    app.dependency_overrides[get_settings] = lambda: settings

    response = client.post(
        "/api/v1/case-analyses",
        files={"file": ("case.txt", BytesIO(b"x"), "text/plain")},
        headers={"content-length": str(2 * 1024 * 1024)},
    )

    _assert_error(response, 413, "file_too_large")
    assert service.calls == []


@pytest.mark.asyncio
async def test_chunked_receive_limit_stops_body_before_form_spooling() -> None:
    messages = iter(
        [
            {"type": "http.request", "body": b"12", "more_body": True},
            {"type": "http.request", "body": b"345", "more_body": False},
        ]
    )

    async def receive() -> dict[str, Any]:
        return next(messages)

    limited_receive = _build_limited_receive(receive, max_body_bytes=4)

    assert (await limited_receive())["body"] == b"12"
    with pytest.raises(CaseUploadBodyTooLargeError):
        await limited_receive()


@pytest.mark.parametrize(
    "payload",
    [
        {"content": "案" * 60_001},
    ],
)
def test_json_content_over_limit_is_rejected(
    client: TestClient,
    payload: dict[str, str],
) -> None:
    service = FakeCaseAnalysisService()
    _override_case_dependencies(service)

    response = client.post("/api/v1/case-analyses", json=payload)

    _assert_error(response, 413, "content_too_long")
    assert service.calls == []


def test_decoded_text_over_limit_is_rejected(client: TestClient) -> None:
    service = FakeCaseAnalysisService()
    parser = _override_case_dependencies(service)

    response = client.post(
        "/api/v1/case-analyses",
        files={
            "file": (
                "case.md",
                BytesIO(("案" * 60_001).encode()),
                "text/markdown",
            )
        },
    )

    _assert_error(response, 413, "content_too_long")
    assert parser.filenames == []
    assert service.calls == []


def test_mineru_failure_returns_sanitized_error(
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    service = FakeCaseAnalysisService()
    parser = FakeDocumentParser(
        error=DocumentParseError("upstream secret material and signed URL")
    )
    _override_case_dependencies(service, parser)

    response = client.post(
        "/api/v1/case-analyses",
        files={
            "file": (
                "刘某身份证案件材料.pdf",
                BytesIO(b"pdf"),
                "application/pdf",
            )
        },
    )

    _assert_error(response, 400, "document_parse_error")
    assert "upstream secret" not in response.text
    assert "刘某身份证案件材料.pdf" not in caplog.text
    assert service.calls == []


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
def test_case_analysis_maps_document_parser_infrastructure_errors(
    client: TestClient,
    parser_error: Exception,
    status_code: int,
    code: str,
) -> None:
    service = FakeCaseAnalysisService()
    _override_case_dependencies(service, FakeDocumentParser(error=parser_error))

    response = client.post(
        "/api/v1/case-analyses",
        files={"file": ("case.pdf", BytesIO(b"pdf"), "application/pdf")},
    )

    _assert_error(response, status_code, code)
    assert str(parser_error) not in response.text
    assert service.calls == []


def test_unexpected_parser_bug_is_not_misreported_as_client_error(
    client: TestClient,
) -> None:
    service = FakeCaseAnalysisService()
    parser = FakeDocumentParser(error=TypeError("programming bug"))
    _override_case_dependencies(service, parser)

    with pytest.raises(TypeError, match="programming bug"):
        client.post(
            "/api/v1/case-analyses",
            files={"file": ("case.pdf", BytesIO(b"pdf"), "application/pdf")},
        )

    assert service.calls == []


def test_empty_parsed_content_is_rejected(client: TestClient) -> None:
    service = FakeCaseAnalysisService()
    _override_case_dependencies(service, FakeDocumentParser(parsed_text="   \n"))

    response = client.post(
        "/api/v1/case-analyses",
        files={"file": ("case.docx", BytesIO(b"docx"), "application/octet-stream")},
    )

    _assert_error(response, 400, "empty_content")
    assert service.calls == []


def test_parsed_content_over_limit_is_rejected(client: TestClient) -> None:
    service = FakeCaseAnalysisService()
    _override_case_dependencies(
        service,
        FakeDocumentParser(parsed_text="案" * 60_001),
    )

    response = client.post(
        "/api/v1/case-analyses",
        files={"file": ("case.pdf", BytesIO(b"pdf"), "application/pdf")},
    )

    _assert_error(response, 413, "content_too_long")
    assert service.calls == []


@pytest.mark.parametrize(
    ("error", "status_code", "code"),
    [
        (LLMConfigurationError("missing key"), 503, "llm_configuration_error"),
        (LLMClientError("upstream failed"), 502, "llm_upstream_error"),
        (
            CaseAnalysisCriticalStageError("legal_classification"),
            502,
            "critical_stage_failed",
        ),
        (
            CaseAnalysisStructuredOutputError("invalid structured output"),
            502,
            "structured_output_error",
        ),
    ],
)
def test_case_analysis_service_errors_are_controlled(
    client: TestClient,
    error: Exception,
    status_code: int,
    code: str,
) -> None:
    _override_case_dependencies(FakeCaseAnalysisService(error=error))

    response = client.post("/api/v1/case-analyses", json={"content": "案件事实。"})

    _assert_error(response, status_code, code)
    assert str(error) not in response.text


def test_case_analysis_settings_have_planned_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.case_analysis_max_concurrency == 4
    assert settings.case_analysis_max_issues == 5
    assert settings.case_analysis_model_timeout_seconds == 120
    assert settings.case_analysis_max_content_chars == 60_000
    assert settings.case_analysis_max_upload_bytes == 20 * 1024 * 1024
    assert settings.case_analysis_graph_recursion_limit == 40


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("case_analysis_max_concurrency", 0),
        ("case_analysis_max_concurrency", 33),
        ("case_analysis_max_issues", 0),
        ("case_analysis_max_issues", 6),
        ("case_analysis_model_timeout_seconds", 0),
        ("case_analysis_model_timeout_seconds", 601),
        ("case_analysis_max_content_chars", 0),
        ("case_analysis_max_content_chars", 200_001),
        ("case_analysis_max_upload_bytes", 0),
        ("case_analysis_max_upload_bytes", 100 * 1024 * 1024 + 1),
        ("case_analysis_graph_recursion_limit", 0),
        ("case_analysis_graph_recursion_limit", 201),
    ],
)
def test_case_analysis_settings_reject_out_of_range_values(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})


def test_case_analysis_dependency_uses_all_settings() -> None:
    settings = Settings(
        _env_file=None,
        llm_base_url="https://llm.example/v1",
        llm_api_key="test-key",
        llm_model="primary-model",
        llm_fallback_model="fallback-model",
        case_analysis_max_concurrency=2,
        case_analysis_max_issues=3,
        case_analysis_model_timeout_seconds=30,
        case_analysis_max_content_chars=1_234,
        case_analysis_max_upload_bytes=4_096,
        case_analysis_graph_recursion_limit=17,
    )

    service = get_case_analysis_graph_service(settings)

    assert service.max_issues == 3
    assert service.max_content_chars == 1_234
    assert service.recursion_limit == 17
    assert service.runner.base_url == "https://llm.example/v1"
    assert service.runner.api_key == "test-key"
    assert service.runner.model == "primary-model"
    assert service.runner.fallback_model == "fallback-model"
    assert service.runner.timeout_seconds == 30
    assert service.runner.max_concurrency == 2
