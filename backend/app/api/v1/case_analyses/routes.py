from __future__ import annotations

import logging
import time
import uuid
from typing import Annotated, cast
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse, Response

from app.api.errors import error_response as _error_response
from app.api.v1.case_analyses.dependencies import (
    get_case_analysis_document_renderer,
    get_case_analysis_graph_service,
    get_case_analysis_history_service,
    get_case_analysis_persistence_service,
    get_case_document_parser,
    get_case_stored_document_service,
)
from app.api.v1.case_analyses.request_parsing import _resolve_case_content
from app.core.config import Settings, get_settings
from app.integrations.llm.client import LLMClientError, LLMConfigurationError
from app.schemas.case_analysis import (
    CaseAnalysisHistoryResponse,
    CaseAnalysisResponse,
    DocumentDraftStageResult,
)
from app.services.case_analysis.agents import CaseAnalysisStructuredOutputError
from app.services.case_analysis.document import (
    CaseAnalysisDocumentRenderer,
    CaseDocumentGenerationError,
)
from app.services.case_analysis.graph import (
    CaseAnalysisCriticalStageError,
    CaseAnalysisGraphService,
)
from app.services.case_analysis.history import CaseAnalysisHistoryService
from app.services.case_analysis.persistence import (
    CaseAnalysisDocumentNotFoundError,
    CaseAnalysisDocumentReadError,
    CaseAnalysisPersistenceService,
    CaseAnalysisStoredDocumentService,
)
from app.services.history import HistoryNotFoundError, HistorySnapshotError
from app.services.mineru_parser import DocumentParserProtocol

logger = logging.getLogger("legal_ai.api.case_analyses")

router = APIRouter(prefix="/api/v1", tags=["case-analysis"])


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
