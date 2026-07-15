import logging
import time
import uuid
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse, Response

from app.api.errors import error_response as _error_response
from app.api.v1.contract_reviews.dependencies import (
    get_contract_background_service,
    get_contract_review_document_service,
    get_contract_review_graph_service,
    get_contract_review_history_service,
    get_contract_review_pdf_renderer,
    get_contract_review_persistence_service,
    get_document_parser,
)
from app.api.v1.contract_reviews.request_parsing import (
    _parse_related_documents,
    _resolve_contract_review_content,
    _resolve_review_perspective,
)
from app.integrations.llm.client import LLMClientError, LLMConfigurationError
from app.schemas.contract_review import (
    ContractReviewHistoryResponse,
    ContractReviewReportResponse,
)
from app.schemas.contract_review.background import ContractBackgroundResponse
from app.services.contract_review.background import ContractBackgroundService
from app.services.contract_review.documents import (
    ContractReviewDocumentService,
    ReportDocumentNotFoundError,
    ReportDocumentReadError,
)
from app.services.contract_review.graph import ContractReviewGraphService
from app.services.contract_review.history import ContractReviewHistoryService
from app.services.contract_review.pdf import (
    ContractReviewPdfRenderer,
    PdfRendererUnavailableError,
    ReportPdfGenerationError,
)
from app.services.contract_review.persistence import ContractReviewPersistenceService
from app.services.history import HistoryNotFoundError, HistorySnapshotError
from app.services.mineru_parser import DocumentParserProtocol

logger = logging.getLogger("legal_ai.api.contract_reviews")

router = APIRouter(prefix="/api/v1", tags=["legal-analysis"])


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
                pdf_form=analysis.pdf_form,
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
