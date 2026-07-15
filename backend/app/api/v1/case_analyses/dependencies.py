from typing import Annotated

from fastapi import Depends

from app.core.config import Settings, get_settings
from app.db.session import build_mysql_session_factory
from app.repositories.case_analysis import SqlAlchemyCaseAnalysisRepository
from app.services.case_analysis.agents import LangChainCaseAnalysisAgentRunner
from app.services.case_analysis.document import CaseAnalysisDocumentRenderer
from app.services.case_analysis.graph import CaseAnalysisGraphService
from app.services.case_analysis.history import CaseAnalysisHistoryService
from app.services.case_analysis.persistence import (
    CaseAnalysisPersistenceService,
    CaseAnalysisStoredDocumentService,
)
from app.services.mineru_parser import DocumentParserProtocol, MineruDocumentParser
from app.services.object_storage import MinioObjectStorage
from app.services.pdf_runtime import TectonicCompiler


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
