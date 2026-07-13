import logging
import re
import time
import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from starlette.datastructures import UploadFile

from app.core.config import Settings, get_settings
from app.db.session import build_mysql_session_factory
from app.integrations.llm.client import (
    LLMClientError,
    LLMClientProtocol,
    LLMConfigurationError,
    OpenAICompatibleLLMClient,
)
from app.repositories.contract_review import (
    PymongoContractReviewAuditRepository,
    SqlAlchemyContractReviewSnapshotRepository,
)
from app.schemas.analysis import AnalysisRequest, AnalysisResponse
from app.schemas.contract_background import ContractBackgroundResponse
from app.services.case_analysis import CaseAnalysisService
from app.services.contract_background import ContractBackgroundService
from app.services.contract_review_persistence import (
    ContractReviewPersistenceService,
    ContractReviewSourceFile,
)
from app.services.document_parser import DocumentParseError
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


class UnsupportedRelatedFileTypeError(ValueError):
    """关联文件类型不在 Phase 0 允许的 PDF/DOCX 白名单中。"""


@dataclass(frozen=True)
class ResolvedContractReviewContent:
    title: str | None
    content: str
    source_file: ContractReviewSourceFile | None = None
    related_files: tuple[ContractReviewSourceFile, ...] = ()
    provided_related_documents: tuple[str, ...] = ()
    mineru_result: MineruParseResult | None = None


def get_llm_client(settings: Annotated[Settings, Depends(get_settings)]) -> LLMClientProtocol:
    return OpenAICompatibleLLMClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        fallback_model=settings.llm_fallback_model,
    )


def get_contract_background_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> ContractBackgroundService:
    return ContractBackgroundService.from_llm_settings(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        fallback_model=settings.llm_fallback_model,
    )


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
        logger.info(
            "document_upload_received filename=%s content_type=%s",
            filename,
            file.content_type,
        )
        try:
            started = time.monotonic()
            logger.info("document_parse_started filename=%s", filename)
            content = await document_parser.parse(file)
            logger.info(
                "document_parse_completed filename=%s content_length=%d elapsed=%.2fs",
                filename,
                len(content),
                time.monotonic() - started,
            )
        except DocumentParseError as exc:
            logger.warning(
                "document_parse_failed filename=%s error_type=%s",
                filename,
                exc.__class__.__name__,
            )
            return _error_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                code="document_parse_error",
                message=str(exc),
            )
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
    content_type = file.content_type or "application/octet-stream"
    logger.info(
        "contract_document_upload_received filename=%s content_type=%s",
        filename,
        content_type,
    )
    try:
        source_bytes = await file.read()
        await file.seek(0)
        related_files = await _read_related_files(form)
    except UnsupportedRelatedFileTypeError:
        return _error_response(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="unsupported_related_file_type",
            message="关联文件仅支持 PDF 或 DOCX 格式。",
        )
    except Exception:
        logger.warning("contract_document_read_failed filename=%s", filename)
        return _error_response(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="document_read_error",
            message="读取上传文件失败。",
        )

    try:
        started = time.monotonic()
        logger.info("contract_document_parse_started filename=%s", filename)
        parse_result = getattr(document_parser, "parse_result", None)
        if callable(parse_result):
            mineru_result = await parse_result(file)
            content = mineru_result.markdown
        else:
            mineru_result = None
            content = await document_parser.parse(file)
        logger.info(
            "contract_document_parse_completed filename=%s content_length=%d elapsed=%.2fs",
            filename,
            len(content),
            time.monotonic() - started,
        )
    except DocumentParseError as exc:
        logger.warning(
            "contract_document_parse_failed filename=%s error_type=%s",
            filename,
            exc.__class__.__name__,
        )
        return _error_response(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="document_parse_error",
            message=str(exc),
        )

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

    related_files: list[ContractReviewSourceFile] = []
    for field_name in ("related_files", "related_file"):
        for item in getlist(field_name):
            if not isinstance(item, UploadFile):
                continue
            filename = _sanitize_uploaded_filename(item.filename or "related-document")
            content_type = item.content_type or "application/octet-stream"
            if not _is_supported_related_file(filename, content_type):
                raise UnsupportedRelatedFileTypeError(filename)
            related_files.append(
                ContractReviewSourceFile(
                    filename=filename,
                    content_type=content_type,
                    content=await item.read(),
                )
            )
    return tuple(related_files)


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
        content_type.lower() in RELATED_FILE_CONTENT_TYPES
    )


@router.post("/case-analyses", response_model=AnalysisResponse)
async def create_case_analysis(
    request: Request,
    llm_client: Annotated[LLMClientProtocol, Depends(get_llm_client)],
    document_parser: Annotated[DocumentParserProtocol, Depends(get_document_parser)],
) -> AnalysisResponse | JSONResponse:
    resolved = await _resolve_content(request, document_parser)
    if isinstance(resolved, JSONResponse):
        return resolved
    title, content = resolved

    try:
        started = time.monotonic()
        logger.info(
            "case_analysis_started content_length=%d has_title=%s",
            len(content),
            bool(title),
        )
        result = await CaseAnalysisService(llm_client).analyze(
            title=title,
            content=content,
        )
        logger.info(
            "case_analysis_completed risk_level=%s elapsed=%.2fs",
            result.risk_level,
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
    except LLMClientError:
        logger.warning("case_analysis_failed error_type=LLMClientError")
        return _error_response(
            status_code=status.HTTP_502_BAD_GATEWAY,
            code="llm_upstream_error",
            message="模型服务暂时不可用，请稍后重试。",
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


def _error_response(*, status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
    )
