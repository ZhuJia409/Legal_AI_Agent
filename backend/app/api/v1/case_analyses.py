from __future__ import annotations

import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated, cast
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import Message

from app.core.config import Settings, get_settings
from app.db.session import build_mysql_session_factory
from app.integrations.llm.client import LLMClientError, LLMConfigurationError
from app.repositories.case_analysis import SqlAlchemyCaseAnalysisRepository
from app.schemas.analysis import AnalysisRequest
from app.schemas.case_analysis import (
    CaseAnalysisHistoryResponse,
    CaseAnalysisResponse,
    DocumentDraftStageResult,
)
from app.services.analysis_history import (
    CaseAnalysisHistoryService,
    HistoryNotFoundError,
    HistorySnapshotError,
)
from app.services.case_analysis_agents import (
    CaseAnalysisStructuredOutputError,
    LangChainCaseAnalysisAgentRunner,
)
from app.services.case_analysis_document import (
    CaseAnalysisDocumentRenderer,
    CaseDocumentGenerationError,
)
from app.services.case_analysis_graph import (
    CaseAnalysisCriticalStageError,
    CaseAnalysisGraphService,
)
from app.services.case_analysis_persistence import (
    CaseAnalysisDocumentNotFoundError,
    CaseAnalysisDocumentReadError,
    CaseAnalysisPersistenceService,
    CaseAnalysisStoredDocumentService,
)
from app.services.document_parser import (
    DocumentParseError,
    DocumentParserConfigurationError,
    DocumentParserUpstreamError,
)
from app.services.latex_pdf import TectonicCompiler
from app.services.mineru_parser import DocumentParserProtocol, MineruDocumentParser
from app.services.object_storage import MinioObjectStorage

logger = logging.getLogger("legal_ai.api.case_analyses")

router = APIRouter(prefix="/api/v1", tags=["case-analysis"])

_FILE_CONTENT_TYPES = {
    ".pdf": frozenset({"application/pdf", "application/octet-stream"}),
    ".docx": frozenset(
        {
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/octet-stream",
        }
    ),
    ".md": frozenset(
        {
            "text/markdown",
            "text/x-markdown",
            "text/plain",
            "application/octet-stream",
        }
    ),
    ".txt": frozenset({"text/plain", "application/octet-stream"}),
}
_TEXT_EXTENSIONS = frozenset({".md", ".txt"})
_MULTIPART_BODY_OVERHEAD_BYTES = 1024 * 1024

ReceiveCallable = Callable[[], Awaitable[Message]]


class CaseUploadBodyTooLargeError(OSError):
    """multipart 请求体在表单落盘过程中超过服务端硬边界。"""


@dataclass(frozen=True, slots=True)
class ResolvedCaseContent:
    title: str | None
    content: str


def get_case_analysis_graph_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> CaseAnalysisGraphService:
    """按服务端边界配置组装案件分析 Agent 与并联图。"""

    runner = LangChainCaseAnalysisAgentRunner(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        fallback_model=settings.llm_fallback_model,
        max_concurrency=settings.case_analysis_max_concurrency,
        timeout_seconds=settings.case_analysis_model_timeout_seconds,
    )
    return CaseAnalysisGraphService(
        runner,
        max_issues=settings.case_analysis_max_issues,
        max_content_chars=settings.case_analysis_max_content_chars,
        recursion_limit=settings.case_analysis_graph_recursion_limit,
    )


def get_case_document_parser(
    settings: Annotated[Settings, Depends(get_settings)],
) -> DocumentParserProtocol:
    return MineruDocumentParser(
        api_key=settings.mineru_api_key,
        base_url=settings.mineru_base_url,
        model_version=settings.mineru_model_version,
        poll_interval_seconds=settings.mineru_poll_interval_seconds,
        poll_timeout_seconds=settings.mineru_poll_timeout_seconds,
    )


def _case_repository(settings: Settings) -> SqlAlchemyCaseAnalysisRepository:
    return SqlAlchemyCaseAnalysisRepository(build_mysql_session_factory(settings))


def _case_object_storage(settings: Settings) -> MinioObjectStorage:
    return MinioObjectStorage(
        endpoint=settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        bucket=settings.minio_bucket,
    )


def get_case_analysis_document_renderer(
    settings: Annotated[Settings, Depends(get_settings)],
) -> CaseAnalysisDocumentRenderer:
    return CaseAnalysisDocumentRenderer(
        compiler=TectonicCompiler(
            tectonic_path=settings.tectonic_path,
            timeout_seconds=settings.tectonic_timeout_seconds,
        )
    )


def get_case_analysis_persistence_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> CaseAnalysisPersistenceService:
    return CaseAnalysisPersistenceService(
        repository=_case_repository(settings),
        object_storage=_case_object_storage(settings),
    )


def get_case_analysis_history_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> CaseAnalysisHistoryService:
    return CaseAnalysisHistoryService(_case_repository(settings))


def get_case_stored_document_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> CaseAnalysisStoredDocumentService:
    return CaseAnalysisStoredDocumentService(
        repository=_case_repository(settings),
        object_storage=_case_object_storage(settings),
    )


@router.post("/case-analyses", response_model=CaseAnalysisResponse)
async def create_case_analysis(
    request: Request,
    service: Annotated[
        CaseAnalysisGraphService,
        Depends(get_case_analysis_graph_service),
    ],
    document_parser: Annotated[
        DocumentParserProtocol,
        Depends(get_case_document_parser),
    ],
    settings: Annotated[Settings, Depends(get_settings)],
    document_renderer: Annotated[
        CaseAnalysisDocumentRenderer,
        Depends(get_case_analysis_document_renderer),
    ],
    persistence_service: Annotated[
        CaseAnalysisPersistenceService,
        Depends(get_case_analysis_persistence_service),
    ],
) -> CaseAnalysisResponse | JSONResponse:
    resolved = await _resolve_case_content(request, document_parser, settings)
    if isinstance(resolved, JSONResponse):
        return resolved

    try:
        started = time.monotonic()
        logger.info(
            "case_analysis_started content_length=%d has_title=%s",
            len(resolved.content),
            bool(resolved.title),
        )
        result = await service.analyze(
            title=resolved.title,
            content=resolved.content,
        )
        draft_stage = cast(
            DocumentDraftStageResult,
            next(stage for stage in result.stages if stage.stage == "document_draft"),
        )
        try:
            document = await document_renderer.render(
                analysis_id=result.analysis_id,
                title=resolved.title,
                status=result.status,
                risk_level=result.risk_level,
                draft_stage=draft_stage,
            )
        except CaseDocumentGenerationError as exc:
            logger.warning(
                "case_document_generation_failed analysis_id=%s error_type=%s",
                result.analysis_id,
                exc.__class__.__name__,
            )
            return _error_response(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                code="case_document_generation_error",
                message="案件文书 PDF 暂时无法生成，请稍后重试。",
            )
        try:
            await persistence_service.persist(
                title=resolved.title,
                response=result,
                document=document,
            )
        except Exception as exc:
            logger.warning(
                "case_analysis_persistence_failed analysis_id=%s error_type=%s",
                result.analysis_id,
                exc.__class__.__name__,
            )
            return _error_response(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                code="persistence_error",
                message="案件分析结果暂时无法保存，请稍后重试。",
            )
        logger.info(
            "case_analysis_completed analysis_id=%s status=%s elapsed=%.2fs",
            result.analysis_id,
            result.status,
            time.monotonic() - started,
        )
        return result
    except LLMConfigurationError:
        logger.warning("case_analysis_failed error_type=LLMConfigurationError")
        return _error_response(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="llm_configuration_error",
            message="模型服务未配置，请检查服务端环境变量。",
        )
    except CaseAnalysisStructuredOutputError:
        logger.warning("case_analysis_failed error_type=CaseAnalysisStructuredOutputError")
        return _error_response(
            status_code=status.HTTP_502_BAD_GATEWAY,
            code="structured_output_error",
            message="模型未返回有效的结构化案件分析结果，请稍后重试。",
        )
    except CaseAnalysisCriticalStageError as exc:
        logger.warning(
            "case_analysis_failed error_type=CaseAnalysisCriticalStageError stage=%s",
            exc.stage,
        )
        return _error_response(
            status_code=status.HTTP_502_BAD_GATEWAY,
            code="critical_stage_failed",
            message="案件分析关键阶段执行失败，请稍后重试。",
        )
    except LLMClientError:
        logger.warning("case_analysis_failed error_type=LLMClientError")
        return _error_response(
            status_code=status.HTTP_502_BAD_GATEWAY,
            code="llm_upstream_error",
            message="模型服务暂时不可用，请稍后重试。",
        )


@router.get("/case-analyses", response_model=CaseAnalysisHistoryResponse)
async def list_case_analyses(
    history_service: Annotated[
        CaseAnalysisHistoryService,
        Depends(get_case_analysis_history_service),
    ],
) -> CaseAnalysisHistoryResponse | JSONResponse:
    try:
        return await history_service.list_history()
    except Exception as exc:
        logger.warning("case_history_list_failed error_type=%s", exc.__class__.__name__)
        return _error_response(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="history_storage_error",
            message="案件分析历史暂时无法读取，请稍后重试。",
        )


@router.get("/case-analyses/{analysis_id}", response_model=CaseAnalysisResponse)
async def get_case_analysis(
    analysis_id: str,
    history_service: Annotated[
        CaseAnalysisHistoryService,
        Depends(get_case_analysis_history_service),
    ],
) -> CaseAnalysisResponse | JSONResponse:
    normalized = _normalize_uuid(analysis_id)
    if normalized is None:
        return _invalid_analysis_id_response()
    try:
        return await history_service.get_analysis(normalized)
    except HistoryNotFoundError:
        return _error_response(
            status_code=status.HTTP_404_NOT_FOUND,
            code="history_not_found",
            message="未找到该案件分析历史。",
        )
    except HistorySnapshotError:
        return _error_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="history_snapshot_error",
            message="案件分析历史数据无法恢复。",
        )
    except Exception as exc:
        logger.warning("case_history_read_failed error_type=%s", exc.__class__.__name__)
        return _error_response(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="history_storage_error",
            message="案件分析历史暂时无法读取，请稍后重试。",
        )


@router.get("/case-analyses/{analysis_id}/document")
async def download_case_analysis_document(
    analysis_id: str,
    document_service: Annotated[
        CaseAnalysisStoredDocumentService,
        Depends(get_case_stored_document_service),
    ],
) -> Response:
    normalized = _normalize_uuid(analysis_id)
    if normalized is None:
        return _invalid_analysis_id_response()
    try:
        document = await document_service.get_document(normalized)
    except CaseAnalysisDocumentNotFoundError:
        return _error_response(
            status_code=status.HTTP_404_NOT_FOUND,
            code="case_document_not_found",
            message="未找到该案件的文书草稿。",
        )
    except CaseAnalysisDocumentReadError:
        return _error_response(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="case_document_read_error",
            message="案件文书草稿暂时无法读取，请稍后重试。",
        )
    record = document.record
    encoded_filename = quote(record.document_filename, safe="")
    fallback_extension = (
        "pdf" if record.document_content_type == "application/pdf" else "docx"
    )
    return Response(
        content=document.content,
        media_type=record.document_content_type,
        headers={
            "Content-Disposition": (
                f'attachment; filename="case-analysis-draft.{fallback_extension}"; '
                f"filename*=UTF-8''{encoded_filename}"
            ),
            "Content-Length": str(record.document_size_bytes),
            "ETag": f'"{record.document_sha256}"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


def _normalize_uuid(value: str) -> str | None:
    try:
        return str(uuid.UUID(value))
    except ValueError:
        return None


def _invalid_analysis_id_response() -> JSONResponse:
    return _error_response(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        code="validation_error",
        message="分析 ID 格式无效。",
    )


async def _resolve_case_content(
    request: Request,
    document_parser: DocumentParserProtocol,
    settings: Settings,
) -> ResolvedCaseContent | JSONResponse:
    request_media_type = _normalize_media_type(request.headers.get("content-type"))
    if request_media_type == "application/json":
        return await _resolve_json_content(request, settings.case_analysis_max_content_chars)
    if request_media_type == "multipart/form-data":
        return await _resolve_uploaded_content(request, document_parser, settings)
    return _error_response(
        status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        code="unsupported_media_type",
        message="仅支持 application/json 或 multipart/form-data 请求。",
    )


async def _resolve_json_content(
    request: Request,
    max_content_chars: int,
) -> ResolvedCaseContent | JSONResponse:
    try:
        data = await request.json()
    except ValueError:
        return _error_response(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="invalid_json",
            message="请求内容不是有效的 JSON。",
        )

    if not isinstance(data, dict):
        return _error_response(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="validation_error",
            message="JSON 请求体必须是对象。",
        )
    raw_content = data.get("content")
    if raw_content is None or (isinstance(raw_content, str) and not raw_content.strip()):
        return _error_response(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="missing_content",
            message="请求体必须包含非空 content 字段。",
        )

    try:
        analysis_request = AnalysisRequest.model_validate(data)
    except ValidationError:
        return _error_response(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="validation_error",
            message="请求字段格式无效。",
        )

    if analysis_request.content is None:
        return _error_response(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="missing_content",
            message="请求体必须包含非空 content 字段。",
        )
    content_error = _validate_resolved_content(
        analysis_request.content,
        max_content_chars=max_content_chars,
    )
    if content_error is not None:
        return content_error
    return ResolvedCaseContent(
        title=analysis_request.title,
        content=analysis_request.content,
    )


async def _resolve_uploaded_content(
    request: Request,
    document_parser: DocumentParserProtocol,
    settings: Settings,
) -> ResolvedCaseContent | JSONResponse:
    max_body_bytes = (
        settings.case_analysis_max_upload_bytes + _MULTIPART_BODY_OVERHEAD_BYTES
    )
    declared_length = request.headers.get("content-length")
    if declared_length is not None:
        try:
            if int(declared_length) > max_body_bytes:
                return _file_too_large_response()
        except ValueError:
            pass

    limited_request = Request(
        request.scope,
        _build_limited_receive(request.receive, max_body_bytes=max_body_bytes),
    )
    try:
        form = await limited_request.form(max_files=1, max_fields=4)
    except CaseUploadBodyTooLargeError:
        return _file_too_large_response()
    except StarletteHTTPException:
        # Starlette 仅用该异常表示 multipart 格式错误，未知编程异常继续向上暴露。
        return _error_response(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="invalid_multipart",
            message="multipart 请求格式无效。",
        )

    file = form.get("file")
    if not isinstance(file, UploadFile):
        return _error_response(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="missing_file",
            message="请上传案件材料文件。",
        )

    title = form.get("title")
    try:
        normalized_title = AnalysisRequest.model_validate(
            {"title": title, "content": "placeholder"}
        ).title
    except ValidationError:
        return _error_response(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="validation_error",
            message="请求字段格式无效。",
        )

    filename = _safe_filename(file.filename or "uploaded-document")
    extension = _file_extension(filename)
    media_type = _normalize_media_type(file.content_type) or "application/octet-stream"
    if media_type not in _FILE_CONTENT_TYPES.get(extension, frozenset()):
        return _error_response(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            code="unsupported_file_type",
            message="案件材料仅支持 PDF、DOCX、MD 或 TXT 格式。",
        )

    try:
        source_bytes = await file.read(settings.case_analysis_max_upload_bytes + 1)
        await file.seek(0)
    except OSError as exc:
        logger.warning(
            "case_document_read_failed extension=%s error_type=%s",
            extension or "unknown",
            exc.__class__.__name__,
        )
        return _error_response(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="document_parse_error",
            message="读取案件材料失败。",
        )

    if len(source_bytes) > settings.case_analysis_max_upload_bytes:
        return _file_too_large_response()
    if not source_bytes:
        return _error_response(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="empty_file",
            message="上传文件不能为空。",
        )

    if extension in _TEXT_EXTENSIONS:
        try:
            content = source_bytes.decode("utf-8-sig")
        except UnicodeDecodeError:
            return _error_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                code="invalid_text_encoding",
                message="MD/TXT 文件必须使用 UTF-8 编码。",
            )
    else:
        try:
            content = await document_parser.parse(file)
        except DocumentParseError as exc:
            logger.warning(
                "case_document_parse_failed extension=%s error_type=%s",
                extension,
                exc.__class__.__name__,
            )
            return _document_parser_error_response(exc)

    if not isinstance(content, str):
        return _error_response(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="document_parse_error",
            message="案件材料解析失败，请检查文件后重试。",
        )
    normalized_content = content.strip()
    content_error = _validate_resolved_content(
        normalized_content,
        max_content_chars=settings.case_analysis_max_content_chars,
    )
    if content_error is not None:
        return content_error
    return ResolvedCaseContent(title=normalized_title, content=normalized_content)


def _validate_resolved_content(
    content: str,
    *,
    max_content_chars: int,
) -> JSONResponse | None:
    if not content:
        return _error_response(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="empty_content",
            message="案件材料未包含可分析的正文。",
        )
    if len(content) > max_content_chars:
        return _error_response(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            code="content_too_long",
            message="案件材料正文超过服务端字符限制。",
        )
    return None


def _build_limited_receive(
    receive: ReceiveCallable,
    *,
    max_body_bytes: int,
) -> ReceiveCallable:
    received = 0

    async def limited_receive() -> Message:
        nonlocal received
        message = await receive()
        if message["type"] == "http.request":
            body = message.get("body", b"")
            received += len(body)
            if received > max_body_bytes:
                raise CaseUploadBodyTooLargeError("multipart body exceeds limit")
        return message

    return limited_receive


def _file_too_large_response() -> JSONResponse:
    return _error_response(
        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
        code="file_too_large",
        message="上传文件超过服务端大小限制。",
    )


def _document_parser_error_response(exc: DocumentParseError) -> JSONResponse:
    if isinstance(exc, DocumentParserConfigurationError):
        return _error_response(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="document_parser_configuration_error",
            message="文档解析服务配置不可用，请联系管理员。",
        )
    if isinstance(exc, DocumentParserUpstreamError):
        return _error_response(
            status_code=status.HTTP_502_BAD_GATEWAY,
            code="document_parser_upstream_error",
            message="文档解析服务暂时不可用，请稍后重试。",
        )
    return _error_response(
        status_code=status.HTTP_400_BAD_REQUEST,
        code="document_parse_error",
        message="案件材料解析失败，请检查文件后重试。",
    )


def _normalize_media_type(value: str | None) -> str:
    if not value:
        return ""
    return value.partition(";")[0].strip().lower()


def _file_extension(filename: str) -> str:
    if "." not in filename:
        return ""
    return f".{filename.rsplit('.', 1)[-1].lower()}"


def _safe_filename(filename: str) -> str:
    basename = filename.replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = re.sub(r"[\x00-\x1f\x7f]+", "", basename).strip()
    return cleaned[:255] or "uploaded-document"


def _error_response(*, status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
    )
