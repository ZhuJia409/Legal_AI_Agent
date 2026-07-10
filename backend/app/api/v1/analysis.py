import logging
import time
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from starlette.datastructures import UploadFile

from app.core.config import Settings, get_settings
from app.integrations.llm.client import (
    LLMClientError,
    LLMClientProtocol,
    LLMConfigurationError,
    OpenAICompatibleLLMClient,
)
from app.schemas.analysis import AnalysisRequest, AnalysisResponse
from app.schemas.contract_background import ContractBackgroundResponse
from app.services.case_analysis import CaseAnalysisService
from app.services.contract_background import ContractBackgroundService
from app.services.document_parser import DocumentParseError
from app.services.mineru_parser import DocumentParserProtocol, MineruDocumentParser

logger = logging.getLogger("legal_ai.api.analysis")

router = APIRouter(prefix="/api/v1", tags=["legal-analysis"])


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
) -> ContractBackgroundResponse | JSONResponse:
    return await _create_contract_background_response(
        request=request,
        service=service,
        document_parser=document_parser,
    )


async def _create_contract_background_response(
    *,
    request: Request,
    service: ContractBackgroundService,
    document_parser: DocumentParserProtocol,
) -> ContractBackgroundResponse | JSONResponse:
    resolved = await _resolve_content(request, document_parser)
    if isinstance(resolved, JSONResponse):
        return resolved
    title, content = resolved

    try:
        started = time.monotonic()
        logger.info(
            "contract_background_started content_length=%d has_title=%s",
            len(content),
            bool(title),
        )
        result = await service.analyze(
            title=title,
            content=content,
        )
        logger.info(
            "contract_background_completed category=%s elapsed=%.2fs",
            result.contract_category,
            time.monotonic() - started,
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
