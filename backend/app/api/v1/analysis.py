import asyncio
import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from io import BytesIO
from typing import Annotated, cast
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse, Response
from starlette.datastructures import FormData, Headers, UploadFile
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import Message

from app.core.config import Settings, get_settings
from app.db.session import build_mysql_session_factory
from app.integrations.llm.client import (
    LLMClientError,
    LLMConfigurationError,
)
from app.repositories.contract_review import (
    PymongoContractReviewAuditRepository,
    SqlAlchemyContractReviewSnapshotRepository,
)
from app.schemas.analysis import AnalysisRequest
from app.schemas.contract_background import ContractBackgroundResponse
from app.schemas.contract_review import (
    ContractReviewHistoryResponse,
    ContractReviewReportResponse,
    ReviewPerspective,
)
from app.services.analysis_history import (
    ContractReviewHistoryService,
    HistoryNotFoundError,
    HistorySnapshotError,
)
from app.services.contract_background import ContractBackgroundService
from app.services.contract_review_documents import (
    ContractReviewDocumentService,
    ReportDocumentNotFoundError,
    ReportDocumentReadError,
)
from app.services.contract_review_graph import (
    ContractReviewGraphService,
    LangChainReviewAgentRunner,
    ParsedRelatedDocument,
)
from app.services.contract_review_pdf import (
    ContractReviewPdfRenderer,
    PdfRendererUnavailableError,
    ReportPdfGenerationError,
    TectonicCompiler,
)
from app.services.contract_review_persistence import (
    ContractReviewPersistenceService,
    ContractReviewSourceFile,
)
from app.services.document_parser import (
    DocumentParseError,
    DocumentParserConfigurationError,
    DocumentParserUpstreamError,
)
from app.services.mineru_parser import (
    DocumentParserProtocol,
    MineruDocumentParser,
    MineruParseResult,
)
from app.services.object_storage import MinioObjectStorage

logger = logging.getLogger("legal_ai.api.analysis")

router = APIRouter(prefix="/api/v1", tags=["legal-analysis"])

RELATED_FILE_EXTENSIONS = (".pdf", ".docx")
RELATED_FILE_CONTENT_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/octet-stream",
}
MAX_RELATED_FILES = 8
MAX_CONTRACT_FILE_BYTES = 20 * 1024 * 1024
MAX_RELATED_FILE_BYTES = 20 * 1024 * 1024
MAX_RELATED_TOTAL_BYTES = 64 * 1024 * 1024
RELATED_PARSE_CONCURRENCY = 3
_CONTRACT_MULTIPART_BODY_OVERHEAD_BYTES = 1024 * 1024

ReceiveCallable = Callable[[], Awaitable[Message]]


class ContractUploadBodyTooLargeError(OSError):
    """合同 multipart 请求体在表单落盘过程中超过硬边界。"""


class UnsupportedRelatedFileTypeError(ValueError):
    """关联文件类型不在合同背景审查允许的 PDF/DOCX 白名单中。"""


class RelatedFileLimitError(ValueError):
    """关联文件超过数量或大小边界。"""

    def __init__(self, *, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class ResolvedContractReviewContent:
    title: str | None
    content: str
    source_file: ContractReviewSourceFile | None = None
    related_files: tuple[ContractReviewSourceFile, ...] = ()
    provided_related_documents: tuple[str, ...] = ()
    mineru_result: MineruParseResult | None = None


def get_contract_background_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> ContractBackgroundService:
    return ContractBackgroundService.from_llm_settings(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        fallback_model=settings.llm_fallback_model,
    )


def get_contract_review_graph_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> ContractReviewGraphService:
    """按官方 LangChain/LangGraph 接口组装完整合同审查 DAG。"""

    background_service = ContractBackgroundService.from_llm_settings(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        fallback_model=settings.llm_fallback_model,
    )
    runner = LangChainReviewAgentRunner(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        fallback_model=settings.llm_fallback_model,
    )
    return ContractReviewGraphService(background_service, runner)


def get_document_parser(
    settings: Annotated[Settings, Depends(get_settings)],
) -> DocumentParserProtocol:
    return MineruDocumentParser(
        api_key=settings.mineru_api_key,
        base_url=settings.mineru_base_url,
        model_version=settings.mineru_model_version,
        poll_interval_seconds=settings.mineru_poll_interval_seconds,
        poll_timeout_seconds=settings.mineru_poll_timeout_seconds,
    )


def get_contract_review_persistence_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> ContractReviewPersistenceService:
    session_factory = build_mysql_session_factory(settings)
    return ContractReviewPersistenceService(
        object_storage=MinioObjectStorage(
            endpoint=settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            bucket=settings.minio_bucket,
        ),
        snapshot_repository=SqlAlchemyContractReviewSnapshotRepository(session_factory),
        audit_repository=PymongoContractReviewAuditRepository(settings.mongodb_url),
    )


def get_contract_review_pdf_renderer(
    settings: Annotated[Settings, Depends(get_settings)],
) -> ContractReviewPdfRenderer:
    """使用服务端固定配置组装离线 Tectonic 渲染器。"""

    return ContractReviewPdfRenderer(
        compiler=TectonicCompiler(
            tectonic_path=settings.tectonic_path,
            timeout_seconds=settings.tectonic_timeout_seconds,
        )
    )


def get_contract_review_document_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> ContractReviewDocumentService:
    """组装报告元数据与 MinIO 只读边界，不向浏览器暴露对象地址。"""

    session_factory = build_mysql_session_factory(settings)
    return ContractReviewDocumentService(
        repository=SqlAlchemyContractReviewSnapshotRepository(session_factory),
        object_storage=MinioObjectStorage(
            endpoint=settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            bucket=settings.minio_bucket,
        ),
    )


def get_contract_review_history_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> ContractReviewHistoryService:
    return ContractReviewHistoryService(
        SqlAlchemyContractReviewSnapshotRepository(build_mysql_session_factory(settings))
    )


async def _resolve_content(
    request: Request,
    document_parser: DocumentParserProtocol,
) -> tuple[str | None, str] | JSONResponse:
    content_type = request.headers.get("content-type", "").lower()

    if "multipart/form-data" in content_type:
        form = await request.form()
        title = form.get("title")
        file = form.get("file")
        if not isinstance(file, UploadFile):
            return _error_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                code="missing_file",
                message="请上传 PDF 或 DOCX 文件。",
            )
        filename = file.filename or "uploaded-document"
        extension = _file_extension(filename)
        logger.info(
            "document_upload_received extension=%s content_type=%s",
            extension,
            file.content_type,
        )
        try:
            started = time.monotonic()
            logger.info("document_parse_started extension=%s", extension)
            content = await document_parser.parse(file)
            logger.info(
                "document_parse_completed extension=%s content_length=%d elapsed=%.2fs",
                extension,
                len(content),
                time.monotonic() - started,
            )
        except DocumentParseError as exc:
            logger.warning(
                "document_parse_failed extension=%s error_type=%s",
                extension,
                exc.__class__.__name__,
            )
            return _document_parser_error_response(exc)
        return (title if isinstance(title, str) else None), content

    if "application/json" in content_type:
        try:
            data = await request.json()
        except Exception:
            return _error_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                code="invalid_json",
                message="请求内容不是有效的 JSON。",
            )
        try:
            analysis_request = AnalysisRequest.model_validate(data)
        except Exception as exc:
            return _error_response(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                code="validation_error",
                message=str(exc),
            )
        if not analysis_request.content:
            return _error_response(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                code="missing_content",
                message="请求体中必须包含 content 字段。",
            )
        logger.info(
            "json_content_received content_length=%d has_title=%s",
            len(analysis_request.content),
            bool(analysis_request.title),
        )
        return analysis_request.title, analysis_request.content

    return _error_response(
        status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        code="unsupported_media_type",
        message="仅支持 application/json 或 multipart/form-data 请求。",
    )


async def _resolve_contract_review_content(
    request: Request,
    document_parser: DocumentParserProtocol,
) -> ResolvedContractReviewContent | JSONResponse:
    content_type = request.headers.get("content-type", "").lower()
    if "multipart/form-data" not in content_type:
        resolved = await _resolve_content(request, document_parser)
        if isinstance(resolved, JSONResponse):
            return resolved
        title, content = resolved
        return ResolvedContractReviewContent(title=title, content=content)

    form = await _parse_contract_multipart_form(request)
    if isinstance(form, JSONResponse):
        return form
    title = form.get("title")
    file = form.get("file")
    if not isinstance(file, UploadFile):
        return _error_response(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="missing_file",
            message="请上传 PDF 或 DOCX 文件。",
        )

    filename = file.filename or "uploaded-document"
    extension = _file_extension(filename)
    content_type = file.content_type or "application/octet-stream"
    # 主合同与关联文件共用 PDF/DOCX 白名单，避免绕过前端限制提交其他格式。
    if not _is_supported_related_file(filename, content_type):
        return _error_response(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            code="unsupported_file_type",
            message="合同文件仅支持 PDF 或 DOCX 格式。",
        )
    logger.info(
        "contract_document_upload_received extension=%s content_type=%s",
        extension,
        content_type,
    )
    try:
        source_bytes = await file.read(MAX_CONTRACT_FILE_BYTES + 1)
        if len(source_bytes) > MAX_CONTRACT_FILE_BYTES:
            return _contract_file_too_large_response()
        await file.seek(0)
        related_files = await _read_related_files(form)
    except UnsupportedRelatedFileTypeError:
        return _error_response(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="unsupported_related_file_type",
            message="关联文件仅支持 PDF 或 DOCX 格式。",
        )
    except RelatedFileLimitError as exc:
        return _error_response(
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
        )
    except OSError:
        logger.warning("contract_document_read_failed extension=%s", extension)
        return _error_response(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="document_read_error",
            message="读取上传文件失败。",
        )

    try:
        started = time.monotonic()
        logger.info("contract_document_parse_started extension=%s", extension)
        parse_result = getattr(document_parser, "parse_result", None)
        if callable(parse_result):
            mineru_result = await parse_result(file)
            content = mineru_result.markdown
        else:
            mineru_result = None
            content = await document_parser.parse(file)
        logger.info(
            "contract_document_parse_completed extension=%s content_length=%d elapsed=%.2fs",
            extension,
            len(content),
            time.monotonic() - started,
        )
    except DocumentParseError as exc:
        logger.warning(
            "contract_document_parse_failed extension=%s error_type=%s",
            extension,
            exc.__class__.__name__,
        )
        return _document_parser_error_response(exc)

    return ResolvedContractReviewContent(
        title=title if isinstance(title, str) else None,
        content=content,
        source_file=ContractReviewSourceFile(
            filename=filename,
            content_type=content_type,
            content=source_bytes,
        ),
        related_files=related_files,
        provided_related_documents=_provided_related_document_names(related_files),
        mineru_result=mineru_result,
    )


async def _read_related_files(form: object) -> tuple[ContractReviewSourceFile, ...]:
    getlist = getattr(form, "getlist", None)
    if not callable(getlist):
        return ()

    uploads: list[UploadFile] = []
    for field_name in ("related_files", "related_file"):
        for item in getlist(field_name):
            if isinstance(item, UploadFile):
                uploads.append(item)

    if len(uploads) > MAX_RELATED_FILES:
        raise RelatedFileLimitError(
            code="too_many_related_files",
            message=f"关联文件最多上传 {MAX_RELATED_FILES} 个。",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    related_files: list[ContractReviewSourceFile] = []
    total_bytes = 0
    for item in uploads:
        filename = _sanitize_uploaded_filename(item.filename or "related-document")
        content_type = item.content_type or "application/octet-stream"
        if not _is_supported_related_file(filename, content_type):
            raise UnsupportedRelatedFileTypeError(filename)
        content = await item.read(MAX_RELATED_FILE_BYTES + 1)
        if len(content) > MAX_RELATED_FILE_BYTES:
            raise RelatedFileLimitError(
                code="related_file_too_large",
                message=f"单个关联文件不能超过 {MAX_RELATED_FILE_BYTES // 1024 // 1024} MB。",
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            )
        total_bytes += len(content)
        if total_bytes > MAX_RELATED_TOTAL_BYTES:
            raise RelatedFileLimitError(
                code="related_files_too_large",
                message=f"关联文件总大小不能超过 {MAX_RELATED_TOTAL_BYTES // 1024 // 1024} MB。",
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            )
        related_files.append(
            ContractReviewSourceFile(
                filename=filename,
                content_type=content_type,
                content=content,
            )
        )
    return tuple(related_files)


async def _parse_related_documents(
    files: Sequence[ContractReviewSourceFile],
    document_parser: DocumentParserProtocol,
) -> tuple[
    list[ParsedRelatedDocument],
    list[tuple[ContractReviewSourceFile, MineruParseResult]],
]:
    """并发解析附件；单个附件失败只记录限制，不中断主合同审查。"""

    semaphore = asyncio.Semaphore(RELATED_PARSE_CONCURRENCY)

    async def parse_one(
        source_file: ContractReviewSourceFile,
    ) -> tuple[ParsedRelatedDocument, tuple[ContractReviewSourceFile, MineruParseResult] | None]:
        async with semaphore:
            try:
                parse_bytes = getattr(document_parser, "parse_bytes", None)
                if callable(parse_bytes):
                    result = await parse_bytes(
                        filename=source_file.filename,
                        file_bytes=source_file.content,
                    )
                    return (
                        ParsedRelatedDocument(
                            filename=source_file.filename,
                            content=result.markdown,
                        ),
                        (source_file, result),
                    )

                upload = UploadFile(
                    file=BytesIO(source_file.content),
                    filename=source_file.filename,
                    headers=Headers({"content-type": source_file.content_type}),
                )
                parse_result = getattr(document_parser, "parse_result", None)
                if callable(parse_result):
                    result = await parse_result(upload)
                    return (
                        ParsedRelatedDocument(
                            filename=source_file.filename,
                            content=result.markdown,
                        ),
                        (source_file, result),
                    )
                content = await document_parser.parse(upload)
                return (
                    ParsedRelatedDocument(filename=source_file.filename, content=content),
                    None,
                )
            except DocumentParseError as exc:
                # 仅降级解析器声明的业务异常；编程错误必须继续暴露，避免静默生成残缺报告。
                logger.warning(
                    "related_document_parse_failed extension=%s error_type=%s",
                    _file_extension(source_file.filename),
                    exc.__class__.__name__,
                )
                return (
                    ParsedRelatedDocument(
                        filename=source_file.filename,
                        error="document_parse_error",
                    ),
                    None,
                )

    parsed_pairs = await asyncio.gather(*(parse_one(item) for item in files))
    parsed_documents = [item[0] for item in parsed_pairs]
    mineru_results = [item[1] for item in parsed_pairs if item[1] is not None]
    return parsed_documents, mineru_results


async def _resolve_review_perspective(
    request: Request,
) -> ReviewPerspective | JSONResponse:
    content_type = request.headers.get("content-type", "").lower()
    if "multipart/form-data" in content_type:
        form = await _parse_contract_multipart_form(request)
        if isinstance(form, JSONResponse):
            return form
        raw_value = form.get("review_perspective", "neutral")
    elif "application/json" in content_type:
        try:
            payload = await request.json()
        except Exception:
            return _error_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                code="invalid_json",
                message="请求内容不是有效的 JSON。",
            )
        raw_value = (
            payload.get("review_perspective", "neutral")
            if isinstance(payload, dict)
            else None
        )
    else:
        raw_value = "neutral"

    if raw_value not in {"neutral", "party_a", "party_b"}:
        return _error_response(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="invalid_review_perspective",
            message="review_perspective 仅支持 neutral、party_a 或 party_b。",
        )
    return cast("ReviewPerspective", raw_value)


def _provided_related_document_names(
    related_files: tuple[ContractReviewSourceFile, ...],
) -> tuple[str, ...]:
    # 只有真实上传的文件才进入模型材料清单，文本声明不能冒充已提供文件。
    return tuple(dict.fromkeys(file.filename for file in related_files))


def _sanitize_uploaded_filename(filename: str) -> str:
    """移除路径和控制字符，避免文件名污染提示词、日志或对象键。"""

    basename = filename.replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = re.sub(r"[\x00-\x1f\x7f]+", "", basename).strip()
    return cleaned[:255] or "related-document"


def _is_supported_related_file(filename: str, content_type: str) -> bool:
    return filename.lower().endswith(RELATED_FILE_EXTENSIONS) and (
        _normalize_media_type(content_type) in RELATED_FILE_CONTENT_TYPES
    )


def _normalize_media_type(value: str) -> str:
    return value.partition(";")[0].strip().lower()


def _file_extension(filename: str) -> str:
    basename = filename.replace("\\", "/").rsplit("/", 1)[-1]
    if "." not in basename:
        return "unknown"
    return f".{basename.rsplit('.', 1)[-1].lower()}"


async def _parse_contract_multipart_form(
    request: Request,
) -> FormData | JSONResponse:
    if getattr(request, "_form", None) is not None:
        return await request.form()

    max_body_bytes = (
        MAX_CONTRACT_FILE_BYTES
        + MAX_RELATED_TOTAL_BYTES
        + _CONTRACT_MULTIPART_BODY_OVERHEAD_BYTES
    )
    declared_length = request.headers.get("content-length")
    if declared_length is not None:
        try:
            if int(declared_length) > max_body_bytes:
                return _contract_file_too_large_response()
        except ValueError:
            pass

    # 同一 Request 会被报告视角解析复用，直接替换 receive 可确保首次 form 落盘就受限。
    request._receive = _build_contract_limited_receive(  # noqa: SLF001
        request.receive,
        max_body_bytes=max_body_bytes,
    )
    try:
        return await request.form(max_files=100, max_fields=16)
    except ContractUploadBodyTooLargeError:
        return _contract_file_too_large_response()
    except StarletteHTTPException:
        return _error_response(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="invalid_multipart",
            message="multipart 请求格式无效。",
        )


def _build_contract_limited_receive(
    receive: ReceiveCallable,
    *,
    max_body_bytes: int,
) -> ReceiveCallable:
    received = 0

    async def limited_receive() -> Message:
        nonlocal received
        message = await receive()
        if message["type"] == "http.request":
            received += len(message.get("body", b""))
            if received > max_body_bytes:
                raise ContractUploadBodyTooLargeError(
                    "contract multipart body exceeds limit"
                )
        return message

    return limited_receive


def _contract_file_too_large_response() -> JSONResponse:
    return _error_response(
        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
        code="file_too_large",
        message="上传文件超过服务端大小限制。",
    )


@router.post("/contract-reviews", response_model=ContractBackgroundResponse)
async def create_contract_review(
    request: Request,
    service: Annotated[ContractBackgroundService, Depends(get_contract_background_service)],
    document_parser: Annotated[DocumentParserProtocol, Depends(get_document_parser)],
    persistence_service: Annotated[
        ContractReviewPersistenceService,
        Depends(get_contract_review_persistence_service),
    ],
) -> ContractBackgroundResponse | JSONResponse:
    return await _create_contract_background_response(
        request=request,
        service=service,
        document_parser=document_parser,
        persistence_service=persistence_service,
    )


async def _create_contract_background_response(
    *,
    request: Request,
    service: ContractBackgroundService,
    document_parser: DocumentParserProtocol,
    persistence_service: ContractReviewPersistenceService,
) -> ContractBackgroundResponse | JSONResponse:
    resolved = await _resolve_contract_review_content(request, document_parser)
    if isinstance(resolved, JSONResponse):
        return resolved
    title = resolved.title
    content = resolved.content

    try:
        started = time.monotonic()
        logger.info(
            "contract_background_started content_length=%d has_title=%s",
            len(content),
            bool(title),
        )
        analysis = await service.analyze_with_raw_output(
            title=title,
            content=content,
            provided_related_documents=resolved.provided_related_documents,
        )
        result = analysis.response
        logger.info(
            "contract_background_completed category=%s elapsed=%.2fs",
            result.contract_category,
            time.monotonic() - started,
        )
        task_id = str(uuid.uuid4())
        try:
            await persistence_service.persist_review(
                task_id=task_id,
                title=title,
                response=result,
                source_file=resolved.source_file,
                related_files=resolved.related_files,
                mineru_result=resolved.mineru_result,
                content=content,
                raw_model_output=analysis.raw_output,
            )
        except Exception as exc:
            logger.exception(
                "contract_review_persistence_failed task_id=%s error_type=%s",
                task_id,
                exc.__class__.__name__,
            )
            return _error_response(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                code="persistence_error",
                message="审查结果保存服务暂时不可用，请稍后重试。",
            )
        return result
    except LLMConfigurationError:
        logger.warning("contract_background_failed error_type=LLMConfigurationError")
        return _error_response(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="llm_configuration_error",
            message="模型服务未配置，请检查服务端环境变量。",
        )
    except LLMClientError:
        logger.warning("contract_background_failed error_type=LLMClientError")
        return _error_response(
            status_code=status.HTTP_502_BAD_GATEWAY,
            code="llm_upstream_error",
            message="模型服务暂时不可用，请稍后重试。",
        )


@router.post("/contract-review-reports", response_model=ContractReviewReportResponse)
async def create_contract_review_report(
    request: Request,
    service: Annotated[ContractReviewGraphService, Depends(get_contract_review_graph_service)],
    document_parser: Annotated[DocumentParserProtocol, Depends(get_document_parser)],
    persistence_service: Annotated[
        ContractReviewPersistenceService,
        Depends(get_contract_review_persistence_service),
    ],
    pdf_renderer: Annotated[
        ContractReviewPdfRenderer,
        Depends(get_contract_review_pdf_renderer),
    ],
) -> ContractReviewReportResponse | JSONResponse:
    perspective = await _resolve_review_perspective(request)
    if isinstance(perspective, JSONResponse):
        return perspective

    resolved = await _resolve_contract_review_content(request, document_parser)
    if isinstance(resolved, JSONResponse):
        return resolved

    parsed_related, related_mineru_results = await _parse_related_documents(
        resolved.related_files,
        document_parser,
    )
    task_id = str(uuid.uuid4())
    try:
        started = time.monotonic()
        logger.info(
            "contract_review_report_started task_id=%s content_length=%d related_count=%d",
            task_id,
            len(resolved.content),
            len(parsed_related),
        )
        analysis = await service.analyze(
            task_id=task_id,
            title=resolved.title,
            content=resolved.content,
            review_perspective=perspective,
            related_documents=parsed_related,
        )
        result = analysis.response
        try:
            report_pdf = await pdf_renderer.render(
                result,
                task_id=task_id,
                title=resolved.title,
                source_filename=(
                    resolved.source_file.filename if resolved.source_file is not None else None
                ),
            )
            # 先回填公开元数据，持久化服务随后把同一响应写入审计快照。
            result.report_document = report_pdf.to_document_info(task_id)
        except PdfRendererUnavailableError as exc:
            logger.warning(
                "contract_review_pdf_renderer_unavailable task_id=%s error_type=%s "
                "failure_stage=%s cause_type=%s return_code=%s",
                task_id,
                exc.__class__.__name__,
                exc.failure_stage,
                exc.cause_type or "none",
                exc.return_code if exc.return_code is not None else "none",
            )
            return _error_response(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                code="pdf_renderer_unavailable",
                message="PDF 报告生成服务未配置，请联系管理员。",
            )
        except ReportPdfGenerationError as exc:
            logger.warning(
                "contract_review_pdf_generation_failed task_id=%s error_type=%s "
                "failure_stage=%s cause_type=%s return_code=%s",
                task_id,
                exc.__class__.__name__,
                exc.failure_stage,
                exc.cause_type or "none",
                exc.return_code if exc.return_code is not None else "none",
            )
            return _error_response(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                code="report_pdf_generation_error",
                message="合同审查报告 PDF 生成失败，请稍后重试。",
            )
        try:
            await persistence_service.persist_review(
                task_id=task_id,
                title=resolved.title,
                response=result,
                source_file=resolved.source_file,
                related_files=resolved.related_files,
                mineru_result=resolved.mineru_result,
                related_mineru_results=related_mineru_results,
                content=resolved.content,
                raw_model_outputs=analysis.raw_outputs,
                report_pdf=report_pdf,
            )
        except Exception as exc:
            logger.exception(
                "contract_review_report_persistence_failed task_id=%s error_type=%s",
                task_id,
                exc.__class__.__name__,
            )
            return _error_response(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                code="persistence_error",
                message="审查结果保存服务暂时不可用，请稍后重试。",
            )
        logger.info(
            "contract_review_report_completed task_id=%s status=%s elapsed=%.2fs",
            task_id,
            result.status,
            time.monotonic() - started,
        )
        return result
    except LLMConfigurationError:
        return _error_response(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="llm_configuration_error",
            message="模型服务未配置，请检查服务端环境变量。",
        )
    except LLMClientError:
        return _error_response(
            status_code=status.HTTP_502_BAD_GATEWAY,
            code="llm_upstream_error",
            message="模型服务暂时不可用，请稍后重试。",
        )


@router.get("/contract-review-reports", response_model=ContractReviewHistoryResponse)
async def list_contract_review_reports(
    history_service: Annotated[
        ContractReviewHistoryService,
        Depends(get_contract_review_history_service),
    ],
) -> ContractReviewHistoryResponse | JSONResponse:
    try:
        return await history_service.list_history()
    except Exception as exc:
        logger.warning(
            "contract_review_history_list_failed error_type=%s",
            exc.__class__.__name__,
        )
        return _error_response(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="history_storage_error",
            message="合同审查历史暂时无法读取，请稍后重试。",
        )


@router.get(
    "/contract-review-reports/{task_id}",
    response_model=ContractReviewReportResponse,
)
async def get_contract_review_report(
    task_id: str,
    history_service: Annotated[
        ContractReviewHistoryService,
        Depends(get_contract_review_history_service),
    ],
) -> ContractReviewReportResponse | JSONResponse:
    try:
        normalized_task_id = str(uuid.UUID(task_id))
    except ValueError:
        return _error_response(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="validation_error",
            message="任务 ID 格式无效。",
        )
    try:
        return await history_service.get_report(normalized_task_id)
    except HistoryNotFoundError:
        return _error_response(
            status_code=status.HTTP_404_NOT_FOUND,
            code="history_not_found",
            message="未找到该合同审查历史。",
        )
    except HistorySnapshotError:
        return _error_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="history_snapshot_error",
            message="合同审查历史数据无法恢复。",
        )
    except Exception as exc:
        logger.warning(
            "contract_review_history_read_failed error_type=%s",
            exc.__class__.__name__,
        )
        return _error_response(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="history_storage_error",
            message="合同审查历史暂时无法读取，请稍后重试。",
        )


@router.get("/contract-review-reports/{task_id}/document")
async def download_contract_review_report_document(
    task_id: str,
    document_service: Annotated[
        ContractReviewDocumentService,
        Depends(get_contract_review_document_service),
    ],
) -> Response:
    try:
        normalized_task_id = str(uuid.UUID(task_id))
    except ValueError:
        return _error_response(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="validation_error",
            message="任务 ID 格式无效。",
        )

    try:
        document = await document_service.get_report_pdf(normalized_task_id)
    except ReportDocumentNotFoundError:
        return _error_response(
            status_code=status.HTTP_404_NOT_FOUND,
            code="report_document_not_found",
            message="未找到该任务的合同审查 PDF 报告。",
        )
    except ReportDocumentReadError as exc:
        logger.warning(
            "contract_review_report_document_read_failed task_id=%s error_type=%s",
            normalized_task_id,
            exc.__class__.__name__,
        )
        return _error_response(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="report_document_read_error",
            message="合同审查 PDF 报告暂时无法读取，请稍后重试。",
        )

    metadata = document.metadata
    # ASCII 回退名保证旧客户端可下载，RFC 5987 参数保留可信中文文件名。
    encoded_filename = quote(metadata.filename, safe="")
    headers = {
        "Content-Disposition": (
            "attachment; filename=\"contract-review-report.pdf\"; "
            f"filename*=UTF-8''{encoded_filename}"
        ),
        "Content-Length": str(metadata.size_bytes),
        "ETag": f'"{metadata.sha256}"',
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
    }
    return Response(
        content=document.content,
        media_type="application/pdf",
        headers=headers,
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
        message="文档解析失败，请检查文件后重试。",
    )


def _error_response(*, status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
    )
